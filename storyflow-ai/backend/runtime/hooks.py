"""Hook Framework - Before/After/Retry hooks for pipeline steps.

Hooks allow cross-cutting concerns (logging, quality checks, prompt optimization,
retry logic) without modifying any Agent code.

Usage:
    hooks = HookFramework()

    @hooks.before("image")
    async def optimize_prompt(context):
        context["prompt"] = enhance(context["prompt"])
        return context  # Modified context goes to the agent

    @hooks.after("image")
    async def validate_image(context, result):
        if not quality_ok(result):
            raise HookAbort("Image quality too low", retry=True)

    @hooks.on_error("image")
    async def handle_image_error(context, error):
        log_error(error)
        return ErrorAction.RETRY  # or ErrorAction.ABORT, ErrorAction.CONTINUE
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class ErrorAction(str, Enum):
    """Actions the hook system can take on errors."""
    RETRY = "retry"          # Retry the step
    ABORT = "abort"          # Abort the entire pipeline
    CONTINUE = "continue"    # Skip this step and continue
    FALLBACK = "fallback"    # Use a fallback implementation


class HookAbort(Exception):
    """Raised by a hook to signal that the step should be retried or aborted.

    Args:
        message: Description of why the hook aborted
        retry: Whether the step should be retried
        fallback_data: Optional data to use as fallback result
    """
    def __init__(self, message: str, retry: bool = False, fallback_data: Any = None):
        super().__init__(message)
        self.retry = retry
        self.fallback_data = fallback_data


@dataclass
class StepContext:
    """Context passed to hooks, containing all information about the current step."""
    step_name: str
    session_id: str
    blackboard: Any = None  # Reference to the Blackboard
    artifact_manager: Any = None  # Reference to the ArtifactManager
    attempt: int = 1
    extra: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.extra.get(key, default)

    def set(self, key: str, value: Any):
        self.extra[key] = value


# Hook function types
BeforeHook = Callable[[StepContext], Coroutine[Any, Any, StepContext | None]]
AfterHook = Callable[[StepContext, Any], Coroutine[Any, Any, Any | None]]
ErrorHook = Callable[[StepContext, Exception], Coroutine[Any, Any, ErrorAction]]


class HookFramework:
    """Manages before/after/error hooks for pipeline steps.

    Hooks are registered per-step or globally (using "*" as step name).
    Multiple hooks can be registered for the same step and run in order.
    """

    def __init__(self):
        self._before_hooks: dict[str, list[BeforeHook]] = {}
        self._after_hooks: dict[str, list[AfterHook]] = {}
        self._error_hooks: dict[str, list[ErrorHook]] = {}
        self._max_retries: int = 3

    def before(self, step: str):
        """Decorator to register a before-hook for a step."""
        def decorator(func: BeforeHook):
            self._before_hooks.setdefault(step, []).append(func)
            return func
        return decorator

    def after(self, step: str):
        """Decorator to register an after-hook for a step."""
        def decorator(func: AfterHook):
            self._after_hooks.setdefault(step, []).append(func)
            return func
        return decorator

    def on_error(self, step: str):
        """Decorator to register an error-hook for a step."""
        def decorator(func: ErrorHook):
            self._error_hooks.setdefault(step, []).append(func)
            return func
        return decorator

    def add_before(self, step: str, hook: BeforeHook):
        """Programmatically register a before-hook."""
        self._before_hooks.setdefault(step, []).append(hook)

    def add_after(self, step: str, hook: AfterHook):
        """Programmatically register an after-hook."""
        self._after_hooks.setdefault(step, []).append(hook)

    def add_error(self, step: str, hook: ErrorHook):
        """Programmatically register an error-hook."""
        self._error_hooks.setdefault(step, []).append(hook)

    async def run_before(self, context: StepContext) -> StepContext:
        """Run all before-hooks for a step.

        Hooks can modify the context and return it.
        If a hook raises HookAbort, the step is skipped/retried.
        """
        hooks = self._get_hooks(self._before_hooks, context.step_name)
        for hook in hooks:
            logger.debug("Running before-hook %s for step %s",
                         hook.__qualname__, context.step_name)
            try:
                result = await hook(context)
                if isinstance(result, StepContext):
                    context = result
            except HookAbort as e:
                logger.warning("Before-hook %s aborted step %s: %s",
                               hook.__qualname__, context.step_name, e)
                raise
            except Exception as e:
                logger.error("Before-hook %s failed for step %s: %s",
                             hook.__qualname__, context.step_name, e)
        return context

    async def run_after(self, context: StepContext, result: Any) -> Any:
        """Run all after-hooks for a step.

        Hooks can modify the result. If a hook raises HookAbort
        with retry=True, the step will be retried.
        """
        hooks = self._get_hooks(self._after_hooks, context.step_name)
        for hook in hooks:
            logger.debug("Running after-hook %s for step %s",
                         hook.__qualname__, context.step_name)
            try:
                hook_result = await hook(context, result)
                if hook_result is not None:
                    result = hook_result
            except HookAbort as e:
                logger.warning("After-hook %s aborted step %s: %s",
                               hook.__qualname__, context.step_name, e)
                raise
            except Exception as e:
                logger.error("After-hook %s failed for step %s: %s",
                             hook.__qualname__, context.step_name, e)
        return result

    async def run_on_error(self, context: StepContext, error: Exception) -> ErrorAction:
        """Run error-hooks to determine what to do after a step failure.

        Returns the first non-CONTINUE action from any error-hook.
        If all hooks return CONTINUE (or no hooks), returns CONTINUE.
        """
        hooks = self._get_hooks(self._error_hooks, context.step_name)
        for hook in hooks:
            logger.debug("Running error-hook %s for step %s",
                         hook.__qualname__, context.step_name)
            try:
                action = await hook(context, error)
                if action != ErrorAction.CONTINUE:
                    logger.info("Error-hook %s decided: %s for step %s",
                                hook.__qualname__, action.value, context.step_name)
                    return action
            except Exception as e:
                logger.error("Error-hook %s itself failed: %s",
                             hook.__qualname__, e)
        return ErrorAction.CONTINUE

    def _get_hooks(self, hook_dict: dict, step_name: str) -> list:
        """Get hooks for a specific step, including global hooks (*)."""
        step_hooks = hook_dict.get(step_name, [])
        global_hooks = hook_dict.get("*", [])
        return global_hooks + step_hooks

    def set_max_retries(self, max_retries: int):
        """Set the maximum number of retries for hook-triggered retries."""
        self._max_retries = max_retries