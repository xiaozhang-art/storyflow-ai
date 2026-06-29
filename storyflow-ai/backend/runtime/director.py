"""Director Agent - Observes, thinks, and makes decisions.

The Director NEVER generates content. It only:
    1. Observes step results via EventBus
    2. Thinks about what went wrong
    3. Makes decisions: retry, rollback, skip, rewrite prompt, etc.

Example decisions:
    - Image failed → Retry with modified prompt
    - Character inconsistency detected → Re-run character agent, then re-run image
    - Quality check failed → Analyze why and trigger fix
    - Voice mismatched emotion → Re-generate with different parameters

The Director subscribes to EventBus events and can publish decisions
that the WorkflowEngine acts upon.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runtime.event_bus import EventBus, EventType, Event, get_event_bus

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Types of decisions the Director can make."""
    CONTINUE = "continue"          # Everything looks good, proceed
    RETRY = "retry"                # Retry the current step
    ROLLBACK = "rollback"          # Go back to a previous step
    SKIP = "skip"                  # Skip this step
    MODIFY_AND_RETRY = "modify_retry"  # Modify context and retry
    ABORT = "abort"                # Abort the entire pipeline
    HUMAN_REVIEW = "human_review"  # Pause and ask for human input


@dataclass
class Decision:
    """A decision made by the Director."""
    type: DecisionType
    step: str
    reason: str
    target_step: str = ""       # For ROLLBACK: which step to go back to
    modifications: dict = field(default_factory=dict)  # For MODIFY_AND_RETRY
    confidence: float = 1.0     # How confident is this decision (0-1)


