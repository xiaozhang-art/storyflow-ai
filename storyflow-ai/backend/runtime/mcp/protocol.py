"""MCP Protocol - Constants and protocol definitions for Agent OS communication."""

# Message routing patterns
ROUTING_DIRECT = "direct"
ROUTING_BROADCAST = "broadcast"
ROUTING_FANOUT = "fanout"

# Agent roles
ROLE_PLANNER = "planner"
ROLE_EXECUTOR = "executor"
ROLE_REVIEWER = "reviewer"
ROLE_CRITIC = "critic"
ROLE_OPTIMIZER = "optimizer"

# Conversation states
CONV_INIT = "init"
CONV_PLANNING = "planning"
CONV_EXECUTING = "executing"
CONV_WAITING_FEEDBACK = "waiting_feedback"
CONV_REVISING = "revising"
CONV_COMPLETED = "completed"
CONV_FAILED = "failed"

# Session states
SESSION_CREATE = "create"
SESSION_ACTIVE = "active"
SESSION_IDLE = "idle"
SESSION_SUSPENDED = "suspended"
SESSION_EXPIRED = "expired"

# Priority levels
PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_MEDIUM = 2
PRIORITY_LOW = 3

# Task types
TASK_LLM = "llm"
TASK_TOOL = "tool"
TASK_SKILL = "skill"
TASK_A2A = "a2a"
TASK_GPU = "gpu"