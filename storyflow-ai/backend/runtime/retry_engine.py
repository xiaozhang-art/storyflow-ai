"""Retry Runtime - Strategy-based retry engine with pluggable policies.

Extracts retry logic from WorkflowEngine into a dedicated, configurable engine
that maps error types to named RetryPolicies, each carrying an ordered list of
RetryActions.  The engine publishes STEP_RETRY events on every attempt and
integrates with the DirectorAgent for intelligent decision-making.

**Action-list semantics**

Each :class:`RetryPolicy` carries an ``actions`` list.  The *last* element is
always the **terminal action** (``ABORT`` or ``FALLBACK``) applied when all
retries are exhausted.  All preceding elements are *retry strategies* executed
per-attempt (clamped to the last retry strategy when retries exceed the list
length).

Example::

    engine = RetryEngine()
    result = await engine.execute_with_retry(
        agent_func=some_agent.run,
        state=current_state,
        step_name="generate_chapter",
        session_id="sess-123",
    )
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol

from runtime.event_bus import Event, EventType, EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class RetryAction(str, Enum):
    """Actions the retry engine can take on each attempt."""

    RETRY_SAME = "retry_same"           # Retry with the same parameters
    MODIFY_PROMPT = "modify_prompt"     # Ask LLM to modify the prompt before retrying
    SWITCH_MODEL = "switch_model"       # Try a different model backend
    FALLBACK = "fallback"               # Use mock/degraded output
    ABORT = "abort"                     # Give up entirely

    @property
    def is_terminal(self) -> bool:
        """Return *True* if this action ends the retry loop without calling
        the agent."""
        return self in (RetryAction.ABORT, RetryAction.FALLBACK)


@dataclass
class RetryPolicy:
    """A named retry strategy tied to a specific error pattern.

    Attributes:
        name: Human-readable policy identifier (e.g. ``"timeout"``).
        max_retries: Maximum number of retry attempts (0 = no retry).
        backoff_base: Exponential backoff base in seconds.
        backoff_max: Upper bound for a single backoff interval in seconds.
        jitter: When *True*, add random jitter (50 %–100 % of computed
            interval) to prevent thundering-herd effects.
        actions: Ordered list of actions defining the retry strategy.
            All actions except the last are *retry strategies* applied
            per-attempt (clamped to the last retry strategy when retries
            exceed the list length).  The **final** action is the *terminal
            action* — applied when all retries are exhausted.  ``ABORT``
            produces a failure result; ``FALLBACK`` returns an empty dict
            with ``success=True``.  If the last element is *not* terminal,
            ``ABORT`` is used implicitly.
    """

    name: str
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 30.0
    jitter: bool = True
    actions: list[RetryAction] = field(default_factory=lambda: [RetryAction.RETRY_SAME])


@dataclass
class RetryResult:
    """Outcome of an ``execute_with_retry`` call.

    Attributes:
        success: Whether the agent function eventually succeeded.
        result: The agent's return value (a dict) on success, or *None*.
        attempts: Total number of attempts made (1 = first try, 2 = one retry, …).
        final_action: The :class:`RetryAction` that concluded the retry loop.
        errors: Collected error messages from every failed attempt.
        total_wait_time: Cumulative seconds spent in backoff sleeps.
    """

    success: bool
    result: dict | None
    attempts: int
    final_action: RetryAction
    errors: list[str]
    total_wait_time: float


# ---------------------------------------------------------------------------
# Agent function protocol
# ---------------------------------------------------------------------------

class AgentFunc(Protocol):
    """Protocol for the callable passed to :meth:`RetryEngine.execute_with_retry`."""

    def __call__(
        self,
        state: dict[str, Any],
        step_name: str,
        session_id: str,
    ) -> Awaitable[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Default policies
# ---------------------------------------------------------------------------

def _default_policies() -> dict[str, RetryPolicy]:
    """Build the built-in set of retry policies.

    These cover the most common failure modes for LLM-backed content
    generation pipelines.
    """
    return {
        "timeout": RetryPolicy(
            name="timeout",
            max_retries=3,
            backoff_base=2.0,
            backoff_max=10.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME, RetryAction.ABORT],
        ),
        "rate_limit": RetryPolicy(
            name="rate_limit",
            max_retries=5,
            backoff_base=4.0,
            backoff_max=30.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME],
        ),
        "api_error": RetryPolicy(
            name="api_error",
            max_retries=3,
            backoff_base=2.0,
            backoff_max=30.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME, RetryAction.FALLBACK],
        ),
        "quality_fail": RetryPolicy(
            name="quality_fail",
            max_retries=2,
            backoff_base=3.0,
            backoff_max=30.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME, RetryAction.ABORT],
        ),
        "auth_error": RetryPolicy(
            name="auth_error",
            max_retries=0,
            backoff_base=2.0,
            backoff_max=10.0,
            jitter=False,
            actions=[RetryAction.ABORT],
        ),
        "content_filter": RetryPolicy(
            name="content_filter",
            max_retries=1,
            backoff_base=2.0,
            backoff_max=10.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME, RetryAction.ABORT],
        ),
        "_default": RetryPolicy(
            name="_default",
            max_retries=3,
            backoff_base=2.0,
            backoff_max=30.0,
            jitter=True,
            actions=[RetryAction.RETRY_SAME, RetryAction.ABORT],
        ),
    }


# ---------------------------------------------------------------------------
# Error → policy matching heuristics
# ---------------------------------------------------------------------------

# Maps lowercased keyword fragments to policy names.  Evaluated in order;
# first match wins.
_ERROR_PATTERN_MAP: list[tuple[tuple[str, ...], str]] = [
    (("timeout", "timed out", "read timed out"), "timeout"),
    (("rate limit", "rate_limit", "429", "too many requests", "throttl"), "rate_limit"),
    (("connectionerror", "http error", "httperror", "500", "502", "503", "server error"), "api_error"),
    (("quality", "quality_check", "quality_fail", "validation"), "quality_fail"),
    (("auth", "authentication", "unauthorized", "401", "403", "forbidden", "invalid api key", "permission"), "auth_error"),
    (("content_filter", "content filter", "content_policy", "blocked", "safety"), "content_filter"),
]


def _classify_error(error: Exception) -> str:
    """Return a policy name by inspecting *error* type and message.

    Falls back to ``"_default"`` when no pattern matches.
    """
    error_lower = f"{type(error).__name__} {str(error)}".lower()

    for keywords, policy_name in _ERROR_PATTERN_MAP:
        for kw in keywords:
            if kw in error_lower:
                return policy_name

    return "_default"


# ---------------------------------------------------------------------------
# RetryEngine
# ---------------------------------------------------------------------------

class RetryEngine:
    """Strategy-based retry engine for agent execution.

    The engine maintains a registry of :class:`RetryPolicy` instances keyed
    by name.  When :meth:`execute_with_retry` catches an exception it calls
    :meth:`match_policy` to automatically select the right policy, then
    iterates through the policy's action list across retries.

    Example::

        engine = RetryEngine()
        result = await engine.execute_with_retry(
            agent_func=chapter_agent.run,
            state=blackboard.snapshot(),
            step_name="write_chapter",
            session_id="abc-123",
        )
        if not result.success:
            print(f"Failed after {result.attempts} attempts: {result.errors}")

    Args:
        event_bus: The :class:`EventBus` to publish retry events on.  When
            *None*, the global bus from :func:`get_event_bus` is used.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._bus: EventBus = event_bus or get_event_bus()
        self._policies: dict[str, RetryPolicy] = _default_policies()

        # Runtime statistics
        self._stats: dict[str, Any] = {
            "total_retries": 0,
            "total_successes_after_retry": 0,
            "total_fallbacks": 0,
            "total_aborts": 0,
            "policy_usage": {},
        }

    # -- Policy management --------------------------------------------------

    def register_policy(self, policy: RetryPolicy) -> None:
        """Register (or replace) a retry policy by name.

        Args:
            policy: The :class:`RetryPolicy` to register.
        """
        self._policies[policy.name] = policy
        logger.info(
            "RetryEngine: registered policy '%s' (max_retries=%d, actions=%s)",
            policy.name,
            policy.max_retries,
            [a.value for a in policy.actions],
        )

    def match_policy(self, error: Exception) -> RetryPolicy:
        """Auto-detect the appropriate retry policy for *error*.

        The classification is based on keyword matching against the
        exception's type name and message string.  Returns the
        ``"_default"`` policy when nothing matches.

        Args:
            error: The caught exception to classify.

        Returns:
            The matching :class:`RetryPolicy`.
        """
        policy_name = _classify_error(error)
        policy = self._policies.get(policy_name)
        if policy is None:
            logger.warning(
                "RetryEngine: no policy for '%s', falling back to _default",
                policy_name,
            )
            policy = self._policies["_default"]
        return policy

    # -- Core execution -----------------------------------------------------

    async def execute_with_retry(
        self,
        agent_func: Callable[..., Awaitable[dict[str, Any]]],
        state: dict[str, Any],
        step_name: str,
        session_id: str,
        director: Any | None = None,
    ) -> RetryResult:
        """Execute *agent_func* wrapped in the full retry loop.

        The function is called with ``(state, step_name, session_id)``.
        On failure the engine selects a :class:`RetryPolicy`, walks through
        its action list, and retries up to ``policy.max_retries`` times
        with exponential backoff (plus optional jitter).

        For each retry attempt a ``STEP_RETRY`` event is published via the
        :class:`EventBus`.

        When a :class:`DirectorAgent` is provided the engine calls its
        ``decide`` method (if available) to let the Director influence the
        chosen action.  The Director's decision is advisory — the engine
        still respects hard policy limits.

        Args:
            agent_func: An async callable returning a ``dict`` result.
            state: The current blackboard / state dict passed to the agent.
            step_name: Human-readable name of the current step (for events
                and logging).
            session_id: Session identifier for event correlation.
            director: Optional :class:`DirectorAgent` instance for
                decision-making integration.

        Returns:
            A :class:`RetryResult` summarising the outcome.
        """
        errors: list[str] = []
        total_wait: float = 0.0

        # --- First attempt (not a "retry" per se) ---
        try:
            result = await agent_func(state, step_name, session_id)
            return RetryResult(
                success=True,
                result=result,
                attempts=1,
                final_action=RetryAction.RETRY_SAME,
                errors=[],
                total_wait_time=0.0,
            )
        except Exception as exc:
            errors.append(str(exc))
            policy = self.match_policy(exc)
            logger.warning(
                "RetryEngine [%s]: step '%s' failed on attempt 1: %s  →  policy='%s'",
                session_id,
                step_name,
                exc,
                policy.name,
            )

        # --- Decompose policy actions ---
        retry_actions, terminal_action = self._decompose_actions(policy)

        if policy.max_retries == 0:
            # No retries allowed — apply terminal action immediately.
            return await self._apply_terminal(
                terminal_action, policy, errors, total_wait,
                step_name, session_id,
            )

        # --- Retry loop ---
        for retry_index in range(1, policy.max_retries + 1):
            current_action = retry_actions[
                min(retry_index - 1, len(retry_actions) - 1)
            ]

            # If the resolved retry strategy is itself a terminal action,
            # execute it immediately without calling the agent.
            if current_action.is_terminal:
                return await self._apply_terminal(
                    current_action, policy, errors, total_wait,
                    step_name, session_id,
                    attempt_number=retry_index,
                )

            # Consult Director if available
            if director is not None and hasattr(director, "decide"):
                try:
                    director_decision = await director.decide(
                        step_name=step_name,
                        error=errors[-1],
                        attempt=retry_index,
                        max_retries=policy.max_retries,
                        policy_name=policy.name,
                    )
                    if getattr(director_decision, "type", None) == "abort":
                        logger.info(
                            "RetryEngine [%s]: Director voted ABORT for step '%s'",
                            session_id,
                            step_name,
                        )
                        return await self._apply_terminal(
                            RetryAction.ABORT, policy, errors, total_wait,
                            step_name, session_id,
                            attempt_number=retry_index,
                        )
                except Exception as dir_exc:
                    logger.warning(
                        "RetryEngine [%s]: Director consultation failed: %s",
                        session_id,
                        dir_exc,
                    )

            # Pre-action hooks (MODIFY_PROMPT, SWITCH_MODEL stubs)
            self._pre_action_hook(
                current_action, step_name, session_id, retry_index,
            )

            # Exponential backoff with optional jitter
            wait = min(policy.backoff_base ** retry_index, policy.backoff_max)
            if policy.jitter:
                wait *= 0.5 + 0.5 * random.random()  # 50 %–100 % of base
            logger.info(
                "RetryEngine [%s]: step '%s' — backing off %.2fs before attempt %d "
                "(action=%s, policy='%s')",
                session_id,
                step_name,
                wait,
                1 + retry_index,
                current_action.value,
                policy.name,
            )
            total_wait += wait
            await asyncio.sleep(wait)

            # Publish STEP_RETRY event
            await self._bus.publish_event(
                event_type=EventType.STEP_RETRY,
                data={
                    "step_name": step_name,
                    "attempt": 1 + retry_index,
                    "max_retries": policy.max_retries,
                    "action": current_action.value,
                    "policy": policy.name,
                    "error": errors[-1],
                    "backoff_seconds": wait,
                },
                session_id=session_id,
                source="RetryEngine",
            )

            # Execute the agent
            self._stats["total_retries"] += 1
            try:
                result = await agent_func(state, step_name, session_id)
                logger.info(
                    "RetryEngine [%s]: step '%s' succeeded on attempt %d",
                    session_id,
                    step_name,
                    1 + retry_index,
                )
                self._stats["total_successes_after_retry"] += 1
                self._track_policy(policy.name)
                return RetryResult(
                    success=True,
                    result=result,
                    attempts=1 + retry_index,
                    final_action=current_action,
                    errors=errors,
                    total_wait_time=total_wait,
                )
            except Exception as exc:
                errors.append(str(exc))
                logger.warning(
                    "RetryEngine [%s]: step '%s' failed on attempt %d: %s",
                    session_id,
                    step_name,
                    1 + retry_index,
                    exc,
                )
                # Re-classify in case the error type changed across retries
                policy = self.match_policy(exc)
                retry_actions, terminal_action = self._decompose_actions(policy)

        # --- Exhausted all retries — apply terminal action ---
        return await self._apply_terminal(
            terminal_action, policy, errors, total_wait,
            step_name, session_id,
        )

    # -- Statistics ---------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return a snapshot of retry engine statistics.

        Returns:
            A dict containing aggregate counters and per-policy usage.
        """
        return {
            **self._stats,
            "registered_policies": list(self._policies.keys()),
        }

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _decompose_actions(
        policy: RetryPolicy,
    ) -> tuple[list[RetryAction], RetryAction]:
        """Split a policy's action list into retry strategies + terminal.

        The **last** element is the terminal action (applied when retries
        are exhausted).  If the last element is *not* a terminal action,
        ``ABORT`` is used implicitly as the terminal.

        Returns:
            ``(retry_actions, terminal_action)``
        """
        if not policy.actions:
            return [RetryAction.RETRY_SAME], RetryAction.ABORT

        terminal = policy.actions[-1]
        if not terminal.is_terminal:
            # No explicit terminal — the whole list is retry strategies.
            return list(policy.actions), RetryAction.ABORT

        return list(policy.actions[:-1]), terminal

    async def _apply_terminal(
        self,
        action: RetryAction,
        policy: RetryPolicy,
        errors: list[str],
        total_wait: float,
        step_name: str,
        session_id: str,
        *,
        attempt_number: int | None = None,
    ) -> RetryResult:
        """Apply a terminal action (ABORT or FALLBACK) and return.

        Args:
            action: The terminal action to execute.
            policy: The active retry policy (for stats / logging).
            errors: Accumulated error messages.
            total_wait: Cumulative backoff time so far.
            step_name: Name of the step being retried.
            session_id: Session identifier.
            attempt_number: If the terminal triggers mid-loop, pass the
                1-based retry index so ``attempts`` is computed correctly.
        """
        attempts = 1 + (
            attempt_number
            if attempt_number is not None
            else policy.max_retries
        )

        self._track_policy(policy.name)

        if action == RetryAction.FALLBACK:
            logger.warning(
                "RetryEngine [%s]: step '%s' — FALLBACK after %d attempts "
                "(policy '%s')",
                session_id,
                step_name,
                attempts,
                policy.name,
            )
            self._stats["total_fallbacks"] += 1
            self._stats["total_successes_after_retry"] += 1
            return RetryResult(
                success=True,
                result={},
                attempts=attempts,
                final_action=RetryAction.FALLBACK,
                errors=errors,
                total_wait_time=total_wait,
            )

        # ABORT (default terminal)
        logger.warning(
            "RetryEngine [%s]: step '%s' — ABORT after %d attempts "
            "(policy '%s'). Last error: %s",
            session_id,
            step_name,
            attempts,
            policy.name,
            errors[-1] if errors else "N/A",
        )
        self._stats["total_aborts"] += 1
        return RetryResult(
            success=False,
            result=None,
            attempts=attempts,
            final_action=RetryAction.ABORT,
            errors=errors,
            total_wait_time=total_wait,
        )

    def _pre_action_hook(
        self,
        action: RetryAction,
        step_name: str,
        session_id: str,
        attempt: int,
    ) -> None:
        """Execute any synchronous pre-action logic.

        MODIFY_PROMPT and SWITCH_MODEL are currently logged as stubs;
        the actual LLM prompt modification and model-switching logic
        will be wired in when those subsystems are ready.
        """
        if action == RetryAction.MODIFY_PROMPT:
            logger.info(
                "RetryEngine [%s]: step '%s' — MODIFY_PROMPT on attempt %d "
                "(prompt modification not yet implemented; retrying with same params)",
                session_id,
                step_name,
                attempt,
            )
        elif action == RetryAction.SWITCH_MODEL:
            logger.info(
                "RetryEngine [%s]: step '%s' — SWITCH_MODEL on attempt %d "
                "(model switching not yet implemented; retrying with same params)",
                session_id,
                step_name,
                attempt,
            )

    def _track_policy(self, policy_name: str) -> None:
        """Increment per-policy usage counter."""
        self._stats.setdefault("policy_usage", {})
        self._stats["policy_usage"][policy_name] = (
            self._stats["policy_usage"].get(policy_name, 0) + 1
        )