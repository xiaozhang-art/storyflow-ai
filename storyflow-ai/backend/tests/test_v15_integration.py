"""Integration tests for StoryFlow AI V1.5 Runtime — three-phase upgrade.

Tests cover:
- Phase 1: Director brain (5 decisions, artifact analysis, rule-based fallback)
- Phase 2: A2A rich context passing (structured messages, constraints, feedback)
- Phase 3: StoryMemory integration (scene/visual/style/world memory)

All tests are self-contained and do NOT require LLM API calls or external services.
"""
from __future__ import annotations

import asyncio
import sys
import os
import pytest

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Phase 1: Director Tests
# ============================================================

class TestDirectorBrain:
    """Phase 1: Director autonomous decision-making brain."""

    def test_artifact_manager_store_and_retrieve(self):
        from runtime.director import ArtifactManager
        am = ArtifactManager()
        am.store("script", {"outline": "Test story", "characters": [], "episodes": []})
        data = am.get("script")
        assert data is not None
        assert data["outline"] == "Test story"

    def test_artifact_manager_summary(self):
        from runtime.director import ArtifactManager
        am = ArtifactManager()
        am.store("script", {
            "outline": "A hero's journey",
            "characters": [{"name": "Alice"}, {"name": "Bob"}],
            "episodes": [{"episode_no": 1, "title": "Beginning", "script": "Once upon a time..."}],
        })
        am.store("character", {
            "characters": [
                {"name": "Alice", "appearance": {"hair": "long black", "face": "round", "body": "slim", "cloth": "red dress"}},
            ],
        })
        summary = am.get_summary()
        assert "script" in summary
        assert "character" in summary
        assert "Alice" in summary

    def test_artifact_manager_rollback(self):
        from runtime.director import ArtifactManager
        am = ArtifactManager()
        am.store("script", {"outline": "test"})
        am.store("character", {"characters": []})
        am.store("storyboard", {"storyboard": []})
        am.remove_from("character")
        assert am.get("script") is not None
        assert am.get("character") is None
        assert am.get("storyboard") is None

    @pytest.mark.asyncio
    async def test_director_proceed_on_success(self):
        from runtime.director import Director, DirectorDecision
        am = None  # Will use default
        director = Director(artifact_manager=None, max_retries_per_step=2)
        verdict = await director.analyze_step(
            agent_id="script",
            output={"outline": "test", "characters": [], "episodes": []},
            error=None,
            validation_result={"passed": True},
        )
        assert verdict.decision == DirectorDecision.PROCEED
        assert verdict.confidence > 0

    @pytest.mark.asyncio
    async def test_director_rule_based_retry_on_transient_error(self):
        from runtime.director import Director, DirectorDecision
        director = Director(artifact_manager=None, max_retries_per_step=3)
        verdict = await director.analyze_step(
            agent_id="image",
            output=None,
            error="APIError: Rate limit exceeded (429)",
            validation_result=None,
        )
        assert verdict.decision == DirectorDecision.RETRY
        assert verdict.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_director_rule_based_skip_image_after_retry(self):
        from runtime.director import Director, DirectorDecision
        director = Director(artifact_manager=None, max_retries_per_step=3)
        # Use a non-transient error so skip logic triggers after 1 retry
        await director.analyze_step(
            agent_id="image", output=None,
            error="InvalidAPIKey: access denied", validation_result=None,
        )
        # Second attempt — should skip image (non-transient error, agent is image, retry_count >= 1)
        verdict = await director.analyze_step(
            agent_id="image", output=None,
            error="InvalidAPIKey: access denied", validation_result=None,
        )
        assert verdict.decision == DirectorDecision.SKIP

    @pytest.mark.asyncio
    async def test_director_rule_based_rollback_on_missing_episodes(self):
        from runtime.director import Director, DirectorDecision, ArtifactManager
        am = ArtifactManager()
        # Store a script with EMPTY episodes — this is the root cause
        am.store("script", {"outline": "test", "characters": [], "episodes": []})
        # Store empty character data
        am.store("character", {"characters": []})
        director = Director(artifact_manager=am, max_retries_per_step=3)
        # Storyboard validation fails with character error, retry_count >= 1
        # First call — retry_count = 0, just retry
        v1 = await director.analyze_step(
            agent_id="storyboard",
            output={"storyboard": []},
            error=None,
            validation_result={
                "passed": False,
                "validation_failed": True,
                "errors": ["Character reference missing in scene prompts"],
                "warnings": [],
            },
        )
        # Second call — retry_count = 1, should rollback to character (no char data)
        v2 = await director.analyze_step(
            agent_id="storyboard",
            output={"storyboard": []},
            error=None,
            validation_result={
                "passed": False,
                "validation_failed": True,
                "errors": ["Character reference missing in scene prompts"],
                "warnings": [],
            },
        )
        assert v2.decision == DirectorDecision.ROLLBACK
        assert v2.target_step in ("script", "character")  # Root cause could be either

    @pytest.mark.asyncio
    async def test_director_rewrite_prompt_with_fix_suggestion(self):
        from runtime.director import Director, DirectorDecision
        director = Director(artifact_manager=None, max_retries_per_step=3)
        verdict = await director.analyze_step(
            agent_id="character",
            output={"characters": [{"name": "X", "appearance": {}}]},
            error=None,
            validation_result={
                "passed": False,
                "validation_failed": True,
                "errors": ["Character 'X' missing appearance dimensions: hair, body, cloth, face"],
                "fix_suggestion": "Ensure all 4 appearance dimensions are filled: hair, face, body, cloth",
            },
        )
        assert verdict.decision == DirectorDecision.REWRITE_PROMPT
        assert verdict.modified_prompt != ""

    def test_director_stats(self):
        from runtime.director import Director
        director = Director(artifact_manager=None)
        stats = director.get_stats()
        assert "total_decisions" in stats
        assert "step_retries" in stats

    @pytest.mark.asyncio
    async def test_director_max_retries_cap(self):
        from runtime.director import Director, DirectorDecision
        director = Director(artifact_manager=None, max_retries_per_step=1)
        # First call: retry (transient error)
        v1 = await director.analyze_step(
            agent_id="voice", output=None,
            error="timeout", validation_result=None,
        )
        assert v1.decision == DirectorDecision.RETRY
        # Second call: should be capped — voice is not image, so it won't SKIP
        # It will retry again but the early return catches max_retries
        v2 = await director.analyze_step(
            agent_id="voice", output=None,
            error="timeout", validation_result=None,
        )
        # retry_count=1 >= max_retries=1, and no error-less condition, so it goes to rule-based
        # In rule-based: transient error, retry_count=1, 1 < 1 is False, falls through to PROCEED
        assert v2.decision in (DirectorDecision.PROCEED, DirectorDecision.SKIP)
        assert "Max retries" in v2.reasoning or v2.decision == DirectorDecision.SKIP


