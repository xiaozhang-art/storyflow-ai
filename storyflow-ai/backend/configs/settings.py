from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    APP_NAME: str = "StoryFlow AI"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow"

    # Redis (PubSub, caching)
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096

    # ComfyUI (image generation)
    COMFYUI_URL: str = "http://localhost:8188"
    COMFYUI_POLL_TIMEOUT: int = 300
    COMFYUI_MAX_RETRIES: int = 2

    # CosyVoice (TTS)
    COSYVOICE_URL: str = "http://localhost:50000"

    # Storage
    STORAGE_PATH: str = "./storage"

    # Langfuse (optional observability)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Generation
    MAX_EPISODES: int = 6
    SCENES_PER_EPISODE: tuple = (5, 10)


settings = Settings()