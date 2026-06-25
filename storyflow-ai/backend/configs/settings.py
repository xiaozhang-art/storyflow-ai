from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "StoryFlow AI"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "story_memory"
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096
    COMFYUI_URL: str = "http://localhost:8188"
    COSYVOICE_URL: str = "http://localhost:50000"
    STORAGE_PATH: str = "./storage"


settings = Settings()