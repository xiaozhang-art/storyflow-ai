"""Capability Registry — Agent 不直接写死调用 ComfyUI/CosyVoice.

核心思想：
- Agent 只声明"我需要什么能力"
- Runtime 根据配置选择具体实现
- 新 Agent 直接组合已有 Capability
- 以后换 SD → FLUX，只改 Capability 实现，不动 Agent

Example:
    # Agent 代码
    image_prompt = await self.use_capability("generate_image", {
        "prompt": "...",
        "width": 1024,
        "height": 1024,
    })

    # Runtime 注册
    registry.register("generate_image", ComfyUICapability())
    # 以后换成 FLUX:
    registry.register("generate_image", FluxCapability())
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Capability Definition
# ──────────────────────────────────────────────

class Capability(ABC):
    """能力接口 — 每个 Capability 是一个可执行的单元."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def description(self) -> str:
        return ""

    @property
    def input_schema(self) -> dict:
        """JSON Schema 描述输入参数."""
        return {}

    @property
    def output_schema(self) -> dict:
        """JSON Schema 描述输出."""
        return {"type": "object"}

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """执行能力.

        Args:
            params: 输入参数
            context: 上下文（包含 StoryWorld, Workspace, Project 等）

        Returns:
            执行结果
        """
        ...


# ──────────────────────────────────────────────
# Built-in Capabilities
# ──────────────────────────────────────────────

class GenerateImageCapability(Capability):
    """图像生成能力 — 默认使用 ComfyUI."""

    def __init__(self, comfyui_url: str | None = None):
        from configs.settings import settings
        self.url = comfyui_url or settings.COMFYUI_URL
        self.poll_timeout = settings.COMFYUI_POLL_TIMEOUT
        self.max_retries = settings.COMFYUI_MAX_RETRIES

    @property
    def description(self) -> str:
        return "Generate images using Stable Diffusion via ComfyUI"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "negative_prompt": {"type": "string", "default": ""},
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 1024},
                "output_path": {"type": "string"},
                "seed": {"type": "integer", "default": -1},
            },
            "required": ["prompt", "output_path"],
        }

    async def execute(self, params: dict, context: dict) -> dict:
        import httpx

        prompt = params["prompt"]
        output_path = params.get("output_path", "")
        negative_prompt = params.get("negative_prompt", "")
        width = params.get("width", 1024)
        height = params.get("height", 1024)

        # Build ComfyUI workflow (simplified SDXL)
        workflow = self._build_workflow(prompt, negative_prompt, width, height)

        # Submit
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{self.url}/prompt", json={"prompt": workflow})
            resp.raise_for_status()
            prompt_id = resp.json().get("prompt_id")

            # Poll
            image_data = await self._poll_result(prompt_id, client)

        # Save
        if image_data and output_path:
            import os
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            import base64
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(image_data))

        return {"file_path": output_path, "success": bool(image_data)}

    def _build_workflow(self, prompt, negative, w, h):
        """Build a minimal ComfyUI SDXL workflow."""
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42, "steps": 25, "cfg": 7,
                    "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1,
                    "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "revAnimated_v2.safetensors"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "low quality, blurry", "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "storyflow", "images": ["8", 0]}},
        }

    async def _poll_result(self, prompt_id: str, client) -> str | None:
        """Poll ComfyUI for result."""
        import asyncio
        elapsed = 0
        while elapsed < self.poll_timeout:
            await asyncio.sleep(2)
            elapsed += 2
            try:
                resp = await client.get(f"{self.url}/history/{prompt_id}")
                history = resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    for node_id, node_out in outputs.items():
                        if "images" in node_out:
                            img = node_out["images"][0]
                            subfolder = img.get("subfolder", "")
                            img_resp = await client.get(f"{self.url}/view", params={
                                "filename": img["filename"],
                                "subfolder": subfolder,
                                "type": "output",
                            })
                            import base64
                            return base64.b64encode(img_resp.content).decode()
            except Exception as e:
                logger.warning("[GenerateImage] Poll error: %s", e)
        return None


class GenerateVoiceCapability(Capability):
    """语音合成能力 — 默认使用 CosyVoice."""

    def __init__(self, cosyvoice_url: str | None = None):
        from configs.settings import settings
        self.url = cosyvoice_url or settings.COSYVOICE_URL

    @property
    def description(self) -> str:
        return "Generate speech from text using CosyVoice TTS"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "speaker": {"type": "string", "default": "female_1"},
                "speed": {"type": "number", "default": 1.0},
                "output_path": {"type": "string"},
            },
            "required": ["text", "output_path"],
        }

    async def execute(self, params: dict, context: dict) -> dict:
        import httpx
        import base64
        import os

        text = params["text"]
        output_path = params.get("output_path", "")
        speaker = params.get("speaker", "female_1")
        speed = params.get("speed", 1.0)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.url}/voice/generate",
                json={"text": text, "speaker": speaker, "speed": speed},
            )

            if resp.status_code != 200:
                return {"file_path": "", "success": False, "error": resp.text}

            data = resp.json()
            audio_content = None

            # Support 3 response formats
            if "audio" in data:  # base64
                audio_content = base64.b64decode(data["audio"])
            elif "audio_url" in data:  # URL
                audio_resp = await client.get(data["audio_url"])
                audio_content = audio_resp.content
            else:  # Raw binary
                audio_content = resp.content

        if audio_content and output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_content)

        return {"file_path": output_path, "success": bool(audio_content)}