class DirectorAgent:
    """The Director observes pipeline execution and makes decisions.

    It subscribes to STEP_COMPLETED and STEP_FAILED events and can
    intervene in the pipeline flow.

    V2: Rule-based decisions
    V3+: LLM-powered decisions
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or get_event_bus()
        self._decision_log: list[dict] = []
        self._enabled = True
        self._retry_counts: dict[str, int] = {}  # step → retry count

        # Register event handlers
        self.event_bus.subscribe(EventType.STEP_COMPLETED, self._on_step_completed)
        self.event_bus.subscribe(EventType.STEP_FAILED, self._on_step_failed)
        self.event_bus.subscribe(EventType.QUALITY_FAIL, self._on_quality_fail)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    async def _on_step_completed(self, event: Event):
        """Called when a step completes. Director reviews the result."""
        if not self._enabled:
            return

        step = event.data.get("step", "")
        session_id = event.session_id

        logger.info("Director reviewing completed step: %s", step)

        # Reset retry count on success
        self._retry_counts.pop(step, None)

        # V2: Rule-based review
        decision = await self._review_step_result(step, event.data, session_id)
        if decision and decision.type != DecisionType.CONTINUE:
            self._log_decision(decision, session_id)
            await self._publish_decision(decision, session_id)

    async def _on_step_failed(self, event: Event):
        """Called when a step fails. Director decides what to do."""
        if not self._enabled:
            return

        step = event.data.get("step", "")
        session_id = event.session_id
        error = event.data.get("error", "")

        # Track retry count
        self._retry_counts[step] = self._retry_counts.get(step, 0) + 1

        retry_count = self._retry_counts[step]

        if retry_count <= 2:
            decision = Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Step failed (attempt {retry_count}): {error}. "
                       f"Retrying with exponential backoff.",
                confidence=0.9 if retry_count == 1 else 0.6,
            )
        else:
            # After 3 failures, try to diagnose and fix
            decision = Decision(
                type=DecisionType.MODIFY_AND_RETRY,
                step=step,
                reason=f"Step failed {retry_count} times. Analyzing root cause.",
                target_step=step,
                confidence=0.4,
            )

        self._log_decision(decision, session_id)
        await self._publish_decision(decision, session_id)

    async def _on_quality_fail(self, event: Event):
        """Called when a quality check fails."""
        if not self._enabled:
            return

        artifact_type = event.data.get("artifact_type", "")
        result = event.data.get("result", {})
        session_id = event.session_id

        logger.warning("Director: quality check failed for %s: %s",
                        artifact_type, result)

        # Analyze the quality failure and decide
        issues = result.get("issues", [])
        if not issues:
            return

        # Determine which step to go back to
        rollback_map = {
            "image": "storyboard",       # Bad image → fix prompt in storyboard
            "voice": "voice",            # Bad voice → retry voice
            "character": "character",    # Bad character → redo character
            "storyboard": "character",   # Bad storyboard → might need better characters
        }

        target_step = rollback_map.get(artifact_type, artifact_type)

        decision = Decision(
            type=DecisionType.ROLLBACK,
            step=artifact_type,
            target_step=target_step,
            reason=f"Quality check failed for {artifact_type}: "
                   f"{', '.join(issues[:3])}. Rolling back to {target_step}.",
            confidence=0.7,
        )

        self._log_decision(decision, session_id)
        await self._publish_decision(decision, session_id)

    async def _review_step_result(self, step: str, data: dict,
                                   session_id: str) -> Decision | None:
        """Review a completed step's result and optionally intervene.

        V2: Simple rule-based checks
        V3.5: Uses LLM for deeper analysis when available
        """
        # Try LLM-powered review if reflection data is available
        try:
            from runtime.reflection import get_reflection_runtime
            reflection_rt = get_reflection_runtime()
            ref = reflection_rt.get_reflection(session_id, step)
            if ref and ref.score < 0.5 and ref.bad:
                # Low reflection score + issues → consider intervention
                decision = await self._llm_root_cause_analysis(
                    step, ref, session_id
                )
                if decision and decision.type != DecisionType.CONTINUE:
                    return decision
        except Exception:
            pass  # Fall through to V2 behavior

        return None

    async def _llm_root_cause_analysis(
        self, step: str, reflection: Any, session_id: str
    ) -> Decision | None:
        """Use LLM to diagnose the root cause of a quality issue.

        This is the V3.5 Director: instead of "Image retry N times",
        it finds the root cause and points to the correct Agent.
        """
        try:
            from app.llm import get_precise_llm
            llm = get_precise_llm()

            prompt = (
                f"A pipeline step '{step}' produced low-quality output.\n"
                f"Reflection analysis:\n"
                f"  Good: {reflection.good}\n"
                f"  Bad: {reflection.bad}\n"
                f"  Suggestions: {reflection.suggestion}\n"
                f"  Score: {reflection.score}\n\n"
                f"Diagnose the root cause. Which upstream step is responsible?\n"
                f"Options: script, character, storyboard, image, voice, video, "
                f"or the step itself ({step}).\n"
                f"Respond in JSON: {{\"root_cause_step\": \"...\", "
                f"\"reason\": \"...\", \"action\": \"retry|rollback|continue\"}}"
            )

            response = await llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)

            import json, re
            match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                root_step = data.get("root_cause_step", step)
                reason = data.get("reason", "")
                action = data.get("action", "retry")

                if action == "rollback" and root_step != step:
                    return Decision(
                        type=DecisionType.ROLLBACK,
                        step=step,
                        target_step=root_step,
                        reason=f"LLM root cause: {reason}. "
                               f"Root cause in '{root_step}', not '{step}'.",
                        confidence=0.7,
                    )
                elif action == "retry":
                    return Decision(
                        type=DecisionType.RETRY,
                        step=step,
                        reason=f"LLM diagnosis: {reason}",
                        confidence=0.7,
                    )
        except Exception as e:
            logger.debug("Director LLM analysis failed: %s", e)

        return None

    async def decide_on_error(self, step: str, error: Exception,
                               context: dict) -> Decision:
        """Called by the WorkflowEngine when an error occurs.

        The Director analyzes the error and decides what to do.

        Args:
            step: The step that failed
            error: The exception
            context: The step context (blackboard state, etc.)

        Returns:
            A Decision indicating what to do
        """
        error_str = str(error).lower()

        # Common error patterns
        if "timeout" in error_str or "timed out" in error_str:
            return Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Timeout error, likely transient: {error}",
                confidence=0.85,
            )
        elif "api_key" in error_str or "authentication" in error_str:
            return Decision(
                type=DecisionType.ABORT,
                step=step,
                reason=f"Authentication error, cannot retry: {error}",
                confidence=0.95,
            )
        elif "rate_limit" in error_str:
            return Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Rate limited, waiting and retrying: {error}",
                confidence=0.9,
            )
        elif "content_filter" in error_str or "safety" in error_str:
            # Content filtered → go back to storyboard to fix prompt
            if step == "image":
                return Decision(
                    type=DecisionType.ROLLBACK,
                    step=step,
                    target_step="storyboard",
                    reason=f"Content safety issue in image generation. "
                           f"Need to revise storyboard prompts.",
                    confidence=0.8,
                )
            return Decision(
                type=DecisionType.SKIP,
                step=step,
                reason=f"Content safety issue, skipping: {error}",
                confidence=0.7,
            )
        else:
            # Default: retry
            return Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Unknown error, retrying: {error}",
                confidence=0.5,
            )

    async def decide_on_quality_fail(self, step: str, quality_result,
                                      session_id: str) -> Decision:
        """Called by WorkflowEngine when a quality check fails.

        The Director analyzes the quality issues and decides whether
        to retry, skip, or continue.

        Args:
            step: The step that failed quality
            quality_result: QualityResult from the quality engine
            session_id: Session ID

        Returns:
            A Decision
        """
        issues = quality_result.issues
        score = quality_result.score

        # High score (close to passing): retry with hope of improvement
        if score >= 0.7:
            decision = Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Quality almost passed (score={score:.1f}), retrying. "
                       f"Issues: {', '.join(issues[:2])}",
                confidence=0.7,
            )
        # Very low score: the step output is fundamentally wrong
        elif score < 0.3:
            # Determine rollback target
            rollback_map = {
                "image": "storyboard",
                "voice": "storyboard",
                "character": "script",
                "storyboard": "character",
            }
            target = rollback_map.get(step, step)

            decision = Decision(
                type=DecisionType.ROLLBACK if target != step else DecisionType.RETRY,
                step=step,
                target_step=target,
                reason=f"Quality critically low (score={score:.1f}). "
                       f"Issues: {', '.join(issues[:3])}. "
                       f"{'Rolling back to ' + target + ' to fix root cause.' if target != step else 'Retrying with modified input.'}",
                confidence=0.8,
            )
        else:
            # Medium score: retry is reasonable
            decision = Decision(
                type=DecisionType.RETRY,
                step=step,
                reason=f"Quality check failed (score={score:.1f}). "
                       f"Issues: {', '.join(issues[:2])}",
                confidence=0.6,
            )

        self._log_decision(decision, session_id)
        await self._publish_decision(decision, session_id)
        return decision

    async def _publish_decision(self, decision: Decision, session_id: str):
        """Publish a director decision event."""
        await self.event_bus.publish_event(
            EventType.DIRECTOR_DECISION,
            data={
                "decision_type": decision.type.value,
                "step": decision.step,
                "target_step": decision.target_step,
                "reason": decision.reason,
                "modifications": decision.modifications,
                "confidence": decision.confidence,
            },
            session_id=session_id,
            source="director",
        )

    def _log_decision(self, decision: Decision, session_id: str):
        """Log a decision for auditing."""
        self._decision_log.append({
            "session_id": session_id,
            "decision": decision.type.value,
            "step": decision.step,
            "reason": decision.reason,
            "confidence": decision.confidence,
        })
        logger.info("Director decision: %s → %s (confidence=%.1f) [%s]",
                     decision.step, decision.type.value,
                     decision.confidence, decision.reason)

    def get_decision_log(self, session_id: str = None) -> list[dict]:
        """Get the decision log, optionally filtered by session."""
        if session_id:
            return [d for d in self._decision_log if d["session_id"] == session_id]
        return list(self._decision_log)

    def get_stats(self) -> dict:
        """Get Director statistics."""
        return {
            "enabled": self._enabled,
            "total_decisions": len(self._decision_log),
            "by_type": self._count_by_type(),
        }

    def _count_by_type(self) -> dict[str, int]:
        counts = {}
        for d in self._decision_log:
            t = d["decision"]
            counts[t] = counts.get(t, 0) + 1
        return counts