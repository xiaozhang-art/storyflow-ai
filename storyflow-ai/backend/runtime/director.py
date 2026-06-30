"""Director Runtime - The autonomous decision-making brain of the Agent OS.

The Director monitors every agent step, reads all produced Artifacts,
and uses LLM analysis to make intelligent decisions about how to proceed.

Five decisions the Director can make:
1. RETRY          - Re-run the current step (transient failure, quality issue)
2. ROLLBACK       - Go back to a previous step and re-execute from there
3. REWRITE_PROMPT - Modify the prompt/input and re-run the current step
4. SKIP           - Skip the current step (non-critical, can proceed without)
5. INSERT_STEP    - Insert a new remediation step before continuing

The Director is NOT a simple rule engine. It uses LLM to analyze
the full artifact context (script, characters, storyboard, images, etc.)
and understand WHY a failure occurred before deciding what to do.
"""
from __future__ import annotations

import json
import logging
import re
import time
from enum import Enum
from typing import Any, Optional

from runtime.hook.dispatcher import HookEvent, HookHandler, get_hook_dispatcher
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)


class DirectorDecision(str, Enum):
    """Decisions the Director can make."""
    PROCEED = "proceed"
    RETRY = "retry"
    ROLLBACK = "rollback"
    REWRITE_PROMPT = "rewrite_prompt"
    SKIP = "skip"
    INSERT_STEP = "insert_step"


class DirectorVerdict:
    """Result of the Director's analysis."""
    __slots__ = (
        "decision", "agent_id", "reasoning", "target_step",
        "modified_prompt", "modified_state", "insert_step_config",
        "confidence", "analysis_latency_ms",
    )

    def __init__(
        self,
        decision: DirectorDecision,
        agent_id: str,
        reasoning: str = "",
        target_step: str = "",
        modified_prompt: str = "",
        modified_state: dict | None = None,
        insert_step_config: dict | None = None,
        confidence: float = 0.0,
        analysis_latency_ms: float = 0.0,
    ):
        self.decision = decision
        self.agent_id = agent_id
        self.reasoning = reasoning
        self.target_step = target_step
        self.modified_prompt = modified_prompt
        self.modified_state = modified_state or {}
        self.insert_step_config = insert_step_config or {}
        self.confidence = confidence
        self.analysis_latency_ms = analysis_latency_ms

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "agent_id": self.agent_id,
            "reasoning": self.reasoning,
            "target_step": self.target_step,
            "modified_prompt": self.modified_prompt,
            "modified_state": self.modified_state,
            "insert_step_config": self.insert_step_config,
            "confidence": self.confidence,
            "analysis_latency_ms": self.analysis_latency_ms,
        }


