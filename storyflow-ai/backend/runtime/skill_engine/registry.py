"""Skill Registry - Stores and retrieves skill definitions."""
from __future__ import annotations
import logging
import yaml
from pathlib import Path
from typing import Optional
from runtime.skill_engine.models import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central registry for all skill definitions.
    
    Skills can be registered:
    1. Programmatically via register()
    2. From YAML files via load_from_directory()
    3. From Python dicts via register_from_dict()
    """
    
    def __init__(self):
        self._skills: dict[str, Skill] = {}
    
    def register(self, skill: Skill):
        """Register a skill definition."""
        key = f"{skill.skill_id}@{skill.version}"
        self._skills[key] = skill
        logger.info("Skill registered: %s (v%s) for agent %s", skill.skill_id, skill.version, skill.agent_id)
    
    def register_from_dict(self, data: dict) -> Skill:
        """Register a skill from a dictionary (e.g., loaded YAML)."""
        from runtime.skill_engine.models import SkillConstraint
        constraints_data = data.pop("constraints", {})
        constraints = SkillConstraint(**constraints_data) if constraints_data else SkillConstraint()
        skill = Skill(**data, constraints=constraints)
        self.register(skill)
        return skill
    
    def get(self, skill_id: str, version: str = "1.0") -> Optional[Skill]:
        """Get a skill by ID and version."""
        key = f"{skill_id}@{version}"
        return self._skills.get(key)
    
    def get_by_agent(self, agent_id: str) -> list[Skill]:
        """Get all skills registered for a specific agent."""
        return [s for s in self._skills.values() if s.agent_id == agent_id and s.enabled]
    
    def get_latest(self, skill_id: str) -> Optional[Skill]:
        """Get the latest version of a skill."""
        matches = [(k, s) for k, s in self._skills.items() if k.startswith(f"{skill_id}@")]
        if not matches:
            return None
        # Sort by version (simple string comparison for now)
        matches.sort(key=lambda x: x[1].version, reverse=True)
        return matches[0][1]
    
    def list_all(self) -> list[Skill]:
        """List all registered skills."""
        return list(self._skills.values())
    
    def load_from_directory(self, directory: str):
        """Load all skill definitions from a directory of YAML files.
        
        Expected structure:
        skills/
        ├── script_writer/
        │   ├── skill.yaml
        │   ├── prompt.md
        │   └── schema.json
        """
        skill_dir = Path(directory)
        if not skill_dir.exists():
            logger.warning("Skill directory not found: %s", directory)
            return
        
        for skill_path in skill_dir.iterdir():
            if not skill_path.is_dir():
                continue
            yaml_file = skill_path / "skill.yaml"
            if not yaml_file.exists():
                continue
            
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                
                # Load prompt template from prompt.md if it exists
                prompt_file = skill_path / "prompt.md"
                if prompt_file.exists():
                    with open(prompt_file, "r", encoding="utf-8") as f:
                        data["prompt_template"] = f.read()
                
                # Load schemas from schema.json if it exists
                schema_file = skill_path / "schema.json"
                if schema_file.exists():
                    import json
                    with open(schema_file, "r", encoding="utf-8") as f:
                        schemas = json.load(f)
                    data.setdefault("input_schema", schemas.get("input", {}))
                    data.setdefault("output_schema", schemas.get("output", {}))
                
                self.register_from_dict(data)
            except Exception as e:
                logger.error("Failed to load skill from %s: %s", yaml_file, e)
        
        logger.info("Loaded skills from %s: %d total", directory, len(self._skills))
