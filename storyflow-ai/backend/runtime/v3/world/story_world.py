"""StoryWorld — AI 漫剧的核心知识资产.

不是聊天记录，不是 Chat History，而是结构化的世界模型。
参考影视编剧的 Story Bible，用 Git 式状态管理保持最新。

所有 Agent 只读 StoryWorld，不自己总结。
Image Agent 根据 Character Library 生成 Prompt，
而非"根据上一张图"。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Character Library
# ──────────────────────────────────────────────

class CharacterAppearance(BaseModel):
    """角色外观四维度 — 所有 Image Agent 的唯一真相源."""
    hair: str = ""       # e.g. "long straight black hair with bangs"
    body: str = ""       # e.g. "slender, 165cm, pale skin"
    cloth: str = ""      # e.g. "white school uniform with blue ribbon"
    face: str = ""       # e.g. "large amber eyes, small nose, gentle smile"


class CharacterProfile(BaseModel):
    """角色完整档案 — 存入 Character Library，全管线共享."""
    name: str
    gender: str = ""
    age: str = ""
    appearance: CharacterAppearance = Field(default_factory=CharacterAppearance)
    personality: list[str] = Field(default_factory=list)
    catchphrase: str = ""
    backstory: str = ""
    current_state: dict[str, Any] = Field(default_factory=dict)  # "injured", "location": "forest"
    reference_images: list[str] = Field(default_factory=list)    # 已生成的参考图路径

    def to_prompt_fragment(self) -> str:
        """生成供 Image Agent 直接使用的英文 Prompt 片段."""
        a = self.appearance
        parts = [f"{a.hair}", f"{a.body}", f"wearing {a.cloth}", f"{a.face}"]
        return ", ".join(p for p in parts if p)


# ──────────────────────────────────────────────
# Location Library
# ──────────────────────────────────────────────

class LocationProfile(BaseModel):
    """场景地点档案."""
    name: str
    description: str = ""       # e.g. "ancient temple with overgrown vines"
    visual_style: str = ""      # e.g. "dark gothic, soft moonlight"
    atmosphere: str = ""        # e.g. "mysterious, sacred"
    reference_images: list[str] = Field(default_factory=list)

    def to_prompt_fragment(self) -> str:
        """生成供 Image Agent 直接使用的背景 Prompt 片段."""
        parts = [self.description, self.visual_style]
        return ", ".join(p for p in parts if p).strip()


# ──────────────────────────────────────────────
# Relationship Graph
# ──────────────────────────────────────────────

class RelationType(str, Enum):
    FRIEND = "friend"
    ENEMY = "enemy"
    LOVER = "lover"
    FAMILY = "family"
    MENTOR = "mentor"
    RIVAL = "rival"
    MASTER = "master"
    SUBORDINATE = "subordinate"
    CUSTOM = "custom"


class Relationship(BaseModel):
    """角色间关系."""
    character_a: str
    character_b: str
    type: RelationType
    description: str = ""       # e.g. "former classmates, now estranged"
    since_episode: int = 1      # 从第几集开始
    current: bool = True        # 当前是否仍有效


# ──────────────────────────────────────────────
# Timeline
# ──────────────────────────────────────────────

class TimelineEvent(BaseModel):
    """时间线事件 — 像 Git commit 一样记录世界状态变更."""
    episode: int
    scene: int = 0
    event_type: str = ""        # "character_injured", "location_discovered", "relationship_change"
    description: str = ""
    affected_characters: list[str] = Field(default_factory=list)
    state_changes: dict[str, Any] = Field(default_factory=dict)  # {"林晓": {"current_state": {"injured": true}}}
    timestamp: float = Field(default_factory=time.time)


# ──────────────────────────────────────────────
# Lore (世界观设定)
# ──────────────────────────────────────────────

class LoreEntry(BaseModel):
    """世界观设定条目."""
    key: str                    # e.g. "magic_system", "technology_level"
    name: str
    content: str
    category: str = ""          # "world", "culture", "technology", "magic", "history"


# ──────────────────────────────────────────────
# Story Bible (故事大纲)
# ──────────────────────────────────────────────

class StoryBible(BaseModel):
    """故事圣经 — 整部作品的顶层设定."""
    title: str = ""
    genre: str = ""
    theme: str = ""
    premise: str = ""           # 一句话概括
    synopsis: str = ""          # 完整梗概
    target_audience: str = ""
    visual_style: str = ""      # "anime", "manhwa", "comic", "watercolor"
    tone: str = ""              # "dark", "lighthearted", "epic", "romantic"
    total_episodes: int = 0
    custom_rules: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# StoryWorld — 顶层容器
# ──────────────────────────────────────────────

class StoryWorld(BaseModel):
    """StoryWorld — 整个漫剧项目的唯一真相源.

    所有 Agent 只读这里。
    每次变更产生 Timeline Event（像 Git commit）。
    永远保持最新状态。
    """

    # 核心组件
    story_bible: StoryBible = Field(default_factory=StoryBible)
    characters: dict[str, CharacterProfile] = Field(default_factory=dict)   # name → profile
    locations: dict[str, LocationProfile] = Field(default_factory=dict)     # name → profile
    relationships: list[Relationship] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    lore: list[LoreEntry] = Field(default_factory=list)

    # 元信息
    version: int = 0            # 每次 commit 递增
    story_id: str = ""
    project_id: str = ""

    # ── Character Operations ──

    def add_character(self, profile: CharacterProfile) -> TimelineEvent:
        """添加角色，生成 Timeline Event."""
        self.characters[profile.name] = profile
        self.version += 1
        event = TimelineEvent(
            episode=0, event_type="character_added",
            description=f"角色 {profile.name} 加入故事",
            affected_characters=[profile.name],
            state_changes={profile.name: profile.model_dump()},
        )
        self.timeline.append(event)
        logger.info("[StoryWorld] v%d character_added: %s", self.version, profile.name)
        return event

    def update_character_state(self, name: str, changes: dict[str, Any],
                               episode: int = 0, scene: int = 0) -> TimelineEvent | None:
        """更新角色状态（受伤/换装/位置变更等），像 Git commit.

        Example:
            world.update_character_state("林晓", {"current_state": {"injured": True}}, episode=5)
        """
        if name not in self.characters:
            logger.warning("[StoryWorld] Character not found: %s", name)
            return None

        old_state = self.characters[name].current_state.copy()
        # Deep merge changes into current_state
        self._deep_merge(self.characters[name].current_state, changes)
        self.version += 1

        event = TimelineEvent(
            episode=episode, scene=scene,
            event_type="character_state_change",
            description=f"{name} 状态变更: {json.dumps(changes, ensure_ascii=False)}",
            affected_characters=[name],
            state_changes={name: {"old": old_state, "new": self.characters[name].current_state}},
        )
        self.timeline.append(event)
        logger.info("[StoryWorld] v%d character_state_change: %s → %s", self.version, name, changes)
        return event

    def apply_patch(self, name: str, field_path: str, old_value: Any, new_value: Any,
                    episode: int = 0) -> TimelineEvent | None:
        """应用用户 Patch — 精确修改角色某个字段.

        Example:
            world.apply_patch("林晓", "appearance.cloth", "white dress", "black armor", episode=3)
            → 以后所有 Image 自动使用 "black armor"
        """
        if name not in self.characters:
            return None

        profile = self.characters[name]
        # Navigate field path like "appearance.cloth"
        parts = field_path.split(".")
        obj = profile
        for part in parts[:-1]:
            obj = getattr(obj, part, None)
            if obj is None:
                logger.warning("[StoryWorld] Field path invalid: %s", field_path)
                return None

        current_value = getattr(obj, parts[-1], None)
        if current_value != old_value:
            logger.warning("[StoryWorld] Patch old_value mismatch: expected %s, got %s",
                           old_value, current_value)

        setattr(obj, parts[-1], new_value)
        self.version += 1

        event = TimelineEvent(
            episode=episode, event_type="user_patch",
            description=f"用户 Patch: {name}.{field_path} {old_value} → {new_value}",
            affected_characters=[name],
            state_changes={name: {field_path: {"old": old_value, "new": new_value}}},
        )
        self.timeline.append(event)
        logger.info("[StoryWorld] v%d user_patch: %s.%s", self.version, name, field_path)
        return event

    # ── Location Operations ──

    def add_location(self, profile: LocationProfile) -> TimelineEvent:
        """添加地点."""
        self.locations[profile.name] = profile
        self.version += 1
        event = TimelineEvent(
            episode=0, event_type="location_added",
            description=f"地点 {profile.name} 加入故事",
        )
        self.timeline.append(event)
        logger.info("[StoryWorld] v%d location_added: %s", self.version, profile.name)
        return event

    # ── Relationship Operations ──

    def add_relationship(self, rel: Relationship) -> TimelineEvent:
        """添加角色关系."""
        self.relationships.append(rel)
        self.version += 1
        event = TimelineEvent(
            episode=0, event_type="relationship_added",
            description=f"{rel.character_a} → {rel.character_b}: {rel.type.value}",
            affected_characters=[rel.character_a, rel.character_b],
        )
        self.timeline.append(event)
        return event

    # ── Query Operations ──

    def get_character(self, name: str) -> CharacterProfile | None:
        """获取角色档案."""
        return self.characters.get(name)

    def get_characters_in_scene(self, scene_characters: list[str]) -> list[CharacterProfile]:
        """获取场景中所有角色的完整档案."""
        return [self.characters[n] for n in scene_characters if n in self.characters]

    def build_image_prompt_context(self, character_names: list[str],
                                    location_name: str | None = None) -> str:
        """构建 Image Agent 的完整 Prompt 上下文.

        直接拼出角色外观 + 地点背景，Agent 不需要"记住"之前的内容。
        """
        parts = []

        for name in character_names:
            profile = self.characters.get(name)
            if profile:
                parts.append(f"Character '{name}': {profile.to_prompt_fragment()}")

        if location_name and location_name in self.locations:
            loc = self.locations[location_name]
            parts.append(f"Background: {loc.to_prompt_fragment()}")

        if self.story_bible.visual_style:
            parts.append(f"Art style: {self.story_bible.visual_style}")

        return " | ".join(parts)

    def get_relationship_between(self, name_a: str, name_b: str) -> list[Relationship]:
        """查询两个角色间的关系."""
        return [
            r for r in self.relationships
            if r.current and {r.character_a, r.character_b} == {name_a, name_b}
        ]

    def get_character_history(self, name: str) -> list[TimelineEvent]:
        """获取角色的完整时间线（所有相关事件）."""
        return [e for e in self.timeline if name in e.affected_characters]

    # ── Serialization ──

    def to_dict(self) -> dict:
        """序列化为 dict（用于 Checkpoint 存储）."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "StoryWorld":
        """从 dict 反序列化（用于 Checkpoint 恢复）."""
        return cls.model_validate(data)

    def compute_fingerprint(self) -> str:
        """计算当前状态的指纹（用于快速比对是否变更）."""
        content = json.dumps(self.model_dump(exclude={"timeline"}), sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()[:12]

    # ── Internal ──

    @staticmethod
    def _deep_merge(base: dict, overlay: dict):
        """递归合并字典."""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                StoryWorld._deep_merge(base[key], value)
            else:
                base[key] = value