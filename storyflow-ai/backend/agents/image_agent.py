"""Image Agent — generate images via cloud API (DashScope / OpenAI DALL-E / Mock).

All cloud APIs, no local GPU required. Provider is selected by IMAGE_API_PROVIDER env var.
"""

import asyncio
import base64
import logging
import random
import time
from pathlib import Path

import httpx

from configs.settings import settings

logger = logging.getLogger(__name__)


def _select_prompt(scene: dict, enriched_prompts: dict | None) -> tuple[str, bool]:
    """Select the best prompt for a scene.

    Priority:
        1. Enriched prompt (from PromptRuntime + Reflection)
        2. Original scene prompt

    Returns:
        (prompt_text, was_enriched)
    """
    scene_no = scene.get("scene_no", 0)
    if enriched_prompts and scene_no in enriched_prompts:
        return enriched_prompts[scene_no], True
    return scene.get("prompt", ""), False


async def image_agent(state: dict, context: dict) -> dict:
    """Image generation agent.

    Generates images for each storyboard scene, using enriched prompts
    when available (from PromptRuntime + ReflectionRuntime).

    The agent looks for '_enriched_scene_prompts' in the state dict,
    which is populated by WorkflowEngine._enrich_image_prompts().
    Enriched prompts include:
        - Character appearance constraints
        - Reflection suggestions from previous steps (storyboard/character)
        - World environment settings

    Args:
        state: Pipeline state with storyboard, characters, story_id,
               and optionally '_enriched_scene_prompts' (scene_no → enriched prompt)
        context: Runtime context

    Returns:
        dict with images list, status, and enrichment metadata
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    characters = state.get("characters", [])

    # V1.5: Check for enriched prompts from PromptRuntime + Reflection
    enriched_prompts = state.get("_enriched_scene_prompts")
    if enriched_prompts:
        logger.info(
            "image_agent received %d enriched prompts from PromptRuntime",
            len(enriched_prompts),
        )

    logger.info("image_agent started | story_id=%s, %d scenes", story_id, len(storyboard))

    if not storyboard:
        logger.error("No storyboard scenes | story_id=%s", story_id)
        return {"images": [], "status": "error", "error": "No storyboard scenes."}

    images: list[dict] = []
    errors: list[str] = []
    enriched_count = 0

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "images"
    save_dir.mkdir(parents=True, exist_ok=True)

    provider = settings.IMAGE_API_PROVIDER

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)

        # V1.5: Use enriched prompt if available, fall back to original
        prompt_text, was_enriched = _select_prompt(scene, enriched_prompts)
        if was_enriched:
            enriched_count += 1
            logger.debug(
                "Scene %d: using enriched prompt (%d chars, was %d chars)",
                scene_no, len(prompt_text),
                len(scene.get("prompt", "")),
            )

        if not prompt_text:
            errors.append(f"Scene {scene_no}: empty prompt")
            continue

        output_path = str(save_dir / f"scene_{scene_no}.png")

        if provider == "mock" or not settings.IMAGE_API_KEY:
            _create_placeholder(output_path, scene_no, prompt_text)
            images.append(_make_image_entry(story_id, scene_no, output_path))
            continue

        try:
            if provider in ("dashscope", "dashscope_image"):
                await _dashscope_generate(prompt_text, output_path, scene_no)
            elif provider == "openai":
                await _openai_generate(prompt_text, output_path, scene_no)
            else:
                logger.warning("Unknown image provider '%s', using mock", provider)
                _create_placeholder(output_path, scene_no, prompt_text)

            images.append(_make_image_entry(story_id, scene_no, output_path))
            logger.info("Image generated for scene %d via %s", scene_no, provider)

        except Exception as exc:
            logger.error("Image generation failed for scene %d: %s", scene_no, exc)
            errors.append(f"Scene {scene_no}: {exc}")
            # Fallback to placeholder
            try:
                _create_placeholder(output_path, scene_no, prompt_text)
                images.append(_make_image_entry(story_id, scene_no, output_path))
            except Exception:
                pass

    error_msg = ""
    status = "image_done"
    if errors and not images:
        status = "error"
        error_msg = f"All image generations failed: {'; '.join(errors)}"
    elif errors:
        status = "image_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info(
        "image_agent completed | %d/%d images | status=%s | "
        "enriched=%d/%d | story_id=%s",
        len(images), len(storyboard), status,
        enriched_count, len(storyboard), story_id,
    )

    return {
        "images": images,
        "status": status,
        "error": error_msg,
        "enrichment": {
            "scenes_total": len(storyboard),
            "scenes_enriched": enriched_count,
            "had_enriched_prompts": enriched_prompts is not None,
        },
    }


def _make_image_entry(story_id: str, scene_no: int, image_path: str) -> dict:
    return {
        "scene_no": scene_no,
        "image_path": image_path,
        "image_url": f"/storage/stories/{story_id}/images/scene_{scene_no}.png",
    }


# ── DashScope (通义万相) ──

async def _dashscope_generate(prompt: str, output_path: str, scene_no: int):
    """Generate image via DashScope Wanx API (async task + poll)."""
    api_key = settings.IMAGE_API_KEY
    base_url = settings.IMAGE_API_BASE_URL
    model = settings.IMAGE_MODEL
    size = settings.IMAGE_SIZE

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Submit task
    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": 1},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}/services/aigc/text2image/image-synthesis",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"DashScope: no task_id returned: {result}")

    # Poll for completion
    poll_url = f"{base_url}/tasks/{task_id}"
    for _ in range(settings.IMAGE_POLL_TIMEOUT // settings.IMAGE_POLL_INTERVAL):
        await asyncio.sleep(settings.IMAGE_POLL_INTERVAL)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(poll_url, headers=headers)
            resp_data = resp.json()

        task_status = resp_data.get("output", {}).get("task_status", "")
        if task_status == "SUCCEEDED":
            results = resp_data.get("output", {}).get("results", [])
            if not results:
                raise RuntimeError(f"DashScope: no results in response: {resp_data}")

            url = results[0].get("url", "")
            if url:
                # Download image
                async with httpx.AsyncClient(timeout=60) as dl_client:
                    img_resp = await dl_client.get(url)
                    img_resp.raise_for_status()
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(img_resp.content)
                return

            # Base64 fallback
            b64 = results[0].get("b64_image", "")
            if b64:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(base64.b64decode(b64))
                return

            raise RuntimeError(f"DashScope: no url or b64_image in result")

        elif task_status == "FAILED":
            error_msg = resp_data.get("output", {}).get("message", "unknown error")
            raise RuntimeError(f"DashScope task failed: {error_msg}")

    raise RuntimeError(f"DashScope: task {task_id} timed out after {settings.IMAGE_POLL_TIMEOUT}s")


# ── OpenAI DALL-E ──

async def _openai_generate(prompt: str, output_path: str, scene_no: int):
    """Generate image via OpenAI DALL-E API."""
    api_key = settings.IMAGE_API_KEY
    base_url = settings.IMAGE_API_BASE_URL
    model = getattr(settings, "IMAGE_MODEL", "dall-e-3")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{base_url}/images/generations",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    data = result.get("data", [])
    if not data:
        raise RuntimeError(f"OpenAI: no data in response: {result}")

    b64 = data[0].get("b64_json", "")
    if b64:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(base64.b64decode(b64))
        return

    url = data[0].get("url", "")
    if url:
        async with httpx.AsyncClient(timeout=60) as dl_client:
            img_resp = await dl_client.get(url)
            img_resp.raise_for_status()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(img_resp.content)
        return

    raise RuntimeError(f"OpenAI: no b64_json or url in response")


# ── Mock Placeholder ──

def _create_placeholder(path: str, scene_no: int, prompt: str):
    """Create a colored placeholder PNG with scene info."""
    from PIL import Image, ImageDraw, ImageFont

    colors = [
        (66, 133, 244), (234, 67, 53), (251, 188, 4),
        (52, 168, 83), (171, 71, 188), (0, 172, 193),
    ]
    color = colors[scene_no % len(colors)]

    img = Image.new("RGB", (1024, 1024), color)
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((512, 400), f"Scene {scene_no}", fill="white", anchor="mm", font=font_large)
    draw.text((512, 480), "(Placeholder - API not configured)", fill="white", anchor="mm", font=font_small)

    preview = prompt[:80] + "..." if len(prompt) > 80 else prompt
    draw.text((512, 550), preview, fill=(255, 255, 255, 180), anchor="mm", font=font_small)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")