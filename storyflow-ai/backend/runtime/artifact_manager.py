"""Artifact Manager - File-based artifact storage with metadata tracking.

Every step produces artifacts (script, image, voice, video, etc.).
The ArtifactManager saves them to disk in a structured layout:

    artifacts/{session_id}/
        script.json
        characters.json
        storyboard.json
        scenes/
            scene_001/
                prompt.txt
                image.png
                voice.wav
                video.mp4
            scene_002/
                ...
        final/
            story.mp4
            subtitles.ass

This enables:
    1. Partial regeneration (only re-run specific steps)
    2. Checkpoint/recovery (resume from any step)
    3. Debugging (inspect intermediate artifacts)
    4. Caching (skip steps if artifacts exist)
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ArtifactManager:
    """Manages artifacts produced by each pipeline step.

    Artifacts are organized by session and step, enabling partial
    regeneration and inspection of intermediate results.
    """

    def __init__(self, base_path: str = "./artifacts"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._metadata: dict[str, dict] = {}  # session_id → metadata

    def get_session_dir(self, session_id: str) -> Path:
        """Get the artifact directory for a session."""
        session_dir = self.base_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def get_step_dir(self, session_id: str, step: str) -> Path:
        """Get the artifact directory for a specific step."""
        session_dir = self.get_session_dir(session_id)
        step_dir = session_dir / step
        step_dir.mkdir(parents=True, exist_ok=True)
        return step_dir

    def get_scene_dir(self, session_id: str, scene_no: int) -> Path:
        """Get the artifact directory for a specific scene."""
        scenes_dir = self.get_session_dir(session_id) / "scenes"
        scene_dir = scenes_dir / f"scene_{scene_no:03d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        return scene_dir

    def save_json(self, session_id: str, step: str, data: Any,
                  filename: str | None = None) -> str:
        """Save a JSON artifact.

        Args:
            session_id: Session identifier
            step: Pipeline step name (e.g., "script", "character")
            data: Data to serialize as JSON
            filename: Optional filename (defaults to {step}.json)

        Returns:
            Path to the saved file
        """
        step_dir = self.get_step_dir(session_id, step)
        filename = filename or f"{step}.json"
        filepath = step_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self._record_artifact(session_id, step, str(filepath), "json")
        logger.info("Artifact saved: %s", filepath)
        return str(filepath)

    def save_file(self, session_id: str, step: str, content: bytes,
                  filename: str, scene_no: int | None = None) -> str:
        """Save a binary artifact (image, audio, video, etc.).

        Args:
            session_id: Session identifier
            step: Pipeline step name
            content: Binary content
            filename: Filename (e.g., "scene_001.png")
            scene_no: Optional scene number for scene-level artifacts

        Returns:
            Path to the saved file
        """
        if scene_no is not None:
            save_dir = self.get_scene_dir(session_id, scene_no)
        else:
            save_dir = self.get_step_dir(session_id, step)

        filepath = save_dir / filename
        with open(filepath, "wb") as f:
            f.write(content)

        ext = Path(filename).suffix.lstrip(".")
        self._record_artifact(session_id, step, str(filepath), ext)
        logger.info("Artifact saved: %s (%d bytes)", filepath, len(content))
        return str(filepath)

    def save_text(self, session_id: str, step: str, text: str,
                  filename: str, scene_no: int | None = None) -> str:
        """Save a text artifact.

        Args:
            session_id: Session identifier
            step: Pipeline step name
            text: Text content
            filename: Filename (e.g., "prompt.txt")
            scene_no: Optional scene number for scene-level artifacts

        Returns:
            Path to the saved file
        """
        if scene_no is not None:
            save_dir = self.get_scene_dir(session_id, scene_no)
        else:
            save_dir = self.get_step_dir(session_id, step)

        filepath = save_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)

        self._record_artifact(session_id, step, str(filepath), "text")
        logger.info("Artifact saved: %s", filepath)
        return str(filepath)

    def load_json(self, session_id: str, step: str,
                  filename: str | None = None) -> Any | None:
        """Load a JSON artifact.

        Returns None if the file doesn't exist.
        """
        step_dir = self.get_step_dir(session_id, step)
        filename = filename or f"{step}.json"
        filepath = step_dir / filename

        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_file(self, session_id: str, step: str, filename: str,
                  scene_no: int | None = None) -> bytes | None:
        """Load a binary artifact. Returns None if not found."""
        if scene_no is not None:
            load_dir = self.get_scene_dir(session_id, scene_no)
        else:
            load_dir = self.get_step_dir(session_id, step)

        filepath = load_dir / filename
        if not filepath.exists():
            return None

        with open(filepath, "rb") as f:
            return f.read()

    def artifact_exists(self, session_id: str, step: str,
                        filename: str | None = None) -> bool:
        """Check if an artifact exists for a given step."""
        step_dir = self.get_step_dir(session_id, step)
        filename = filename or f"{step}.json"
        return (step_dir / filename).exists()

    def list_artifacts(self, session_id: str) -> dict[str, list[dict]]:
        """List all artifacts for a session.

        Returns:
            Dict mapping step names to lists of artifact records.
        """
        session_dir = self.get_session_dir(session_id)
        result = {}

        if session_id not in self._metadata:
            # Rebuild metadata from disk
            self._scan_session(session_id)

        return self._metadata.get(session_id, {})

    def get_completed_steps(self, session_id: str) -> list[str]:
        """Get list of steps that have artifacts (i.e., have been completed)."""
        artifacts = self.list_artifacts(session_id)
        return list(artifacts.keys())

    def copy_artifact(self, session_id: str, src_step: str, src_filename: str,
                      dst_step: str, dst_filename: str | None = None) -> str:
        """Copy an artifact from one step to another."""
        dst_filename = dst_filename or src_filename
        src_path = self.get_step_dir(session_id, src_step) / src_filename
        dst_path = self.get_step_dir(session_id, dst_step) / dst_filename
        shutil.copy2(src_path, dst_path)
        return str(dst_path)

    def get_session_storage_size(self, session_id: str) -> int:
        """Get total size of all artifacts for a session in bytes."""
        session_dir = self.get_session_dir(session_id)
        total = 0
        for f in session_dir.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total

    def cleanup_session(self, session_id: str):
        """Remove all artifacts for a session."""
        session_dir = self.get_session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("Cleaned up artifacts for session %s", session_id)
        self._metadata.pop(session_id, None)

    def save_checkpoint(self, session_id: str, step: str, state: dict):
        """Save a runtime checkpoint (state snapshot) for crash recovery."""
        checkpoint_dir = self.get_step_dir(session_id, "_checkpoints")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"checkpoint_{step}_{timestamp}.json"
        filepath = checkpoint_dir / filename

        checkpoint_data = {
            "session_id": session_id,
            "step": step,
            "timestamp": timestamp,
            "state": state,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)

        logger.info("Checkpoint saved: %s (after %s)", filepath, step)

    def load_latest_checkpoint(self, session_id: str) -> dict | None:
        """Load the most recent checkpoint for a session."""
        checkpoint_dir = self.get_step_dir(session_id, "_checkpoints")
        if not checkpoint_dir.exists():
            return None

        checkpoints = sorted(checkpoint_dir.glob("checkpoint_*.json"), reverse=True)
        if not checkpoints:
            return None

        with open(checkpoints[0], "r", encoding="utf-8") as f:
            return json.load(f)

    def _record_artifact(self, session_id: str, step: str, path: str, artifact_type: str):
        """Record an artifact in the metadata."""
        if session_id not in self._metadata:
            self._metadata[session_id] = {}

        if step not in self._metadata[session_id]:
            self._metadata[session_id][step] = []

        self._metadata[session_id][step].append({
            "path": path,
            "type": artifact_type,
            "created_at": datetime.now().isoformat(),
        })

    def _scan_session(self, session_id: str):
        """Scan the filesystem to rebuild metadata for a session."""
        session_dir = self.get_session_dir(session_id)
        self._metadata[session_id] = {}

        for step_dir in session_dir.iterdir():
            if step_dir.is_dir() and not step_dir.name.startswith("_"):
                step_name = step_dir.name
                self._metadata[session_id][step_name] = []

                for f in step_dir.rglob("*"):
                    if f.is_file():
                        self._metadata[session_id][step_name].append({
                            "path": str(f),
                            "type": f.suffix.lstrip("."),
                            "created_at": datetime.fromtimestamp(
                                f.stat().st_mtime
                            ).isoformat(),
                        })

    def __repr__(self):
        return f"ArtifactManager(base={self.base_path})"