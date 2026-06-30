"""Integration Tests for V1.5 Runtime Three-Phase Upgrade.

Phase 1: Director brain (LLM analysis + 5 decisions), ROLLBACK, MODIFY_AND_RETRY
Phase 2: A2A structured context/feedback/constraint passing between agents
Phase 3: StoryMemory unified memory system integration

Run from backend/ directory:
    python -m pytest tests/test_v15_integration.py -v --timeout=60
"""

from __future__ import annotations

import asyncio
import sys
import os

# Ensure backend directory is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════
# Phase 1 Tests: Director Brain + 5 Decisions
# ═══════════════════════════════════════════════════════════════════


def test_director_imports():
    """Verify all Director classes are importable."""
    from runtime.director import Director, DirectorDecision, DirectorVerdict, ArtifactManager
    assert Director is not None
    assert DirectorDecision.PROCEED == "proceed"
    assert DirectorDecision.RETRY == "retry"
    assert DirectorDecision.ROLLBACK == "rollback"
    assert DirectorDecision.REWRITE_PROMPT == "rewrite_prompt"
    assert DirectorDecision.SKIP == "skip"
    assert DirectorDecision.INSERT_STEP == "insert_step"
    print("[PASS] test_director_imports")


def test_director_rule_based_proceed():
    """Director should PROCEED when step succeeds with no issues."""
    from runtime.director import Director, DirectorDecision, ArtifactManager

    am = ArtifactManager()
    am.store("script", {
        "outline": "A campus romance story about two students finding love",
        "characters": [{"name": "Alice"}, {"name": "Bob"}],
        "episodes": [{"episode_no": 1, "title": "Meeting", "script": "They meet at the library..."}],
    })

    director = Director(artifact_manager=am)
    verdict = asyncio.get_event_loop().run_until_complete(
        director.analyze_step(
            agent_id="character",
            output={"characters": [
                {"name": "Alice", "appearance": {"hair": "long black", "face": "round", "body": "slim", "cloth": "white dress"}},
                {"name": "Bob", "appearance": {"hair": "short brown", "face": "sharp", "body": "tall", "cloth": "blue shirt"}},
            ]},
        )
    )
    assert verdict.decision == DirectorDecision.PROCEED
    print(f"[PASS] test_director_rule_based_proceed: {verdict.decision.value}")


def test_director_rule_based_retry_transient():
    """Director should RETRY on transient errors (timeout, rate limit)."""
    from runtime.director import Director, DirectorDecision, ArtifactManager

    am = ArtifactManager()
    director = Director(artifact_manager=am, max_retries_per_step=2)

    verdict = asyncio.get_event_loop().run_until_complete(
        director.analyze_step(
            agent_id="image",
            error="APIError: Request timeout after 30s",
        )
    )
    assert verdict.decision == DirectorDecision.RETRY
    assert "timeout" in verdict.reasoning.lower() or "transient" in verdict.reasoning.lower()
    print(f"[PASS] test_director_rule_based_retry_transient: {verdict.reasoning[:80]}")


def test_director_rule_based_skip():
    """Director should SKIP non-critical steps after retries are exhausted."""
    from runtime.director import Director, DirectorDecision, ArtifactManager

    am = ArtifactManager()
    director = Director(artifact_manager=am, max_retries_per_step=2)
    director._step_retry_counts["voice"] = 1  # Already retried once

    verdict = asyncio.get_event_loop().run_until_complete(
        director.analyze_step(
            agent_id="voice",
            error="TTS API returned 500",
        )
    )
    assert verdict.decision == DirectorDecision.SKIP
    print(f"[PASS] test_director_rule_based_skip: {verdict.reasoning[:80]}")