class ArtifactManager:
    """Manages all artifacts produced during the workflow."""

    PIPELINE_ORDER = ["script", "character", "storyboard", "image", "voice", "video"]

    def __init__(self):
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._execution_log: list[dict[str, Any]] = []

    def store(self, agent_id: str, artifact: dict[str, Any]):
        """Store an artifact produced by an agent."""
        self._artifacts[agent_id] = {
            "data": artifact,
            "stored_at": time.time(),
        }
        self._execution_log.append({
            "agent_id": agent_id,
            "action": "store",
            "timestamp": time.time(),
        })
        logger.debug("Artifact stored: %s (%d keys)", agent_id, len(artifact))

    def get(self, agent_id: str) -> dict[str, Any] | None:
        """Get artifact by agent_id."""
        entry = self._artifacts.get(agent_id)
        return entry["data"] if entry else None

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all artifacts."""
        return {k: v["data"] for k, v in self._artifacts.items()}

    def get_summary(self) -> str:
        """Generate a human-readable summary of all artifacts for LLM analysis."""
        lines = []
        for agent_id, entry in self._artifacts.items():
            data = entry["data"]
            lines.append(f"=== {agent_id} ===")

            if agent_id == "script":
                outline = data.get("outline", "")
                characters = data.get("characters", [])
                episodes = data.get("episodes", [])
                lines.append(f"Outline: {outline[:500]}")
                lines.append(f"Characters: {[c.get('name', '') for c in characters]}")
                lines.append(f"Episodes: {len(episodes)} episodes")
                for ep in episodes[:3]:
                    lines.append(f"  - Ep {ep.get('episode_no', '?')}: {ep.get('title', '')} ({len(ep.get('script', ''))} chars)")
                if len(episodes) > 3:
                    lines.append(f"  ... and {len(episodes) - 3} more episodes")

            elif agent_id == "character":
                chars = data.get("characters", [])
                for c in chars[:5]:
                    name = c.get("name", "?")
                    appearance = c.get("appearance", {})
                    if isinstance(appearance, dict):
                        lines.append(f"  {name}: hair={appearance.get('hair', 'N/A')}, cloth={appearance.get('cloth', 'N/A')}")
                    else:
                        lines.append(f"  {name}: {str(appearance)[:100]}")

            elif agent_id == "storyboard":
                scenes = data.get("storyboard", [])
                lines.append(f"Total scenes: {len(scenes)}")
                for s in scenes[:5]:
                    prompt = s.get("prompt", "")
                    chars = s.get("characters", [])
                    lines.append(f"  Scene {s.get('scene_no', '?')}: [{', '.join(chars)}] {prompt[:120]}")
                if len(scenes) > 5:
                    lines.append(f"  ... and {len(scenes) - 5} more scenes")

            elif agent_id == "image":
                images = data.get("images", [])
                lines.append(f"Images generated: {len(images)}")
                for img in images[:5]:
                    lines.append(f"  Scene {img.get('scene_no', '?')}: {img.get('image_url', 'N/A')[:80]}")

            elif agent_id == "voice":
                audios = data.get("audios", [])
                lines.append(f"Audio files: {len(audios)}")
                for a in audios[:3]:
                    lines.append(f"  Scene {a.get('scene_no', '?')}: duration={a.get('duration', 0):.1f}s")

            elif agent_id == "video":
                lines.append(f"Video path: {data.get('video_path', 'N/A')}")

            else:
                lines.append(json.dumps(data, ensure_ascii=False, default=str)[:300])

            lines.append("")

        return "\n".join(lines)

    def remove_from(self, agent_id: str):
        """Remove artifacts from this step onward (for rollback)."""
        idx = self.PIPELINE_ORDER.index(agent_id) if agent_id in self.PIPELINE_ORDER else 0
        to_remove = [k for k in self._artifacts
                     if k in self.PIPELINE_ORDER and self.PIPELINE_ORDER.index(k) >= idx]
        for key in to_remove:
            del self._artifacts[key]
            self._execution_log.append({
                "agent_id": key,
                "action": "rollback_remove",
                "timestamp": time.time(),
            })
        logger.info("Artifacts removed from step %s onward: %s", agent_id, to_remove)

    def get_log(self) -> list[dict]:
        return list(self._execution_log)


class Director:
    """The autonomous decision-making brain of the Agent OS."""

    PIPELINE_ORDER = ["script", "character", "storyboard", "image", "voice", "video"]

    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        session_manager=None,
        llm_call=None,
        max_retries_per_step: int = 2,
        max_total_decisions: int = 10,
    ):
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.session_manager = session_manager
        self.llm_call = llm_call
        self.max_retries_per_step = max_retries_per_step
        self.max_total_decisions = max_total_decisions
        self._step_retry_counts: dict[str, int] = {}
        self._total_decisions: int = 0
        self._decision_history: list[dict] = []
        self.hooks = get_hook_dispatcher()

    async def analyze_step(
        self,
        agent_id: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        validation_result: dict | None = None,
        conversation_id: str = "",
        trace_id: str = "",
    ) -> DirectorVerdict:
        start_time = time.time()

        if output and not error:
            self.artifact_manager.store(agent_id, output)

        if not error and validation_result and not validation_result.get("validation_failed", False):
            return self._make_verdict(
                agent_id=agent_id,
                decision=DirectorDecision.PROCEED,
                reasoning="Step completed successfully, validation passed.",
                latency=start_time,
            )

        retry_count = self._step_retry_counts.get(agent_id, 0)
        if retry_count >= self.max_retries_per_step and not error:
            return self._make_verdict(
                agent_id=agent_id,
                decision=DirectorDecision.PROCEED,
                reasoning=f"Max retries ({self.max_retries_per_step}) exceeded.",
                latency=start_time,
                confidence=0.3,
            )

        if self._total_decisions >= self.max_total_decisions:
            return self._make_verdict(
                agent_id=agent_id,
                decision=DirectorDecision.PROCEED,
                reasoning=f"Max total decisions ({self.max_total_decisions}) reached.",
                latency=start_time,
                confidence=0.3,
            )

        if self.llm_call:
            verdict = await self._llm_analyze(
                agent_id=agent_id, output=output, error=error,
                validation_result=validation_result,
                conversation_id=conversation_id, trace_id=trace_id,
            )
        else:
            verdict = self._rule_based_analyze(
                agent_id=agent_id, output=output, error=error,
                validation_result=validation_result,
            )

        verdict.analysis_latency_ms = (time.time() - start_time) * 1000
        self._total_decisions += 1
        self._step_retry_counts[agent_id] = retry_count + 1
        self._decision_history.append(verdict.to_dict())

        logger.info("Director verdict: %s -> %s (confidence=%.2f)",
                     agent_id, verdict.decision.value, verdict.confidence)

        await self.hooks.emit(HookEvent(
            name="DIRECTOR_DECISION",
            payload=verdict.to_dict(),
            trace_id=trace_id, session_id="",
            conversation_id=conversation_id, agent_id=agent_id,
        ))

        return verdict

    async def _llm_analyze(
        self, agent_id, output, error, validation_result, conversation_id, trace_id,
    ) -> DirectorVerdict:
        artifact_summary = self.artifact_manager.get_summary()
        validation_info = json.dumps(validation_result, ensure_ascii=False, indent=2) if validation_result else ""
        error_info = error or "No error (quality gate failed)"

        # Build decision history context for the LLM
        decision_history = ""
        if self._decision_history:
            recent = self._decision_history[-5:]
            decision_history = "\n## Recent Decisions\n"
            for d in recent:
                decision_history += (
                    f"- {d.get('agent_id', '?')}: {d.get('decision', '?')} "
                    f"(confidence={d.get('confidence', 0):.2f}) — {d.get('reasoning', '')[:100]}\n"
                )

        # Build retry context
        retry_count = self._step_retry_counts.get(agent_id, 0)
        retry_info = f"\n## Retry Context\nCurrent step '{agent_id}' has been retried {retry_count} time(s). Max: {self.max_retries_per_step}"

        # Pipeline position context
        try:
            idx = self.PIPELINE_ORDER.index(agent_id)
            position = f"\n## Pipeline Position\nStep {idx + 1}/{len(self.PIPELINE_ORDER)}: {' -> '.join(self.PIPELINE_ORDER)}\nCurrent: **{agent_id}** (← already completed); Next: {self.PIPELINE_ORDER[idx + 1] if idx + 1 < len(self.PIPELINE_ORDER) else 'DONE'}"
        except ValueError:
            position = f"\nCurrent step: {agent_id}"

        system_prompt = """You are the Director of an AI story generation pipeline. You have access to ALL artifacts produced so far and must make intelligent decisions.

