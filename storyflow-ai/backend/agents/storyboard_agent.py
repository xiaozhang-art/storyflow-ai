"""Storyboard Agent - converts script to scene-by-scene storyboard."""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from utils.json_helper import parse_json_response
from workflows.state import StoryState
from app.llm import get_precise_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位资深动画分镜师，擅长将剧本拆解为精确的分镜脚本。
你需要根据每集的剧本内容，生成逐场景的分镜描述，每个场景将用于AI图像生成。

分镜原则：
1. **镜头语言**：合理运用远景、中景、近景、特写、俯拍、仰拍等镜头
2. **场景切换**：每个场景之间要有自然的过渡逻辑
3. **角色一致性**：场景描述中必须精确引用角色外观，确保AI生成图像时角色形象一致
4. **时长合理**：每个场景3-8秒，对话场景适当延长
5. **画面构图**：每个场景的prompt要包含画面构图、光影、色调等细节

可用镜头类型：
- 远景（wide shot）：展示环境和氛围
- 中景（medium shot）：展示人物上半身和互动
- 近景（close-up）：展示人物面部表情
- 特写（extreme close-up）：展示细节（眼睛、手、物品）
- 俯拍（high angle shot）：从上往下看
- 仰拍（low angle shot）：从下往上看

输出必须是合法JSON数组，每个元素格式：
{"scene": 1, "camera": "中景", "duration": 5, "prompt": "英文图像生成prompt", "characters": ["角色A"], "dialogue": "台词"}
"""

USER_PROMPT_TEMPLATE = """\
请为以下剧集生成分镜脚本：

## 剧集信息
第{episode_no}集：{title}
剧情概要：{summary}

## 完整剧本
{script}

## 角色外观参考（请严格保持一致）
{character_descriptions}

## 要求
1. 根据剧本内容，将每个关键场景拆分为独立的分镜
2. 每个场景的prompt必须用英文编写，格式为：
   "anime style, [镜头类型], [场景环境描述], [角色外观描述], [动作/表情描述], [光影/氛围], high quality, detailed"
3. 角色外观必须完整引用上面的参考信息
4. 每个场景的dialogue字段填写该场景对应的台词，无台词则为空字符串
5. 每集生成5-10个场景

请直接输出JSON数组，不要包含其他文字。
"""


def _build_character_descriptions(characters: list[dict]) -> str:
    """Build a formatted string of character appearance descriptions."""
    parts = []
    for char in characters:
        name = char.get("name", "未命名")
        appearance = char.get("appearance", {})
        if isinstance(appearance, dict):
            hair = appearance.get("hair", "")
            body = appearance.get("body", "")
            cloth = appearance.get("cloth", "")
            face = appearance.get("face", "")
            desc = f"{name}: {hair}, {face}, {body}, wearing {cloth}"
        else:
            desc = f"{name}: {appearance}"
        parts.append(desc)
    return "\n".join(parts)


def _validate_scenes(scenes: list[dict]) -> list[dict]:
    """Validate and normalize scene data."""
    valid = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        valid.append({
            "scene": scene.get("scene", i + 1),
            "camera": scene.get("camera", "中景"),
            "duration": max(3, min(15, int(scene.get("duration", 5)))),
            "prompt": scene.get("prompt", ""),
            "characters": scene.get("characters", []),
            "dialogue": scene.get("dialogue", ""),
        })
    return valid


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda retry_state: logger.warning(
        "Storyboard generation retry %d/3 for episode",
        retry_state.attempt_number,
    ),
)
async def _generate_storyboard_for_episode(
    episode: dict,
    character_descriptions: str,
    llm: ChatOpenAI,
) -> list[dict]:
    """Generate storyboard scenes for a single episode with retry."""
    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT_TEMPLATE),
    ])

    chain = chat_prompt | llm

    response = await chain.ainvoke({
        "episode_no": episode.get("episode_no", 1),
        "title": episode.get("title", ""),
        "summary": episode.get("summary", ""),
        "script": episode.get("script", ""),
        "character_descriptions": character_descriptions,
    })

    raw_text = response.content.strip()
    scenes = parse_json_response(raw_text)

    if not isinstance(scenes, list):
        # Wrap single object in list
        scenes = [scenes] if isinstance(scenes, dict) else []

    # Validate
    scenes = _validate_scenes(scenes)

    # Tag each scene with its episode number
    for scene in scenes:
        scene["episode_no"] = episode.get("episode_no", 1)

    return scenes


async def storyboard_agent(state: StoryState) -> dict:
    """
    Storyboard generation agent.
    Takes episodes and enriched character data from state, and for each
    episode calls the LLM to produce a scene-by-scene storyboard suitable
    for image generation.
    """
    logger.info(
        "storyboard_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    try:
        episodes = state.get("episodes", [])
        characters = state.get("characters", [])

        if not episodes:
            raise ValueError("No episodes found in state.")
        if not characters:
            raise ValueError("No characters found in state.")

        character_descriptions = _build_character_descriptions(characters)

        llm = get_precise_llm()

        all_scenes: list[dict] = []
        for episode in episodes:
            logger.info(
                "Generating storyboard for episode %d | task_id=%s",
                episode.get("episode_no", 0),
                state.get("task_id"),
            )
            scenes = await _generate_storyboard_for_episode(
                episode, character_descriptions, llm
            )
            all_scenes.extend(scenes)

        # Assign global scene number
        for idx, scene in enumerate(all_scenes, 1):
            scene["scene_no"] = idx

        logger.info(
            "storyboard_agent completed | %d total scenes | task_id=%s",
            len(all_scenes),
            state.get("task_id"),
        )

        return {
            "storyboard": all_scenes,
            "current_step": "storyboard",
            "status": "storyboard_done",
            "error": "",
        }

    except Exception as exc:
        logger.exception("storyboard_agent failed | task_id=%s", state.get("task_id"))
        return {
            "current_step": "storyboard",
            "status": "error",
            "error": f"Storyboard generation failed: {exc}",
        }