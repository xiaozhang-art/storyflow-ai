"""Skill data models - The fundamental capability unit of the Agent OS."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional


class SkillConstraint(BaseModel):
    """Constraints that limit skill behavior (anti-drift mechanism)."""
    max_output_items: Optional[int] = None
    max_tokens: Optional[int] = None
    allowed_formats: list[str] = Field(default_factory=lambda: ["json"])
    forbidden_content: list[str] = Field(default_factory=list)
    style: str = ""
    custom_rules: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    """A Skill is an executable capability module with constraints.
    
    Unlike a Tool (low-level execution), a Skill is a high-level capability
    that combines prompt templates, tool access, and behavioral constraints.
    
    Example: 'storyboard_designer' skill combines:
    - Prompt template for scene composition
    - Tools: comfyui_generate, image_refiner
    - Constraints: max_scenes=15, style=anime, output=json
    """
    skill_id: str
    name: str
    version: str = "1.0"
    description: str = ""
    agent_id: str = ""
    
    # Core skill definition
    prompt_template: str = ""
    tools: list[str] = Field(default_factory=list)
    
    # Schemas
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    
    # Behavioral constraints
    constraints: SkillConstraint = Field(default_factory=SkillConstraint)
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class SkillExecutionResult(BaseModel):
    """Result of a skill execution."""
    skill_id: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    validation_passed: bool = True
    validation_errors: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0