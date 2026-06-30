"""StoryFlow AI — Configuration.

All external services use cloud APIs (no local GPU needed).
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

    # ── Image-to-Video API (e.g. Kling / Runway) ──
    # Provider: "kling", "runway", "mock"
    I2V_API_PROVIDER: str = "kling"
    I2V_API_KEY: str = ""
    I2V_API_BASE_URL: str = "https://api.klingai.com/v1"
    I2V_MODEL: str = "kling-v1"
    I2V_DURATION: float = 5.0           # seconds per clip
    I2V_POLL_INTERVAL: int = 5
    I2V_POLL_TIMEOUT: int = 300

    # ── TTS / Voice API (e.g. DashScope TTS / Azure) ──
    # Provider: "dashscope_tts", "azure", "mock"
    VOICE_API_PROVIDER: str = "dashscope_tts"
    VOICE_API_KEY: str = ""
    VOICE_API_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    VOICE_MODEL: str = "cosyvoice-v1-25hz"
    VOICE_SAMPLE_RATE: int = 22050

    # ── Montage Engine (OpenMontage integration) ──
    MONTAGE_ENABLED: bool = True
    MONTAGE_TTS_PROVIDER: str = "auto"  # "auto" / "openai" / "dashscope" / "elevenlabs" / "google" / "piper"
    MONTAGE_TTS_PROVIDERS: str = ""  # comma-separated, e.g. "openai,dashscope,piper"
    MONTAGE_TRANSITION: str = "crossfade"  # "cut" / "crossfade" / "fade"
    MONTAGE_TRANSITION_DURATION: float = 0.5
    MONTAGE_BURN_SUBTITLES: bool = True
    MONTAGE_QUALITY_CHECK: bool = True
    MONTAGE_BGM_PATH: str = ""  # Optional BGM file path
    MONTAGE_OUTPUT_PROFILE: str = "storyflow_default"
    MONTAGE_MEDIA_PROFILE: str = "storyflow_default"  # "youtube_landscape" / "tiktok" / "instagram_reels" / etc.

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