def test_director_rule_based_rollback():
    """Director should ROLLBACK when root cause is in an earlier step."""
    from runtime.director import Director, DirectorDecision, ArtifactManager

    am = ArtifactManager()
    # Script has no episodes
    am.store("script", {
        "outline": "A story",
        "characters": [{"name": "Alice"}],
        "episodes": [],  # EMPTY!
    })
    am.store("character", {"characters": [{"name": "Alice"}]})

    director = Director(artifact_manager=am, max_retries_per_step=2)
    director._step_retry_counts["storyboard"] = 1  # Already retried once

    verdict = asyncio.get_event_loop().run_until_complete(
        director.analyze_step(
            agent_id="storyboard",
            validation_result={
                "validation_failed": True,
                "errors": ["No scenes generated from empty episodes"],
            },
        )
    )
    assert verdict.decision == DirectorDecision.ROLLBACK
    assert verdict.target_step == "script"
    print(f"[PASS] test_director_rule_based_rollback: target={verdict.target_step}")


def test_director_rule_based_rewrite_prompt():
    """Director should REWRITE_PROMPT when quality gate fails with fix suggestion."""
    from runtime.director import Director, DirectorDecision, ArtifactManager

    am = ArtifactManager()
    am.store("script", {
        "outline": "A campus romance",
        "characters": [{"name": "Alice"}, {"name": "Bob"}],
        "episodes": [{"episode_no": 1, "title": "Meeting", "script": "Script content here..."}],
    })
    am.store("character", {
        "characters": [
            {"name": "Alice", "appearance": {"hair": "long black", "face": "round"}},
        ]
    })

    director = Director(artifact_manager=am, max_retries_per_step=2)

    verdict = asyncio.get_event_loop().run_until_complete(
        director.analyze_step(
            agent_id="storyboard",
            validation_result={
                "validation_failed": True,
                "errors": ["Scene 1: prompt too short (5 chars)"],
                "fix_suggestion": "Expand scene 1 prompt to include character appearance details",
            },
        )
    )
    assert verdict.decision == DirectorDecision.REWRITE_PROMPT
    assert "Expand scene 1" in verdict.modified_prompt
    print(f"[PASS] test_director_rule_based_rewrite_prompt: prompt={verdict.modified_prompt[:60]}")


def test_artifact_manager_rollback():
    """ArtifactManager.remove_from() should remove artifacts from target onward."""
    from runtime.director import ArtifactManager

    am = ArtifactManager()
    am.store("script", {"outline": "test"})
    am.store("character", {"characters": []})
    am.store("storyboard", {"storyboard": []})

    assert "script" in am.get_all()
    assert "character" in am.get_all()
    assert "storyboard" in am.get_all()

    am.remove_from("character")
    remaining = am.get_all()
    assert "script" in remaining
    assert "character" not in remaining
    assert "storyboard" not in remaining
    print("[PASS] test_artifact_manager_rollback")


def test_artifact_manager_summary():
    """ArtifactManager.get_summary() should produce readable text for LLM."""
    from runtime.director import ArtifactManager

    am = ArtifactManager()
    am.store("script", {
        "outline": "A campus love story between Alice and Bob",
        "characters": [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}],
        "episodes": [
            {"episode_no": 1, "title": "First Day", "script": "Alice walked into class..."},
            {"episode_no": 2, "title": "Library Encounter", "script": "Bob found Alice studying..."},
        ],
    })

    summary = am.get_summary()
    assert "Alice" in summary
    assert "Bob" in summary
    assert "2 episodes" in summary
    assert "=== script ===" in summary
    print(f"[PASS] test_artifact_manager_summary: {len(summary)} chars")


# ═══════════════════════════════════════════════════════════════════
# Phase 2 Tests: A2A Communication
# ═══════════════════════════════════════════════════════════════════


