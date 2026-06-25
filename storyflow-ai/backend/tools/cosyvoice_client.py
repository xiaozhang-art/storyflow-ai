"""CosyVoice API client for text-to-speech."""

import logging
import httpx
from configs.settings import settings

logger = logging.getLogger(__name__)


class CosyVoiceClient:
    """Async client for CosyVoice TTS API."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.COSYVOICE_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        )

    async def generate_speech(
        self,
        text: str,
        speaker: str = "male",
        emotion: str = "neutral",
        speed: float = 1.0,
    ) -> bytes:
        """Generate speech audio from text.

        Returns raw WAV audio bytes.
        """
        resp = await self.client.post(
            "/voice/generate",
            json={
                "speaker": speaker,
                "emotion": emotion,
                "text": text,
                "speed": speed,
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "application/json" in content_type:
            data = resp.json()
            # Handle URL-based response
            if "audio_url" in data:
                audio_resp = await self.client.get(data["audio_url"])
                audio_resp.raise_for_status()
                return audio_resp.content
            # Handle base64 response
            if "audio_base64" in data:
                import base64
                return base64.b64decode(data["audio_base64"])

        # Direct audio bytes response
        return resp.content

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()