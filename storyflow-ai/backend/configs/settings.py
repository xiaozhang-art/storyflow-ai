"""StoryFlow AI — Configuration.

All external services use cloud APIs (no local ComfyUI / CosyVoice needed).
Only LLM is strictly required; image / video / voice can run in mock mode.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── App ──
    APP_NAME: str = "StoryFlow AI"
    DEBUG: bool = False

    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow"

    # ── Redis ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── LLM (required) ──
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096

    # ── Text-to-Image API (e.g. 通义万相 / DALL·E / SD API) ──
    # Provider: "dashscope", "openai", "replicate", "mock"
    IMAGE_API_PROVIDER: str = "dashscope"
    IMAGE_API_KEY: str = ""
    IMAGE_API_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    IMAGE_MODEL: str = "wanx-v1"
    IMAGE_SIZE: str = "1024*1024"
    IMAGE_POLL_INTERVAL: int = 3        # seconds between poll
    IMAGE_POLL_TIMEOUT: int = 120       # max wait for async APIs

    # ── Image-to-Video API (e.g. 可灵 Kling / Runway / Pika) ──
    # Provider: "kling", "runway", "pika", "mock"
    VIDEO_API_PROVIDER: str = "kling"
    VIDEO_API_KEY: str = ""
    VIDEO_API_BASE_URL: str = "https://api.klingai.com/v1"
    VIDEO_MODEL: str = "kling-v1"
    VIDEO_DURATION: str = "5"            # "5" or "10"
    VIDEO_POLL_INTERVAL: int = 5
    VIDEO_POLL_TIMEOUT: int = 300

    # ── TTS / Voice API (e.g. CosyVoice Cloud / DashScope TTS / Azure) ──
    # Provider: "dashscope_tts", "cosyvoice_cloud", "azure", "mock"
    VOICE_API_PROVIDER: str = "dashscope_tts"
    VOICE_API_KEY: str = ""
    VOICE_API_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    VOICE_MODEL: str = "cosyvoice-v1"
    VOICE_SAMPLE_RATE: int = 22050

    # ── Storage ──
    STORAGE_PATH: str = "./storage"

    # ── Langfuse (optional) ──
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ── Generation limits ──
    MAX_EPISODES: int = 6
    SCENES_PER_EPISODE: tuple = (5, 10)


settings = Settings()