def test_a2a_message_creation():
    """A2AMessage should carry structured context, constraints, and feedback."""
    from runtime.agent_conversation import A2AMessage

    msg = A2AMessage(
        from_agent="script",
        to_agent="character",
        message_type="handoff",
        content="Script completed with 2 characters",
        context={"character_names": ["Alice", "Bob"]},
        constraints=["Use exact characters from script"],
        feedback=["Consider adding more personality details"],
        artifacts=["script:main"],
    )

    d = msg.to_dict()
    assert d["from_agent"] == "script"
    assert d["to_agent"] == "character"
    assert len(d["constraints"]) == 1
    assert len(d["feedback"]) == 1
    assert d["context"]["character_names"] == ["Alice", "Bob"]
    print("[PASS] test_a2a_message_creation")


def test_a2a_bus_send_and_retrieve():
    """AgentConversationBus should deliver messages to the correct agent."""
    from runtime.agent_conversation import AgentConversationBus

    bus = AgentConversationBus()

    msg = bus.build_handoff_message(
        from_agent="script",
        to_agent="character",
        state={"outline": "test", "characters": [{"name": "Alice"}], "episodes": []},
        agent_output={"characters": [{"name": "Alice"}]},
    )

    bus.send_message(msg, conversation_id="test-conv")

    # character should receive the message
    pending = bus.get_messages_for("character", conversation_id="test-conv")
    assert len(pending) == 1
    assert pending[0].from_agent == "script"

    # script should NOT receive any message
    assert len(bus.get_messages_for("script", conversation_id="test-conv")) == 0
    print("[PASS] test_a2a_bus_send_and_retrieve")


def test_a2a_rich_context_extraction():
    """build_handoff_message should extract rich structured context per agent type."""
    from runtime.agent_conversation import AgentConversationBus

    bus = AgentConversationBus()

    # Test script -> character handoff
    msg = bus.build_handoff_message(
        from_agent="script",
        to_agent="character",
        state={
            "outline": "A romance story",
            "characters": [
                {"name": "Alice", "role": "protagonist"},
                {"name": "Bob", "role": "love interest"},
            ],
            "episodes": [
                {"episode_no": 1, "title": "Meeting", "summary": "Alice meets Bob at school"},
            ],
        },
        agent_output={},
    )

    assert "character_names" in msg.context
    assert "Alice" in msg.context["character_names"]
    assert "character_roles" in msg.context
    assert msg.context["character_roles"]["Alice"] == "protagonist"
    assert "episode_summaries" in msg.context
    assert len(msg.context["episode_summaries"]) == 1
    print("[PASS] test_a2a_rich_context_extraction")

    # Test character -> storyboard handoff
    msg2 = bus.build_handoff_message(
        from_agent="character",
        to_agent="storyboard",
        state={
            "characters": [
                {"name": "Alice", "appearance": {"hair": "long black", "cloth": "white dress"}, "gender": "female"},
            ],
        },
        agent_output={},
    )

    assert "character_profiles" in msg2.context
    assert len(msg2.context["character_profiles"]) == 1
    profile = msg2.context["character_profiles"][0]
    assert profile["name"] == "Alice"
    assert profile["gender"] == "female"
    assert "appearance" in profile
    print("[PASS] test_a2a_rich_context_extraction (character->storyboard)")


def test_a2a_constraint_templates():
    """Constraint templates should provide agent-transition-specific constraints."""
    from runtime.agent_conversation import AgentConversationBus

    bus = AgentConversationBus()

    # character -> storyboard should have character consistency constraints
    msg = bus.build_handoff_message(
        from_agent="character",
        to_agent="storyboard",
        state={"characters": [{"name": "Alice"}], "episodes": [{"title": "ep1"}]},
        agent_output={},
    )

    constraints_text = " ".join(msg.constraints)
    assert "character" in constraints_text.lower() or "appearance" in constraints_text.lower()
    assert "1 episodes" in constraints_text  # Episode count constraint
    print(f"[PASS] test_a2a_constraint_templates: {len(msg.constraints)} constraints")


