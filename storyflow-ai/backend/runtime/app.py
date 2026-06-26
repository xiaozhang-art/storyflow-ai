"""Runtime Application - Initializes and wires together all Runtime components.

This module provides a single entry point to bootstrap the entire Agent OS:
- Hook Dispatcher with default handlers
- Skill Registry loaded from skill definitions
- Session Manager
- A2A Message Bus (Control Server + Transport)
- Conversation Manager
- Agent Runtime
- Memory Manager
- Execution Scheduler
"""
from __future__ import annotations
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class RuntimeApp:
    """Top-level Runtime application that wires all components together.
    
    Usage:
        app = RuntimeApp()
        app.init()
        
        # Access components
        runtime = app.agent_runtime
        control_server = app.control_server
        scheduler = app.scheduler
    """

    def __init__(self):
        # Components (initialized in init())
        self.hook_dispatcher = None
        self.skill_registry = None
        self.session_manager = None
        self.transport = None
        self.control_server = None
        self.conversation_manager = None
        self.memory_manager = None
        self.agent_runtime = None
        self.execution_scheduler = None
        self.mcp_router = None
        self.mcp_validator = None

        self._initialized = False

    def init(
        self,
        settings=None,
        redis_client=None,
        qdrant_client=None,
    ):
        """Initialize all Runtime components.
        
        Args:
            settings: Application settings object (for Langfuse keys, etc.)
            redis_client: Redis client for A2A transport.
            qdrant_client: Qdrant client for memory vector store.
        """
        if self._initialized:
            logger.debug("RuntimeApp already initialized")
            return

        logger.info("Initializing StoryFlow Runtime...")

        # 1. Hook Dispatcher (always first - other components depend on it)
        from runtime.hook.dispatcher import HookDispatcher, get_hook_dispatcher
        self.hook_dispatcher = HookDispatcher()
        # Set as global singleton
        import runtime.hook.dispatcher as hd
        hd._global_dispatcher = self.hook_dispatcher

        # Register default hooks
        self._register_default_hooks(settings)

        # 2. MCP Protocol
        from runtime.mcp.router import MCPRouter
        from runtime.mcp.validator import MCPValidator
        self.mcp_router = MCPRouter()
        self.mcp_validator = MCPValidator()

        # 3. Skill Registry
        from runtime.skill_engine.registry import SkillRegistry
        self.skill_registry = SkillRegistry()
        self._load_skills()

        # 4. Session Manager
        from runtime.session.manager import SessionManager
        self.session_manager = SessionManager()

        # 5. A2A Transport + Control Server
        if redis_client:
            from runtime.message_bus.transport import RedisStreamTransport
            self.transport = RedisStreamTransport(redis_client=redis_client)
            logger.info("A2A Transport: Redis Stream")
        else:
            from runtime.message_bus.transport import InMemoryTransport
            self.transport = InMemoryTransport()
            logger.info("A2A Transport: In-Memory (development mode)")

        from runtime.message_bus.control_server import ControlServer
        self.control_server = ControlServer(
            session_manager=self.session_manager,
            transport=self.transport,
        )

        # 6. Conversation Manager
        from runtime.conversation.manager import ConversationManager
        self.conversation_manager = ConversationManager(
            control_server=self.control_server,
        )

        # 7. Memory Manager
        from runtime.memory.manager import MemoryManager
        self.memory_manager = MemoryManager(
            qdrant_client=qdrant_client,
        )

        # 8. Agent Runtime
        from runtime.agent_runtime.runtime import AgentRuntime
        self.agent_runtime = AgentRuntime(
            skill_registry=self.skill_registry,
            hook_dispatcher=self.hook_dispatcher,
            memory_manager=self.memory_manager,
        )

        # 9. Execution Scheduler
        from runtime.execution.scheduler import ExecutionScheduler
        self.execution_scheduler = ExecutionScheduler()

        self._initialized = True
        logger.info("StoryFlow Runtime initialized successfully")

        # Log stats
        self._log_init_stats()

    def _register_default_hooks(self, settings=None):
        """Register default hook handlers."""
        # Structured logger (always active)
        from runtime.handlers.logger_handler import create_logger_handler
        self.hook_dispatcher.register_global(create_logger_handler())
        logger.info("Hook registered: StructuredLogger")

        # Langfuse (if configured)
        if settings:
            langfuse_pk = getattr(settings, "LANGFUSE_PUBLIC_KEY", "")
            langfuse_sk = getattr(settings, "LANGFUSE_SECRET_KEY", "")
            langfuse_host = getattr(settings, "LANGFUSE_HOST", "https://cloud.langfuse.com")
            if langfuse_pk and langfuse_sk:
                from runtime.handlers.langfuse_handler import create_langfuse_handler
                self.hook_dispatcher.register_global(
                    create_langfuse_handler(
                        public_key=langfuse_pk,
                        secret_key=langfuse_sk,
                        host=langfuse_host,
                    )
                )
                logger.info("Hook registered: Langfuse")

    def _load_skills(self):
        """Load skill definitions from the skills/ directory."""
        # Try to load from the standard skills directory
        skill_dirs = [
            os.path.join(os.path.dirname(__file__), "..", "skills"),
            "/app/skills",
        ]

        for skill_dir in skill_dirs:
            if os.path.isdir(skill_dir):
                try:
                    import yaml
                    self.skill_registry.load_from_directory(skill_dir)
                except ImportError:
                    logger.warning("PyYAML not installed, skipping skill loading")
                except Exception as e:
                    logger.warning("Failed to load skills from %s: %s", skill_dir, e)
                break

    def _log_init_stats(self):
        """Log initialization statistics."""
        stats = {
            "skills": len(self.skill_registry.list_all()),
            "sessions": self.session_manager.get_stats(),
            "hooks": "structured_logger",
        }
        logger.info("Runtime init stats: %s", stats)

    def get_workflow_runner(self):
        """Get a RuntimeWorkflowRunner with all agents pre-registered."""
        from runtime.adapter import RuntimeWorkflowRunner
        runner = RuntimeWorkflowRunner(
            control_server=self.control_server,
            conversation_manager=self.conversation_manager,
            skill_registry=self.skill_registry,
            memory_manager=self.memory_manager,
        )
        return runner

    def get_stats(self) -> dict:
        """Get comprehensive runtime statistics."""
        stats = {
            "initialized": self._initialized,
            "skills": len(self.skill_registry.list_all()) if self.skill_registry else 0,
            "sessions": self.session_manager.get_stats() if self.session_manager else {},
            "conversations": self.conversation_manager.get_stats() if self.conversation_manager else {},
        }
        if self.execution_scheduler:
            stats["execution"] = self.execution_scheduler.get_stats()
        if self.memory_manager:
            stats["memory"] = self.memory_manager.get_stats()
        if self.control_server:
            stats["a2a"] = self.control_server.get_stats()
        return stats


# Global runtime application instance
_runtime_app: Optional[RuntimeApp] = None


def get_runtime_app() -> RuntimeApp:
    """Get the global RuntimeApp instance, initializing if needed."""
    global _runtime_app
    if _runtime_app is None:
        _runtime_app = RuntimeApp()
    return _runtime_app


def init_runtime(settings=None, redis_client=None, qdrant_client=None) -> RuntimeApp:
    """Initialize and return the global RuntimeApp."""
    global _runtime_app
    _runtime_app = RuntimeApp()
    _runtime_app.init(settings=settings, redis_client=redis_client, qdrant_client=qdrant_client)
    return _runtime_app