Output a JSON object with:
{"decision": "proceed" | "retry" | "rollback" | "rewrite_prompt" | "skip" | "insert_step",
"reasoning": "detailed explanation of WHY you chose this decision",
"target_step": "rollback target agent_id (only for rollback)",
"modified_prompt": "improved prompt with specific fixes (only for rewrite_prompt)",
"insert_step_config": {"type": "step_type"} (only for insert_step),
"confidence": 0.0-1.0}

Decision guidelines:
- PROCEED: Output is good quality, no issues detected.
- RETRY: Transient failure (timeout, rate limit). Same inputs, try again.
- ROLLBACK: Fundamental issue rooted in an EARLIER step. E.g., bad characters → bad storyboard. Set target_step to the problematic earlier step.
- REWRITE_PROMPT: The current step's input needs improvement but the issue is not in an earlier step. Provide a concrete modified_prompt with specific fixes.
- SKIP: Non-critical failure; the pipeline can continue without this step's output (e.g., voice generation fails but video can proceed silently).
- INSERT_STEP: A remediation step is needed before continuing. E.g., character consistency check before image generation.

IMPORTANT: Analyze the full artifact context to understand ROOT CAUSE before deciding. Don't just react to the error surface.
Output ONLY JSON, no other text."""

        user_prompt = f"""Analyze this pipeline step and decide what to do next.

## Current Step: {agent_id}
{position}{retry_info}
{decision_history}

## Error (if any): {error_info}

## Quality Gate Validation:\n{validation_info or 'No validation result (step succeeded without quality gate failure)'}

## All Artifacts Produced So Far:
{artifact_summary}

## Pipeline Flow: script -> character -> storyboard -> image -> voice -> video