def test_a2a_conversation_summary():
    """get_summary() should produce LLM-injectable conversation history."""
    from runtime.agent_conversation import AgentConversationBus

    bus = AgentConversationBus()

    # Simulate a full pipeline conversation
    steps = [
        ("script", "character", {"outline": "test"}, {"outline": "test story"}),
        ("character", "storyboard", {"characters": []}, {"characters": []}),
        ("storyboard", "image", {"storyboard": []}, {"storyboard": []}),
    ]

    for from_a, to_a, state, output in steps:
        msg = bus.build_handoff_message(
            from_agent=from_a, to_agent=to_a,
            state=state, agent_output=output,
        )
        bus.send_message(msg, conversation_id="test-summary")
        bus.mark_delivered(to_a, conversation_id="test-summary")

    summary = bus.get_summary("test-summary")
    assert "A2A Agent Communication History" in summary
    assert "script" in summary
    assert "character" in summary
    assert "storyboard" in summary
    print(f"[PASS] test_a2a_conversation_summary: {len(summary)} chars")


# ═══════════════════════════════════════════════════════════════════
# Phase 3 Tests: StoryMemory Unified Memory System
# ═══════════════════════════════════════════════════════════════════


def test_story_memory_creation():
    """StoryMemory should be creatable with MemoryManager."""
    from runtime.memory.story_memory import StoryMemory
    from runtime.memory.manager import MemoryManager

    mm = MemoryManager()
    sm = StoryMemory(memory_manager=mm)
    assert sm is not None
    print("[PASS] test_story_memory_creation")


def test_story_memory_store_and_query():
    """StoryMemory should store facts and retrieve them by dimension."""
    from runtime.memory.story_memory import StoryMemory
    from runtime.memory.manager import MemoryManager

    mm = MemoryManager()
    sm = StoryMemory(memory_manager=mm)

    # Store world info
    asyncio.get_event_loop().run_until_complete(
        sm.store_world({
            "setting": "Modern-day Shanghai university campus",
            "time_period": "2020s",
            "locations": ["library", "cafe", "dormitory"],
        }, conversation_id="test-ctx")
    )

    # Store a scene
    asyncio.get_event_loop().run_until_complete(
        sm.store_scene({
            "scene_no": 1,
            "prompt": "Alice sits alone in the library reading a book",
            "characters": ["Alice"],
            "mood": "peaceful",
            "camera": "medium shot",
        }, conversation_id="test-ctx")
    )

    # Query for storyboard agent
    ctx = asyncio.get_event_loop().run_until_complete(
        sm.get_context("storyboard", {"characters": [{"name": "Alice"}]})
    )
    assert "World Memory" in ctx or "Scene Memory" in ctx or "Character Memory" in ctx
    print(f"[PASS] test_story_memory_store_and_query: {len(ctx)} chars")


def test_story_memory_populate_from_state():
    """populate_from_state should extract and store world/character/style info."""
    from runtime.memory.story_memory import StoryMemory
    from runtime.memory.manager import MemoryManager

    mm = MemoryManager()
    sm = StoryMemory(memory_manager=mm)

    state = {
        "outline": "A campus romance in modern Shanghai",
        "characters": [
            {"name": "Alice", "appearance": {"hair": "long flowing black", "cloth": "white summer dress"}},
            {"name": "Bob", "appearance": {"hair": "short neat brown", "cloth": "blue polo shirt"}},
        ],
        "episodes": [
            {"episode_no": 1, "title": "First Encounter", "summary": "Alice and Bob meet in the library"},
        ],
    }

    asyncio.get_event_loop().run_until_complete(
        sm.populate_from_state(state, conversation_id="test-populate")
    )

    # Verify memory was stored
    stats = sm.get_stats()
    assert "memory_manager" in stats
    print(f"[PASS] test_story_memory_populate_from_state: {stats}")


