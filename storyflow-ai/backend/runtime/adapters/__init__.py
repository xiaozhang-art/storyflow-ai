"""Model Adapters - Pluggable cloud API backends.

All adapters use cloud APIs — no local GPU required.
Switch providers by changing IMAGE_API_PROVIDER / VOICE_API_PROVIDER / I2V_API_PROVIDER.

Architecture:
    ImageAdapter → DashScope (通义万相) | OpenAI DALL-E | Mock
    VoiceAdapter → DashScope TTS | Mock
    I2VAdapter   → Kling | Runway | Mock (FFmpeg)
    VideoAdapter → FFmpeg (local concat)
    LLMAdapter   → OpenAI | DeepSeek | Qwen
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Abstract base for all model adapters."""

    name: str = "base"

    @abstractmethod
    async def generate(self, **kwargs) -> Any:
        """Execute the model and return results."""
        ...

    async def health_check(self) -> bool:
        """Check if the backend is available."""
        return True


class LLMAdapter(BaseAdapter):
    """Adapter for LLM calls. Wraps the existing LLM factory."""

    name = "llm"

    async def generate(self, **kwargs) -> str:
        from app.llm import get_creative_llm, get_precise_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = kwargs.get("prompt", "")
        system = kwargs.get("system", "")
        temperature = kwargs.get("temperature", 0.7)

        llm = get_creative_llm() if temperature >= 0.7 else get_precise_llm()

        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        response = await llm.ainvoke(messages)
        return response.content

    async def generate_structured(self, **kwargs) -> Any:
        from app.llm import get_creative_llm, get_precise_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = kwargs.get("prompt", "")
        system = kwargs.get("system", "")
        output_parser = kwargs.get("output_parser")
        temperature = kwargs.get("temperature", 0.7)

        llm = get_creative_llm() if temperature >= 0.7 else get_precise_llm()

        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        if output_parser:
            chain = llm | output_parser
            return await chain.ainvoke(messages)
        else:
            response = await llm.ainvoke(messages)
            return response.content


class ImageAdapter(BaseAdapter):
    """Adapter for cloud image generation (DashScope / OpenAI / Mock)."""

    name = "image"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "IMAGE_API_PROVIDER", "dashscope")

    async def generate(self, **kwargs) -> dict:
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        else:
            # Delegate to the image_agent which handles all providers
            from agents.image_agent import image_agent
            state = {
                "storyboard": [{"scene_no": kwargs.get("scene_no", 1),
                                "prompt": kwargs.get("prompt", "")}],
                "story_id": kwargs.get("story_id", ""),
            }
            result = await image_agent(state, {})
            images = result.get("images", [])
            if images:
                return images[0]
            return {"scene_no": kwargs.get("scene_no", 1), "image_url": "", "image_path": ""}

    def _mock_generate(self, **kwargs) -> dict:
        return {
            "scene_no": kwargs.get("scene_no", 1),
            "image_url": "",
            "image_path": "",
            "provider": "mock",
        }


class VoiceAdapter(BaseAdapter):
    """Adapter for cloud TTS (DashScope TTS / Mock)."""

    name = "voice"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "VOICE_API_PROVIDER", "dashscope_tts")

    async def generate(self, **kwargs) -> dict:
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        else:
            from agents.voice_agent import voice_agent
            state = {
                "storyboard": [{"scene_no": kwargs.get("scene_no", 1),
                                "dialogue": kwargs.get("text", ""),
                                "characters": []}],
                "characters": kwargs.get("characters", []),
                "story_id": kwargs.get("story_id", ""),
            }
            result = await voice_agent(state, {})
            audios = result.get("audios", [])
            if audios:
                return audios[0]
            return {"scene_no": kwargs.get("scene_no", 1), "audio_url": "", "audio_path": ""}

    def _mock_generate(self, **kwargs) -> dict:
        return {
            "scene_no": kwargs.get("scene_no", 1),
            "audio_url": "",
            "audio_path": "",
            "provider": "mock",
        }


class I2VAdapter(BaseAdapter):
    """Adapter for cloud image-to-video (Kling / Runway / Mock)."""

    name = "image_to_video"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "I2V_API_PROVIDER", "kling")

    async def generate(self, **kwargs) -> dict:
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        else:
            from agents.image_to_video_agent import image_to_video_agent
            state = {
                "images": [{"scene_no": kwargs.get("scene_no", 1),
                            "image_path": kwargs.get("image_path", "")}],
                "story_id": kwargs.get("story_id", ""),
            }
            result = await image_to_video_agent(state, {})
            clips = result.get("video_clips", [])
            if clips:
                return clips[0]
            return {"scene_no": kwargs.get("scene_no", 1), "video_url": "", "video_path": ""}

    def _mock_generate(self, **kwargs) -> dict:
        return {
            "scene_no": kwargs.get("scene_no", 1),
            "video_url": "",
            "video_path": "",
            "provider": "mock",
        }


class VideoAdapter(BaseAdapter):
    """Adapter for video compositing (FFmpeg concat, always local)."""

    name = "video"

    async def generate(self, **kwargs) -> dict:
        from agents.video_agent import video_agent
        state = kwargs.get("state", {})
        result = await video_agent(state, {})
        return result if isinstance(result, dict) else {}

    async def health_check(self) -> bool:
        import shutil
        return shutil.which("ffmpeg") is not None


class AdapterRegistry:
    """Registry for all model adapters."""

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}
        self._register_defaults()

    def _register_defaults(self):
        self._adapters["llm"] = LLMAdapter()
        self._adapters["image"] = ImageAdapter()
        self._adapters["voice"] = VoiceAdapter()
        self._adapters["image_to_video"] = I2VAdapter()
        self._adapters["video"] = VideoAdapter()

    def get(self, adapter_type: str) -> BaseAdapter:
        adapter = self._adapters.get(adapter_type)
        if not adapter:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        return adapter

    def register(self, adapter_type: str, adapter: BaseAdapter):
        self._adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s → %s", adapter_type, adapter.name)

    def list_adapters(self) -> dict[str, str]:
        return {k: v.name for k, v in self._adapters.items()}

    async def health_check_all(self) -> dict[str, bool]:
        results = {}
        for name, adapter in self._adapters.items():
            try:
                results[name] = await adapter.health_check()
            except Exception as e:
                logger.error("Health check failed for %s: %s", name, e)
                results[name] = False
        return results