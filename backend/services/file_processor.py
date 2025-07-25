"""File processing service for agent uploads and validation."""

import os
import base64
import json
import ast
import re
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from backend.core.config import settings
from backend.schemas.upload import FileValidationResult, FileValidationResponse


class FileProcessor:
    """Handles file processing, validation, and storage for dynamic agents."""
    
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.generated_dir = Path(settings.generated_dir)
        
        # Ensure directories exist
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
    
    async def validate_agent_files(
        self, 
        files: Dict[str, str], 
        agent_config: Dict[str, Any] = None
    ) -> FileValidationResponse:
        """Validate uploaded agent files."""
        
        validation_results = []
        overall_valid = True
        
        # Expected files
        expected_files = {
            "prompts": {"extensions": [".py"], "required": True},
            "output_class": {"extensions": [".py"], "required": True},
            "tools": {"extensions": [".py"], "required": True},
            "dependencies": {"extensions": [".json", ".txt"], "required": True}
        }
        
        # Validate each file
        for file_key, file_content_b64 in files.items():
            try:
                # Decode base64 content
                file_content = base64.b64decode(file_content_b64).decode('utf-8')
                
                # Determine file type
                file_type = self._determine_file_type(file_key, file_content)
                
                # Validate file
                result = await self._validate_single_file(
                    file_key, file_content, file_type, agent_config
                )
                
                validation_results.append(result)
                
                if not result.valid:
                    overall_valid = False
                    
            except Exception as e:
                error_result = FileValidationResult(
                    filename=file_key,
                    valid=False,
                    file_type="unknown",
                    size_bytes=0,
                    errors=[f"Failed to process file: {str(e)}"]
                )
                validation_results.append(error_result)
                overall_valid = False
        
        # Check for missing required files
        provided_keys = set(files.keys())
        for file_key, config in expected_files.items():
            if config["required"] and file_key not in provided_keys:
                missing_result = FileValidationResult(
                    filename=file_key,
                    valid=False,
                    file_type="missing",
                    size_bytes=0,
                    errors=[f"Required file '{file_key}' is missing"]
                )
                validation_results.append(missing_result)
                overall_valid = False
        
        # Create summary
        valid_count = sum(1 for r in validation_results if r.valid)
        invalid_count = len(validation_results) - valid_count
        total_size = sum(r.size_bytes for r in validation_results)
        
        summary = {
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "total_size_bytes": total_size,
            "files_processed": len(validation_results)
        }
        
        return FileValidationResponse(
            overall_valid=overall_valid,
            validation_results=validation_results,
            summary=summary
        )
    
    async def _validate_single_file(
        self,
        filename: str,
        content: str,
        file_type: str,
        agent_config: Dict[str, Any] = None
    ) -> FileValidationResult:
        """Validate a single file."""
        
        errors = []
        warnings = []
        metadata = {}
        size_bytes = len(content.encode('utf-8'))
        
        # File-specific validation
        if filename == "prompts":
            errors.extend(self._validate_prompts_file(content, metadata))
        elif filename == "output_class":
            errors.extend(self._validate_output_class_file(content, metadata))
        elif filename == "tools":
            errors.extend(self._validate_tools_file(content, metadata))
        elif filename == "dependencies":
            errors.extend(self._validate_dependencies_file(content, metadata))
        
        # Security validation
        security_issues = self._check_security_issues(content, file_type)
        if security_issues:
            errors.extend(security_issues)
        
        # Size validation
        if size_bytes > settings.max_upload_size:
            errors.append(f"File size ({size_bytes} bytes) exceeds maximum allowed ({settings.max_upload_size} bytes)")
        
        is_valid = len(errors) == 0
        
        return FileValidationResult(
            filename=filename,
            valid=is_valid,
            file_type=file_type,
            size_bytes=size_bytes,
            errors=errors,
            warnings=warnings,
            metadata=metadata
        )
    
    def _determine_file_type(self, filename: str, content: str) -> str:
        """Determine file type from filename and content."""
        if filename.endswith('.py') or filename in ["prompts", "output_class", "tools"]:
            return "python"
        elif filename.endswith('.json') or filename == "dependencies":
            return "json"
        elif filename.endswith(('.md', '.txt')):
            return "text"
        else:
            # Try to detect from content
            if content.strip().startswith('{') or content.strip().startswith('['):
                return "json"
            elif 'class ' in content or 'def ' in content or 'import ' in content:
                return "python"
            else:
                return "text"
    
    def _validate_prompts_file(self, content: str, metadata: Dict) -> List[str]:
        """Validate prompts file content."""
        errors = []
        
        if not content.strip():
            errors.append("Prompts file is empty")
            return errors
        
        # Basic content validation
        if len(content) < 50:
            errors.append("Prompts file seems too short (less than 50 characters)")
        
        try:
            # Parse as Python and look for prompts constants
            tree = ast.parse(content)
            
            # Look for string constants that might be prompts
            prompts_found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_name = target.id.upper()
                            if 'PROMPT' in var_name or 'SYSTEM' in var_name:
                                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                    prompts_found.append(var_name)
            
            if prompts_found:
                metadata["format"] = "python"
                metadata["prompts_found"] = prompts_found
                metadata["prompt_count"] = len(prompts_found)
            else:
                errors.append("No prompt constants found. Expected variables like SYSTEM_PROMPT or similar.")
            
            # Check for reasonable prompts content in the file
            prompt_indicators = ['you are', 'your role', 'your task', 'instructions', 'guidelines']
            if not any(indicator in content.lower() for indicator in prompt_indicators):
                errors.append("Content doesn't appear to contain typical prompt instructions")
            
        except SyntaxError as e:
            errors.append(f"Python syntax error in prompts file: {str(e)}")
        except Exception as e:
            errors.append(f"Error parsing prompts file: {str(e)}")
        
        return errors
    
    def _validate_output_class_file(self, content: str, metadata: Dict) -> List[str]:
        """Validate Python output class file."""
        errors = []
        
        try:
            # Parse Python code
            tree = ast.parse(content)
            
            # Find classes
            classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            if not classes:
                errors.append("No class definitions found in output class file")
                return errors
            
            # Check for Pydantic BaseModel inheritance
            pydantic_classes = []
            for cls in classes:
                for base in cls.bases:
                    if isinstance(base, ast.Name) and base.id == 'BaseModel':
                        pydantic_classes.append(cls.name)
                    elif isinstance(base, ast.Attribute) and base.attr == 'BaseModel':
                        pydantic_classes.append(cls.name)
            
            if not pydantic_classes:
                errors.append("No Pydantic BaseModel classes found")
            else:
                metadata["pydantic_classes"] = pydantic_classes
                metadata["pydantic_model_detected"] = True
            
            # Check for Field imports
            imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom)]
            has_field_import = any(
                (isinstance(imp, ast.ImportFrom) and imp.module == 'pydantic' and 
                 any(alias.name == 'Field' for alias in imp.names))
                for imp in imports
            )
            
            if not has_field_import:
                errors.append("Missing 'Field' import from pydantic")
            
            metadata["classes_found"] = [cls.name for cls in classes]
            
        except SyntaxError as e:
            errors.append(f"Python syntax error: {str(e)}")
        except Exception as e:
            errors.append(f"Error parsing Python file: {str(e)}")
        
        return errors
    
    def _validate_tools_file(self, content: str, metadata: Dict) -> List[str]:
        """Validate Python tools file."""
        errors = []
        
        try:
            # Parse Python code
            tree = ast.parse(content)
            
            # Find function definitions
            functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            
            # Look for tool decorators
            tool_functions = []
            for func in functions:
                for decorator in func.decorator_list:
                    if (isinstance(decorator, ast.Name) and decorator.id == 'tool') or \
                       (isinstance(decorator, ast.Attribute) and decorator.attr == 'tool'):
                        tool_functions.append(func.name)
            
            if not tool_functions:
                errors.append("No functions with @tool decorator found")
            else:
                metadata["tools_detected"] = tool_functions
                metadata["tool_count"] = len(tool_functions)
            
            # Check for required imports
            imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom)]
            
            # Check for langchain tool import
            has_tool_import = any(
                (isinstance(imp, ast.ImportFrom) and 
                 ('langchain' in str(imp.module) or 'langgraph' in str(imp.module)) and
                 any(alias.name == 'tool' for alias in imp.names))
                for imp in imports if imp.module
            )
            
            if not has_tool_import:
                errors.append("Missing @tool decorator import from langchain")
            
            metadata["functions_found"] = [func.name for func in functions]
            metadata["langchain_compatible"] = has_tool_import
            
        except SyntaxError as e:
            errors.append(f"Python syntax error: {str(e)}")
        except Exception as e:
            errors.append(f"Error parsing Python file: {str(e)}")
        
        return errors
    
    def _validate_dependencies_file(self, content: str, metadata: Dict) -> List[str]:
        """Validate dependencies file (JSON or text)."""
        errors = []
        
        try:
            # Try to parse as JSON first
            dependencies = json.loads(content)
            
            if isinstance(dependencies, list):
                # List of agent names
                if not all(isinstance(dep, str) for dep in dependencies):
                    errors.append("All dependencies must be strings (agent names)")
                else:
                    metadata["dependencies"] = dependencies
                    metadata["dependency_count"] = len(dependencies)
            elif isinstance(dependencies, dict):
                # More complex dependency structure
                metadata["dependencies"] = list(dependencies.keys())
                metadata["dependency_count"] = len(dependencies)
            else:
                errors.append("Dependencies must be a list of agent names or dependency object")
                
        except json.JSONDecodeError:
            # Try to parse as simple text (one per line)
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            if lines:
                metadata["dependencies"] = lines
                metadata["dependency_count"] = len(lines)
                metadata["format"] = "text"
            else:
                errors.append("No dependencies found in file")
        
        # Check for circular dependencies (basic check)
        if "dependencies" in metadata:
            deps = metadata["dependencies"]
            # This is a basic check - more sophisticated circular dependency detection
            # would require knowledge of other agents in the system
            if len(set(deps)) != len(deps):
                errors.append("Duplicate dependencies detected")
            
            metadata["circular_dependency"] = False  # TODO: Implement proper check
        
        return errors
    
    def _check_security_issues(self, content: str, file_type: str) -> List[str]:
        """Check for potential security issues in file content."""
        security_issues = []
        
        # Dangerous patterns to check for
        dangerous_patterns = [
            r'exec\s*\(',
            r'eval\s*\(',
            r'__import__\s*\(',
            r'subprocess\.',
            r'os\.system',
            r'open\s*\([\'"][^\'"]*/[\'"]',  # Absolute path file access
            r'\.\./',  # Directory traversal
            r'import\s+subprocess',
            r'from\s+subprocess',
            r'import\s+os\b',
            r'socket\.',
            r'urllib\.request',
            r'requests\.',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                security_issues.append(f"Potentially dangerous code pattern detected: {pattern}")
        
        return security_issues
    
    async def save_agent_files(
        self, 
        agent_name: str, 
        files: Dict[str, str],
        agent_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """Save agent files to storage and return file paths."""
        
        agent_dir = self.upload_dir / agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)
        
        file_paths = {}
        
        # File mappings
        file_mappings = {
            'prompts': 'prompts.py',
            'output_class': 'output_class.py',
            'tools': 'tools.py',
            'dependencies': 'dependencies.json'
        }
        
        for file_key, filename in file_mappings.items():
            if file_key in files:
                file_path = agent_dir / filename
                
                # Decode and save file
                content = base64.b64decode(files[file_key]).decode('utf-8')
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                file_paths[f"{file_key}_file_path"] = str(file_path)
        
        # Save config.json with agent metadata (as per DYNAMIC_WORKFLOW.md plan)
        if agent_metadata:
            config_path = agent_dir / "config.json"
            import json
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(agent_metadata, f, indent=2, default=str)
            file_paths["config_file_path"] = str(config_path)
        
        return file_paths
    
    async def load_agent_files(self, agent_name: str) -> Dict[str, str]:
        """Load agent files from storage."""
        
        agent_dir = self.upload_dir / agent_name
        if not agent_dir.exists():
            return {}
        
        files = {}
        file_mappings = {
            'prompts.py': 'prompts',
            'output_class.py': 'output_class',
            'tools.py': 'tools',
            'dependencies.json': 'dependencies'
        }
        
        for filename, file_key in file_mappings.items():
            file_path = agent_dir / filename
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    files[file_key] = f.read()
        
        return files
    
    async def delete_agent_files(self, agent_name: str) -> bool:
        """Delete all files for an agent."""
        try:
            agent_dir = self.upload_dir / agent_name
            if agent_dir.exists():
                import shutil
                shutil.rmtree(agent_dir)
            
            # Also clean up generated files
            generated_agent_dir = self.generated_dir / "agents" 
            generated_files = [
                generated_agent_dir / f"{agent_name}.py",
                self.generated_dir / "models" / f"{agent_name}_output.py"
            ]
            
            for file_path in generated_files:
                if file_path.exists():
                    file_path.unlink()
            
            return True
            
        except Exception as e:
            print(f"Error deleting agent files: {e}")
            return False