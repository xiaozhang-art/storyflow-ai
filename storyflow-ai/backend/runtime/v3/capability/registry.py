"""Capability Registry — Agent 不直接调用任何外部服务.

核心思想：
- Agent 只声明"我需要什么能力"
- Runtime 根据配置选择具体实现（云端 API 或 Mock）
- 换服务商只改 Capability 实现，不动 Agent

支持的 Provider:
  文生图: dashscope(通义万相), openai(DALL·E), replicate, mock
  图生视频: kling(可灵), runway, pika, mock
  TTS: dashscope_tts, cosyvoice_cloud, azure, mock
  视频拼接: ffmpeg (本地)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Capability Base
# ──────────────────────────────────────────────

class Capability(ABC):
    """能力接口 — 每个 Capability 是一个可执行的单元."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def description(self) -> str:
        return ""

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        ...


# ──────────────────────────────────────────────
# 1. Text-to-Image
# ──────────────────────────────────────────────

class DashscopeImageCapability(Capability):
    """文生图 — 通义万相 (DashScope WANx)."""

    @property
    def description(self) -> str:
        return "Text-to-Image via 阿里云通义万相 (DashScope)"

    async def execute(self, params: dict, context: dict) -> dict:
        from configs.settings import settings

        prompt = params["prompt"]
        output_path = params.get("output_path", "")
        negative_prompt = params.get("negative_prompt", "")
        size = params.get("size", settings.IMAGE_SIZE)  # "1024*1024"

        headers = {
            "Authorization": f"Bearer {settings.IMAGE_API_KEY}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        body = {
            "model": params.get("model", settings.IMAGE_MODEL),
            "input": {"prompt": prompt, "negative_prompt": negative_prompt},
            "parameters": {"size": size, "n": 1},
        }

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Submit task
            resp = await client.post(
                f"{settings.IMAGE_API_BASE_URL}/services/aigc/text2image/image-synthesis",
                headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return {"success": False, "error": f"No task_id: {data}"}

            # 2. Poll result
            image_url = await self._poll(task_id, client, settings.IMAGE_API_BASE_URL,
                                         settings.IMAGE_API_KEY,
                                         settings.IMAGE_POLL_INTERVAL, settings.IMAGE_POLL_TIMEOUT)
            if not image_url:
                return {"success": False, "error": "Image generation timed out"}

            # 3. Download
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_resp.content)

        return {"file_path": output_path, "image_url": image_url, "success": True}

    @staticmethod
    async def _poll(task_id: str, client: httpx.AsyncClient,
                    base_url: str, api_key: str,
                    interval: int, timeout: int) -> str | None:
        headers = {"Authorization": f"Bearer {api_key}"}
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                resp = await client.get(
                    f"{base_url}/tasks/{task_id}",
                    headers=headers, timeout=30,
                )
                data = resp.json()
                status = data.get("output", {}).get("task_status", "")
                if status == "SUCCEEDED":
                    results = data.get("output", {}).get("results", [])
                    if results:
                        return results[0].get("url", "")
                elif status in ("FAILED", "CANCELLED"):
                    logger.error("[DashscopeImage] Task %s failed: %s", task_id, data)
                    return None
            except Exception as e:
                logger.warning("[DashscopeImage] Poll error: %s", e)
        return None


class OpenAIImageCapability(Capability):
    """文生图 — OpenAI DALL·E API (兼容接口)."""

    @property
    def description(self) -> str:
        return "Text-to-Image via OpenAI DALL·E compatible API"

    async def execute(self, params: dict, context: dict) -> dict:
        from configs.settings import settings

        prompt = params["prompt"]
        output_path = params.get("output_path", "")
        size = params.get("size", "1024x1024")

        # DashScope format "1024*1024" → "1024x1024"
        size = size.replace("*", "x")

        headers = {
            "Authorization": f"Bearer {settings.IMAGE_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": params.get("model", settings.IMAGE_MODEL),
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.IMAGE_API_BASE_URL}/images/generations",
                headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            image_url = data["data"][0].get("url", "")

            if output_path and image_url:
                img_resp = await client.get(image_url)
                img_resp.raise_for_status()
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(img_resp.content)

        return {"file_path": output_path, "image_url": image_url, "success": True}


