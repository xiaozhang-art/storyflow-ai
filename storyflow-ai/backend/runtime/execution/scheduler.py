"""Execution Scheduler - DAG executor with worker pools and backpressure."""
from __future__ import annotations
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Awaitable, Optional
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class ScheduledTask:
    """A task scheduled for execution."""
    id: str
    type: str  # skill, tool, llm, a2a, gpu
    handler: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    priority: Priority = Priority.MEDIUM
    depends_on: list[str] = field(default_factory=list)
    
    # State
    status: str = "pending"  # pending, running, done, failed
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0


class WorkerPool:
    """A pool of async workers for executing tasks of a specific type."""
    
    def __init__(self, name: str, max_concurrency: int = 5):
        self.name = name
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active = 0
        self._completed = 0
        self._failed = 0
    
    @property
    def is_available(self) -> bool:
        return self._active < self.max_concurrency
    
    async def execute(self, task: ScheduledTask) -> Any:
        """Execute a task with concurrency control."""
        async with self._semaphore:
            self._active += 1
            task.status = "running"
            task.started_at = time.time()
            
            try:
                result = await task.handler(*task.args, **task.kwargs)
                task.result = result
                task.status = "done"
                self._completed += 1
                return result
            except Exception as e:
                task.error = str(e)
                task.status = "failed"
                self._failed += 1
                raise
            finally:
                self._active -= 1
                task.completed_at = time.time()
    
    def stats(self) -> dict:
        return {
            "name": self.name,
            "max_concurrency": self.max_concurrency,
            "active": self._active,
            "completed": self._completed,
            "failed": self._failed,
        }


class ExecutionScheduler:
    """Global execution scheduler for the Agent OS.
    
    Responsibilities:
    - Priority-based task scheduling
    - DAG execution (respect dependencies)
    - Worker pool management (LLM, Tool, GPU, etc.)
    - Backpressure control
    - Retry with exponential backoff
    - Execution state tracking
    """
    
    def __init__(self):
        self.hooks = get_hook_dispatcher()
        
        # Task registry
        self._tasks: dict[str, ScheduledTask] = {}
        
        # Worker pools by task type
        self._pools: dict[str, WorkerPool] = {
            "llm": WorkerPool("llm", max_concurrency=10),
            "tool": WorkerPool("tool", max_concurrency=8),
            "skill": WorkerPool("skill", max_concurrency=5),
            "gpu": WorkerPool("gpu", max_concurrency=2),  # GPU is scarce
            "a2a": WorkerPool("a2a", max_concurrency=10),
        }
        
        # Priority queue (simple list sorted by priority)
        self._queue: list[str] = []
        
        # Backpressure
        self._max_queue_size = 100
        self._backpressure = False
    
    def schedule(
        self,
        task_id: str,
        task_type: str,
        handler: Callable[..., Awaitable[Any]],
        priority: Priority = Priority.MEDIUM,
        depends_on: list[str] | None = None,
        **kwargs,
    ) -> ScheduledTask:
        """Schedule a task for execution."""
        task = ScheduledTask(
            id=task_id,
            type=task_type,
            handler=handler,
            priority=priority,
            depends_on=depends_on or [],
            kwargs=kwargs,
        )
        self._tasks[task_id] = task
        self._queue.append(task_id)
        self._queue.sort(key=lambda tid: self._tasks[tid].priority)
        
        logger.info("Task scheduled: %s (type=%s, priority=%s, deps=%s)",
                     task_id, task_type, priority.name, depends_on)
        return task
    
    async def execute_dag(self, task_graph: dict[str, list[str]]) -> dict[str, Any]:
        """Execute a DAG of tasks respecting dependencies.
        
        Args:
            task_graph: {task_id: [dependency_task_ids]}
        
        Returns:
            Dict of task_id -> result
        """
        results: dict[str, Any] = {}
        completed: set[str] = set()
        failed: set[str] = set()
        running: set[str] = set()
        
        # Build reverse dependency map
        dependents: dict[str, list[str]] = defaultdict(list)
        for task_id, deps in task_graph.items():
            for dep in deps:
                dependents[dep].append(task_id)
        
        # Get initial ready tasks
        ready = [
            tid for tid, deps in task_graph.items()
            if not deps or all(d in completed for d in deps)
        ]
        
        while ready or running:
            # Launch ready tasks
            for task_id in ready:
                if task_id in failed:
                    continue
                task = self._tasks.get(task_id)
                if not task:
                    continue
                
                running.add(task_id)
                task.status = "running"
                
                # Emit hook
                await self.hooks.emit(HookEvent(
                    name=hook_events.BEFORE_EXECUTE_TASK,
                    payload={"task_id": task_id, "type": task.type},
                ))
                
                # Execute in background
                asyncio.create_task(self._run_and_collect(
                    task_id, task, completed, failed, running, results,
                ))
            
            ready = []
            
            if running:
                # Wait for at least one task to complete
                await asyncio.sleep(0.1)
        
        return results
    
    async def _run_and_collect(
        self,
        task_id: str,
        task: ScheduledTask,
        completed: set,
        failed: set,
        running: set,
        results: dict,
    ):
        """Run a task and collect its result."""
        pool = self._pools.get(task.type)
        
        try:
            if pool:
                result = await pool.execute(task)
            else:
                result = await task.handler(**task.kwargs)
            
            results[task_id] = result
            completed.add(task_id)
            
            await self.hooks.emit(HookEvent(
                name=hook_events.AFTER_EXECUTE_TASK,
                payload={"task_id": task_id, "success": True},
            ))
            
        except Exception as e:
            logger.error("Task %s failed: %s", task_id, e)
            failed.add(task_id)
            
            # Retry if allowed
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                logger.info("Retrying task %s (attempt %d/%d)",
                             task_id, task.retry_count, task.max_retries)
                await asyncio.sleep(2 ** task.retry_count)  # Exponential backoff
                running.discard(task_id)
                asyncio.create_task(self._run_and_collect(
                    task_id, task, completed, failed, running, results,
                ))
                return
            
            await self.hooks.emit(HookEvent(
                name=hook_events.ON_TASK_FAIL,
                payload={"task_id": task_id, "error": str(e), "retries": task.retry_count},
            ))
        
        finally:
            running.discard(task_id)
    
    async def execute_single(self, task_id: str) -> Any:
        """Execute a single scheduled task by ID."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        pool = self._pools.get(task.type)
        if pool:
            return await pool.execute(task)
        return await task.handler(**task.kwargs)
    
    def check_backpressure(self) -> bool:
        """Check if the system is under backpressure."""
        queue_size = len(self._queue)
        self._backpressure = queue_size > self._max_queue_size
        
        if self._backpressure:
            logger.warning("Backpressure detected: queue_size=%d", queue_size)
        
        return self._backpressure
    
    def get_stats(self) -> dict:
        return {
            "queued_tasks": len(self._queue),
            "total_tasks": len(self._tasks),
            "pools": {name: pool.stats() for name, pool in self._pools.items()},
            "backpressure": self._backpressure,
        }