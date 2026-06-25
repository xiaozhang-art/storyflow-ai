from pydantic import BaseModel


class CharacterCard(BaseModel):
    name: str
    gender: str = "unknown"
    age: int | None = None
    appearance: dict = {}
    personality: dict = {}


class StoryboardScene(BaseModel):
    scene: int
    camera: str = "中景"
    duration: int = 5
    prompt: str
    characters: list[str] = []


class EpisodeData(BaseModel):
    episode_no: int
    title: str
    summary: str
    script: str
    characters: list[str] = []


class ScriptOutput(BaseModel):
    outline: str
    characters: list[CharacterCard]
    episodes: list[EpisodeData]