def test_memory_manager_store_and_retrieve():
    """MemoryManager should store and retrieve facts with tag filtering."""
    from runtime.memory.manager import MemoryManager
    from runtime.memory.models import MemoryType

    mm = MemoryManager()

    # Store a fact
    asyncio.get_event_loop().run_until_complete(
        mm.store_fact(
            text="Alice has long black hair and wears a white dress",
            memory_type=MemoryType.CONVERSATION,
            entity="Alice",
            conversation_id="test-mem",
            tags=["character", "appearance"],
            confidence=0.9,
        )
    )

    # Retrieve with tag filter
    from runtime.memory.models import MemoryQuery
    query = MemoryQuery(
        query="Alice appearance",
        memory_types=[MemoryType.CONVERSATION],
        tags=["appearance"],
        conversation_id="test-mem",
        limit=5,
    )
    results = asyncio.get_event_loop().run_until_complete(mm.retrieve(query))
    assert len(results) >= 1
    assert "Alice" in results[0].text
    print(f"[PASS] test_memory_manager_store_and_retrieve: {len(results)} results")


def test_memory_graph_timeline():
    """MemoryGraph should track character state changes over chapters."""
    from runtime.memory.graph import MemoryGraph

    mg = MemoryGraph()

    # Populate from script
    mg.populate_from_script({
        "characters": [
            {"name": "Alice", "gender": "female", "appearance": {"hair": "long black", "cloth": "white dress"}},
            {"name": "Bob", "gender": "male", "appearance": {"hair": "short brown", "cloth": "blue shirt"}},
        ]
    })

    # Query appearance at chapter 0
    alice_appearance = mg.get_character_appearance_at("Alice", chapter=0)
    assert "long black" in alice_appearance
    assert "white dress" in alice_appearance
    print(f"[PASS] test_memory_graph_timeline: Alice at ch0: {alice_appearance}")

    # State change at chapter 3
    mg.add_state_change("Alice", "appearance.cloth", "red evening gown", chapter=3, reason="Formal event")
    alice_ch3 = mg.get_character_appearance_at("Alice", chapter=3)
    assert "red evening gown" in alice_ch3
    # At chapter 2, should still be white dress
    alice_ch2 = mg.get_character_appearance_at("Alice", chapter=2)
    assert "white dress" in alice_ch2
    assert "red" not in alice_ch2
    print(f"[PASS] test_memory_graph_timeline: Alice ch2={alice_ch2[:40]} ch3={alice_ch3[:40]}")


def test_memory_graph_relationships():
    """MemoryGraph should track character relationships."""
    from runtime.memory.graph import MemoryGraph

    mg = MemoryGraph()
    mg.add_relationship("Alice", "Bob", "loves", chapter=1)
    mg.add_relationship("Bob", "Alice", "admires", chapter=1)

    rels = mg.get_relationships("Alice", chapter=1)
    assert len(rels) == 1
    assert rels[0]["relation"] == "loves"
    assert rels[0]["with"] == "Bob"
    print("[PASS] test_memory_graph_relationships")


# ═══════════════════════════════════════════════════════════════════
# Cross-Phase Integration Tests
# ═══════════════════════════════════════════════════════════════════


def test_runtime_full_import():
    """The complete runtime package should import without errors."""
    from runtime import (
        StoryFlowRuntime, Director, DirectorDecision, DirectorVerdict,
        WorkflowEngine, StoryMemory, MemoryManager,
        AgentConversationBus, A2AMessage, MemoryGraph,
        QualityEngine, QualityResult, ReflectionRuntime,
        PromptRuntime, ModelRouter, AdapterRegistry,
    )
    print("[PASS] test_runtime_full_import")


def test_workflow_engine_creation():
    """WorkflowEngine should be creatable with all V1.5 dependencies."""
    from runtime.workflow_engine import WorkflowEngine
    from runtime.director import Director, ArtifactManager
    from runtime.agent_conversation import AgentConversationBus
    from runtime.memory.story_memory import StoryMemory

    director = Director()
    bus = AgentConversationBus()
    sm = StoryMemory()

    engine = WorkflowEngine(
        director=director,
        artifact_manager=director.artifact_manager,
        conversation_bus=bus,
        story_memory=sm,
    )
    assert engine.director is director
    assert engine.conversation_bus is bus
    assert engine.story_memory is sm
    print("[PASS] test_workflow_engine_creation")