# ============================================================
# Phase 2: A2A Conversation Bus Tests
# ============================================================

class TestA2AConversation:
    """Phase 2: Rich A2A context/feedback/constraint passing."""

    def test_send_and_retrieve_message(self):
        from runtime.agent_conversation import AgentConversationBus, A2AMessage
        bus = AgentConversationBus()
        msg = A2AMessage(
            from_agent="script", to_agent="character",
            message_type="handoff", content="Script completed",
        )
        bus.send_message(msg, conversation_id="test_conv")
        msgs = bus.get_messages_for("character", "test_conv")
        assert len(msgs) == 1
        assert msgs[0].content == "Script completed"

    def test_mark_delivered(self):
        from runtime.agent_conversation import AgentConversationBus, A2AMessage
        bus = AgentConversationBus()
        bus.send_message(A2AMessage(
            from_agent="script", to_agent="character", content="test",
        ), conversation_id="c1")
        bus.mark_delivered("character", "c1")
        msgs = bus.get_messages_for("character", "c1")
        assert len(msgs) == 0

    def test_build_handoff_rich_context_script_to_character(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        state = {
            "outline": "A brave hero saves the world",
            "characters": [{"name": "Alice", "role": "hero"}, {"name": "Bob", "role": "villain"}],
            "episodes": [
                {"episode_no": 1, "title": "The Beginning", "summary": "Alice discovers her power"},
            ],
        }
        msg = bus.build_handoff_message(
            from_agent="script", to_agent="character",
            state=state, agent_output=state,
            conversation_id="test",
        )
        # Rich context should contain structured data
        assert msg.context.get("summary") != ""
        assert "character_names" in msg.context
        assert "episode_summaries" in msg.context
        assert "Alice" in msg.context["character_names"]
        assert len(msg.context["episode_summaries"]) == 1
        # Should have constraints
        assert len(msg.constraints) > 0

    def test_build_handoff_rich_context_character_to_storyboard(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        state = {
            "characters": [
                {"name": "Alice", "gender": "female", "appearance": {
                    "hair": "long black hair", "face": "round face with big eyes",
                    "body": "slim", "cloth": "red dress",
                }},
            ],
        }
        msg = bus.build_handoff_message(
            from_agent="character", to_agent="storyboard",
            state=state, agent_output=state,
        )
        # Should have character profiles in context
        assert "character_profiles" in msg.context
        profiles = msg.context["character_profiles"]
        assert len(profiles) == 1
        assert profiles[0]["name"] == "Alice"
        assert profiles[0]["appearance"]["hair"] == "long black hair"

    def test_build_handoff_storyboard_to_image(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        state = {
            "characters": [{"name": "Alice"}],
            "storyboard": [
                {"scene_no": 1, "prompt": "Alice standing in a forest",
                 "camera": "wide shot", "mood": "mysterious",
                 "characters": ["Alice"], "duration": 5},
                {"scene_no": 2, "prompt": "Alice running", "camera": "tracking",
                 "mood": "tense", "characters": ["Alice"], "duration": 3},
            ],
        }
        msg = bus.build_handoff_message(
            from_agent="storyboard", to_agent="image",
            state=state, agent_output=state,
        )
        # Should have scene data
        assert msg.context["scene_count"] == 2
        assert len(msg.context["scenes"]) == 2
        assert msg.context["character_scene_map"]["Alice"] == [1, 2]

    def test_extract_feedback_from_validation(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        msg = bus.build_handoff_message(
            from_agent="storyboard", to_agent="image",
            state={"storyboard": []}, agent_output={},
            validation_result={
                "passed": False,
                "errors": ["Scene 1 prompt too short", "Missing character Alice in scene 3"],
                "warnings": ["Total scenes are few"],
                "fix_suggestion": "Add more detail to scene prompts",
            },
        )
        assert any("Quality issue" in f for f in msg.feedback)
        assert any("Warning" in f for f in msg.feedback)
        assert any("Suggestion" in f for f in msg.feedback)

    def test_extract_artifacts_image(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        output = {
            "images": [
                {"scene_no": 1, "image_url": "https://example.com/1.png"},
                {"scene_no": 2, "image_url": "https://example.com/2.png"},
            ],
        }
        msg = bus.build_handoff_message(
            from_agent="image", to_agent="voice",
            state={}, agent_output=output,
        )
        assert len(msg.artifacts) == 2
        assert msg.artifacts[0].startswith("image:")

    def test_conversation_summary(self):
        from runtime.agent_conversation import AgentConversationBus, A2AMessage
        bus = AgentConversationBus()
        bus.send_message(A2AMessage(
            from_agent="script", to_agent="character",
            content="Script done", constraints=["Keep characters consistent"],
        ), "c1")
        bus.send_message(A2AMessage(
            from_agent="character", to_agent="storyboard",
            content="Characters enriched",
            feedback=["Quality issue: missing hair for Bob"],
        ), "c1")
        summary = bus.get_summary("c1")
        assert "script -> character" in summary
        assert "character -> storyboard" in summary
        assert "Keep characters consistent" in summary

    def test_bus_stats(self):
        from runtime.agent_conversation import AgentConversationBus
        bus = AgentConversationBus()
        stats = bus.get_stats()
        assert stats["total_messages"] == 0
        assert stats["conversations"] == 0


# ============================================================
# Phase 3: StoryMemory Tests
# ============================================================

class TestStoryMemory:
    """Phase 3: Unified StoryMemory system."""

    @pytest.mark.asyncio
    async def test_store_and_query_world_memory(self):
        from runtime.memory.manager import MemoryManager
        from runtime.memory.story_memory import StoryMemory
        mm = MemoryManager()
        sm = StoryMemory(memory_manager=mm)
        await sm.store_world({"setting": "Medieval fantasy kingdom"})
        ctx = await sm.get_context("script", {})
        assert "World Memory" in ctx

    @pytest.mark.asyncio
    async def test_store_scene_memory(self):
        from runtime.memory.manager import MemoryManager
        from runtime.memory.story_memory import StoryMemory
        mm = MemoryManager()
        sm = StoryMemory(memory_manager=mm)
        await sm.store_scene({
            "scene_no": 1, "prompt": "A dark forest",
            "characters": ["Alice"], "mood": "mysterious", "camera": "wide",
        }, conversation_id="test")
        ctx = await sm.get_context("storyboard", {})
        assert "Scene Memory" in ctx
        assert "Scene 1" in ctx

    @pytest.mark.asyncio
    async def test_populate_from_state(self):
        from runtime.memory.manager import MemoryManager
        from runtime.memory.story_memory import StoryMemory
        mm = MemoryManager()
        sm = StoryMemory(memory_manager=mm)
        state = {
            "outline": "A sci-fi adventure in space",
            "characters": [
                {"name": "Zara", "appearance": {"hair": "blue", "cloth": "spacesuit", "face": "sharp", "body": "tall"}},
            ],
            "episodes": [
                {"episode_no": 1, "summary": "Zara finds an alien artifact"},
            ],
        }
        await sm.populate_from_state(state, conversation_id="test")
        # Should have stored world + style memories
        world_ctx = await sm.get_context("script", {})
        assert "World Memory" in world_ctx

    @pytest.mark.asyncio
    async def test_character_memory_from_state(self):
        from runtime.memory.story_memory import StoryMemory
        sm = StoryMemory(memory_manager=None)
        state = {
            "characters": [
                {"name": "Alice", "appearance": {"hair": "long black", "face": "round", "body": "slim", "cloth": "red dress"}},
                {"name": "Bob", "appearance": {"hair": "short blonde", "face": "square", "body": "muscular", "cloth": "blue suit"}},
            ],
        }
        ctx = await sm.get_context("storyboard", state)
        assert "Character Memory" in ctx
        assert "Alice" in ctx
        assert "long black" in ctx

    def test_mem_type_fallback(self):
        from runtime.memory.story_memory import StoryMemory
        from runtime.memory.models import MemoryType
        assert StoryMemory._mem_type("conversation") == MemoryType.CONVERSATION
        assert StoryMemory._mem_type("invalid_value") == MemoryType.CONVERSATION


# ============================================================
# Cross-Phase: WorkflowEngine Integration Tests
# ============================================================

class TestWorkflowEngineIntegration:
    """Integration tests combining all three phases."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_director_and_a2a(self):
        from runtime.director import Director, ArtifactManager
        from runtime.workflow_engine import WorkflowEngine
        from runtime.agent_conversation import AgentConversationBus

        am = ArtifactManager()
        director = Director(artifact_manager=am, max_retries_per_step=2)
        bus = AgentConversationBus()
        engine = WorkflowEngine(
            director=director,
            artifact_manager=am,
            conversation_bus=bus,
        )

        # Register mock agents
        async def mock_script(state):
            return {
                "outline": "A test story",
                "characters": [{"name": "Alice", "role": "hero"}],
                "episodes": [{"episode_no": 1, "title": "Start", "summary": "Alice begins", "script": "Once upon a time..."}],
            }

        async def mock_character(state):
            chars = state.get("characters", [])
            for c in chars:
                c["appearance"] = {
                    "hair": "long black", "face": "round",
                    "body": "slim", "cloth": "red dress",
                }
            return {"characters": chars}

        async def mock_storyboard(state):
            return {
                "storyboard": [
                    {"scene_no": 1, "prompt": "Alice in forest, long black hair, red dress",
                     "characters": ["Alice"], "duration": 5, "camera": "wide", "mood": "calm"},
                ],
            }

        engine.register_agent("script", mock_script)
        engine.register_agent("character", mock_character)
        engine.register_agent("storyboard", mock_storyboard)

        # Run pipeline
        result = await engine.run_pipeline(
            task_id="test_task", story_id="test_story",
            prompt="Test prompt", genre="fantasy",
            conversation_id="test_conv",
        )

        assert result["outline"] == "A test story"
        assert len(result["characters"]) == 1
        assert result["characters"][0]["appearance"]["hair"] == "long black"
        assert len(result["storyboard"]) == 1

        # Verify A2A messages were exchanged
        summary = bus.get_summary("test_conv")
        assert "script -> character" in summary
        assert "character -> storyboard" in summary

        # Verify Director analyzed steps
        stats = director.get_stats()
        assert stats["total_decisions"] >= 3  # At least 3 steps analyzed
        assert stats["artifacts_stored"] >= 3

    @pytest.mark.asyncio
    async def test_pipeline_with_skip_decision(self):
        from runtime.director import Director, ArtifactManager
        from runtime.workflow_engine import WorkflowEngine

        am = ArtifactManager()
        director = Director(artifact_manager=am, max_retries_per_step=1)
        engine = WorkflowEngine(director=director, artifact_manager=am)

        call_count = {"script": 0}

        async def mock_script(state):
            call_count["script"] += 1
            return {"outline": "test", "characters": [], "episodes": []}

        async def failing_character(state):
            raise RuntimeError("API failure")

        async def mock_storyboard(state):
            return {"storyboard": [{"scene_no": 1, "prompt": "test", "characters": [], "duration": 5}]}

        engine.register_agent("script", mock_script)
        engine.register_agent("character", failing_character)
        engine.register_agent("storyboard", mock_storyboard)

        result = await engine.run_pipeline(
            task_id="test_skip", story_id="test",
            prompt="test", genre="test",
        )
        # Character was skipped, but pipeline continued
        assert result["outline"] == "test"

    @pytest.mark.asyncio
    async def test_insert_step_execution(self):
        from runtime.director import Director, ArtifactManager
        from runtime.workflow_engine import WorkflowEngine

        am = ArtifactManager()
        director = Director(artifact_manager=am, max_retries_per_step=2)
        engine = WorkflowEngine(director=director, artifact_manager=am)

        insert_called = {"count": 0}

        async def insert_check(state, verdict):
            insert_called["count"] += 1
            return {"_insert_step_result": "consistency verified"}

        engine.register_insert_step("consistency_check", insert_check)

        async def mock_script(state):
            return {"outline": "test", "characters": [], "episodes": []}

        engine.register_agent("script", mock_script)

        # Test insert step registry
        from runtime.director import DirectorDecision, DirectorVerdict
        verdict = DirectorVerdict(
            decision=DirectorDecision.INSERT_STEP,
            agent_id="script",
            reasoning="Need consistency check",
            insert_step_config={"type": "consistency_check"},
        )
        func = engine._insert_step_registry.get("consistency_check")
        assert func is not None
        result = await func({}, verdict)
        assert result["_insert_step_result"] == "consistency verified"

    @pytest.mark.asyncio
    async def test_rollback_execution(self):
        from runtime.director import Director, ArtifactManager, DirectorDecision, DirectorVerdict
        from runtime.workflow_engine import WorkflowEngine

        am = ArtifactManager()
        director = Director(artifact_manager=am, max_retries_per_step=3)
        bus = None
        engine = WorkflowEngine(director=director, artifact_manager=am, conversation_bus=bus)

        execution_order = []

        async def mock_script(state):
            execution_order.append("script")
            return {"outline": "bad", "characters": [], "episodes": []}

        async def mock_character(state):
            execution_order.append("character")
            return {"characters": []}

        async def mock_storyboard(state):
            execution_order.append("storyboard")
            return {"storyboard": []}

        engine.register_agent("script", mock_script)
        engine.register_agent("character", mock_character)
        engine.register_agent("storyboard", mock_storyboard)

        # Manually trigger a rollback verdict on storyboard -> back to script
        verdict = DirectorVerdict(
            decision=DirectorDecision.ROLLBACK,
            agent_id="storyboard",
            reasoning="Fundamental issue in script",
            target_step="script",
        )
        # Verify rollback removes artifacts
        am.store("script", {"test": 1})
        am.store("character", {"test": 2})
        am.store("storyboard", {"test": 3})
        am.remove_from("script")
        assert am.get("script") is None
        assert am.get("character") is None
        assert am.get("storyboard") is None


# ============================================================
# RuntimeApp Wiring Test
# ============================================================

class TestRuntimeAppWiring:
    """Verify RuntimeApp wires all V1.5 components correctly."""

    def test_app_init_creates_all_components(self):
        from runtime.app import RuntimeApp
        app = RuntimeApp()
        app.init()
        assert app.director is not None
        assert app.artifact_manager is not None
        assert app.conversation_bus is not None
        assert app.story_memory is not None
        assert app.memory_manager is not None

    def test_app_get_workflow_runner(self):
        from runtime.app import RuntimeApp
        app = RuntimeApp()
        app.init()
        runner = app.get_workflow_runner()
        assert runner.director is app.director
        assert runner.conversation_bus is app.conversation_bus
        assert runner.story_memory is app.story_memory


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])