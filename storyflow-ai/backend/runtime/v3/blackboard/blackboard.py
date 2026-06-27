"""Blackboard — 共享任务黑板.

Agent 不直接互相调用，而是通过 Blackboard 交换任务。
类似车间黑板：任务写上去，对应 Agent 看到后领取、执行、标记完成。

任务有依赖关系，形成 DAG。Engine 只投递「依赖已满足」的任务。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"           # 等待依赖
    READY = "ready"               # 依赖已满足，可执行
    IN_PROGRESS = "in_progress"   # Agent 正在执行
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"           # 被上游失败阻塞
    CANCELLED = "cancelled"


@dataclass
class BlackboardTask:
    """黑板上的一个任务."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: str = ""                # "generate_script", "generate_image.scene_3"
    agent_type: str = ""          # "script", "character", "image" ...
    priority: int = 0             # 数字越小越先执行
    status: TaskStatus = TaskStatus.PENDING
    data: dict = field(default_factory=dict)
    result: dict | None = None
    error: str = ""
    dependencies: list[str] = field(default_factory=list)  # 依赖的 task id
    retry_count: int = 0
    max_retries: int = 2
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    scene_no: int | None = None   # 关联的场景编号（用于 Scene 级调度）

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "agent_type": self.agent_type,
            "priority": self.priority, "status": self.status.value,
            "data": self.data, "result": self.result, "error": self.error,
            "dependencies": self.dependencies, "retry_count": self.retry_count,
            "scene_no": self.scene_no,
            "created_at": self.created_at, "completed_at": self.completed_at,
        }


class Blackboard:
    """共享任务黑板.

    Agent 通过 Blackboard 交互:
      - add_task(): Planner 或 Agent 写入新任务
      - claim_task(): Agent 领取一个就绪任务
      - complete_task(): Agent 标记任务完成
      - fail_task(): Agent 标记任务失败
      - get_tasks_by_type(): 查询任务
    """

    def __init__(self):
        self._tasks: dict[str, BlackboardTask] = {}
        self._listeners: list[Callable] = []  # onChange callbacks

    # ── Write Operations ──

    def add_task(self, type: str, agent_type: str, *,
                 data: dict | None = None, priority: int = 0,
                 dependencies: list[str] | None = None,
                 scene_no: int | None = None,
                 max_retries: int = 2) -> BlackboardTask:
        """添加任务到黑板."""
        task = BlackboardTask(
            type=type, agent_type=agent_type,
            data=data or {}, priority=priority,
            dependencies=dependencies or [],
            scene_no=scene_no, max_retries=max_retries,
        )
        self._tasks[task.id] = task
        self._refresh_status(task)
        logger.debug("[Blackboard] Task added: %s (%s) deps=%s",
                      task.id, task.type, task.dependencies)
        self._notify()
        return task

    def claim_task(self, agent_type: str | None = None) -> BlackboardTask | None:
        """Agent 领取下一个就绪任务.

        Args:
            agent_type: 限定只领取此类型 Agent 的任务（None = 任意）
        Returns:
            领取到的任务，或 None
        """
        ready = self.get_ready_tasks(agent_type)
        if not ready:
            return None

        # 按优先级排序
        ready.sort(key=lambda t: (t.priority, t.created_at))
        task = ready[0]
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = time.time()
        logger.info("[Blackboard] Task claimed: %s (%s) by %s",
                     task.id, task.type, agent_type or "any")
        self._notify()
        return task

    def complete_task(self, task_id: str, result: dict | None = None):
        """标记任务完成."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.DONE
        task.result = result
        task.completed_at = time.time()
        logger.info("[Blackboard] Task done: %s (%s)", task.id, task.type)

        # Refresh dependents
        for t in self._tasks.values():
            if task_id in t.dependencies:
                self._refresh_status(t)

        self._notify()

    def fail_task(self, task_id: str, error: str = "", retry: bool = True):
        """标记任务失败.

        If retry and retry_count < max_retries: 重新变为 READY.
        Else: FAILED, 阻塞所有依赖任务.
        """
        task = self._tasks.get(task_id)
        if not task:
            return
        task.error = error
        task.completed_at = time.time()

        if retry and task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.READY
            task.started_at = 0
            logger.warning("[Blackboard] Task retry %d/%d: %s (%s) — %s",
                           task.retry_count, task.max_retries, task.id, task.type, error)
        else:
            task.status = TaskStatus.FAILED
            logger.error("[Blackboard] Task failed: %s (%s) — %s", task.id, task.type, error)
            # Block dependents
            for t in self._tasks.values():
                if task_id in t.dependencies and t.status != TaskStatus.DONE:
                    t.status = TaskStatus.BLOCKED

        self._notify()

    def cancel_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status not in (TaskStatus.DONE,):
            task.status = TaskStatus.CANCELLED
            self._notify()

    # ── Read Operations ──

    def get_task(self, task_id: str) -> BlackboardTask | None:
        return self._tasks.get(task_id)

    def get_ready_tasks(self, agent_type: str | None = None) -> list[BlackboardTask]:
        """获取所有就绪任务."""
        tasks = [t for t in self._tasks.values() if t.status == TaskStatus.READY]
        if agent_type:
            tasks = [t for t in tasks if t.agent_type == agent_type]
        return tasks

    def get_tasks_by_type(self, task_type: str) -> list[BlackboardTask]:
        """按类型查询任务."""
        return [t for t in self._tasks.values() if t.type == task_type]

    def get_tasks_by_agent(self, agent_type: str) -> list[BlackboardTask]:
        """按 Agent 类型查询."""
        return [t for t in self._tasks.values() if t.agent_type == agent_type]

    def get_scene_tasks(self, scene_no: int) -> list[BlackboardTask]:
        """按场景编号查询."""
        return [t for t in self._tasks.values() if t.scene_no == scene_no]

    # ── Status Queries ──

    @property
    def is_complete(self) -> bool:
        """所有任务是否完成."""
        return all(
            t.status in (TaskStatus.DONE, TaskStatus.CANCELLED)
            for t in self._tasks.values()
        )

    @property
    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self._tasks.values())

    def progress_summary(self) -> dict:
        """进度统计."""
        counts = {}
        for t in self._tasks.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        total = len(self._tasks)
        done = counts.get("done", 0) + counts.get("cancelled", 0)
        return {
            "total": total, "done": done, "failed": counts.get("failed", 0),
            "in_progress": counts.get("in_progress", 0),
            "pending": counts.get("pending", 0) + counts.get("ready", 0),
            "progress": int(done / total * 100) if total else 0,
        }

    def list_all(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    # ── Internal ──

    def _refresh_status(self, task: BlackboardTask):
        """刷新任务状态 — 检查依赖是否满足."""
        if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            return
        all_deps_met = all(
            self._tasks[dep_id].status == TaskStatus.DONE
            for dep_id in task.dependencies
            if dep_id in self._tasks
        )
        any_dep_failed = any(
            self._tasks[dep_id].status == TaskStatus.FAILED
            for dep_id in task.dependencies
            if dep_id in self._tasks
        )
        if any_dep_failed:
            task.status = TaskStatus.BLOCKED
        elif all_deps_met:
            task.status = TaskStatus.READY

    def on_change(self, callback: Callable):
        """注册变更监听."""
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            try:
                cb(self)
            except Exception as e:
                logger.error("[Blackboard] Listener error: %s", e)