"""Quality Engine — 不是 Reviewer Agent，而是结构化的多 Checker 审核引擎.

核心思想：
- 每个产出物经过多个 Checker
- 每个 Checker 独立返回 PASS / FAIL / RETRY / ASK_USER
- ASK_USER 触发 Human Review Checkpoint
- 用户反馈生成 Patch，更新 StoryWorld，后续自动采用

不是"一个 Prompt 让 LLM 判断质量"，
而是"多个确定性 Checker + 必要时才问人"。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Checker Result
# ──────────────────────────────────────────────

class CheckResult(str, Enum):
    """Checker 判定结果."""
    PASS = "pass"              # 通过，继续
    FAIL = "fail"              # 失败，终止当前步骤
    RETRY = "retry"            # 重试当前步骤（带 hint）
    ASK_USER = "ask_user"      # 暂停，等待人工审核


@dataclass
class CheckerOutput:
    """单个 Checker 的输出."""
    checker_name: str
    result: CheckResult
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    hint: str = ""             # RETRY 时的修复提示
    patch_suggestion: dict[str, Any] | None = None  # ASK_USER 时的 Patch 建议


@dataclass
class QualityReport:
    """一次质量审核的完整报告."""
    step: str
    artifact_type: str         # "script", "character", "storyboard", "image", "voice", "video"
    checkers: list[CheckerOutput] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.result == CheckResult.PASS for c in self.checkers)

    @property
    def worst_result(self) -> CheckResult:
        """最严重的判定结果 — 决定后续动作."""
        priority = [CheckResult.ASK_USER, CheckResult.FAIL, CheckResult.RETRY, CheckResult.PASS]
        for r in priority:
            if any(c.result == r for c in self.checkers):
                return r
        return CheckResult.PASS

    @property
    def retry_hints(self) -> list[str]:
        return [c.hint for c in self.checkers if c.result == CheckResult.RETRY and c.hint]

    @property
    def failed_checkers(self) -> list[str]:
        return [c.checker_name for c in self.checkers if c.result != CheckResult.PASS]


# ──────────────────────────────────────────────
# Base Checker
# ──────────────────────────────────────────────

class BaseChecker(ABC):
    """所有 Checker 的基类."""

    @property
    def name(self) -> string:
        return self.__class__.__name__

    @abstractmethod
    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        """检查产出物.

        Args:
            artifact: 待检查的产出物（类型取决于步骤）
            context: 上下文信息，包含 StoryWorld、当前 episode/scene 等

        Returns:
            CheckerOutput
        """
        ...


# ──────────────────────────────────────────────
# Built-in Checkers
# ──────────────────────────────────────────────

class CharacterConsistencyChecker(BaseChecker):
    """检查角色一致性 — 对比产出物与 StoryWorld Character Library."""

    REQUIRED_DIMENSIONS = ["hair", "body", "cloth", "face"]

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        world = context.get("story_world")
        if not world:
            return CheckerOutput(self.name, CheckResult.PASS, "No StoryWorld, skip")

        prompt = ""
        if isinstance(artifact, dict):
            prompt = artifact.get("prompt", "") or artifact.get("image_prompt", "")
        elif isinstance(artifact, str):
            prompt = artifact

        if not prompt:
            return CheckerOutput(self.name, CheckResult.PASS, "No prompt to check")

        # 找出 prompt 中提到的角色
        mentioned_chars = []
        for name, profile in world.characters.items():
            if name in prompt or any(
                kw in prompt.lower() for kw in name.lower().split()
            ):
                mentioned_chars.append((name, profile))

        if not mentioned_chars:
            return CheckerOutput(self.name, CheckResult.PASS, "No known characters in prompt")

        missing_features = []
        for name, profile in mentioned_chars:
            fragment = profile.to_prompt_fragment().lower()
            for dim in self.REQUIRED_DIMENSIONS:
                # Check if the dimension value appears in the prompt
                dim_value = getattr(profile.appearance, dim, "")
                if dim_value and dim_value.lower() not in prompt.lower():
                    missing_features.append(f"{name}.{dim}")

        if missing_features:
            # Build hint with correct descriptions
            hints = []
            for name, profile in mentioned_chars:
                hints.append(f"{name}: {profile.to_prompt_fragment()}")
            return CheckerOutput(
                self.name, CheckResult.RETRY,
                f"角色特征缺失: {', '.join(missing_features)}",
                details={"missing": missing_features},
                hint="请确保以下角色外观描述完整:\n" + "\n".join(hints),
            )

        return CheckerOutput(self.name, CheckResult.PASS, "Character consistency OK")


class SceneContinuityChecker(BaseChecker):
    """检查场景连续性 — 对比分镜与 Timeline."""

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        world = context.get("story_world")
        episode = context.get("episode", 0)
        scene_no = context.get("scene_no", 0)

        if not world or not world.timeline:
            return CheckerOutput(self.name, CheckResult.PASS, "No timeline, skip")

        # Check if scene respects recent state changes
        issues = []
        recent_events = [
            e for e in world.timeline
            if e.episode <= episode and e.event_type == "character_state_change"
        ]

        for event in recent_events:
            for char_name, change in event.state_changes.items():
                new_state = change.get("new", {})
                if isinstance(new_state, dict) and new_state.get("injured"):
                    # If character is injured, check if scene acknowledges it
                    if isinstance(artifact, dict):
                        prompt = artifact.get("prompt", "")
                        dialogue = artifact.get("dialogue", "")
                        content = f"{prompt} {dialogue}"
                        if char_name in content and "injured" not in content.lower() and "伤" not in content:
                            issues.append(f"{char_name} 已受伤但场景未体现")

        if issues:
            return CheckerOutput(
                self.name, CheckResult.RETRY,
                "场景连续性问题: " + "; ".join(issues),
                hint="请参考 Timeline 最近事件调整场景内容",
            )

        return CheckerOutput(self.name, CheckResult.PASS, "Scene continuity OK")


class ScriptStructureChecker(BaseChecker):
    """检查剧本结构完整性."""

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        if not isinstance(artifact, dict):
            return CheckerOutput(self.name, CheckResult.PASS, "Not a dict, skip")

        episodes = artifact.get("episodes", [])
        world = context.get("story_world")

        issues = []

        # 1. Check episode count
        if len(episodes) < 1:
            issues.append("至少需要 1 集")
        if world and world.story_bible.total_episodes > 0:
            if len(episodes) != world.story_bible.total_episodes:
                issues.append(f"集数不匹配: 期望 {world.story_bible.total_episodes}, 实际 {len(episodes)}")

        # 2. Check each episode
        for i, ep in enumerate(episodes):
            if not ep.get("title"):
                issues.append(f"第 {i+1} 集缺少标题")
            if not ep.get("summary") or len(ep.get("summary", "")) < 20:
                issues.append(f"第 {i+1} 集摘要太短")

        # 3. Check character count (2-8)
        if world:
            char_count = len(world.characters)
            if char_count < 2:
                issues.append(f"角色太少: {char_count} (最少 2)")
            elif char_count > 8:
                issues.append(f"角色太多: {char_count} (最多 8)")

        if issues:
            return CheckerOutput(
                self.name, CheckResult.RETRY if len(issues) <= 3 else CheckResult.FAIL,
                "剧本结构问题: " + "; ".join(issues),
                hint="请修正: " + "; ".join(issues),
            )

        return CheckerOutput(self.name, CheckResult.PASS, "Script structure OK")


class DialogueChecker(BaseChecker):
    """检查对话质量 — 台词与角色人设是否匹配."""

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        world = context.get("story_world")
        if not world:
            return CheckerOutput(self.name, CheckResult.PASS, "No StoryWorld, skip")

        dialogue = ""
        character_name = context.get("character_name", "")

        if isinstance(artifact, dict):
            dialogue = artifact.get("dialogue", "")
            character_name = artifact.get("character_name", "") or character_name

        if not dialogue or not character_name:
            return CheckerOutput(self.name, CheckResult.PASS, "No dialogue to check")

        profile = world.get_character(character_name)
        if not profile:
            return CheckerOutput(self.name, CheckResult.PASS, f"Unknown character: {character_name}")

        # Check if dialogue matches personality
        issues = []
        if profile.catchphrase and profile.catchphrase not in dialogue:
            # Only warn, not fail — not every line needs catchphrase
            pass

        # Check for out-of-character indicators (basic heuristic)
        if profile.personality:
            personality_text = " ".join(profile.personality).lower()
            # If character is "gentle" but dialogue has aggressive words
            aggressive_words = ["杀", "毁灭", "去死", "消灭"]
            if "gentle" in personality_text or "温柔" in personality_text:
                for word in aggressive_words:
                    if word in dialogue:
                        issues.append(f"角色 {character_name} 性格温和但台词含攻击性词汇 '{word}'")

        if issues:
            return CheckerOutput(
                self.name, CheckResult.RETRY,
                "对话与角色人设不匹配: " + "; ".join(issues),
                hint=f"角色 {character_name} 的性格: {', '.join(profile.personality)}",
            )

        return CheckerOutput(self.name, CheckResult.PASS, "Dialogue OK")


class SafetyChecker(BaseChecker):
    """安全检查 — 内容安全过滤."""

    BLOCKED_KEYWORDS = [
        # Basic content safety — extend as needed
        "gore", "extreme violence", "nsfw",
    ]

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        content = ""
        if isinstance(artifact, dict):
            content = " ".join(str(v) for v in artifact.values())
        elif isinstance(artifact, str):
            content = artifact

        if not content:
            return CheckerOutput(self.name, CheckResult.PASS, "Empty content, skip")

        found = [kw for kw in self.BLOCKED_KEYWORDS if kw.lower() in content.lower()]
        if found:
            return CheckerOutput(
                self.name, CheckResult.FAIL,
                f"内容安全问题: {', '.join(found)}",
                hint=f"请移除以下内容: {', '.join(found)}",
            )

        return CheckerOutput(self.name, CheckResult.PASS, "Safety OK")


class StyleChecker(BaseChecker):
    """风格一致性检查 — 产出物是否符合 Story Bible 定义的视觉风格."""

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        world = context.get("story_world")
        if not world or not world.story_bible.visual_style:
            return CheckerOutput(self.name, CheckResult.PASS, "No style defined, skip")

        prompt = ""
        if isinstance(artifact, dict):
            prompt = artifact.get("prompt", "") or artifact.get("image_prompt", "")
        elif isinstance(artifact, str):
            prompt = artifact

        if not prompt:
            return CheckerOutput(self.name, CheckResult.PASS, "No prompt, skip")

        style = world.story_bible.visual_style.lower()
        if style not in prompt.lower():
            return CheckerOutput(
                self.name, CheckResult.RETRY,
                f"Prompt 缺少视觉风格 '{style}'",
                hint=f"请在 prompt 中加入风格关键词: {style}",
            )

        return CheckerOutput(self.name, CheckResult.PASS, f"Style '{style}' present")


class FileExistenceChecker(BaseChecker):
    """文件存在性检查 — 产出物文件是否真实生成."""

    def __init__(self, file_key: str = "file_path"):
        self.file_key = file_key

    def check(self, artifact: Any, context: dict[str, Any]) -> CheckerOutput:
        import os

        path = ""
        if isinstance(artifact, dict):
            path = artifact.get(self.file_key, "") or artifact.get("path", "")
        elif isinstance(artifact, str):
            path = artifact

        if not path:
            return CheckerOutput(
                self.name, CheckResult.FAIL,
                "No file path in artifact",
                hint="Agent 未返回文件路径",
            )

        if not os.path.isfile(path):
            return CheckerOutput(
                self.name, CheckResult.RETRY,
                f"文件不存在: {path}",
                hint=f"文件 {path} 未生成，请重试",
            )

        return CheckerOutput(self.name, CheckResult.PASS, f"File exists: {path}")


# ──────────────────────────────────────────────
# Quality Engine
# ──────────────────────────────────────────────

# Default checker sets per step
DEFAULT_CHECKERS: dict[str, list[type[BaseChecker]]] = {
    "script": [ScriptStructureChecker, SafetyChecker],
    "character": [CharacterConsistencyChecker, SafetyChecker],
    "storyboard": [SceneContinuityChecker, StyleChecker, SafetyChecker],
    "image": [CharacterConsistencyChecker, StyleChecker, FileExistenceChecker],
    "voice": [FileExistenceChecker],
    "video": [FileExistenceChecker],
}


class QualityEngine:
    """质量审核引擎.

    不是 Agent，不是 Prompt，而是结构化的多 Checker 管线。
    每个步骤配置自己的 Checker 集合。
    """

    def __init__(self):
        self._checkers: dict[str, list[BaseChecker]] = {}
        self._human_review_callback: Callable[[str, dict], Awaitable[dict | None]] | None = None

    def register_checkers(self, step: str, checkers: list[BaseChecker]):
        """为某个步骤注册 Checker 列表."""
        self._checkers[step] = checkers

    def set_human_review_callback(
        self, callback: Callable[[str, dict], Awaitable[dict | None]]
    ):
        """设置人工审核回调.

        当任何 Checker 返回 ASK_USER 时触发。
        callback(review_id, review_info) → user_feedback or None
        """
        self._human_review_callback = callback

    def setup_defaults(self):
        """加载默认 Checker 配置."""
        for step, checker_classes in DEFAULT_CHECKERS.items():
            self._checkers[step] = [cls() for cls in checker_classes]
        logger.info("[QualityEngine] Loaded default checkers for steps: %s",
                     list(DEFAULT_CHECKERS.keys()))

    async def check(self, step: str, artifact: Any,
                    context: dict[str, Any]) -> QualityReport:
        """执行质量审核.

        Returns:
            QualityReport — 包含每个 Checker 的结果
        """
        report = QualityReport(step=step, artifact_type=step)
        checkers = self._checkers.get(step, [])

        if not checkers:
            logger.debug("[QualityEngine] No checkers for step: %s", step)
            return report

        for checker in checkers:
            try:
                output = checker.check(artifact, context)
                report.checkers.append(output)
                logger.debug("[QualityEngine] %s → %s: %s",
                             step, checker.name, output.result.value)
            except Exception as e:
                logger.error("[QualityEngine] Checker %s error: %s", checker.name, e)
                report.checkers.append(CheckerOutput(
                    checker.name, CheckResult.FAIL,
                    f"Checker 异常: {e}",
                ))

        return report

    async def check_and_handle(self, step: str, artifact: Any,
                                context: dict[str, Any],
                                max_retries: int = 2) -> tuple[QualityReport, bool]:
        """检查并处理 — 自动重试 + 必要时触发人工审核.

        Returns:
            (final_report, should_continue)
            should_continue=False 表示需要停止（FAIL 或未通过人工审核）
        """
        for attempt in range(max_retries + 1):
            report = await self.check(step, artifact, context)

            if report.passed:
                return report, True

            worst = report.worst_result

            if worst == CheckResult.RETRY and attempt < max_retries:
                logger.info("[QualityEngine] %s retry %d/%d: %s",
                            step, attempt + 1, max_retries,
                            "; ".join(report.retry_hints))
                # Return retry info — caller is responsible for re-generating
                return report, False  # Signal: needs retry, caller handles

            if worst == CheckResult.ASK_USER and self._human_review_callback:
                logger.info("[QualityEngine] %s needs human review", step)
                review_info = {
                    "step": step,
                    "report": {
                        "failed_checkers": report.failed_checkers,
                        "messages": [c.message for c in report.checkers if c.result != CheckResult.PASS],
                        "patch_suggestion": next(
                            (c.patch_suggestion for c in report.checkers if c.patch_suggestion), None
                        ),
                    },
                }
                feedback = await self._human_review_callback(step, review_info)
                if feedback and feedback.get("approved"):
                    return report, True
                elif feedback and feedback.get("patch"):
                    # User provided a patch — apply to StoryWorld
                    patch = feedback["patch"]
                    world = context.get("story_world")
                    if world and patch.get("character_name") and patch.get("field_path"):
                        world.apply_patch(
                            patch["character_name"],
                            patch["field_path"],
                            patch.get("old_value", ""),
                            patch["new_value"],
                            episode=context.get("episode", 0),
                        )
                        logger.info("[QualityEngine] User patch applied: %s",
                                    json.dumps(patch, ensure_ascii=False))
                    return report, False  # Signal: needs retry with patched world
                else:
                    # User rejected
                    return report, False

            # FAIL or max retries exceeded
            logger.warning("[QualityEngine] %s failed after %d attempts: %s",
                           step, attempt + 1,
                           "; ".join(report.failed_checkers))
            return report, False

        return report, False


# Need json import for QualityEngine.check_and_handle
import json