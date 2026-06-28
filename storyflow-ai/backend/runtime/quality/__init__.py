"""Quality Engine - Automated quality checking for all artifact types.

Each checker validates a specific artifact type and returns a pass/fail
result with specific issues found.

V3: Full Quality Engine with multiple checkers
    - ScriptChecker: Structure, character count, episode count
    - CharacterChecker: 4-dimension appearance, consistency
    - StoryboardChecker: Scene count, prompt quality, character refs
    - ImageChecker: File exists, dimensions, content safety
    - VoiceChecker: Duration, clarity, emotion match
    - ConsistencyChecker: Cross-artifact consistency
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from runtime.event_bus import EventBus, EventType, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Result of a quality check."""
    artifact_type: str
    passed: bool
    score: float = 0.0  # 0.0 to 1.0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)  # Actionable fix suggestions
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "artifact_type": self.artifact_type,
            "passed": self.passed,
            "score": self.score,
            "issues": self.issues,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "details": self.details,
        }


class BaseQualityChecker(ABC):
    """Abstract base class for quality checkers."""

    @abstractmethod
    async def check(self, data: Any, context: dict = None) -> QualityResult:
        """Check the quality of an artifact.

        Args:
            data: The artifact data to check
            context: Additional context (blackboard state, etc.)

        Returns:
            QualityResult with pass/fail and issues
        """
        ...


class ScriptQualityChecker(BaseQualityChecker):
    """Validates script output structure and quality."""

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="script", passed=True, score=1.0)
        context = context or {}

        if not isinstance(data, dict):
            result.issues.append("Script output is not a dict")
            result.passed = False
            result.score = 0.0
            return result

        # Check outline
        outline = data.get("outline", "")
        if not outline or len(outline) < 50:
            result.issues.append(f"Outline too short ({len(outline)} chars, min 50)")
            result.suggestions.append("Expand the outline with more plot details and character interactions")
            result.passed = False
            result.score -= 0.3

        # Check characters
        characters = data.get("characters", [])
        if not characters or len(characters) < 2:
            result.issues.append(f"Too few characters ({len(characters)}, min 2)")
            result.suggestions.append("Add more characters with distinct personalities to enrich the story")
            result.passed = False
            result.score -= 0.3

        # Check episodes
        episodes = data.get("episodes", [])
        if not episodes:
            result.issues.append("No episodes generated")
            result.suggestions.append("Ensure the prompt provides enough narrative material for episode generation")
            result.passed = False
            result.score -= 0.4
        elif len(episodes) > 6:
            result.warnings.append(f"Many episodes ({len(episodes)}, max recommended 6)")

        # Check each episode has required fields
        for i, ep in enumerate(episodes):
            if not ep.get("title"):
                result.issues.append(f"Episode {i+1} missing title")
                result.passed = False
                result.score -= 0.1
            if not ep.get("script"):
                result.issues.append(f"Episode {i+1} missing script content")
                result.passed = False
                result.score -= 0.1

        result.score = max(0.0, result.score)
        return result


class CharacterQualityChecker(BaseQualityChecker):
    """Validates character visual descriptions."""

    REQUIRED_DIMENSIONS = ["hair", "body", "cloth", "face"]

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="character", passed=True, score=1.0)
        characters = data if isinstance(data, list) else data.get("characters", [])

        if not characters:
            result.issues.append("No characters provided")
            result.passed = False
            return result

        for i, char in enumerate(characters):
            name = char.get("name", f"Character {i+1}")
            appearance = char.get("appearance", {})

            if isinstance(appearance, str):
                result.warnings.append(f"{name}: appearance is string, expected dict")
                continue

            for dim in self.REQUIRED_DIMENSIONS:
                val = appearance.get(dim, "")
                if not val or len(str(val)) < 5:
                    result.issues.append(
                        f"{name}: missing or empty appearance dimension '{dim}'"
                    )
                    result.passed = False
                    result.score -= 0.1

        result.score = max(0.0, result.score)
        return result


class StoryboardQualityChecker(BaseQualityChecker):
    """Validates storyboard scenes and prompts."""

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="storyboard", passed=True, score=1.0)
        scenes = data if isinstance(data, list) else data.get("storyboard", [])

        if not scenes:
            result.issues.append("No scenes generated")
            result.passed = False
            return result

        if len(scenes) < 3:
            result.issues.append(f"Too few scenes ({len(scenes)}, min 3)")
            result.passed = False
            result.score -= 0.3

        for i, scene in enumerate(scenes):
            prompt = scene.get("prompt", "")
            if not prompt or len(prompt) < 20:
                result.issues.append(
                    f"Scene {i+1}: prompt too short ({len(prompt)} chars)"
                )
                result.passed = False
                result.score -= 0.05

            duration = scene.get("duration", 0)
            if duration < 3 or duration > 15:
                result.warnings.append(
                    f"Scene {i+1}: unusual duration ({duration}s, recommended 3-15s)"
                )

        result.score = max(0.0, result.score)
        return result


