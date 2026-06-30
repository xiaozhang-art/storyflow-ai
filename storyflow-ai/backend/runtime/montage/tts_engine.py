"""多供应商 TTS 引擎.

从 OpenMontage tools/audio/ 提取，剥离 BaseTool 依赖，
改为纯函数接口，支持 OpenAI / ElevenLabs / Google / DashScope / Piper。

所有方法为同步调用（由上层 Agent 异步包装）。
"""

from __future__ import annotations

import logging
import subprocess
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """TTS 生成结果."""
    success: bool
    output_path: str = ""
    provider: str = ""
    model: str = ""
    voice: str = ""
    audio_duration_seconds: Optional[float] = None
    text_length: int = 0
    error: str = ""
    cost_usd: float = 0.0


# ---- 供应商常量 ----

PROVIDERS = ["openai", "elevenlabs", "google", "dashscope", "piper"]
VOICE_MAP_OPENAI = {
    "male": "onyx", "female": "nova", "narrator": "alloy",
}
VOICE_MAP_GOOGLE = {
    "male": "en-US-Neural2-D", "female": "en-US-Neural2-F",
    "narrator": "en-US-Neural2-A",
}
VOICE_MAP_DASHSCOPE = {
    "male": "longlaotie", "female": "longxiaochun",
}