Respond with ONLY a JSON object containing your decision."""

        try:
            result = await self.llm_call(system_prompt=system_prompt, user_prompt=user_prompt, model="default")
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            decision_data = self._extract_json(content)
            if not decision_data:
                return self._rule_based_analyze(agent_id, output, error, validation_result)
            try:
                decision = DirectorDecision(decision_data.get("decision", "proceed"))
            except ValueError:
                decision = DirectorDecision.PROCEED
            return DirectorVerdict(
                decision=decision, agent_id=agent_id,
                reasoning=decision_data.get("reasoning", "LLM analysis"),
                target_step=decision_data.get("target_step", ""),
                modified_prompt=decision_data.get("modified_prompt", ""),
                confidence=float(decision_data.get("confidence", 0.7)),
            )
        except Exception as e:
            logger.error("Director LLM analysis failed: %s", e)
            return self._rule_based_analyze(agent_id, output, error, validation_result)

    def _rule_based_analyze(self, agent_id, output, error, validation_result) -> DirectorVerdict:
        retry_count = self._step_retry_counts.get(agent_id, 0)

        if error:
            error_lower = error.lower()
            transient_kw = ["timeout", "rate limit", "connection", "503", "502", "429"]
            if any(kw in error_lower for kw in transient_kw):
                if retry_count < self.max_retries_per_step:
                    return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.RETRY,
                                                          reasoning=f"Transient error: {error[:100]}", confidence=0.9)
            if agent_id in ("image", "voice") and retry_count >= 1:
                return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.SKIP,
                                                          reasoning=f"{agent_id} failed after retry, skipping.", confidence=0.7)
            if retry_count < self.max_retries_per_step:
                return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.RETRY,
                                                          reasoning=f"Agent error: {error[:100]}", confidence=0.6)

        if validation_result and validation_result.get("validation_failed"):
            errors = validation_result.get("errors", [])
            fix_suggestion = validation_result.get("fix_suggestion", "")

            if agent_id == "storyboard" and retry_count >= 1:
                script_art = self.artifact_manager.get("script")
                if script_art:
                    episodes = script_art.get("episodes", [])
                    if not episodes or len(episodes) < 1:
                        return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.ROLLBACK,
                                                          target_step="script", reasoning="Script has no episodes.", confidence=0.8)

            if agent_id == "storyboard" and any("character" in e.lower() for e in errors):
                char_art = self.artifact_manager.get("character")
                if not char_art or not char_art.get("characters"):
                    return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.ROLLBACK,
                                                          target_step="character", reasoning="Missing character data.", confidence=0.8)

            if fix_suggestion and retry_count < self.max_retries_per_step:
                return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.REWRITE_PROMPT,
                                                          reasoning=f"Quality gate failed: {'; '.join(errors[:3])}",
                                                          modified_prompt=fix_suggestion, confidence=0.7)
            if retry_count < self.max_retries_per_step:
                return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.RETRY,
                                                          reasoning=f"Quality gate failed: {'; '.join(errors[:3])}", confidence=0.6)

        return self._make_verdict(agent_id=agent_id, decision=DirectorDecision.PROCEED,
                                          reasoning="No significant issues.", confidence=0.9)

    def _make_verdict(self, agent_id, decision, reasoning, target_step="",
                       modified_prompt="", confidence=0.7, latency=0.0) -> DirectorVerdict:
        return DirectorVerdict(decision=decision, agent_id=agent_id, reasoning=reasoning,
                              target_step=target_step, modified_prompt=modified_prompt,
                              confidence=confidence)

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def reset_retry_count(self, agent_id: str):
        self._step_retry_counts[agent_id] = 0

    def get_stats(self) -> dict:
        return {
            "total_decisions": self._total_decisions,
            "step_retries": dict(self._step_retry_counts),
            "artifacts_stored": len(self.artifact_manager.get_all()),
            "decision_history": self._decision_history[-10:],
        }


def create_director_hook(director: Director) -> HookHandler:
    """Create a hook handler that triggers Director analysis after each agent step."""
    async def handler(event: HookEvent):
        if event.name != hook_events.AFTER_AGENT:
            return
        agent_id = event.payload.get("agent_id", "")
        output = event.payload.get("output", {})
        error = event.payload.get("error")
        validation_result = event.payload.get("validation_result")
        verdict = await director.analyze_step(
            agent_id=agent_id, output=output, error=error,
            validation_result=validation_result,
            conversation_id=event.conversation_id, trace_id=event.trace_id,
        )
        event.payload["director_verdict"] = verdict.to_dict()
    return handler
