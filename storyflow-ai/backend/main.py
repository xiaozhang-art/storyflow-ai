"""StoryFlow AI - AI漫剧自动生成平台.

Powered by StoryFlow Runtime V3:
- EventBus (decoupled pub/sub)
- Blackboard (shared state)
- ArtifactManager (file-based storage + checkpoints)
- SessionManager (partial regeneration)
- HookFramework (before/after/error hooks)
- WorkflowEngine (DSL-driven, parallel execution)
- DirectorAgent (decision making: retry/rollback/skip)
- PlannerAgent (task DAG decomposition)
- QualityEngine (multi-dimensional quality checking)
- AdapterRegistry (pluggable model backends)
- AgentSDK (extensible agent framework)
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
    # Startup
    logger.info("Starting StoryFlow AI...")

    # Init database tables
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

    # Check Redis
    redis = None
    try:
        await redis_client.ping()
        redis = redis_client
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    # Ensure storage directory exists
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)

    # Initialize StoryFlow Runtime V3
    try:
        from runtime.core import get_runtime
        runtime = get_runtime()
        runtime.register_existing_agents()

        # Load default DSL workflow
        dsl_path = os.path.join(
            os.path.dirname(__file__), "workflows", "comic.yaml"
        )
        if os.path.exists(dsl_path):
            runtime.workflow_engine.load_dsl(dsl_path)

        # Configure from environment
        enable_quality = os.environ.get("ENABLE_QUALITY", "true").lower() in ("true", "1", "yes")
        enable_director = os.environ.get("ENABLE_DIRECTOR", "false").lower() in ("true", "1", "yes")

        if runtime.quality_engine:
            runtime.quality_engine.enabled = enable_quality
        if runtime.director:
            runtime.director.enabled = enable_director

        app.state.runtime = runtime
        logger.info("StoryFlow Runtime V3 initialized (quality=%s, director=%s)",
                     enable_quality, enable_director)
    except Exception as e:
        logger.error(f"Runtime initialization failed: {e}")
        logger.exception("Runtime init error details:")
        app.state.runtime = None

    logger.info("StoryFlow AI started successfully")

    yield

    # Shutdown
    logger.info("Shutting down StoryFlow AI...")

    # Log runtime stats before shutdown
    try:
        if hasattr(app.state, "runtime") and app.state.runtime:
            stats = app.state.runtime.get_stats()
            logger.info("Runtime shutdown stats: %s", stats)
    except Exception:
        pass

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
    version="4.0.0",
    description="基于 StoryFlow Runtime V3 的 AI 漫剧自动生成平台",
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
        "version": "4.0.0",
        "runtime": bool(getattr(app.state, "runtime", None)),
    }


@app.get("/api/runtime/stats")
async def runtime_stats():
    """Get StoryFlow Runtime statistics."""
    runtime = getattr(app.state, "runtime", None)
    if not runtime:
        return {"error": "Runtime not initialized"}
    return runtime.get_stats()


@app.post("/api/runtime/session/{session_id}/rerun/{step}")
async def rerun_step(session_id: str, step: str):
    """Re-run a specific step (partial regeneration)."""
    runtime = getattr(app.state, "runtime", None)
    if not runtime:
        return {"error": "Runtime not initialized"}
    try:
        result = await runtime.rerun_step(session_id, step)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}