class TTSEngine:
    """多供应商 TTS 引擎.

    Usage:
        engine = TTSEngine()
        result = engine.generate(
            text="Hello world",
            gender="female",
            output_path="/path/to/output.mp3",
            preferred_provider="openai",
        )
    """

    def __init__(
        self,
        preferred_provider: str = "auto",
        allowed_providers: Optional[list[str]] = None,
        openai_api_key: str = "",
        openai_base_url: str = "https://api.openai.com/v1",
        openai_model: str = "gpt-4o-mini-tts",
        elevenlabs_api_key: str = "",
        google_api_key: str = "",
        dashscope_api_key: str = "",
        dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        dashscope_model: str = "cosyvoice-v1-25hz",
        dashscope_sample_rate: int = 22050,
        piper_model_path: str = "",
    ):
        self.preferred_provider = preferred_provider
        self.allowed_providers = set(allowed_providers or PROVIDERS)

        # Provider configs
        self._openai = {
            "api_key": openai_api_key,
            "base_url": openai_base_url,
            "model": openai_model,
        }
        self._elevenlabs = {
            "api_key": elevenlabs_api_key,
        }
        self._google = {
            "api_key": google_api_key,
        }
        self._dashscope = {
            "api_key": dashscope_api_key,
            "base_url": dashscope_base_url,
            "model": dashscope_model,
            "sample_rate": dashscope_sample_rate,
        }
        self._piper = {
            "model_path": piper_model_path,
        }

        # Availability cache
        self._available: dict[str, bool] = {}
        self._check_availability()

    def _check_availability(self) -> None:
        """检查各供应商可用性."""
        import os

        self._available["openai"] = bool(
            self._openai["api_key"] or os.environ.get("OPENAI_API_KEY")
        )
        self._available["elevenlabs"] = bool(
            self._elevenlabs["api_key"] or os.environ.get("ELEVENLABS_API_KEY")
        )
        self._available["google"] = bool(
            self._google["api_key"] or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        self._available["dashscope"] = bool(
            self._dashscope["api_key"] or os.environ.get("DASHSCOPE_API_KEY")
        )
        self._available["piper"] = (
            bool(self._piper["model_path"])
            or bool(subprocess.run(
                ["which", "piper"], capture_output=True
            ).returncode == 0)
        )

        logger.debug("TTS providers available: %s",
                      {k: v for k, v in self._available.items() if v})

    def list_available(self) -> list[str]:
        """列出当前可用的供应商."""
        return [p for p in PROVIDERS if self._available.get(p) and p in self.allowed_providers]

    def generate(
        self,
        text: str,
        output_path: str,
        gender: str = "female",
        preferred_provider: str = "",
        speed: float = 1.0,
        voice_id: str = "",
        instructions: str = "",
    ) -> TTSResult:
        """生成语音.

        Args:
            text: 要合成的文本
            output_path: 输出文件路径
            gender: 说话人性别 ("male" / "female" / "narrator")
            preferred_provider: 首选供应商（覆盖实例默认值）
            speed: 语速倍率
            voice_id: 显式指定 voice ID（供应商特定）
            instructions: 发音指令（OpenAI gpt-4o-mini-tts 支持）

        Returns:
            TTSResult
        """
        preferred = preferred_provider or self.preferred_provider
        provider = self._select_provider(preferred)

        if not provider:
            logger.warning("No TTS provider available, generating silent WAV")
            self._create_silent_wav(output_path, max(3.0, len(text) * 0.15))
            return TTSResult(
                success=True, output_path=output_path,
                provider="silent", text_length=len(text),
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            if provider == "openai":
                return self._generate_openai(text, output_path, gender, speed, voice_id, instructions)
            elif provider == "elevenlabs":
                return self._generate_elevenlabs(text, output_path, gender, speed, voice_id)
            elif provider == "google":
                return self._generate_google(text, output_path, gender, speed, voice_id)
            elif provider == "dashscope":
                return self._generate_dashscope(text, output_path, gender, speed, voice_id)
            elif provider == "piper":
                return self._generate_piper(text, output_path, gender, speed, voice_id)
            else:
                return TTSResult(success=False, error=f"Unknown provider: {provider}")
        except Exception as e:
            logger.error("TTS %s failed: %s", provider, e)
            # Fallback to silent
            self._create_silent_wav(output_path, max(3.0, len(text) * 0.15))
            return TTSResult(
                success=True, output_path=output_path,
                provider="silent_fallback", text_length=len(text),
                error=f"Original error: {e}",
            )

    def _select_provider(self, preferred: str) -> Optional[str]:
        """选择可用的 TTS 供应商."""
        available = self.list_available()
        if not available:
            return None
        if preferred != "auto" and preferred in available:
            return preferred
        # Priority: openai > dashscope > elevenlabs > google > piper
        for p in ["openai", "dashscope", "elevenlabs", "google", "piper"]:
            if p in available:
                return p
        return available[0]

    # ---- OpenAI TTS ----

    def _generate_openai(
        self, text: str, output_path: str,
        gender: str, speed: float, voice_id: str, instructions: str,
    ) -> TTSResult:
        """OpenAI TTS (gpt-4o-mini-tts / tts-1)."""
        from openai import OpenAI

        import os
        api_key = self._openai["api_key"] or os.environ.get("OPENAI_API_KEY", "")
        base_url = self._openai["base_url"]

        voice = voice_id or VOICE_MAP_OPENAI.get(gender, "alloy")
        model = self._openai["model"]

        client = OpenAI(api_key=api_key, base_url=base_url)

        kwargs: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": Path(output_path).suffix.lstrip(".") or "mp3",
        }
        if instructions and model.startswith("gpt-4o-mini-tts"):
            kwargs["instructions"] = instructions
        if speed != 1.0:
            kwargs["speed"] = speed

        with client.audio.speech.with_streaming_response.create(**kwargs) as response:
            response.stream_to_file(output_path)

        duration = _probe_duration(output_path)
        return TTSResult(
            success=True, output_path=output_path,
            provider="openai", model=model, voice=voice,
            audio_duration_seconds=duration,
            text_length=len(text),
            cost_usd=round(len(text) * 0.000015, 4),
        )

    # ---- ElevenLabs TTS ----

    def _generate_elevenlabs(
        self, text: str, output_path: str,
        gender: str, speed: float, voice_id: str,
    ) -> TTSResult:
        """ElevenLabs TTS API."""
        import os
        import requests

        api_key = self._elevenlabs["api_key"] or os.environ.get("ELEVENLABS_API_KEY", "")
        voice = voice_id or "21m00Tcm4TlvDq8ikWAM"  # Rachel

        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        resp.raise_for_status()

        Path(output_path).write_bytes(resp.content)
        duration = _probe_duration(output_path)

        return TTSResult(
            success=True, output_path=output_path,
            provider="elevenlabs", model="eleven_multilingual_v2", voice=voice,
            audio_duration_seconds=duration,
            text_length=len(text),
            cost_usd=round(len(text) * 0.0003, 4),
        )

    # ---- Google TTS ----

    def _generate_google(
        self, text: str, output_path: str,
        gender: str, speed: float, voice_id: str,
    ) -> TTSResult:
        """Google Cloud TTS API (REST)."""
        import os
        import requests

        api_key = self._google["api_key"] or os.environ.get("GOOGLE_API_KEY", "")
        voice = voice_id or VOICE_MAP_GOOGLE.get(gender, "en-US-Neural2-A")

        resp = requests.post(
            f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}",
            json={
                "input": {"text": text},
                "voice": {
                    "languageCode": "en-US",
                    "name": voice,
                },
                "audioConfig": {
                    "audioEncoding": "MP3",
                    "speakingRate": speed,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        import base64
        audio_content = base64.b64decode(data["audioContent"])
        Path(output_path).write_bytes(audio_content)
        duration = _probe_duration(output_path)

        return TTSResult(
            success=True, output_path=output_path,
            provider="google", model="google_tts", voice=voice,
            audio_duration_seconds=duration,
            text_length=len(text),
        )

    # ---- DashScope TTS ----

    def _generate_dashscope(
        self, text: str, output_path: str,
        gender: str, speed: float, voice_id: str,
    ) -> TTSResult:
        """DashScope TTS (CosyVoice) — async task + poll."""
        import os
        import requests

        api_key = self._dashscope["api_key"] or os.environ.get("DASHSCOPE_API_KEY", "")
        base_url = self._dashscope["base_url"]
        model = self._dashscope["model"]
        sample_rate = self._dashscope["sample_rate"]

        voice = voice_id or VOICE_MAP_DASHSCOPE.get(gender, "longxiaochun")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": {"text": text},
            "parameters": {
                "voice": voice,
                "sample_rate": sample_rate,
            },
        }

        # Submit
        resp = requests.post(
            f"{base_url}/services/aigc/text2audio/generation",
            json=payload, headers=headers, timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        task_id = result.get("output", {}).get("task_id")
        if not task_id:
            audio_url = result.get("output", {}).get("audio_url", "")
            if audio_url:
                audio_resp = requests.get(audio_url, timeout=120)
                audio_resp.raise_for_status()
                Path(output_path).write_bytes(audio_resp.content)
                duration = _probe_duration(output_path)
                return TTSResult(
                    success=True, output_path=output_path,
                    provider="dashscope", model=model, voice=voice,
                    audio_duration_seconds=duration,
                    text_length=len(text),
                )
            raise RuntimeError(f"DashScope TTS: no task_id or audio_url")

        # Poll
        poll_url = f"{base_url}/tasks/{task_id}"
        for _ in range(40):  # 120s max
            import time as _time
            _time.sleep(3)
            poll_resp = requests.get(poll_url, headers=headers, timeout=30)
            poll_data = poll_resp.json()
            status = poll_data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                audio_url = poll_data.get("output", {}).get("audio_url", "")
                if audio_url:
                    audio_resp = requests.get(audio_url, timeout=120)
                    audio_resp.raise_for_status()
                    Path(output_path).write_bytes(audio_resp.content)
                    duration = _probe_duration(output_path)
                    return TTSResult(
                        success=True, output_path=output_path,
                        provider="dashscope", model=model, voice=voice,
                        audio_duration_seconds=duration,
                        text_length=len(text),
                    )
            elif status == "FAILED":
                raise RuntimeError(
                    f"DashScope TTS failed: {poll_data.get('output', {}).get('message', 'unknown')}"
                )

        raise RuntimeError(f"DashScope TTS: task {task_id} timed out")

    # ---- Piper TTS (local) ----

    def _generate_piper(
        self, text: str, output_path: str,
        gender: str, speed: float, voice_id: str,
    ) -> TTSResult:
        """Piper local TTS."""
        import shutil

        piper_bin = shutil.which("piper") or "piper"
        model_path = voice_id or self._piper["model_path"]

        if not model_path:
            raise RuntimeError("Piper model path not configured")

        cmd = [
            piper_bin,
            "--model", model_path,
            "--output-raw",
        ]

        proc = subprocess.run(
            cmd, input=text.encode("utf-8"),
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Piper failed: {proc.stderr.decode()[:200]}")

        # Convert raw to WAV
        import struct
        sample_rate = 22050
        raw = proc.stdout
        n_samples = len(raw) // 2
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(raw[:n_samples * 2])

        duration = _probe_duration(output_path)
        return TTSResult(
            success=True, output_path=output_path,
            provider="piper", model=model_path, voice=gender,
            audio_duration_seconds=duration,
            text_length=len(text),
        )

    # ---- Silent fallback ----

    @staticmethod
    def _create_silent_wav(path: str, duration: float = 3.0) -> None:
        """生成静默 WAV 文件."""
        sample_rate = 22050
        n_frames = int(sample_rate * duration)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)

    def get_info(self) -> dict[str, Any]:
        """获取引擎状态信息."""
        return {
            "available_providers": self.list_available(),
            "preferred": self.preferred_provider,
            "allowed": list(self.allowed_providers),
        }


# ---- Helpers ----

def _probe_duration(path: str) -> Optional[float]:
    """用 ffprobe 获取音频时长."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return None