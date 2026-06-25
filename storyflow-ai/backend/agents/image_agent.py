import asyncio
import logging
import os
from pathlib import Path

import httpx

from configs.settings import settings
from workflows.state import StoryState

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "nsfw, nude, low quality, worst quality, blurry, deformed, disfigured, "
    "bad anatomy, bad hands, missing fingers, extra fingers, cropped, "
    "watermark, text, signature, jpeg artifacts, ugly, duplicate, morbid, "
    "mutated, extra limbs, poorly drawn hands, poorly drawn face"
)

COMFYUI_POLL_INTERVAL = 2.0  # seconds between status checks
COMFYUI_POLL_TIMEOUT = 300.0  # max seconds to wait for a single image


def _build_comfyui_payload(prompt_text: str) -> dict:
    """Build the ComfyUI API request payload."""
    return {
        "prompt": {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42,
                    "steps": 30,
                    "cfg": 7,
                    "sampler_name": "DPM++ 2M Karras",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "stable-diffusion/revAnimated_v2.safetensors",
                },
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": 1024,
                    "height": 1024,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt_text,
                    "clip": ["4", 1],
                },
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": NEGATIVE_PROMPT,
                    "clip": ["4", 1],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2],
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "StoryFlow",
                    "images": ["8", 0],
                },
            },
        },
    }


async def _poll_until_complete(
    client: httpx.AsyncClient,
    prompt_id: str,
) -> dict:
    """Poll ComfyUI history endpoint until the prompt finishes."""
    elapsed = 0.0
    while elapsed < COMFYUI_POLL_TIMEOUT:
        await asyncio.sleep(COMFYUI_POLL_INTERVAL)
        elapsed += COMFYUI_POLL_INTERVAL

        resp = await client.get(f"{settings.COMFYUI_URL}/history/{prompt_id}")
        resp.raise_for_status()
        history = resp.json()

        if prompt_id in history:
            return history[prompt_id]

    raise TimeoutError(
        f"ComfyUI prompt {prompt_id} did not complete within {COMFYUI_POLL_TIMEOUT}s"
    )


async def _download_image(
    client: httpx.AsyncClient,
    filename: str,
    subfolder: str,
    save_path: Path,
) -> str:
    """Download the generated image from ComfyUI and save to disk."""
    params = {"filename": filename, "subfolder": subfolder, "type": "output"}
    resp = await client.get(f"{settings.COMFYUI_URL}/view", params=params)
    resp.raise_for_status()

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(resp.content)
    return str(save_path)


async def _generate_single_image(
    client: httpx.AsyncClient,
    scene_no: int,
    prompt_text: str,
    story_id: str,
) -> dict:
    """Submit a single image generation job to ComfyUI and wait for it."""
    payload = _build_comfyui_payload(prompt_text)

    # Submit the job
    resp = await client.post(f"{settings.COMFYUI_URL}/prompt", json=payload)
    resp.raise_for_status()
    result = resp.json()
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return a prompt_id: {result}")

    logger.debug("ComfyUI job submitted: prompt_id=%s scene_no=%d", prompt_id, scene_no)

    # Poll until complete
    history_entry = await _poll_until_complete(client, prompt_id)
    outputs = history_entry.get("outputs", {})

    # Extract the saved image info
    image_info = None
    for node_id, node_output in outputs.items():
        if "images" in node_output:
            images = node_output["images"]
            if images:
                image_info = images[0]
                break

    if not image_info:
        raise RuntimeError(f"No image returned for prompt_id={prompt_id}")

    filename = image_info["filename"]
    subfolder = image_info.get("subfolder", "")

    # Build save path
    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "images"
    save_path = save_dir / f"scene_{scene_no}.png"

    # Download and save
    image_path = await _download_image(client, filename, subfolder, save_path)

    # Build a URL-style path that the frontend can use
    image_url = f"/storage/stories/{story_id}/images/scene_{scene_no}.png"

    return {
        "scene_no": scene_no,
        "image_path": image_path,
        "image_url": image_url,
    }


async def image_agent(state: StoryState) -> dict:
    """
    Image generation agent.
    Takes the storyboard and characters from state, submits each scene's
    prompt to ComfyUI, polls for completion, downloads the generated image,
    and returns a list of image metadata.
    Partial results are returned on failure so the pipeline can continue.
    """
    logger.info(
        "image_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])

    if not storyboard:
        logger.error("No storyboard scenes found | task_id=%s", state.get("task_id"))
        return {
            "current_step": "image",
            "status": "error",
            "error": "No storyboard scenes to generate images for.",
            "images": [],
        }

    images: list[dict] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for scene in storyboard:
            scene_no = scene.get("scene_no", 0)
            prompt_text = scene.get("prompt", "")

            if not prompt_text:
                logger.warning(
                    "Scene %d has no prompt, skipping | task_id=%s",
                    scene_no,
                    state.get("task_id"),
                )
                errors.append(f"Scene {scene_no}: empty prompt")
                continue

            try:
                result = await _generate_single_image(
                    client, scene_no, prompt_text, story_id
                )
                images.append(result)
                logger.info(
                    "Image generated for scene %d | task_id=%s",
                    scene_no,
                    state.get("task_id"),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to generate image for scene %d: %s | task_id=%s",
                    scene_no,
                    exc,
                    state.get("task_id"),
                )
                errors.append(f"Scene {scene_no}: {exc}")

    if not images:
        error_msg = f"All image generations failed: {'; '.join(errors)}"
        logger.error("%s | task_id=%s", error_msg, state.get("task_id"))
        return {
            "current_step": "image",
            "status": "error",
            "error": error_msg,
            "images": [],
        }

    logger.info(
        "image_agent completed | %d/%d images generated | task_id=%s",
        len(images),
        len(storyboard),
        state.get("task_id"),
    )

    status_msg = "image_done"
    error_msg = ""
    if errors:
        status_msg = "image_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    return {
        "images": images,
        "current_step": "image",
        "status": status_msg,
        "error": error_msg,
    }