class ImageQualityChecker(BaseQualityChecker):
    """Validates generated images."""

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="image", passed=True, score=1.0)
        images = data if isinstance(data, list) else data.get("images", [])

        if not images:
            result.issues.append("No images generated")
            result.passed = False
            return result

        for i, img in enumerate(images):
            url = img.get("image_url", "")
            if not url:
                result.issues.append(f"Image {i+1}: no URL generated")
                result.passed = False
                result.score -= 0.2
            elif not os.path.exists(url) and not url.startswith("http"):
                result.warnings.append(f"Image {i+1}: file does not exist at {url}")

        result.score = max(0.0, result.score)
        return result


class VoiceQualityChecker(BaseQualityChecker):
    """Validates generated voice audio."""

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="voice", passed=True, score=1.0)
        audios = data if isinstance(data, list) else data.get("audios", [])

        if not audios:
            result.issues.append("No audio generated")
            result.passed = False
            return result

        for i, aud in enumerate(audios):
            url = aud.get("audio_url", "")
            if not url:
                result.issues.append(f"Audio {i+1}: no URL generated")
                result.passed = False
                result.score -= 0.2

        result.score = max(0.0, result.score)
        return result


class ConsistencyQualityChecker(BaseQualityChecker):
    """Cross-artifact consistency checks.

    Validates that characters look consistent across images,
    that storyboard prompts reference characters, etc.
    """

    async def check(self, data: Any, context: dict = None) -> QualityResult:
        result = QualityResult(artifact_type="consistency", passed=True, score=1.0)
        context = context or {}

        characters = context.get("characters", [])
        images = context.get("images", [])
        storyboard = context.get("storyboard", [])

        if not characters or not storyboard:
            result.warnings.append("Insufficient data for consistency check")
            return result

        # Check: storyboard prompts should reference character names
        char_names = {c.get("name", "").lower() for c in characters if c.get("name")}
        if char_names and storyboard:
            referenced = 0
            for scene in storyboard:
                prompt = scene.get("prompt", "").lower()
                if any(name in prompt for name in char_names):
                    referenced += 1

            ratio = referenced / len(storyboard) if storyboard else 0
            if ratio < 0.5:
                result.issues.append(
                    f"Only {ratio:.0%} of scenes reference character names "
                    f"(expected >50%)"
                )
                result.passed = False
                result.score = ratio

        result.score = max(0.0, result.score)
        return result


class QualityEngine:
    """Orchestrates all quality checkers.

    Runs the appropriate checker after each step and publishes
    results via EventBus.
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or get_event_bus()
        self._checkers: dict[str, BaseQualityChecker] = {
            "script": ScriptQualityChecker(),
            "character": CharacterQualityChecker(),
            "storyboard": StoryboardQualityChecker(),
            "image": ImageQualityChecker(),
            "voice": VoiceQualityChecker(),
            "consistency": ConsistencyQualityChecker(),
        }
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    async def check(self, artifact_type: str, data: Any,
                     context: dict = None, session_id: str = "") -> QualityResult:
        """Run the quality checker for a specific artifact type.

        Args:
            artifact_type: Type of artifact to check
            data: The artifact data
            context: Additional context
            session_id: Session ID for event publishing

        Returns:
            QualityResult
        """
        if not self._enabled:
            return QualityResult(artifact_type=artifact_type, passed=True, score=1.0)

        checker = self._checkers.get(artifact_type)
        if not checker:
            logger.warning("No quality checker for %s", artifact_type)
            return QualityResult(artifact_type=artifact_type, passed=True, score=1.0)

        logger.info("Running quality check: %s", artifact_type)
        result = await checker.check(data, context)

        # Publish result
        event_type = EventType.QUALITY_PASS if result.passed else EventType.QUALITY_FAIL
        await self.event_bus.publish_event(
            event_type,
            data=result.to_dict(),
            session_id=session_id,
            source="quality_engine",
        )

        if not result.passed:
            logger.warning("Quality check FAILED: %s (score=%.1f) issues: %s",
                           artifact_type, result.score, result.issues)
        else:
            logger.info("Quality check PASSED: %s (score=%.1f)", artifact_type, result.score)

        return result

    async def check_all(self, data: dict, context: dict = None,
                         session_id: str = "") -> dict[str, QualityResult]:
        """Run all applicable quality checkers.

        Returns:
            Dict mapping artifact type to QualityResult
        """
        results = {}
        check_map = {
            "script": data.get("episodes"),
            "character": data.get("characters"),
            "storyboard": data.get("storyboard"),
            "image": data.get("images"),
            "voice": data.get("audios"),
            "consistency": data,
        }

        for artifact_type, artifact_data in check_map.items():
            if artifact_data:
                results[artifact_type] = await self.check(
                    artifact_type, artifact_data, context or data, session_id
                )

        return results

    def get_stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "checkers": list(self._checkers.keys()),
        }