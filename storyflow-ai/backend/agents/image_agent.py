"""Image Agent — generate images via Capability Registry (ComfyUI or Mock)."""

import logging
from pathlib import Path

from configs.settings import settings

logger = logging.getLogger(__name__)


async def image_agent(state: dict, context: dict) -> dict:
    """Image generation agent.

    v3 signature: (state, context) -> dict partial update.
    Uses context["use_capability"]("generate_image", ...) for actual generation.
    Falls back to placeholder images if capability fails or is unavailable.
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    characters = state.get("characters", [])
    use_capability = context.get("use_capability")
    story_world = context.get("story_world")

    logger.info("image_agent started | story_id=%s, %d scenes", story_id, len(storyboard))

    if not storyboard:
        logger.error("No storyboard scenes | story_id=%s", story_id)
        return {"images": [], "status": "error", "error": "No storyboard scenes."}

    images: list[dict] = []
    errors: list[str] = []

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "images"
    save_dir.mkdir(parents=True, exist_ok=True)

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        prompt_text = scene.get("prompt", "")

        if not prompt_text:
            errors.append(f"Scene {scene_no}: empty prompt")
            continue

        # Enrich prompt with StoryWorld character descriptions
        if story_world:
            scene_chars = scene.get("characters", [])
            location = scene.get("location", "")
            world_ctx = story_world.build_image_prompt_context(scene_chars, location)
            if world_ctx:
                prompt_text = f"{world_ctx}, {prompt_text}"

        output_path = str(save_dir / f"scene_{scene_no}.png")

        if use_capability:
            try:
                result = await use_capability("generate_image", {
                    "prompt": prompt_text,
                    "negative_prompt": (
                        "nsfw, nude, low quality, worst quality, blurry, deformed, "
                        "bad anatomy, bad hands, missing fingers, extra fingers, "
                        "watermark, text, signature, jpeg artifacts"
                    ),
                    "width": 1024,
                    "height": 1024,
                    "output_path": output_path,
                }, context)

                if result.get("success"):
                    images.append({
                        "scene_no": scene_no,
                        "image_path": result.get("file_path", output_path),
                        "image_url": f"/storage/stories/{story_id}/images/scene_{scene_no}.png",
                    })
                    logger.info("Image generated for scene %d", scene_no)
                    continue
                else:
                    logger.warning("Capability returned failure for scene %d: %s",
                                   scene_no, result.get("error"))
            except Exception as exc:
                logger.warning("Capability error for scene %d: %s", scene_no, exc)

        # Fallback: generate a placeholder image
        try:
            _create_placeholder(output_path, scene_no, prompt_text)
            images.append({
                "scene_no": scene_no,
                "image_path": output_path,
                "image_url": f"/storage/stories/{story_id}/images/scene_{scene_no}.png",
            })
            logger.info("Placeholder image created for scene %d", scene_no)
        except Exception as exc:
            errors.append(f"Scene {scene_no}: {exc}")

    error_msg = ""
    status = "image_done"
    if errors and not images:
        status = "error"
        error_msg = f"All image generations failed: {'; '.join(errors)}"
    elif errors:
        status = "image_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info("image_agent completed | %d/%d images | story_id=%s",
                len(images), len(storyboard), story_id)

    return {"images": images, "status": status, "error": error_msg}


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
    draw.text((512, 480), "(Placeholder - ComfyUI not connected)", fill="white", anchor="mm", font=font_small)

    # Show first 80 chars of prompt
    preview = prompt[:80] + "..." if len(prompt) > 80 else prompt
    draw.text((512, 550), preview, fill=(255, 255, 255, 180), anchor="mm", font=font_small)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")