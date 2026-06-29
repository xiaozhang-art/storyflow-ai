"""Reflection Runtime - Post-step analysis that generates structured feedback.

After each Agent step, ReflectionRuntime analyzes the output and produces:
    - good:      What went well
    - bad:       What needs improvement
    - suggestion: Concrete, actionable suggestions for the next attempt

These suggestions flow into PromptRuntime (to improve next prompt),
DirectorRuntime (to inform retry/rollback decisions), and MemoryGraph
(to record quality observations).

Flow:
    Agent Step → Reflection → Quality → Director → Retry → Agent Step (improved)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from runtime.event_bus import EventBus, EventType, get_event_bus

logger = logging.getLogger(__name__)

# Global singleton
_reflection_runtime: ReflectionRuntime | None = None


def get_reflection_runtime() -> ReflectionRuntime:
    """Get the global ReflectionRuntime instance."""
    global _reflection_runtime
    if _reflection_runtime is None:
        _reflection_runtime = ReflectionRuntime()
    return _reflection_runtime


@dataclass
class ReflectionResult:
    """Structured feedback from reflecting on a step's output."""

    step: str
    good: list[str] = field(default_factory=list)
    bad: list[str] = field(default_factory=list)
    suggestion: list[str] = field(default_factory=list)
    score: float = 0.0  # 0-1 self-assessed quality score
    timestamp: float = field(default_factory=time.time)
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "good": self.good,
            "bad": self.bad,
            "suggestion": self.suggestion,
            "score": self.score,
            "timestamp": self.timestamp,
        }

    def get_suggestions_text(self) -> str:
        """Return suggestions as a single formatted string for prompt injection."""
        if not self.suggestion:
            return ""
        return "Reflection suggestions:\n" + "\n".join(
            f"- {s}" for s in self.suggestion
        )


REFLECTION_PROMPT = """You are a quality reviewer for an AI content creation pipeline.
An Agent just completed the "{step}" step. Analyze the output and provide feedback.

## Step Output (truncated):
{output_summary}

## Context:
- Previous steps: {previous_steps}
- Story genre: {genre}

## Instructions:
Respond in JSON with exactly this format:
{{
    "score": <float 0.0-1.0>,
    "good": ["<what went well>"],
    "bad": ["<what needs improvement>"],
    "suggestion": ["<concrete, actionable suggestion>"]
}}

Be specific. Focus on:
- For "script": plot coherence, character development, dialogue quality
- For "character": appearance completeness (hair/face/body/cloth), consistency
- For "storyboard": scene count, prompt detail, character references, pacing
- For "image": (skip detailed review, just note if URLs exist)
- For "voice": (skip detailed review, just note if audio exists)
- For "image_to_video": (skip detailed review, just note if clips exist)
- For "video": (skip, this is the final assembly step)

Only list real issues. If everything looks good, return empty bad/suggestion lists.

JSON response:"""


