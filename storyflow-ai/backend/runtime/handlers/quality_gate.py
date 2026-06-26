"""Quality Gate Hooks - Validation hooks that act as "eyes" for the pipeline.

These hooks fire AFTER each agent step to validate output quality.
If validation fails, the hook can:
1. Log warnings (always)
2. Set validation_failed flag (for adapter to trigger retry)
3. Suggest fixes (for adaptive retry with modified prompts)

Quality gates per agent:
- script: validate structure completeness (outline, characters, episodes)
- character: validate appearance cards have all 4 dimensions
- storyboard: validate scene count, character references, prompt quality
- image: validate image exists and is not empty
- voice: validate audio duration > 0
- video: validate final video exists

Usage:
    hooks = get_hook_dispatcher()
    hooks.register(AFTER_AGENT, create_quality_gate_handler())
"""
from __future__ import annotations

import logging
from typing import Any

from runtime.hook.dispatcher import HookEvent, HookHandler
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of a quality gate validation."""
    def __init__(
        self,
        passed: bool,
        agent_id: str,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        fix_suggestion: str = "",
    ):
        self.passed = passed
        self.agent_id = agent_id
        self.errors = errors or []
        self.warnings = warnings or []
        self.fix_suggestion = fix_suggestion

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "agent_id": self.agent_id,
            "errors": self.errors,
            "warnings": self.warnings,
            "fix_suggestion": self.fix_suggestion,
        }


class QualityGateHandler:
    """Validates agent outputs after each step.

    This is the "eyes" of the pipeline — it catches problems early
    before they cascade into later agents.
    """

    # Validation functions per agent
    VALIDATORS = {
        "script": "_validate_script",
        "character": "_validate_character",
        "storyboard": "_validate_storyboard",
        "image": "_validate_image",
        "voice": "_validate_voice",
        "video": "_validate_video",
    }

    async def handle(self, event: HookEvent):
        """Run quality gate validation for the agent that just completed."""
        if event.name != hook_events.AFTER_AGENT:
            return

        agent_id = event.payload.get("agent_id", "")
        validator_name = self.VALIDATORS.get(agent_id)

        if not validator_name:
            return

        validator = getattr(self, validator_name, None)
        if not validator:
            return

        try:
            result = validator(event.payload)
            if not result.passed:
                logger.warning(
                    "QUALITY GATE FAILED [%s]: %s",
                    agent_id, "; ".join(result.errors),
                )
                # Emit an ON_RETRY event so the adapter knows to retry
                # The adapter checks event.payload["validation_failed"]
                event.payload["validation_result"] = result.to_dict()
                event.payload["validation_failed"] = True
            else:
                if result.warnings:
                    logger.info(
                        "QUALITY GATE PASSED [%s] with warnings: %s",
                        agent_id, "; ".join(result.warnings),
                    )
                event.payload["validation_result"] = result.to_dict()
                event.payload["validation_failed"] = False
        except Exception as e:
            logger.error("Quality gate error for %s: %s", agent_id, e)

    # ─────────────────────────────────────────────────────────────
    # Per-agent validators
    # ─────────────────────────────────────────────────────────────

    def _validate_script(self, payload: dict) -> ValidationResult:
        """Validate script output: must have outline, characters, episodes."""
        errors = []
        warnings = []

        # Check from the adapter's result context
        output = payload.get("output", {})
        if not output:
            output = payload

        outline = output.get("outline", "")
        characters = output.get("characters", [])
        episodes = output.get("episodes", [])

        if not outline or len(outline.strip()) < 50:
            errors.append("大纲内容过短（少于50字），可能不完整")

        if not characters or len(characters) < 2:
            errors.append(f"角色数量不足（{len(characters)}个），短剧至少需要2个角色")
        elif len(characters) > 8:
            warnings.append(f"角色数量较多（{len(characters)}个），可能导致视觉一致性困难")

        if not episodes or len(episodes) < 1:
            errors.append("没有生成任何剧集")

        for i, ep in enumerate(episodes):
            ep_no = ep.get("episode_no", i + 1)
            if not ep.get("title"):
                errors.append(f"第{ep_no}集缺少标题")
            if not ep.get("summary") or len(ep.get("summary", "")) < 20:
                errors.append(f"第{ep_no}集剧情概要过短")
            if not ep.get("script") or len(ep.get("script", "")) < 50:
                errors.append(f"第{ep_no}集剧本内容过短")

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="script",
            errors=errors,
            warnings=warnings,
            fix_suggestion="请重新生成剧本，确保大纲完整、角色数量合理、每集有足够的剧本内容。" if errors else "",
        )

    def _validate_character(self, payload: dict) -> ValidationResult:
        """Validate character output: must have appearance cards with 4 dimensions."""
        errors = []
        warnings = []

        output = payload.get("output", {})
        if not output:
            output = payload

        characters = output.get("characters", [])

        if not characters:
            errors.append("没有生成任何角色信息")
            return ValidationResult(
                passed=False, agent_id="character", errors=errors,
                fix_suggestion="请重新生成角色信息。",
            )

        for char in characters:
            name = char.get("name", "未命名")
            appearance = char.get("appearance", {})

            if isinstance(appearance, str):
                warnings.append(f"角色 '{name}' 的外观描述是纯文本，缺少结构化维度")
                continue

            if not isinstance(appearance, dict):
                errors.append(f"角色 '{name}' 的外观格式异常: {type(appearance)}")
                continue

            # Check 4 dimensions
            missing_dims = []
            for dim in ["hair", "body", "cloth", "face"]:
                val = appearance.get(dim, "")
                if not val or len(val.strip()) < 5:
                    missing_dims.append(dim)

            if missing_dims:
                errors.append(
                    f"角色 '{name}' 缺少外观维度: {', '.join(missing_dims)}"
                )

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="character",
            errors=errors,
            warnings=warnings,
            fix_suggestion=(
                "以下角色的外观描述不完整，请在重试时强调四个维度都必须填写："
                + "; ".join(errors)
            ) if errors else "",
        )

    def _validate_storyboard(self, payload: dict) -> ValidationResult:
        """Validate storyboard: scene count, character references, prompt quality."""
        errors = []
        warnings = []

        output = payload.get("output", {})
        if not output:
            output = payload

        storyboard = output.get("storyboard", [])

        if not storyboard:
            errors.append("没有生成任何分镜场景")
            return ValidationResult(
                passed=False, agent_id="storyboard", errors=errors,
                fix_suggestion="请重新生成分镜，确保每个剧集都有对应的场景。",
            )

        if len(storyboard) < 3:
            warnings.append(f"总场景数较少（{len(storyboard)}个），视频可能过短")

        for i, scene in enumerate(storyboard):
            scene_no = scene.get("scene_no", i + 1)

            prompt = scene.get("prompt", "")
            if not prompt or len(prompt) < 20:
                errors.append(f"场景 {scene_no} 的图像 prompt 过短或为空")

            # Check if character names are referenced in the prompt
            characters = scene.get("characters", [])
            if characters and prompt:
                for char_name in characters:
                    # Allow partial match (English transliteration might differ)
                    if char_name not in prompt:
                        # Check if any part of the name is in the prompt
                        if not any(
                            part in prompt for part in char_name
                            if len(part) > 1
                        ):
                            warnings.append(
                                f"场景 {scene_no}: 角色 '{char_name}' 可能未在 prompt 中引用"
                            )

            duration = scene.get("duration", 0)
            if duration < 3 or duration > 15:
                errors.append(f"场景 {scene_no} 时长异常: {duration}秒 (范围3-15)")

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="storyboard",
            errors=errors,
            warnings=warnings,
            fix_suggestion=(
                "分镜质量问题：" + "; ".join(errors)
            ) if errors else "",
        )

    def _validate_image(self, payload: dict) -> ValidationResult:
        """Validate image output: images exist and have valid paths."""
        errors = []
        warnings = []

        output = payload.get("output", {})
        if not output:
            output = payload

        images = output.get("images", [])
        storyboard_count = output.get("_storyboard_count", 0)

        if not images:
            errors.append("没有成功生成任何图片")
        elif storyboard_count and len(images) < storyboard_count:
            errors.append(
                f"图片生成不完整: {len(images)}/{storyboard_count}"
            )
            warnings.append("部分场景的图片生成失败，视频将使用可用图片")

        for img in images:
            scene_no = img.get("scene_no", "?")
            image_url = img.get("image_url", "")
            if not image_url:
                errors.append(f"场景 {scene_no} 缺少图片 URL")

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="image",
            errors=errors,
            warnings=warnings,
            fix_suggestion="" if not images else "部分图片生成失败，可以重试失败的场景。",
        )

    def _validate_voice(self, payload: dict) -> ValidationResult:
        """Validate voice output: audio files exist."""
        errors = []
        warnings = []

        output = payload.get("output", {})
        if not output:
            output = payload

        audios = output.get("audios", [])

        if not audios:
            errors.append("没有成功生成任何配音")

        for aud in audios:
            scene_no = aud.get("scene_no", "?")
            audio_url = aud.get("audio_url", "")
            if not audio_url:
                errors.append(f"场景 {scene_no} 缺少配音 URL")
            duration = aud.get("duration", 0)
            if duration and duration < 0.5:
                warnings.append(f"场景 {scene_no} 的配音时长过短: {duration}秒")

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="voice",
            errors=errors,
            warnings=warnings,
            fix_suggestion="" if not errors else "部分配音生成失败，可以重试失败的场景。",
        )

    def _validate_video(self, payload: dict) -> ValidationResult:
        """Validate video output: final video file exists."""
        errors = []
        warnings = []

        output = payload.get("output", {})
        if not output:
            output = payload

        video_path = output.get("video_path", "")

        if not video_path:
            errors.append("没有生成最终视频文件")
        else:
            import os
            if not os.path.exists(video_path):
                errors.append(f"视频文件不存在: {video_path}")

        return ValidationResult(
            passed=len(errors) == 0,
            agent_id="video",
            errors=errors,
            warnings=warnings,
            fix_suggestion="视频合成失败，请检查图片和配音是否都已正确生成。",
        )


def create_quality_gate_handler() -> HookHandler:
    """Create a quality gate hook handler for AFTER_AGENT events."""
    handler = QualityGateHandler()
    return handler.handle