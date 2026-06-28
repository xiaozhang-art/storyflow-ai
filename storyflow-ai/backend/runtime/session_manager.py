"""Session Manager - Track and resume generation sessions.

A Session represents one generation run. It stores:
    - Which steps have been completed
    - Current state (for partial regeneration)
    - Blackboard snapshot (for checkpoint/resume)
    - Error history (for debugging)

Example:
    session = session_manager.create(story_id, prompt, genre)
    # ... runtime runs steps ...
    session_manager.complete_step(session.id, "script")
    # Later: user wants to regenerate from storyboard
    session = session_manager.get(session.id)
    session_manager.reset_from_step(session.id, "storyboard")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Session:
    """Represents a single generation session."""
    id: str
    story_id: str
    task_id: str = ""
    prompt: str = ""
    genre: str = ""
    status: SessionStatus = SessionStatus.PENDING
    completed_steps: list[str] = field(default_factory=list)
    current_step: str = ""
    error: str = ""
    error_history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "story_id": self.story_id,
            "task_id": self.task_id,
            "prompt": self.prompt,
            "genre": self.genre,
            "status": self.status.value,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "error": self.error,
            "error_history": self.error_history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        data = dict(data)
        if isinstance(data.get("status"), str):
            data["status"] = SessionStatus(data["status"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SessionManager:
    """Manages generation sessions.

    Sessions are stored in memory. For production, this should be
    backed by Redis or a database.
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, story_id: str, task_id: str = "",
               prompt: str = "", genre: str = "",
               session_id: str = "") -> Session:
        """Create a new session."""
        import uuid
        sid = session_id or str(uuid.uuid4())[:8]
        session = Session(
            id=sid,
            story_id=story_id,
            task_id=task_id,
            prompt=prompt,
            genre=genre,
            status=SessionStatus.PENDING,
        )
        self._sessions[sid] = session
        logger.info("Session created: %s (story=%s)", sid, story_id)
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def get_by_story(self, story_id: str) -> Session | None:
        """Get the latest session for a story."""
        for session in reversed(list(self._sessions.values())):
            if session.story_id == story_id:
                return session
        return None

    def get_by_task(self, task_id: str) -> Session | None:
        """Get the session associated with a task."""
        for session in self._sessions.values():
            if session.task_id == task_id:
                return session
        return None

    def update_status(self, session_id: str, status: SessionStatus):
        """Update session status."""
        session = self.get(session_id)
        if session:
            session.status = status
            session.updated_at = datetime.now().isoformat()

    def start_step(self, session_id: str, step: str):
        """Mark a step as currently running."""
        session = self.get(session_id)
        if session:
            session.current_step = step
            session.status = SessionStatus.RUNNING
            session.updated_at = datetime.now().isoformat()

    def complete_step(self, session_id: str, step: str):
        """Mark a step as completed."""
        session = self.get(session_id)
        if session:
            if step not in session.completed_steps:
                session.completed_steps.append(step)
            session.updated_at = datetime.now().isoformat()
            logger.info("Session %s: step '%s' completed", session_id, step)

    def fail_session(self, session_id: str, step: str, error: str):
        """Mark the session as failed."""
        session = self.get(session_id)
        if session:
            session.status = SessionStatus.FAILED
            session.current_step = step
            session.error = error
            session.error_history.append({
                "step": step,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            })
            session.updated_at = datetime.now().isoformat()

    def reset_from_step(self, session_id: str, step: str):
        """Reset a session to re-run from a specific step.

        Removes the step and all subsequent steps from completed_steps.
        This enables partial regeneration.
        """
        session = self.get(session_id)
        if session:
            pipeline = ["script", "character", "storyboard", "image", "voice", "video"]
            step_idx = pipeline.index(step) if step in pipeline else -1

            session.completed_steps = [
                s for s in session.completed_steps
                if s not in pipeline or pipeline.index(s) < step_idx
            ]
            session.current_step = step
            session.status = SessionStatus.PENDING
            session.error = ""
            session.updated_at = datetime.now().isoformat()
            logger.info("Session %s: reset from step '%s' (completed: %s)",
                        session_id, step, session.completed_steps)

    def is_step_completed(self, session_id: str, step: str) -> bool:
        """Check if a step has been completed."""
        session = self.get(session_id)
        return step in session.completed_steps if session else False

    def get_next_step(self, session_id: str,
                       pipeline: list[str] | None = None) -> str | None:
        """Get the next step to run in the pipeline.

        Returns None if all steps are completed.
        """
        session = self.get(session_id)
        if not session:
            return None

        pipeline = pipeline or ["script", "character", "storyboard", "image", "voice", "video"]
        for step in pipeline:
            if step not in session.completed_steps:
                return step
        return None

    def list_sessions(self, story_id: str = None) -> list[Session]:
        """List all sessions, optionally filtered by story_id."""
        sessions = list(self._sessions.values())
        if story_id:
            sessions = [s for s in sessions if s.story_id == story_id]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def delete_session(self, session_id: str):
        """Delete a session."""
        self._sessions.pop(session_id, None)

    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Remove sessions older than max_age_hours."""
        import time
        now = time.time()
        to_delete = []
        for sid, session in self._sessions.items():
            try:
                created = datetime.fromisoformat(session.created_at).timestamp()
                if now - created > max_age_hours * 3600:
                    to_delete.append(sid)
            except (ValueError, TypeError):
                pass

        for sid in to_delete:
            del self._sessions[sid]

        if to_delete:
            logger.info("Cleaned up %d old sessions", len(to_delete))

    def get_stats(self) -> dict:
        """Get session statistics."""
        total = len(self._sessions)
        by_status = {}
        for s in self._sessions.values():
            by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
        return {"total": total, "by_status": by_status}


# Global singleton
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the global SessionManager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager