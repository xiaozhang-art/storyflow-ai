"""ComfyUI API client for image generation."""

import random
import logging
import httpx
from configs.settings import settings

logger = logging.getLogger(__name__)


class ComfyUIClient:
    """Async client for ComfyUI API."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.COMFYUI_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        )

    def _build_workflow_payload(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
    ) -> dict:
        """Build the ComfyUI workflow JSON payload."""
        return {
            "prompt": {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": random.randint(0, 2**32 - 1),
                        "steps": 30,
                        "cfg": 7.0,
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
                    "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
                },
                "5": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": width, "height": height, "batch_size": 1},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": prompt, "clip": ["4", 1]},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": negative_prompt, "clip": ["4", 1]},
                },
                "9": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
                },
                "10": {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "storyflow",
                        "images": ["9", 0],
                    },
                },
            }
        }

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "low quality, blurry, deformed, ugly, bad anatomy",
        width: int = 1024,
        height: int = 1024,
    ) -> bytes:
        """Submit a generation request and return the image bytes."""
        payload = self._build_workflow_payload(prompt, negative_prompt, width, height)

        # Submit prompt
        resp = await self.client.post("/prompt", json=payload)
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]
        logger.info(f"ComfyUI prompt submitted: {prompt_id}")

        # Poll for completion
        import asyncio
        for _ in range(60):  # max 120s (60 * 2s)
            await asyncio.sleep(2)
            history_resp = await self.client.get(f"/history/{prompt_id}")
            history = history_resp.json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                for node_id, node_output in outputs.items():
                    if "images" in node_output:
                        img_info = node_output["images"][0]
                        filename = img_info["filename"]
                        subfolder = img_info.get("subfolder", "")
                        # Download the image
                        img_resp = await self.client.get(
                            "/view",
                            params={
                                "filename": filename,
                                "subfolder": subfolder,
                                "type": "output",
                            },
                        )
                        img_resp.raise_for_status()
                        logger.info(f"Image downloaded: {filename}")
                        return img_resp.content

        raise TimeoutError(f"ComfyUI generation timed out for prompt {prompt_id}")

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()