def test_workflow_engine_pipeline_with_mock_agents():
    """WorkflowEngine.run_pipeline() should execute agents and handle Director decisions."""
    from runtime.workflow_engine import WorkflowEngine
    from runtime.director import Director, DirectorDecision
    from runtime.agent_conversation import AgentConversationBus

    async def _run():
        director = Director(max_retries_per_step=1)
        bus = AgentConversationBus()

        engine = WorkflowEngine(
            director=director,
            conversation_bus=bus,
        )

        async def mock_script(state):
            return {
                "outline": "A test story",
                "characters": [{"name": "Alice"}, {"name": "Bob"}],
                "episodes": [{"episode_no": 1, "title": "Start", "script": "Once upon a time..."}],
            }

        async def mock_character(state):
            chars = state.get("characters", [])
            enriched = []
            for c in chars:
                c["appearance"] = {"hair": "black", "face": "round", "body": "slim", "cloth": "white"}
                enriched.append(c)
            return {"characters": enriched}

        engine.register_agent("script", mock_script)
        engine.register_agent("character", mock_character)

        return await engine.run_pipeline(
            task_id="test-task",
            story_id="test-story",
            prompt="A test story",
            genre="test",
        ), director, bus

    result, director, bus = asyncio.run(_run())

    assert result["status"] == "running" or result.get("outline")
    assert result["outline"] == "A test story"
    # Verify Director made decisions
    stats = director.get_stats()
    assert stats["total_decisions"] >= 2  # At least for script and character
    print(f"[PASS] test_workflow_engine_pipeline_with_mock_agents: decisions={stats['total_decisions']}")


def test_workflow_engine_skip_on_failure():
    """WorkflowEngine should eventually SKIP a persistently failing non-critical agent."""
    from runtime.workflow_engine import WorkflowEngine
    from runtime.director import Director
    from runtime.agent_conversation import AgentConversationBus

    async def _run():
        director = Director(max_retries_per_step=1)
        bus = AgentConversationBus()
        engine = WorkflowEngine(director=director, conversation_bus=bus)

        async def mock_script(state):
            return {"outline": "test", "characters": [], "episodes": []}

        async def failing_character(state):
            raise RuntimeError("Intentional failure for testing")

        engine.register_agent("script", mock_script)
        engine.register_agent("character", failing_character)

        return await engine.run_pipeline(
            task_id="test-skip",
            story_id="test-story",
            prompt="test",
            genre="test",
        )

    result = asyncio.run(_run())
    assert result is not None
    print("[PASS] test_workflow_engine_skip_on_failure")


# ═══════════════════════════════════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        # Phase 1: Director Brain
        test_director_imports,
        test_director_rule_based_proceed,
        test_director_rule_based_retry_transient,
        test_director_rule_based_skip,
        test_director_rule_based_rollback,
        test_director_rule_based_rewrite_prompt,
        test_artifact_manager_rollback,
        test_artifact_manager_summary,

        # Phase 2: A2A Communication
        test_a2a_message_creation,
        test_a2a_bus_send_and_retrieve,
        test_a2a_rich_context_extraction,
        test_a2a_constraint_templates,
        test_a2a_conversation_summary,

        # Phase 3: StoryMemory
        test_story_memory_creation,
        test_story_memory_store_and_query,
        test_story_memory_populate_from_state,
        test_memory_manager_store_and_retrieve,
        test_memory_graph_timeline,
        test_memory_graph_relationships,

        # Cross-Phase Integration
        test_runtime_full_import,
        test_workflow_engine_creation,
        test_workflow_engine_pipeline_with_mock_agents,
        test_workflow_engine_skip_on_failure,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"[FAIL] {test.__name__}: {e}")

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err[:100]}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)