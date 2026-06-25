from langgraph.graph import StateGraph, START, END

from workflows.state import StoryState
from agents.script_agent import script_agent
from agents.character_agent import character_agent
from agents.storyboard_agent import storyboard_agent
from agents.image_agent import image_agent
from agents.voice_agent import voice_agent
from agents.video_agent import video_agent


def build_story_workflow() -> StateGraph:
    """Build and compile the StoryFlow AI LangGraph workflow.

    Pipeline:
        START → script → character → storyboard → image → voice → video → END
    """
    workflow = StateGraph(StoryState)

    workflow.add_node("script", script_agent)
    workflow.add_node("character", character_agent)
    workflow.add_node("storyboard", storyboard_agent)
    workflow.add_node("image", image_agent)
    workflow.add_node("voice", voice_agent)
    workflow.add_node("video", video_agent)

    workflow.add_edge(START, "script")
    workflow.add_edge("script", "character")
    workflow.add_edge("character", "storyboard")
    workflow.add_edge("storyboard", "image")
    workflow.add_edge("image", "voice")
    workflow.add_edge("voice", "video")
    workflow.add_edge("video", END)

    return workflow.compile()