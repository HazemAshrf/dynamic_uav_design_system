"""Template validation service for generated prompts."""

import re
import ast
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of template validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    word_count: int
    line_count: int


class TemplateValidator:
    """Validates generated prompt templates."""
    
    def __init__(self):
        self.min_word_count = 50
        self.max_word_count = 5000
        self.min_line_count = 10
        self.max_line_count = 500
        
    def validate_prompt(self, prompt: str, prompt_type: str = "general") -> ValidationResult:
        """Validate a generated prompt."""
        errors = []
        warnings = []
        
        # Basic structure validation
        word_count = len(prompt.split())
        line_count = len(prompt.split('\n'))
        
        # Check minimum requirements
        if word_count < self.min_word_count:
            errors.append(f"Prompt too short: {word_count} words (minimum: {self.min_word_count})")
        
        if word_count > self.max_word_count:
            warnings.append(f"Prompt very long: {word_count} words (maximum recommended: {self.max_word_count})")
            
        if line_count < self.min_line_count:
            errors.append(f"Prompt too few lines: {line_count} (minimum: {self.min_line_count})")
        
        # Content validation
        errors.extend(self._validate_content_structure(prompt, prompt_type))
        warnings.extend(self._validate_content_quality(prompt, prompt_type))
        
        # Template injection validation
        errors.extend(self._validate_template_injection(prompt))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            word_count=word_count,
            line_count=line_count
        )
    
    def _validate_content_structure(self, prompt: str, prompt_type: str) -> List[str]:
        """Validate prompt content structure."""
        errors = []
        
        # Check for required sections based on type
        if prompt_type == "coordinator":
            required_sections = [
                "role", "responsibilities", "guidelines", "decision", "output"
            ]
        elif prompt_type == "agent":
            required_sections = [
                "role", "responsibilities", "communication", "output"
            ]
        else:
            required_sections = ["role", "output"]
        
        for section in required_sections:
            section_patterns = [
                f"## {section.title()}",
                f"### {section.title()}",
                f"**{section.upper()}",
                f"# {section.title()}"
            ]
            
            found = any(pattern.lower() in prompt.lower() for pattern in section_patterns)
            if not found:
                errors.append(f"Missing {section} section in prompt")
        
        return errors
    
    def _validate_content_quality(self, prompt: str, prompt_type: str) -> List[str]:
        """Validate prompt content quality."""
        warnings = []
        
        # Check for placeholder text
        placeholders = [
            "TODO", "FIXME", "XXX", "PLACEHOLDER", "TBD", 
            "{{", "}}", "<fill", ">", "[REPLACE"
        ]
        
        for placeholder in placeholders:
            if placeholder.lower() in prompt.lower():
                warnings.append(f"Possible placeholder text found: {placeholder}")
        
        # Check for common issues
        if "lorem ipsum" in prompt.lower():
            warnings.append("Lorem ipsum placeholder text found")
            
        if prompt.count("agent") < 2 and prompt_type in ["coordinator", "agent"]:
            warnings.append("Very few references to 'agent' - may be too generic")
            
        # Check for reasonable structure
        sections = prompt.count("##")
        if sections < 3:
            warnings.append("Few section headers - prompt may lack structure")
        elif sections > 15:
            warnings.append("Many section headers - prompt may be over-structured")
            
        return warnings
    
    def _validate_template_injection(self, prompt: str) -> List[str]:
        """Validate against template injection attacks."""
        errors = []
        
        # Check for potentially dangerous patterns
        dangerous_patterns = [
            r"__import__",
            r"exec\s*\(",
            r"eval\s*\(",
            r"open\s*\(",
            r"file\s*\(",
            r"subprocess",
            r"os\.system",
            r"os\.popen",
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                errors.append(f"Potentially dangerous code pattern found: {pattern}")
        
        return errors
    
    def validate_agent_references(self, prompt: str, available_agents: List[str]) -> ValidationResult:
        """Validate that agent references in prompt are correct."""
        errors = []
        warnings = []
        
        # Find all agent name references in prompt
        agent_mentions = re.findall(r'\b(\w+_?\w*)\s+agent\b', prompt, re.IGNORECASE)
        agent_mentions.extend(re.findall(r'\*\*(\w+_?\w*)\*\*:', prompt))  # **agent_name**: pattern
        
        # Check if mentioned agents exist
        for mention in agent_mentions:
            mention = mention.lower().strip()
            if mention and mention not in [a.lower() for a in available_agents]:
                if mention not in ['the', 'an', 'each', 'other', 'all', 'any']:  # Common false positives
                    warnings.append(f"Referenced agent '{mention}' not in available agents list")
        
        # Check if all available agents are mentioned (for coordinator prompts)
        mentioned_agents = set(mention.lower() for mention in agent_mentions)
        available_lower = set(agent.lower() for agent in available_agents)
        
        missing_agents = available_lower - mentioned_agents
        if missing_agents and len(available_agents) > 0:
            warnings.append(f"Available agents not mentioned in prompt: {list(missing_agents)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            word_count=len(prompt.split()),
            line_count=len(prompt.split('\n'))
        )
    
    def validate_coordinator_output_schema(self, prompt: str) -> ValidationResult:
        """Validate that coordinator prompt references correct output schema."""
        errors = []
        warnings = []
        
        required_fields = [
            "project_complete", "completion_reason", "available_agents", 
            "agent_tasks", "messages", "iteration"
        ]
        
        for field in required_fields:
            if field not in prompt:
                errors.append(f"Missing reference to output field: {field}")
        
        # Check for correct field descriptions
        if "project_complete" in prompt and "bool" not in prompt.lower():
            warnings.append("project_complete field should be described as boolean")
            
        if "agent_tasks" in prompt and "list" not in prompt.lower():
            warnings.append("agent_tasks field should be described as list")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            word_count=len(prompt.split()),
            line_count=len(prompt.split('\n'))
        )
    
    def validate_prompt_consistency(self, prompts: Dict[str, str]) -> Dict[str, ValidationResult]:
        """Validate consistency across multiple related prompts."""
        results = {}
        
        for name, prompt in prompts.items():
            # Determine prompt type
            prompt_type = "general"
            if "coordinator" in name.lower():
                prompt_type = "coordinator"
            elif "agent" in name.lower():
                prompt_type = "agent"
                
            results[name] = self.validate_prompt(prompt, prompt_type)
        
        return results
    
    def get_validation_summary(self, results: Dict[str, ValidationResult]) -> str:
        """Generate human-readable validation summary."""
        total_prompts = len(results)
        valid_prompts = sum(1 for r in results.values() if r.is_valid)
        total_errors = sum(len(r.errors) for r in results.values())
        total_warnings = sum(len(r.warnings) for r in results.values())
        
        summary = f"Validation Summary: {valid_prompts}/{total_prompts} prompts valid\n"
        summary += f"Total errors: {total_errors}, Total warnings: {total_warnings}\n\n"
        
        for name, result in results.items():
            status = "✅ VALID" if result.is_valid else "❌ INVALID"
            summary += f"{name}: {status} ({result.word_count} words, {len(result.errors)} errors, {len(result.warnings)} warnings)\n"
            
            for error in result.errors:
                summary += f"  ERROR: {error}\n"
            for warning in result.warnings:
                summary += f"  WARNING: {warning}\n"
            summary += "\n"
        
        return summary