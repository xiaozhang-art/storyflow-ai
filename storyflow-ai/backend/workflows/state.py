"""Shared state type for agent pipeline.

In v3 Runtime, state is a plain dict passed between agents.
This TypedDict provides IDE autocomplete and type hints.

Pipeline (v3.1): script → character → storyboard → image → image_to_video → voice → video
"""

from typing import TypedDict


class StoryState(TypedDict, total=False):
    """Pipeline state — passed through all 7 agents sequentially."""
    # Input
    task_id: str
    story_id: str
    prompt: str
    genre: str
    title: str
    total_episodes: int

    # Step outputs (accumulated)
    outline: str
    characters: list[dict]
    episodes: list[dict]
    storyboard: list[dict]
    images: list[dict]
    video_clips: list[dict]
    voices: list[dict]
    audios: list[dict]
    video_path: str
    video_url: str

    # Pipeline control
    current_step: str
    status: str
    error: str
    _retry_hint: str
    _character_consistency: str