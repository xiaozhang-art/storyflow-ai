"""Skill Selector - Selects the appropriate skill for a given task."""
from __future__ import annotations
import logging
from typing import Optional
from runtime.skill_engine.models import Skill
from runtime.skill_engine.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillSelector:
    """Selects the most appropriate skill for a given agent and task.
    
    Selection strategy:
    1. If agent has exactly 1 skill, use it directly.
    2. If agent has multiple skills, use keyword matching on task description.
    3. Future: LLM-based routing for complex selection.
    """
    
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
    
    def select(self, agent_id: str, task_description: str = "") -> Optional[Skill]:
        """Select the best skill for the given agent and task.
        
        Args:
            agent_id: The agent requesting a skill.
            task_description: Description of what needs to be done.
        
        Returns:
            The selected Skill, or None if no skill is available.
        """
        skills = self.registry.get_by_agent(agent_id)
        
        if not skills:
            logger.warning("No skills registered for agent: %s", agent_id)
            return None
        
        if len(skills) == 1:
            return skills[0]
        
        # Multi-skill: keyword matching
        return self._keyword_match(skills, task_description)
    
    def _keyword_match(self, skills: list[Skill], task: str) -> Skill:
        """Match task description to skill using keyword scoring."""
        if not task:
            return skills[0]
        
        task_lower = task.lower()
        best_skill = skills[0]
        best_score = -1
        
        for skill in skills:
            score = 0
            # Match against skill name
            if skill.name.lower() in task_lower:
                score += 10
            # Match against skill description
            for word in skill.description.split():
                if word.lower() in task_lower:
                    score += 2
            # Match against tags
            for tag in skill.tags:
                if tag.lower() in task_lower:
                    score += 5
            
            if score > best_score:
                best_score = score
                best_skill = skill
        
        logger.debug("Skill selected for task '%s': %s (score=%d)", task[:30], best_skill.skill_id, best_score)
        return best_skill