class MergeVideoCapability(Capability):
    """视频合成能力 — 使用 FFmpeg."""

    @property
    def description(self) -> str:
        return "Merge images and audio into video using FFmpeg"

    async def execute(self, params: dict, context: dict) -> dict:
        import asyncio

        scenes = params.get("scenes", [])  # [{"image": path, "audio": path, "duration": 5.0}]
        output_path = params.get("output_path", "")
        subtitle_path = params.get("subtitle_path", "")

        if not scenes or not output_path:
            return {"file_path": "", "success": False, "error": "No scenes or output path"}

        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Build concat file
        concat_list = []
        for i, scene in enumerate(scenes):
            img = scene.get("image", "")
            audio = scene.get("audio", "")
            duration = scene.get("duration", 5.0)

            if not os.path.isfile(img):
                continue

            # Create individual scene video
            tmp_video = os.path.join(os.path.dirname(output_path), f"_scene_{i:03d}.mp4")
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img, "-t", str(duration)]

            if audio and os.path.isfile(audio):
                cmd += ["-i", audio, "-c:v", "libx264", "-c:a", "aac", "-shortest"]
            else:
                cmd += ["-c:v", "libx264", "-an"]

            if subtitle_path and os.path.isfile(subtitle_path):
                cmd += ["-vf", f"subtitles={subtitle_path}"]

            cmd += ["-pix_fmt", "yuv420p", tmp_video]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            if os.path.isfile(tmp_video):
                concat_list.append(f"file '{tmp_video}'")

        if not concat_list:
            return {"file_path": "", "success": False, "error": "No valid scenes"}

        # Concat all
        concat_file = os.path.join(os.path.dirname(output_path), "_concat.txt")
        with open(concat_file, "w") as f:
            f.write("\n".join(concat_list))

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
               "-c", "copy", output_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=300)

        # Cleanup
        try:
            os.remove(concat_file)
        except Exception:
            pass

        success = os.path.isfile(output_path)
        return {"file_path": output_path, "success": success}


class GenerateStoryboardCapability(Capability):
    """分镜生成能力 — LLM 生成 + 结构化输出.

    这是一个"组合能力"的例子：依赖 LLM 调用但不直接导入 LLM 库。
    """

    @property
    def description(self) -> str:
        return "Generate storyboard scenes from script using LLM"

    async def execute(self, params: dict, context: dict) -> dict:
        # This capability would use LLM to generate storyboard
        # The actual LLM call is injected via context["llm_caller"]
        llm_caller = context.get("llm_caller")
        if not llm_caller:
            return {"scenes": [], "success": False, "error": "No LLM caller in context"}

        script = params.get("script", "")
        characters = params.get("characters", [])
        world = context.get("story_world")

        # Build prompt using StoryWorld
        char_descriptions = ""
        if world:
            char_descriptions = world.build_image_prompt_context(
                [c["name"] for c in characters] if isinstance(characters, list) else []
            )

        prompt = f"""根据以下剧本生成分镜脚本。

## 角色
{char_descriptions}

## 剧本
{script}

## 要求
- 每个场景包含: scene_no, prompt(英文,用于SD生成), dialogue, duration(3-10秒)
- prompt 必须包含完整的角色外观描述
- 保持角色一致性"""

        # Call LLM
        result = await llm_caller(prompt, temperature=0.4, max_tokens=4096)
        return {"scenes": result, "success": True}


# ──────────────────────────────────────────────
# Capability Registry
# ──────────────────────────────────────────────

# Standard capability names
CAP_GENERATE_IMAGE = "generate_image"
CAP_GENERATE_VOICE = "generate_voice"
CAP_MERGE_VIDEO = "merge_video"
CAP_GENERATE_STORYBOARD = "generate_storyboard"
CAP_UPSCALE = "upscale"
CAP_INPAINT = "inpaint"
CAP_FACE_REPAIR = "face_repair"


class CapabilityRegistry:
    """能力注册表.

    Agent 声明需要什么能力，Registry 提供实现。
    """

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical name

    def register(self, name: str, capability: Capability, aliases: list[str] | None = None):
        """注册能力."""
        self._capabilities[name] = capability
        if aliases:
            for alias in aliases:
                self._aliases[alias] = name
        logger.info("[CapabilityRegistry] Registered '%s': %s", name, capability.name)

    def get(self, name: str) -> Capability | None:
        """获取能力实现."""
        canonical = self._aliases.get(name, name)
        return self._capabilities.get(canonical)

    def has(self, name: str) -> bool:
        return name in self._capabilities or name in self._aliases

    async def use(self, name: str, params: dict, context: dict | None = None) -> dict:
        """使用能力 — Agent 的统一调用入口.

        Args:
            name: 能力名称
            params: 输入参数
            context: 上下文（StoryWorld, Workspace 等）

        Returns:
            执行结果
        """
        cap = self.get(name)
        if not cap:
            logger.error("[CapabilityRegistry] Unknown capability: %s", name)
            return {"success": False, "error": f"Unknown capability: {name}"}

        context = context or {}
        start = time.time()
        try:
            result = await cap.execute(params, context)
            result["_duration"] = time.time() - start
            result["_capability"] = name
            return result
        except Exception as e:
            logger.error("[CapabilityRegistry] Capability '%s' error: %s", name, e)
            return {"success": False, "error": str(e), "_duration": time.time() - start}

    def list_all(self) -> list[dict]:
        """列出所有已注册能力."""
        return [
            {"name": name, "class": cap.name, "description": cap.description}
            for name, cap in self._capabilities.items()
        ]

    def setup_defaults(self):
        """注册默认能力集."""
        self.register(CAP_GENERATE_IMAGE, GenerateImageCapability())
        self.register(CAP_GENERATE_VOICE, GenerateVoiceCapability())
        self.register(CAP_MERGE_VIDEO, MergeVideoCapability())
        self.register(CAP_GENERATE_STORYBOARD, GenerateStoryboardCapability())
        logger.info("[CapabilityRegistry] Default capabilities registered")