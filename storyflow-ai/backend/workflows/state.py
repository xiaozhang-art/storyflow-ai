from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
import operator


class StoryState(TypedDict):
    task_id: str
    story_id: str
    prompt: str
    genre: str
    outline: str
    characters: list[dict]
    episodes: list[dict]
    storyboard: list[dict]
    images: list[dict]
    audios: list[dict]
    video_path: str
    current_step: str
    status: str
    error: str