class ReflectionRuntime:
    """Analyzes step outputs and generates structured improvement feedback.

    The ReflectionRuntime is called after each Agent step completes.
    It produces a ReflectionResult that is:
    1. Stored on the Blackboard for downstream steps to consume
    2. Fed to PromptRuntime to improve subsequent prompts
    3. Fed to DirectorRuntime to inform retry/rollback decisions
    4. Published as a REFLECTION_COMPLETED event for observability

    When no LLM is available (or for fast/lightweight mode), it falls back
    to a rule-based reflection that uses the QualityEngine results.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        enabled: bool = True,
        use_llm: bool = True,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.enabled = enabled
        self.use_llm = use_llm
        self._reflections: dict[str, dict[str, ReflectionResult]] = {}
        # session_id → step_name → ReflectionResult

        self._stats = {
            "total_reflections": 0,
            "llm_reflections": 0,
            "rule_based_reflections": 0,
            "avg_score": 0.0,
            "scores": [],
        }

    async def reflect(
        self,
        step_name: str,
        result: dict,
        state: dict,
        session_id: str,
        quality_result: Any = None,
    ) -> ReflectionResult:
        """Analyze a step's output and produce structured feedback.

        Args:
            step_name: Name of the step that just completed
            result: The step's output dict
            state: The full pipeline state (for context)
            session_id: Session ID
            quality_result: Optional QualityResult from QualityEngine

        Returns:
            ReflectionResult with good/bad/suggestion
        """
        if not self.enabled:
            return ReflectionResult(step=step_name, score=1.0)

        # Steps that don't benefit from reflection
        if step_name in ("video",):
            r = ReflectionResult(step=step_name, score=0.9)
            self._store(session_id, step_name, r)
            return r

        # Build output summary (truncate to avoid huge prompts)
        output_summary = self._summarize_output(step_name, result)

        # Get previous steps from state
        previous_steps = self._get_previous_steps(step_name, state)
        genre = state.get("genre", "unknown")

        if self.use_llm and self._has_llm_available():
            reflection = await self._llm_reflect(
                step_name, output_summary, previous_steps, genre, session_id
            )
        else:
            reflection = self._rule_based_reflect(
                step_name, result, quality_result
            )

        # Merge quality engine suggestions if available
        if quality_result and quality_result.suggestions:
            for sug in quality_result.suggestions:
                if sug not in reflection.suggestion:
                    reflection.suggestion.append(sug)

        self._store(session_id, step_name, reflection)

        # Update stats
        self._stats["total_reflections"] += 1
        if self.use_llm and self._has_llm_available():
            self._stats["llm_reflections"] += 1
        else:
            self._stats["rule_based_reflections"] += 1
        self._stats["scores"].append(reflection.score)
        self._stats["avg_score"] = (
            sum(self._stats["scores"]) / len(self._stats["scores"])
        )

        # Publish event
        await self.event_bus.publish_event(
            EventType.REFLECTION_COMPLETED,
            data=reflection.to_dict(),
            session_id=session_id,
            source="reflection_runtime",
        )

        logger.info(
            "[Reflection %s] step=%s score=%.2f good=%d bad=%d sug=%d",
            session_id, step_name, reflection.score,
            len(reflection.good), len(reflection.bad),
            len(reflection.suggestion),
        )

        return reflection

    def get_reflection(
        self, session_id: str, step_name: str
    ) -> ReflectionResult | None:
        """Get the stored reflection for a step."""
        session_refs = self._reflections.get(session_id, {})
        return session_refs.get(step_name)

    def get_all_reflections(self, session_id: str) -> dict[str, ReflectionResult]:
        """Get all reflections for a session."""
        return dict(self._reflections.get(session_id, {}))

    def get_latest_suggestions(self, session_id: str) -> list[str]:
        """Get all suggestions from all steps (for PromptRuntime)."""
        all_suggestions = []
        for step_ref in self._reflections.get(session_id, {}).values():
            all_suggestions.extend(step_ref.suggestion)
        return all_suggestions

    def get_accumulated_context(self, session_id: str) -> str:
        """Build a text block summarizing all reflections for prompt injection.

        This is what PromptRuntime injects into agent prompts.
        """
        session_refs = self._reflections.get(session_id, {})
        if not session_refs:
            return ""

        parts = ["[Previous Step Reflections]"]
        for step_name, ref in session_refs.items():
            if ref.bad or ref.suggestion:
                parts.append(f"\n## {step_name} (score: {ref.score:.1f})")
                if ref.good:
                    parts.append("Good: " + "; ".join(ref.good[:3]))
                if ref.bad:
                    parts.append("Issues: " + "; ".join(ref.bad[:3]))
                if ref.suggestion:
                    parts.append("Suggestions: " + "; ".join(ref.suggestion[:3]))

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

    def get_stats(self) -> dict:
        stats = dict(self._stats)
        stats["sessions"] = len(self._reflections)
        return stats

    def clear_session(self, session_id: str) -> None:
        self._reflections.pop(session_id, None)

    # ── Internal ──

    def _store(
        self, session_id: str, step_name: str, reflection: ReflectionResult
    ):
        if session_id not in self._reflections:
            self._reflections[session_id] = {}
        self._reflections[session_id][step_name] = reflection

    def _summarize_output(self, step_name: str, result: dict) -> str:
        """Create a truncated summary of step output for the LLM prompt."""
        if not result:
            return "(empty result)"

        if step_name == "script":
            outline = result.get("outline", "")
            episodes = result.get("episodes", [])
            summary = f"Outline: {outline[:200]}\n"
            summary += f"Episodes: {len(episodes)}\n"
            for ep in episodes[:2]:
                summary += f"  - {ep.get('title', '')}: {ep.get('summary', '')[:100]}\n"
            return summary[:1500]

        elif step_name == "character":
            chars = result.get("characters", [])
            lines = [f"{len(chars)} characters:"]
            for c in chars[:5]:
                lines.append(
                    f"  - {c.get('name', '?')}: "
                    f"appearance={c.get('appearance', {})}"
                )
            return "\n".join(lines)[:1000]

        elif step_name == "storyboard":
            scenes = result.get("storyboard", [])
            lines = [f"{len(scenes)} scenes:"]
            for s in scenes[:5]:
                lines.append(
                    f"  Scene {s.get('scene_no', '?')}: "
                    f"{s.get('prompt', '')[:80]}..."
                )
            return "\n".join(lines)[:1000]

        else:
            # For image/voice/video/image_to_video: just list keys and counts
            keys = list(result.keys())[:10]
            return f"Result keys: {keys}\n" + str(result)[:500]

    def _get_previous_steps(self, step_name: str, state: dict) -> str:
        """Determine which steps ran before this one."""
        order = [
            "script", "character", "storyboard",
            "image", "image_to_video", "voice", "video",
        ]
        idx = order.index(step_name) if step_name in order else -1
        if idx <= 0:
            return "(none)"
        return ", ".join(order[:idx])

    def _has_llm_available(self) -> bool:
        """Check if LLM is available for reflection."""
        try:
            from app.llm import get_creative_llm
            _ = get_creative_llm()
            return True
        except Exception:
            return False

    async def _llm_reflect(
        self,
        step_name: str,
        output_summary: str,
        previous_steps: str,
        genre: str,
        session_id: str,
    ) -> ReflectionResult:
        """Use LLM to reflect on step output."""
        try:
            from app.llm import get_precise_llm

            llm = get_precise_llm()
            prompt = REFLECTION_PROMPT.format(
                step=step_name,
                output_summary=output_summary,
                previous_steps=previous_steps,
                genre=genre,
            )

            response = await llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)

            # Parse JSON from response
            data = self._parse_json(text)
            if data:
                return ReflectionResult(
                    step=step_name,
                    good=data.get("good", []),
                    bad=data.get("bad", []),
                    suggestion=data.get("suggestion", []),
                    score=float(data.get("score", 0.5)),
                    raw_response=text[:500],
                )
        except Exception as e:
            logger.warning(
                "[Reflection %s] LLM reflection failed for '%s': %s, "
                "falling back to rule-based",
                session_id, step_name, e,
            )

        # Fallback to rule-based
        return ReflectionResult(
            step=step_name, score=0.5,
            bad=["LLM reflection unavailable"],
        )

    def _rule_based_reflect(
        self,
        step_name: str,
        result: dict,
        quality_result: Any = None,
    ) -> ReflectionResult:
        """Simple rule-based reflection without LLM."""
        good = []
        bad = []
        suggestion = []
        score = 0.8  # Default: assume OK

        if step_name == "script":
            outline = result.get("outline", "")
            episodes = result.get("episodes", [])
            characters = result.get("characters", [])

            if len(outline) > 50:
                good.append("Outline has sufficient detail")
            else:
                bad.append("Outline is too short")
                suggestion.append("Expand outline with more plot details")

            if len(characters) >= 2:
                good.append(f"Has {len(characters)} characters")
            else:
                bad.append("Too few characters")
                suggestion.append("Add more characters for richer story")

            if episodes:
                good.append(f"Has {len(episodes)} episodes")
            else:
                bad.append("No episodes generated")
                suggestion.append("Ensure at least 1 episode is generated")

            score = max(0.3, 1.0 - len(bad) * 0.2)

        elif step_name == "character":
            characters = result.get("characters", [])
            required_dims = ["hair", "body", "cloth", "face"]
            for char in characters:
                appearance = char.get("appearance", {})
                if isinstance(appearance, dict):
                    missing = [d for d in required_dims if not appearance.get(d)]
                    if missing:
                        bad.append(
                            f"{char.get('name', '?')} missing: {', '.join(missing)}"
                        )
                        suggestion.append(
                            f"Add {', '.join(missing)} description for "
                            f"{char.get('name', '?')}"
                        )
                    else:
                        good.append(
                            f"{char.get('name', '?')} has complete appearance"
                        )

            score = max(0.3, 1.0 - len(bad) * 0.15)

        elif step_name == "storyboard":
            scenes = result.get("storyboard", [])
            if len(scenes) >= 3:
                good.append(f"Has {len(scenes)} scenes")
            else:
                bad.append(f"Only {len(scenes)} scenes (need at least 3)")
                suggestion.append("Add more scenes for better storytelling")

            short_prompts = 0
            for s in scenes:
                prompt = s.get("prompt", "")
                if len(prompt) < 20:
                    short_prompts += 1
            if short_prompts > 0:
                bad.append(f"{short_prompts} scenes have short prompts")
                suggestion.append(
                    "Add more visual details to scene prompts "
                    "(character appearance, environment, mood)"
                )

            score = max(0.3, 1.0 - len(bad) * 0.15)

        elif step_name == "image":
            images = result.get("images", [])
            if images:
                good.append(f"Generated {len(images)} images")
                score = 0.9
            else:
                bad.append("No images generated")
                score = 0.2

        elif step_name == "image_to_video":
            clips = result.get("video_clips", [])
            if clips:
                good.append(f"Generated {len(clips)} video clips")
                score = 0.9
            else:
                bad.append("No video clips generated")
                score = 0.2

        elif step_name == "voice":
            audios = result.get("audios", [])
            if audios:
                good.append(f"Generated {len(audios)} audio clips")
                score = 0.9
            else:
                bad.append("No audio clips generated")
                score = 0.2

        # If quality_result is available, merge
        if quality_result and not quality_result.passed:
            for issue in quality_result.issues:
                if issue not in bad:
                    bad.append(issue)
            for sug in quality_result.suggestions:
                if sug not in suggestion:
                    suggestion.append(sug)
            score = min(score, quality_result.score)

        return ReflectionResult(
            step=step_name,
            good=good,
            bad=bad,
            suggestion=suggestion,
            score=score,
        )

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Parse JSON from LLM response, handling markdown fences."""
        # Strip markdown code fences
        if "```json" in text:
            text = text.split("```json", 1)[1]
            text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            text = text.split("```", 1)[0]

        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None