"""Task API routes with WebSocket support."""

import json
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.redis import redis_client
from schemas.task import TaskStatusResponse
from repositories import task_repo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get task progress status."""
    task = await task_repo.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.websocket("/{task_id}/ws")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task progress updates."""
    await websocket.accept()
    logger.info(f"WebSocket connected: task={task_id}")

    try:
        # Send current status immediately
        from app.redis import get_task_status
        current = await get_task_status(task_id)
        if current:
            await websocket.send_json(current)

        # Subscribe to Redis PubSub for live updates
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"task:{task_id}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await websocket.send_json(data)
                    # Stop if task is done or failed
                    if data.get("status") in ("completed", "failed", "done"):
                        break
        finally:
            await pubsub.unsubscribe(f"task:{task_id}")
            await pubsub.aclose()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: task={task_id}")
    except Exception as e:
        logger.error(f"WebSocket error: task={task_id}, error={e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass