"""Model Adapters - Pluggable model backends.

Switch models by changing configuration, without modifying any Agent code.

Architecture:
    ImageAdapter → ComfyUI | DashScope | Mock
    VoiceAdapter → CosyVoice | DashScope TTS | Mock
    VideoAdapter → FFmpeg | Kling | Mock
    LLMAdapter   → OpenAI | DeepSeek | Qwen | Mock

Each adapter implements a common interface. The Runtime selects
the adapter based on configuration.
"""

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
        """Call the LLM with given prompt and return response text."""
        from app.llm import get_creative_llm, get_precise_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = kwargs.get("prompt", "")
        system = kwargs.get("system", "")
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)

        if temperature >= 0.7:
            llm = get_creative_llm()
        else:
            llm = get_precise_llm()

        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        response = await llm.ainvoke(messages)
        return response.content

    async def generate_structured(self, **kwargs) -> Any:
        """Call the LLM and parse structured output."""
        from app.llm import get_creative_llm, get_precise_llm

        prompt = kwargs.get("prompt", "")
        system = kwargs.get("system", "")
        output_parser = kwargs.get("output_parser")
        temperature = kwargs.get("temperature", 0.7)

        if temperature >= 0.7:
            llm = get_creative_llm()
        else:
            llm = get_precise_llm()

        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.messages import HumanMessage, SystemMessage

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
    """Adapter for image generation.

    V3: Pluggable backends (ComfyUI, DashScope, Mock, etc.)
    """

    name = "image"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "IMAGE_API_PROVIDER", "comfyui")

    async def generate(self, **kwargs) -> dict:
        """Generate an image.

        Args:
            prompt: Image generation prompt
            scene_no: Scene number
            seed: Random seed

        Returns:
            Dict with image_url and metadata
        """
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        elif self._provider == "comfyui":
            return await self._comfyui_generate(**kwargs)
        else:
            logger.warning("Unknown image provider: %s, using mock", self._provider)
            return self._mock_generate(**kwargs)

    async def _comfyui_generate(self, **kwargs) -> dict:
        """Generate via ComfyUI (existing implementation)."""
        from agents.image_agent import _generate_single_image
        state = {
            "storyboard": [{"scene_no": kwargs.get("scene_no", 1),
                           "prompt": kwargs.get("prompt", "")}],
            "story_id": kwargs.get("story_id", ""),
        }
        results = await _generate_single_image(state, kwargs.get("scene_no", 0))
        return results if isinstance(results, dict) else {}

    def _mock_generate(self, **kwargs) -> dict:
        """Generate a placeholder (for testing without GPU)."""
        return {
            "scene_no": kwargs.get("scene_no", 1),
            "image_url": "",
            "image_path": "",
            "provider": "mock",
        }

    async def health_check(self) -> bool:
        if self._provider == "mock":
            return True
        try:
            from configs.settings import settings
            import httpx
            url = settings.COMFYUI_URL
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{url}/system_stats")
                return resp.status_code == 200
        except Exception:
            return False


class VoiceAdapter(BaseAdapter):
    """Adapter for voice/TTS generation.

    V3: Pluggable backends (CosyVoice, DashScope TTS, Mock, etc.)
    """

    name = "voice"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "VOICE_API_PROVIDER", "cosyvoice")

    async def generate(self, **kwargs) -> dict:
        """Generate voice audio.

        Args:
            text: Text to speak
            speaker: Speaker type (male/female)
            scene_no: Scene number

        Returns:
            Dict with audio_url and metadata
        """
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        elif self._provider == "cosyvoice":
            return await self._cosyvoice_generate(**kwargs)
        else:
            return self._mock_generate(**kwargs)

    async def _cosyvoice_generate(self, **kwargs) -> dict:
        """Generate via CosyVoice (existing implementation)."""
        from agents.voice_agent import _generate_voice_for_scene
        result = await _generate_voice_for_scene(
            scene_no=kwargs.get("scene_no", 1),
            dialogue=kwargs.get("text", ""),
            characters=kwargs.get("characters", []),
        )
        return result if isinstance(result, dict) else {}

    def _mock_generate(self, **kwargs) -> dict:
        return {
            "scene_no": kwargs.get("scene_no", 1),
            "audio_url": "",
            "audio_path": "",
            "provider": "mock",
        }


class VideoAdapter(BaseAdapter):
    """Adapter for video generation/compositing.

    V3: Pluggable backends (FFmpeg, Kling, Mock, etc.)
    """

    name = "video"

    def __init__(self):
        from configs.settings import settings
        self._provider = getattr(settings, "VIDEO_API_PROVIDER", "ffmpeg")

    async def generate(self, **kwargs) -> dict:
        """Generate or composite video.

        Args:
            images: List of image paths
            audios: List of audio paths
            story_id: Story ID for storage path

        Returns:
            Dict with video_url
        """
        if self._provider == "mock":
            return self._mock_generate(**kwargs)
        elif self._provider == "ffmpeg":
            return await self._ffmpeg_generate(**kwargs)
        else:
            return self._mock_generate(**kwargs)

    async def _ffmpeg_generate(self, **kwargs) -> dict:
        """Generate via FFmpeg (existing implementation)."""
        from agents.video_agent import video_agent
        state = kwargs.get("state", {})
        result = await video_agent(state)
        return result if isinstance(result, dict) else {}

    def _mock_generate(self, **kwargs) -> dict:
        return {
            "video_path": "",
            "video_url": "",
            "provider": "mock",
        }


class AdapterRegistry:
    """Registry for all model adapters.

    Provides a single point to get any adapter by type.
    """

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register default adapters."""
        self._adapters["llm"] = LLMAdapter()
        self._adapters["image"] = ImageAdapter()
        self._adapters["voice"] = VoiceAdapter()
        self._adapters["video"] = VideoAdapter()

    def get(self, adapter_type: str) -> BaseAdapter:
        """Get an adapter by type."""
        adapter = self._adapters.get(adapter_type)
        if not adapter:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        return adapter

    def register(self, adapter_type: str, adapter: BaseAdapter):
        """Register a custom adapter."""
        self._adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s → %s", adapter_type, adapter.name)

    def list_adapters(self) -> dict[str, str]:
        """List all registered adapters and their backend names."""
        return {k: v.name for k, v in self._adapters.items()}

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all adapters."""
        results = {}
        for name, adapter in self._adapters.items():
            try:
                results[name] = await adapter.health_check()
            except Exception as e:
                logger.error("Health check failed for %s: %s", name, e)
                results[name] = False
        return results