class MockImageCapability(Capability):
    """Mock — 生成彩色占位图."""

    @property
    def description(self) -> str:
        return "[Mock] Generate placeholder images"

    async def execute(self, params: dict, context: dict) -> dict:
        from PIL import Image, ImageDraw, ImageFont

        prompt = params.get("prompt", "")
        output_path = params.get("output_path", "")
        if not output_path:
            return {"success": False, "error": "No output_path"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        colors = [(66, 133, 244), (234, 67, 53), (251, 188, 4),
                  (52, 168, 83), (171, 71, 188), (0, 172, 193)]
        color = colors[hash(prompt) % len(colors)]
        img = Image.new("RGB", (1024, 1024), color)
        draw = ImageDraw.Draw(img)

        try:
            font_l = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            font_s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            font_l = ImageFont.load_default()
            font_s = ImageFont.load_default()

        draw.text((512, 420), "(Mock Image)", fill="white", anchor="mm", font=font_l)
        draw.text((512, 490), "IMAGE_API_PROVIDER=mock", fill="white", anchor="mm", font=font_s)
        preview = (prompt[:80] + "...") if len(prompt) > 80 else prompt
        draw.text((512, 560), preview, fill=(255, 255, 255, 180), anchor="mm", font=font_s)

        img.save(output_path, "PNG")
        return {"file_path": output_path, "success": True}


# ──────────────────────────────────────────────
# 2. Image-to-Video
# ──────────────────────────────────────────────

class KlingImageToVideoCapability(Capability):
    """图生视频 — 可灵 AI (Kling)."""

    @property
    def description(self) -> str:
        return "Image-to-Video via 可灵 AI (Kling)"

    async def execute(self, params: dict, context: dict) -> dict:
        from configs.settings import settings

        image_path = params.get("image_path", "")
        image_url = params.get("image_url", "")
        output_path = params.get("output_path", "")
        duration = params.get("duration", settings.VIDEO_DURATION)
        prompt = params.get("prompt", "")  # optional motion hint

        if not image_path and not image_url:
            return {"success": False, "error": "No image_path or image_url provided"}

        # If local file, need to upload or use base64
        if image_path and not image_url:
            import base64
            with open(image_path, "rb") as f:
                image_url = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

        headers = {
            "Authorization": f"Bearer {settings.VIDEO_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": settings.VIDEO_MODEL,
            "input": {
                "image_url": image_url,
                "prompt": prompt or "gentle motion, cinematic",
            },
            "parameters": {"duration": duration},
        }

        async with httpx.AsyncClient(timeout=120) as client:
            # 1. Submit
            resp = await client.post(
                f"{settings.VIDEO_API_BASE_URL}/videos/image2video",
                headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("task_id") or data.get("output", {}).get("task_id")
            if not task_id:
                return {"success": False, "error": f"No task_id: {data}"}

            # 2. Poll
            video_url = await self._poll(task_id, client, settings.VIDEO_API_BASE_URL,
                                         settings.VIDEO_API_KEY,
                                         settings.VIDEO_POLL_INTERVAL, settings.VIDEO_POLL_TIMEOUT)
            if not video_url:
                return {"success": False, "error": "Video generation timed out"}

            # 3. Download
            video_resp = await client.get(video_url)
            video_resp.raise_for_status()

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(video_resp.content)

        return {"file_path": output_path, "video_url": video_url, "success": True}

    @staticmethod
    async def _poll(task_id: str, client: httpx.AsyncClient,
                    base_url: str, api_key: str,
                    interval: int, timeout: int) -> str | None:
        headers = {"Authorization": f"Bearer {api_key}"}
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                resp = await client.get(
                    f"{base_url}/videos/image2video/{task_id}",
                    headers=headers, timeout=30,
                )
                data = resp.json()
                status = data.get("status", "") or data.get("task_status", "")
                if status in ("succeed", "completed", "SUCCEEDED"):
                    return data.get("video_url", "") or data.get("output", {}).get("video_url", "")
                elif status in ("failed", "FAILED"):
                    logger.error("[KlingVideo] Task %s failed: %s", task_id, data)
                    return None
            except Exception as e:
                logger.warning("[KlingVideo] Poll error: %s", e)
        return None


class MockImageToVideoCapability(Capability):
    """Mock — 用 FFmpeg 把静态图做成 5 秒视频."""

    @property
    def description(self) -> str:
        return "[Mock] Create 5s video from image via FFmpeg"

    async def execute(self, params: dict, context: dict) -> dict:
        image_path = params.get("image_path", "")
        output_path = params.get("output_path", "")
        duration = params.get("duration", "5")

        if not image_path or not output_path:
            return {"success": False, "error": "Missing image_path or output_path"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", "24",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        success = os.path.isfile(output_path)
        if not success:
            logger.error("[MockI2V] ffmpeg failed: %s", stderr.decode()[:300])
        return {"file_path": output_path, "success": success}


# ──────────────────────────────────────────────
# 3. TTS / Voice
# ──────────────────────────────────────────────

class DashscopeTTSCapability(Capability):
    """TTS — 阿里云 DashScope CosyVoice."""

    @property
    def description(self) -> str:
        return "TTS via 阿里云 DashScope CosyVoice"

    async def execute(self, params: dict, context: dict) -> dict:
        from configs.settings import settings

        text = params["text"]
        output_path = params.get("output_path", "")
        speaker = params.get("speaker", "female_1")
        # Map short names to CosyVoice preset voices
        voice_map = {
            "female": "longxiaochun", "male": "longlaotie",
            "female_1": "longxiaochun", "male_1": "longlaotie",
        }
        voice = voice_map.get(speaker, speaker)

        headers = {
            "Authorization": f"Bearer {settings.VOICE_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": settings.VOICE_MODEL,
            "input": {"text": text},
            "parameters": {"voice": voice},
        }

        async with httpx.AsyncClient(timeout=120) as client:
            # DashScope CosyVoice uses WebSocket or HTTP
            # HTTP mode: submit async task
            resp = await client.post(
                f"{settings.VOICE_API_BASE_URL}/services/aigc/text-generation/generation",
                headers=headers, json=body,
            )
            if resp.status_code == 200:
                data = resp.json()
                audio_url = data.get("output", {}).get("audio_url", "")
                if audio_url:
                    audio_resp = await client.get(audio_url, timeout=60)
                    audio_resp.raise_for_status()
                    audio_bytes = audio_resp.content
                elif "audio" in data.get("output", {}):
                    import base64
                    audio_bytes = base64.b64decode(data["output"]["audio"])
                else:
                    return {"success": False, "error": f"Unexpected TTS response: {data}"}
            else:
                return {"success": False, "error": f"TTS API error {resp.status_code}: {resp.text}"}

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

        return {"file_path": output_path, "success": True}


class CosyVoiceCloudCapability(Capability):
    """TTS — CosyVoice Cloud API (自部署 CosyVoice HTTP 服务)."""

    @property
    def description(self) -> str:
        return "TTS via CosyVoice Cloud API"

    async def execute(self, params: dict, context: dict) -> dict:
        from configs.settings import settings

        text = params["text"]
        output_path = params.get("output_path", "")
        speaker = params.get("speaker", "female_1")
        speed = params.get("speed", 1.0)

        headers = {"Content-Type": "application/json"}
        if settings.VOICE_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VOICE_API_KEY}"

        body = {"text": text, "speaker": speaker, "speed": speed}

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.VOICE_API_BASE_URL}/voice/generate",
                headers=headers, json=body,
            )

            if resp.status_code != 200:
                return {"success": False, "error": resp.text}

            data = resp.json()
            audio_content = None
            if "audio" in data:
                import base64
                audio_content = base64.b64decode(data["audio"])
            elif "audio_url" in data:
                audio_resp = await client.get(data["audio_url"])
                audio_content = audio_resp.content
            else:
                audio_content = resp.content

        if audio_content and output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_content)

        return {"file_path": output_path, "success": bool(audio_content)}


