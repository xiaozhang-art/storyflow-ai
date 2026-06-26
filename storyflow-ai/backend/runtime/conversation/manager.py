"""Conversation Manager - Orchestrates multi-agent collaboration."""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any, Optional
from runtime.conversation.models import (
    Conversation, ConversationStatus, AgentNode, AgentRole,
    Edge, TaskPlan, TaskItem,
)
from runtime.mcp.envelope import MCPEnvelope, MessageType
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher

logger = logging.getLogger(__name__)


class ConversationManager:
    """Multi-Agent Collaboration Scheduler (Swarm Coordinator).
    
    Responsibilities:
    - Task Decomposition (break complex tasks into sub-tasks)
    - Agent Orchestration (build and execute agent interaction graphs)
    - Sub-conversation management (parallel tracks)
    - State management across the collaboration
    - Evaluation integration (judge/reviewer loops)
    """
    
    def __init__(self, control_server=None):
        self._conversations: dict[str, Conversation] = {}
        self._graphs: dict[str, dict[str, AgentNode]] = {}
        self._edges: dict[str, list[Edge]] = {}
        self.control_server = control_server
        self.hooks = get_hook_dispatcher()
    
    async def create_conversation(
        self,
        goal: str = "",
        agents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        """Create a new conversation with a goal and participating agents."""
        conv_id = uuid.uuid4().hex[:16]
        now = time.time()
        
        conversation = Conversation(
            conversation_id=conv_id,
            goal=goal,
            agents=agents or [],
            status=ConversationStatus.INIT,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        
        self._conversations[conv_id] = conversation
        self._graphs[conv_id] = {}
        self._edges[conv_id] = []
        
        # Register with control server if available
        if self.control_server:
            await self.control_server.create_conversation(
                conversation_id=conv_id,
                goal=goal,
                agents=agents,
            )
        
        logger.info("Conversation created: %s (goal: %s, agents: %s)",
                     conv_id, goal[:50], agents)
        return conversation
    
    def add_agent_node(
        self,
        conversation_id: str,
        agent_id: str,
        role: AgentRole = AgentRole.EXECUTOR,
    ) -> AgentNode:
        """Add an agent node to the conversation graph."""
        node = AgentNode(agent_id=agent_id, role=role)
        self._graphs[conversation_id][agent_id] = node
        return node
    
    def add_edge(
        self,
        conversation_id: str,
        from_agent: str,
        to_agent: str,
        condition: str = "always",
    ) -> Edge:
        """Add a directed edge between two agent nodes."""
        edge = Edge(from_agent=from_agent, to_agent=to_agent, condition=condition)
        self._edges[conversation_id].append(edge)
        
        # Update conversation edges list
        conv = self._conversations.get(conversation_id)
        if conv:
            conv.edges.append((from_agent, to_agent))
        
        return edge
    
    def build_linear_pipeline(
        self,
        conversation_id: str,
        agent_ids: list[str],
    ):
        """Build a linear pipeline: A -> B -> C -> D."""
        for i, agent_id in enumerate(agent_ids):
            self.add_agent_node(conversation_id, agent_id)
            if i > 0:
                self.add_edge(conversation_id, agent_ids[i-1], agent_id)
    
    def build_pipeline_with_review(
        self,
        conversation_id: str,
        executor_ids: list[str],
        reviewer_id: str,
    ):
        """Build a pipeline with a review loop.
        
        Executor -> Executor -> ... -> Reviewer
              ^                        |
              +---- (if revision) ------+
        """
        for agent_id in executor_ids:
            self.add_agent_node(conversation_id, agent_id, AgentRole.EXECUTOR)
        
        self.add_agent_node(conversation_id, reviewer_id, AgentRole.REVIEWER)
        
        # Linear edges through executors
        for i in range(1, len(executor_ids)):
            self.add_edge(conversation_id, executor_ids[i-1], executor_ids[i])
        
        # Last executor to reviewer
        if executor_ids:
            self.add_edge(conversation_id, executor_ids[-1], reviewer_id)
        
        # Reviewer back to first executor (revision loop)
        if executor_ids:
            self.add_edge(
                conversation_id, reviewer_id, executor_ids[0],
                condition="revision_needed",
            )
    
    def get_ready_agents(self, conversation_id: str) -> list[AgentNode]:
        """Get agents that are ready to execute (all dependencies met)."""
        graph = self._graphs.get(conversation_id, {})
        edges = self._edges.get(conversation_id, [])
        
        # Find agents whose dependencies are all done
        ready = []
        for agent_id, node in graph.items():
            if node.state != "pending":
                continue
            
            # Check if all incoming edges are from completed nodes
            deps = [e.from_agent for e in edges if e.to_agent == agent_id]
            all_deps_done = all(
                graph.get(dep, AgentNode(agent_id=dep)).state == "done"
                for dep in deps
            )
            
            if all_deps_done:
                ready.append(node)
        
        return ready
    
    def mark_agent_done(
        self,
        conversation_id: str,
        agent_id: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ):
        """Mark an agent node as completed."""
        graph = self._graphs.get(conversation_id, {})
        node = graph.get(agent_id)
        if node:
            node.state = "done" if not error else "failed"
            node.output = output or {}
            node.error = error
            logger.info("Agent %s marked as %s in conversation %s",
                         agent_id, node.state, conversation_id)
    
    def update_conversation_state(
        self,
        conversation_id: str,
        status: ConversationStatus | None = None,
        state: dict[str, Any] | None = None,
    ):
        """Update conversation state."""
        conv = self._conversations.get(conversation_id)
        if not conv:
            return
        
        if status:
            conv.status = status
        if state:
            conv.state.update(state)
        conv.updated_at = time.time()
    
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)
    
    def get_progress(self, conversation_id: str) -> dict:
        """Get execution progress for a conversation."""
        graph = self._graphs.get(conversation_id, {})
        if not graph:
            return {"total": 0, "done": 0, "failed": 0, "progress": 0}
        
        total = len(graph)
        done = sum(1 for n in graph.values() if n.state == "done")
        failed = sum(1 for n in graph.values() if n.state == "failed")
        progress = (done + failed) / total if total > 0 else 0
        
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "running": sum(1 for n in graph.values() if n.state == "running"),
            "pending": sum(1 for n in graph.values() if n.state == "pending"),
            "progress": round(progress * 100, 1),
        }
    
    async def decompose_task(self, task_description: str, llm_call=None) -> TaskPlan:
        """Decompose a complex task into sub-tasks using LLM.
        
        This is a simple template-based decomposition.
        Production systems should use LLM for intelligent decomposition.
        """
        # Known task decompositions for StoryFlow
        if "漫剧" in task_description or "短剧" in task_description or "故事" in task_description:
            return TaskPlan(tasks=[
                TaskItem(id="1", type="skill", agent="script", description="生成剧本", depends_on=[]),
                TaskItem(id="2", type="skill", agent="character", description="设计角色", depends_on=["1"]),
                TaskItem(id="3", type="skill", agent="storyboard", description="生成分镜", depends_on=["1", "2"]),
                TaskItem(id="4", type="skill", agent="image", description="生成图片", depends_on=["3"]),
                TaskItem(id="5", type="skill", agent="voice", description="生成配音", depends_on=["3"]),
                TaskItem(id="6", type="skill", agent="video", description="合成视频", depends_on=["4", "5"]),
            ])
        
        # Generic fallback
        return TaskPlan(tasks=[
            TaskItem(id="1", type="skill", agent="executor", description=task_description, depends_on=[]),
        ])
    
    def get_stats(self) -> dict:
        status_counts = {}
        for conv in self._conversations.values():
            status_counts[conv.status.value] = status_counts.get(conv.status.value, 0) + 1
        return {
            "total_conversations": len(self._conversations),
            "by_status": status_counts,
        }