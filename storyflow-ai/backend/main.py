"""StoryFlow AI — AI 漫剧自动生成平台.

Project Runtime:
  StoryWorld (长篇一致性) + QualityEngine (质量可控) + Checkpoint (长任务可恢复)
  Capability Registry (能力驱动) + HookManager (生命周期扩展)
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
    logger.info("Starting StoryFlow AI...")

    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error("Database init failed: %s", e)

    try:
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available: %s", e)

    os.makedirs(settings.STORAGE_PATH, exist_ok=True)
    logger.info("StoryFlow AI started")

    yield

    logger.info("Shutting down...")
    try:
        await redis_client.close()
    except Exception:
        pass
    try:
        await async_engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version="3.0.0",
    description="AI 漫剧自动生成平台 — Project Runtime",
    lifespan=lifespan,
)

cors_origins = ["*"] if settings.DEBUG else ["http://localhost:3000", "http://localhost:5173"]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

from api.story import router as story_router
from api.task import router as task_router
app.include_router(story_router, prefix="/api/story", tags=["Story"])
app.include_router(task_router, prefix="/api/task", tags=["Task"])

storage_path = os.path.abspath(settings.STORAGE_PATH)
if os.path.isdir(storage_path):
    app.mount("/storage", StaticFiles(directory=storage_path), name="storage")


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": "3.0.0"}