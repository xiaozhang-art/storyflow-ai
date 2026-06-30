"""Agent Conversation Bus - A2A (Agent-to-Agent) structured message passing.

Unlike simple state dict passing, A2A messages carry semantic meaning:
- CONTEXT: What was produced (summary of output for downstream awareness)
- FEEDBACK: What went wrong or could be improved
- CONSTRAINT: What the receiving agent must respect
- HANDOFF: Formal transfer of control from one agent to the next

This enables agents to truly communicate rather than just reading
a flat state dictionary.
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Valid message types in A2A communication
MSG_CONTEXT = "context"
MSG_FEEDBACK = "feedback"
MSG_CONSTRAINT = "constraint"
MSG_HANDOFF = "handoff"


class A2AMessage(BaseModel):
    """A structured A2A message between agents.

    Each message carries semantic type information so the receiving
    agent understands not just WHAT data was produced but HOW to use it.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = MSG_HANDOFF
    content: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=lambda: time.time())
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class AgentConversationBus:
    """Manages A2A message passing between pipeline agents.

    Stores messages per conversation and provides:
    - Structured message creation (build_handoff_message)
    - Message retrieval for an agent
    - Conversation history for LLM context injection
    - Automatic context/constraint extraction based on agent type
    """

    # Constraint templates: what each agent transition requires
    CONSTRAINT_TEMPLATES = {
        ("script", "character"): [
            "Use the exact characters defined in the script output",
            "Maintain character personalities and roles as specified",
            "Preserve character relationships and dynamics",
        ],
        ("character", "storyboard"): [
            "Maintain character visual appearance consistency in all scene descriptions",
            "Include character appearance features (hair, face, body, clothing) in scene prompts",
            "Each scene must reference characters by name with their visual features",
        ],
        ("storyboard", "image"): [
            "Use the exact image prompts from the storyboard",
            "Maintain character visual consistency across all images",
            "Preserve scene mood, lighting, and camera angles",
        ],
        ("image", "voice"): [
            "Match voice tone to the scene mood and character personality",
            "Voice duration should match storyboard scene duration",
            "If character dialogue exists, match voice gender to character gender",
        ],
        ("voice", "video"): [
            "Use all provided image and audio files",
            "Video duration must match total audio duration",
            "Maintain scene order as defined in storyboard",
        ],
    }

    def __init__(self):
        # conversation_id -> list of A2AMessages
        self._messages: dict[str, list[A2AMessage]] = {}

    def send_message(self, msg: A2AMessage, conversation_id: str = ""):
        """Store an A2A message."""
        cid = conversation_id or msg.metadata.get("conversation_id", "")
        if not cid:
            cid = "_default"
        if cid not in self._messages:
            self._messages[cid] = []
        self._messages[cid].append(msg)
        logger.debug(
            "A2A [%s]: %s -> %s (%s) | %s",
            msg.message_type, msg.from_agent, msg.to_agent,
            cid[:8], msg.content[:80],
        )

    def get_messages_for(self, agent_id: str, conversation_id: str = "") -> list[A2AMessage]:
        """Get pending messages for an agent."""
        cid = conversation_id or "_default"
        messages = self._messages.get(cid, [])
        return [m for m in messages
                if m.to_agent == agent_id
                and not m.metadata.get("delivered", False)]

    def mark_delivered(self, agent_id: str, conversation_id: str = ""):
        """Mark all messages for an agent as delivered."""
        cid = conversation_id or "_default"
        for msg in self._messages.get(cid, []):
            if msg.to_agent == agent_id:
                msg.metadata["delivered"] = True

    def get_conversation_history(self, conversation_id: str = "") -> list[A2AMessage]:
        """Get full conversation history."""
        cid = conversation_id or "_default"
        return list(self._messages.get(cid, []))

    def get_summary(self, conversation_id: str = "") -> str:
        """Format conversation as text for LLM context injection."""
        cid = conversation_id or "_default"
        messages = self._messages.get(cid, [])
        if not messages:
            return ""
        lines = ["## A2A Agent Communication History"]
        for msg in messages:
            lines.append(f"### {msg.from_agent} -> {msg.to_agent} ({msg.message_type})")
            if msg.content:
                lines.append(f"\n{msg.content}")
            if msg.constraints:
                lines.append(f"\n**Constraints:**")
                for c in msg.constraints:
                    lines.append(f"- {c}")
            if msg.feedback:
                lines.append(f"\n**Feedback:**")
                for f in msg.feedback:
                    lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines)

    def clear_for_conversation(self, conversation_id: str = ""):
        """Clear all messages for a conversation."""
        cid = conversation_id or "_default"
        self._messages.pop(cid, None)

    def build_handoff_message(
        self,
        from_agent: str,
        to_agent: str,
        state: dict,
        agent_output: dict,
        validation_result: dict | None = None,
        error: str | None = None,
        conversation_id: str = "",
    ) -> A2AMessage:
        """Build a structured handoff message from one agent to the next.

        V1.5 A2A upgrade: Carries rich structured context, not just summaries:
        - context: Rich dict with character profiles, scene data, style hints
        - constraints: What the next agent must respect (template + dynamic)
        - feedback: Quality issues, warnings, fix suggestions from quality gate
        - artifacts: References to produced files (image URLs, audio URLs)
        - metadata: Step timing, retry count, validation score
        """
        context_data = self._extract_rich_context(from_agent, state, agent_output)
        constraints = self._get_constraints(from_agent, to_agent, state, agent_output)
        feedback = self._extract_feedback(from_agent, validation_result, error)
        artifacts = self._extract_artifacts(from_agent, agent_output)

        # Build human-readable content summary
        content = f"Handoff from {from_agent} to {to_agent}."
        summary = context_data.get("summary", "")
        if summary:
            content += f"\n\nProduced: {summary}"
        if error:
            content += f"\n\nError occurred: {error}"

        return A2AMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MSG_HANDOFF,
            content=content,
            context=context_data,
            constraints=constraints,
            feedback=feedback,
            artifacts=artifacts,
            metadata={
                "conversation_id": conversation_id,
                "from_step": from_agent,
                "to_step": to_agent,
                "timestamp": time.time(),
                "validation_score": (validation_result or {}).get("passed", True),
            },
        )

    def _extract_rich_context(self, agent_id: str, state: dict, output: dict) -> dict:
        """Build rich structured context based on which agent produced output.

        V1.5 upgrade: Returns a dict with structured data for the next agent,
        not just a text summary. This enables the receiving agent to access
        precise character profiles, scene data, and style information.
        """
        ctx: dict[str, Any] = {}

        if agent_id == "script":
            outline = state.get("outline", "")
            chars = state.get("characters", [])
            eps = state.get("episodes", [])
            ctx["summary"] = (
                f"Outline: {outline[:300]}; "
                f"Characters: {', '.join(c.get('name', '') for c in chars)}; "
                f"Episodes: {len(eps)} total"
            )
            # Structured character list for character_agent
            ctx["character_names"] = [c.get("name", "") for c in chars]
            ctx["character_roles"] = {
                c.get("name", ""): c.get("role", "")
                for c in chars if c.get("name")
            }
            # Episode summaries for downstream reference
            ctx["episode_summaries"] = [
                {
                    "episode_no": e.get("episode_no", i + 1),
                    "title": e.get("title", ""),
                    "summary": e.get("summary", "")[:200],
                }
                for i, e in enumerate(eps)
            ]

        elif agent_id == "character":
            chars = state.get("characters", [])
            ctx["summary"] = (
                f"{len(chars)} character profiles enriched with visual features: "
                f"{', '.join(c.get('name', '') for c in chars)}"
            )
            # Full character appearance profiles for storyboard/image agents
            ctx["character_profiles"] = []
            for c in chars:
                name = c.get("name", "")
                appearance = c.get("appearance", {})
                if isinstance(appearance, dict):
                    ctx["character_profiles"].append({
                        "name": name,
                        "gender": c.get("gender", "unknown"),
                        "appearance": appearance,
                        "personality": c.get("personality", {}),
                    })
                else:
                    ctx["character_profiles"].append({
                        "name": name,
                        "appearance_text": str(appearance) if appearance else "",
                    })

        elif agent_id == "storyboard":
            scenes = state.get("storyboard", [])
            ctx["summary"] = (
                f"{len(scenes)} scenes storyboarded with image prompts, "
                f"camera angles, and dialogue"
            )
            # Scene data for image agent: prompt + camera + mood per scene
            ctx["scene_count"] = len(scenes)
            ctx["scenes"] = [
                {
                    "scene_no": s.get("scene_no", i + 1),
                    "prompt": s.get("prompt", ""),
                    "camera": s.get("camera", ""),
                    "mood": s.get("mood", ""),
                    "characters": s.get("characters", []),
                    "duration": s.get("duration", 5),
                }
                for i, s in enumerate(scenes)
            ]
            # Character-to-scene mapping for consistency
            char_scenes: dict[str, list[int]] = {}
            for i, s in enumerate(scenes):
                for ch in s.get("characters", []):
                    char_scenes.setdefault(ch, []).append(s.get("scene_no", i + 1))
            ctx["character_scene_map"] = char_scenes

        elif agent_id == "image":
            images = output.get("images", [])
            total = output.get("_storyboard_count", len(images))
            ctx["summary"] = f"{len(images)}/{total} images generated"
            ctx["image_urls"] = [
                {"scene_no": img.get("scene_no"), "url": img.get("image_url", "")}
                for img in images
            ]
            ctx["generation_stats"] = {
                "success": len(images),
                "total": total,
                "coverage": len(images) / max(total, 1),
            }

        elif agent_id == "voice":
            audios = output.get("audios", [])
            ctx["summary"] = f"{len(audios)} audio files generated"
            ctx["audio_urls"] = [
                {"scene_no": a.get("scene_no"), "url": a.get("audio_url", ""),
                 "duration": a.get("duration", 0)}
                for a in audios
            ]
            ctx["total_duration"] = sum(a.get("duration", 0) for a in audios)

        elif agent_id == "video":
            ctx["summary"] = f"Video composed: {state.get('video_path', 'N/A')}"
            ctx["video_path"] = state.get("video_path", "")

        else:
            ctx["summary"] = f"{agent_id} completed"

        return ctx

    def _extract_artifacts(self, agent_id: str, output: dict) -> list[str]:
        """Extract artifact references (file URLs) from agent output."""
        artifacts = []
        if agent_id == "image":
            for img in output.get("images", []):
                url = img.get("image_url", "")
                if url:
                    artifacts.append(f"image:{img.get('scene_no', '?')}:{url}")
        elif agent_id == "voice":
            for aud in output.get("audios", []):
                url = aud.get("audio_url", "")
                if url:
                    artifacts.append(f"audio:{aud.get('scene_no', '?')}:{url}")
        elif agent_id == "video":
            path = output.get("video_path", "") or output.get("video_url", "")
            if path:
                artifacts.append(f"video:final:{path}")
        return artifacts

    def _get_constraints(
        self, from_agent: str, to_agent: str, state: dict, output: dict,
    ) -> list[str]:
        """Get constraints for the next agent based on the transition."""
        key = (from_agent, to_agent)
        template = self.CONSTRAINT_TEMPLATES.get(key, [])
        constraints = list(template)

        # Add character consistency constraint for visual agents
        if to_agent in ("storyboard", "image"):
            chars = state.get("characters", [])
            if chars:
                names = [c.get("name", "") for c in chars]
                constraints.append(
                    f"Characters in scenes: {', '.join(names)} - maintain visual consistency"
                )
        if to_agent == "storyboard":
            ep_count = len(state.get("episodes", []))
            constraints.append(f"Storyboard must cover all {ep_count} episodes")

        return constraints

    def _extract_feedback(
        self, agent_id: str,
        validation_result: dict | None,
        error: str | None,
    ) -> list[str]:
        """Extract feedback/suggestions from quality gate results."""
        feedback = []
        if error:
            feedback.append(f"Previous step error: {error[:200]}")
        errors = []
        warnings = []
        if validation_result:
            errors = validation_result.get("errors", [])
            warnings = validation_result.get("warnings", [])
        if errors:
            feedback.extend([f"Quality issue: {e}" for e in errors])
        if warnings:
            feedback.extend([f"Warning: {w}" for w in warnings[:3]])
        fix = (validation_result or {}).get("fix_suggestion", "")
        if fix:
            feedback.append(f"Suggestion: {fix[:300]}")
        return feedback

    def get_stats(self) -> dict:
        return {
            "total_messages": sum(len(v) for v in self._messages.values()),
            "conversations": len(self._messages),
        }
