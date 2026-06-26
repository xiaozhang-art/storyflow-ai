from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    APP_NAME: str = "StoryFlow AI"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow"

    # Redis (A2A transport, PubSub, caching)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant (vector memory store)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "story_memory"

    # LLM
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096

    # ComfyUI (image generation)
    COMFYUI_URL: str = "http://localhost:8188"

    # CosyVoice (TTS)
    COSYVOICE_URL: str = "http://localhost:50000"

    # Storage
    STORAGE_PATH: str = "./storage"

    # === Agent OS Runtime Settings (v2.0) ===

    # Langfuse (observability)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # A2A Transport
    A2A_TRANSPORT: str = "memory"  # "memory" or "redis"

    # Execution Runtime
    LLM_WORKER_CONCURRENCY: int = 10
    TOOL_WORKER_CONCURRENCY: int = 8
    GPU_WORKER_CONCURRENCY: int = 2
    MAX_TASK_QUEUE_SIZE: int = 100

    # Session
    SESSION_IDLE_TIMEOUT: int = 86400  # 24 hours

    # Memory
    MEMORY_WORKING_TTL: int = 300      # 5 minutes
    MEMORY_SESSION_TTL: int = 86400    # 24 hours
    MEMORY_CONFIDENCE_THRESHOLD: float = 0.7


settings = Settings()