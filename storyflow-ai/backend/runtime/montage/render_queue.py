"""批量渲染队列.

支持多个视频的排队渲染、优先级排序、进度跟踪。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RenderJob:
    """单个渲染任务."""
    job_id: str
    clips: list[str]
    output_path: str
    config: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = first
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error: str = ""
    result: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0


class RenderQueue:
    """批量渲染队列.

    Usage:
        queue = RenderQueue()
        queue.add_job(job_id="1", clips=["a.mp4", "b.mp4"], output_path="out.mp4")
        queue.add_job(job_id="2", clips=["c.mp4", "d.mp4"], output_path="out2.mp4")
        queue.run_all()
    """

    def __init__(self, max_workers: int = 1):
        self._jobs: dict[str, RenderJob] = {}
        self._max_workers = max_workers
        self._lock = threading.Lock()
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable[[str, float, str], None]) -> None:
        """设置进度回调 (job_id, progress, status)."""
        self._progress_callback = callback

    def add_job(
        self,
        job_id: str,
        clips: list[str],
        output_path: str,
        config: Optional[dict[str, Any]] = None,
        priority: int = 0,
    ) -> RenderJob:
        """添加渲染任务."""
        job = RenderJob(
            job_id=job_id,
            clips=clips,
            output_path=output_path,
            config=config or {},
            priority=priority,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info("RenderQueue: added job %s (%d clips, priority=%d)", job_id, len(clips), priority)
        return job

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        """获取任务状态."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出所有任务."""
        return [
            {
                "job_id": j.job_id,
                "status": j.status.value,
                "progress": j.progress,
                "priority": j.priority,
                "output": j.output_path,
                "error": j.error,
            }
            for j in sorted(self._jobs.values(), key=lambda x: -x.priority)
        ]

    def run_all(self) -> dict[str, Any]:
        """按优先级顺序执行所有待处理任务.

        Returns:
            {total, completed, failed, results: {job_id: result}}
        """
        # Sort by priority (highest first)
        pending = sorted(
            [j for j in self._jobs.values() if j.status == JobStatus.PENDING],
            key=lambda x: -x.priority,
        )

        results: dict[str, Any] = {}
        completed = 0
        failed = 0

        for job in pending:
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            self._notify(job.job_id, 0.0, "running")

            try:
                from runtime.montage.video_composer import VideoComposer, ComposeConfig

                config = ComposeConfig(**{k: v for k, v in job.config.items() if k in ComposeConfig.__dataclass_fields__})
                config.output_path = job.output_path

                composer = VideoComposer()
                result = composer.compose(job.clips, config)
                job.result = result
                job.status = JobStatus.COMPLETED
                job.progress = 100.0
                completed += 1
                self._notify(job.job_id, 100.0, "completed")

            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                failed += 1
                self._notify(job.job_id, job.progress, "failed")
                logger.error("RenderQueue: job %s failed: %s", job.job_id, e)

            job.completed_at = time.time()
            results[job.job_id] = job.result or {"error": job.error}

        logger.info(
            "RenderQueue: batch complete | total=%d | completed=%d | failed=%d",
            len(pending), completed, failed,
        )

        return {
            "total": len(pending),
            "completed": completed,
            "failed": failed,
            "results": results,
        }

    def _notify(self, job_id: str, progress: float, status: str) -> None:
        if self._progress_callback:
            try:
                self._progress_callback(job_id, progress, status)
            except Exception:
                pass

    def get_stats(self) -> dict[str, Any]:
        """获取队列统计."""
        status_counts = {}
        for j in self._jobs.values():
            s = j.status.value
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "total_jobs": len(self._jobs),
            "by_status": status_counts,
            "max_workers": self._max_workers,
        }