class MockVoiceCapability(Capability):
    """Mock — 生成静默 WAV."""

    @property
    def description(self) -> str:
        return "[Mock] Generate silent WAV"

    async def execute(self, params: dict, context: dict) -> dict:
        import wave

        output_path = params.get("output_path", "")
        if not output_path:
            return {"success": False, "error": "No output_path"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        sample_rate = 22050
        duration = 3.0
        n_frames = int(sample_rate * duration)

        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)

        return {"file_path": output_path, "success": True}


# ──────────────────────────────────────────────
# 4. Video Merge (FFmpeg — always local)
# ──────────────────────────────────────────────

class MergeVideoCapability(Capability):
    """视频拼接 — FFmpeg concat."""

    @property
    def description(self) -> str:
        return "Concat video clips into final MP4 via FFmpeg"

    async def execute(self, params: dict, context: dict) -> dict:
        clips = params.get("clips", [])  # [{"video_path": str, "audio_path": str|None}]
        output_path = params.get("output_path", "")
        subtitle_path = params.get("subtitle_path", "")

        if not clips or not output_path:
            return {"file_path": "", "success": False, "error": "No clips or output path"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Step 1: burn subtitles per clip if provided
        processed_clips = []
        if subtitle_path and os.path.isfile(subtitle_path):
            for i, clip in enumerate(clips):
                src = clip.get("video_path", "")
                if not os.path.isfile(src):
                    continue
                out = os.path.join(os.path.dirname(output_path), f"_sub_{i:03d}.mp4")
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", src,
                    "-vf", f"ass={subtitle_path}",
                    "-c:a", "copy", out,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
                if os.path.isfile(out):
                    processed_clips.append(out)
                else:
                    processed_clips.append(src)
        else:
            processed_clips = [c["video_path"] for c in clips if os.path.isfile(c.get("video_path", ""))]

        if not processed_clips:
            return {"file_path": "", "success": False, "error": "No valid clips"}

        # Step 2: concat
        concat_file = os.path.join(os.path.dirname(output_path), "_concat.txt")
        with open(concat_file, "w") as f:
            for p in processed_clips:
                f.write(f"file '{p}'\n")

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file, "-c", "copy", output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                logger.error("[MergeVideo] ffmpeg concat failed: %s", stderr.decode()[:300])
        except asyncio.TimeoutError:
            return {"file_path": "", "success": False, "error": "Video concat timed out"}
        finally:
            try:
                os.remove(concat_file)
            except Exception:
                pass

        # Cleanup temp subtitled files
        for p in processed_clips:
            if "_sub_" in os.path.basename(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        return {"file_path": output_path, "success": os.path.isfile(output_path)}


class GenerateStoryboardCapability(Capability):
    """分镜生成 — LLM (组合能力示例)."""

    @property
    def description(self) -> str:
        return "Generate storyboard scenes from script using LLM"

    async def execute(self, params: dict, context: dict) -> dict:
        llm_caller = context.get("llm_caller")
        if not llm_caller:
            return {"scenes": [], "success": False, "error": "No LLM caller in context"}
        result = await llm_caller(params.get("script", ""), temperature=0.4, max_tokens=4096)
        return {"scenes": result, "success": True}


# ──────────────────────────────────────────────
# Capability Registry
# ──────────────────────────────────────────────

CAP_GENERATE_IMAGE = "generate_image"
CAP_IMAGE_TO_VIDEO = "image_to_video"
CAP_GENERATE_VOICE = "generate_voice"
CAP_MERGE_VIDEO = "merge_video"
CAP_GENERATE_STORYBOARD = "generate_storyboard"


class CapabilityRegistry:
    """能力注册表."""

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, name: str, capability: Capability):
        self._capabilities[name] = capability
        logger.info("[CapabilityRegistry] Registered '%s': %s", name, capability.name)

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def has(self, name: str) -> bool:
        return name in self._capabilities

    async def use(self, name: str, params: dict, context: dict | None = None) -> dict:
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
        return [
            {"name": name, "class": cap.name, "description": cap.description}
            for name, cap in self._capabilities.items()
        ]

    def setup_defaults(self):
        """根据 settings 中的 provider 配置注册能力.

        任何 provider="mock" 或 API_KEY 为空且非 mock-only provider → 自动降级为 Mock.
        """
        from configs.settings import settings

        # ── generate_image ──
        self._setup_capability(
            CAP_GENERATE_IMAGE,
            provider=settings.IMAGE_API_PROVIDER,
            key=settings.IMAGE_API_KEY,
            providers={
                "dashscope": DashscopeImageCapability,
                "openai": OpenAIImageCapability,
                "mock": MockImageCapability,
            },
            mock_class=MockImageCapability,
        )

        # ── image_to_video ──
        self._setup_capability(
            CAP_IMAGE_TO_VIDEO,
            provider=settings.VIDEO_API_PROVIDER,
            key=settings.VIDEO_API_KEY,
            providers={
                "kling": KlingImageToVideoCapability,
                "mock": MockImageToVideoCapability,
            },
            mock_class=MockImageToVideoCapability,
        )

        # ── generate_voice ──
        self._setup_capability(
            CAP_GENERATE_VOICE,
            provider=settings.VOICE_API_PROVIDER,
            key=settings.VOICE_API_KEY,
            providers={
                "dashscope_tts": DashscopeTTSCapability,
                "cosyvoice_cloud": CosyVoiceCloudCapability,
                "mock": MockVoiceCapability,
            },
            mock_class=MockVoiceCapability,
        )

        # ── merge_video (always FFmpeg, no API) ──
        self.register(CAP_MERGE_VIDEO, MergeVideoCapability())

        # ── generate_storyboard (LLM-based) ──
        self.register(CAP_GENERATE_STORYBOARD, GenerateStoryboardCapability())

        logger.info("[CapabilityRegistry] All default capabilities registered")

    def _setup_capability(self, name: str, provider: str, key: str,
                          providers: dict, mock_class: type):
        """根据 provider 选择实现，无 key 时自动降级 Mock."""
        if provider == "mock":
            self.register(name, mock_class())
            logger.info("[CapabilityRegistry] %s → Mock (explicit)", name)
            return

        cap_class = providers.get(provider)
        if cap_class:
            if key:
                self.register(name, cap_class())
                logger.info("[CapabilityRegistry] %s → %s (real)", name, provider)
            else:
                self.register(name, mock_class())
                logger.warning("[CapabilityRegistry] %s → Mock (no API key for %s)", name, provider)
        else:
            self.register(name, mock_class())
            logger.warning("[CapabilityRegistry] %s → Mock (unknown provider '%s' for %s)", provider, name)