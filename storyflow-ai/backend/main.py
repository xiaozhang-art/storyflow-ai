"""StoryFlow AI - AI 漫剧自动生成平台.

基于 LangGraph 的 6-Agent 串行工作流：
剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from configs.settings import settings
from app.database import init_db, async_engine
from app.redis import redis_client

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Starting StoryFlow AI...")

    # Init database tables
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

    # Check Redis
    try:
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    # Ensure storage directory exists
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)

    logger.info("StoryFlow AI started successfully")

    yield

    # Shutdown
    logger.info("Shutting down StoryFlow AI...")
    try:
        await redis_client.close()
        logger.info("Redis disconnected")
    except Exception:
        pass
    try:
        await async_engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="基于 LangGraph Multi-Agent 的 AI 漫剧自动生成平台",
    lifespan=lifespan,
)

# CORS
cors_origins = ["*"] if settings.DEBUG else [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
from api.story import router as story_router
from api.task import router as task_router

app.include_router(story_router, prefix="/api/story", tags=["Story"])
app.include_router(task_router, prefix="/api/task", tags=["Task"])


# Static files for generated content
storage_path = os.path.abspath(settings.STORAGE_PATH)
if os.path.isdir(storage_path):
    app.mount("/storage", StaticFiles(directory=storage_path), name="storage")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "1.0.0",
    }
