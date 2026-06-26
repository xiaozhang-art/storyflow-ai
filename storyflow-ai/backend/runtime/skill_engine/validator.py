"""Skill Validator - Validates skill output against schema and constraints."""
from __future__ import annotations
import json
import logging
from typing import Any
from runtime.skill_engine.models import Skill, SkillExecutionResult

logger = logging.getLogger(__name__)


class SkillValidator:
    """Validates skill execution results against defined schemas and constraints.
    
    This is the second layer of the anti-drift mechanism:
    1. First layer: Prompt constraints (in prompt template)
    2. Second layer: Schema validation (this class)
    3. Third layer: Policy check (constraint rules)
    """
    
    def validate(self, result: SkillExecutionResult, skill: Skill) -> SkillExecutionResult:
        """Validate a skill result against its skill definition.
        
        Mutates and returns the result with validation info.
        """
        if not result.success:
            return result
        
        errors: list[str] = []
        
        # 1. Schema validation (output structure)
        if skill.output_schema:
            schema_errors = self._validate_schema(result.output, skill.output_schema)
            errors.extend(schema_errors)
        
        # 2. Constraint validation (business rules)
        constraint_errors = self._validate_constraints(result.output, skill)
        errors.extend(constraint_errors)
        
        result.validation_passed = len(errors) == 0
        result.validation_errors = errors
        
        if not result.validation_passed:
            logger.warning(
                "Skill validation failed [%s]: %s",
                skill.skill_id, "; ".join(errors),
            )
        
        return result
    
    def _validate_schema(self, output: dict, schema: dict) -> list[str]:
        """Validate output against JSON schema."""
        errors = []
        if not schema:
            return errors
        
        # Check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in output:
                errors.append(f"Missing required field: {field}")
        
        # Check field types
        properties = schema.get("properties", {})
        for field, spec in properties.items():
            if field in output:
                expected_type = spec.get("type")
                if expected_type == "array" and not isinstance(output[field], list):
                    errors.append(f"Field '{field}' should be array")
                elif expected_type == "object" and not isinstance(output[field], dict):
                    errors.append(f"Field '{field}' should be object")
                elif expected_type == "string" and not isinstance(output[field], str):
                    errors.append(f"Field '{field}' should be string")
        
        return errors
    
    def _validate_constraints(self, output: dict, skill: Skill) -> list[str]:
        """Validate output against skill constraints."""
        errors = []
        c = skill.constraints
        
        # Check max output items
        if c.max_output_items is not None:
            for key in output:
                if isinstance(output[key], list) and len(output[key]) > c.max_output_items:
                    errors.append(
                        f"Output '{key}' has {len(output[key])} items, "
                        f"max allowed is {c.max_output_items}"
                    )
        
        # Check forbidden content
        if c.forbidden_content:
            output_str = json.dumps(output, ensure_ascii=False)
            for forbidden in c.forbidden_content:
                if forbidden in output_str:
                    errors.append(f"Output contains forbidden content: {forbidden}")
        
        # Check format
        if c.allowed_formats and isinstance(output, dict):
            # Infer format from output keys
            pass  # Format check is primarily done by schema validation
        
        return errors
