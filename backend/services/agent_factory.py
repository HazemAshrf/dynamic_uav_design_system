"""Agent factory service for dynamic agent creation."""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

from backend.core.config import settings
from backend.services.file_processor import FileProcessor


class AgentFactory:
    """Factory for creating and managing dynamic agents."""
    
    def __init__(self):
        self.file_processor = FileProcessor()
        self.generated_dir = Path(settings.generated_dir)
        
        # Ensure generated directories exist
        (self.generated_dir / "agents").mkdir(parents=True, exist_ok=True)
        (self.generated_dir / "models").mkdir(parents=True, exist_ok=True)
    
    async def create_agent(
        self,
        agent_name: str,
        display_name: str,
        role: str,
        llm_name: str,
        temperature: float,
        dependencies: List[str],
        files: Dict[str, str]
    ) -> Dict[str, Any]:
        """Create a new dynamic agent from uploaded files."""
        
        # Prepare agent metadata for config.json
        agent_metadata = {
            "name": agent_name,
            "display_name": display_name,
            "role": role,
            "llm_name": llm_name,
            "temperature": temperature,
            "max_tokens": 4000,  # Default value
            "dependencies": dependencies,
            "created_at": datetime.now().isoformat(),
            "agent_type": "dynamic",
            "version": "1.0"
        }
        
        # Save uploaded files with metadata
        file_paths = await self.file_processor.save_agent_files(agent_name, files, agent_metadata)
        
        # Load file contents for processing
        file_contents = {}
        for file_key in ['prompts', 'output_class', 'tools', 'dependencies']:
            if file_key in files:
                import base64
                file_contents[file_key] = base64.b64decode(files[file_key]).decode('utf-8')
        
        # Generate agent class
        agent_class_code = await self._generate_agent_class(
            agent_name, role, dependencies, file_contents
        )
        
        # Generate output model
        output_model_code = await self._generate_output_model(
            agent_name, file_contents.get('output_class', '')
        )
        
        # Save generated files
        generated_paths = await self._save_generated_files(
            agent_name, agent_class_code, output_model_code
        )
        
        # Create agent configuration
        agent_config = {
            'name': agent_name,
            'display_name': display_name,
            'role': role,
            'llm_name': llm_name,
            'temperature': temperature,
            'dependencies': dependencies,
            **file_paths,
            **generated_paths,
            'prompts_content': file_contents.get('prompts', ''),
            'tools_content': file_contents.get('tools', ''),
            'output_class_content': file_contents.get('output_class', ''),
            'dependencies_data': self._parse_dependencies(file_contents.get('dependencies', '[]'))
        }
        
        return agent_config
    
    async def _generate_agent_class(
        self,
        agent_name: str,
        role: str,
        dependencies: List[str],
        file_contents: Dict[str, str]
    ) -> str:
        """Generate the complete agent class code."""
        
        class_name = f"{agent_name.title()}Agent"
        prompts_content = file_contents.get('prompts', '').replace('"""', '\\"\\"\\"')
        tools_content = file_contents.get('tools', '')
        
        # Extract tool function names
        tool_names = self._extract_tool_names(tools_content)
        
        # Generate agent class
        template = f'''"""Dynamically generated agent: {agent_name}"""

import asyncio
from typing import Dict, List, Any, Optional
from langchain_openai import ChatOpenAI

from backend.agents.base_agent import BaseAgent
from backend.langgraph.state import DynamicGlobalState

# Import generated output model
from backend.storage.generated.models.{agent_name}_output import {agent_name.title()}Output

# Import tools
{self._generate_tool_imports(agent_name, tool_names)}


class {class_name}(BaseAgent):
    """
    {role}
    
    Generated agent for: {agent_name}
    Dependencies: {', '.join(dependencies) if dependencies else 'None'}
    """
    
    def __init__(self, llm: ChatOpenAI, tools: List, output_class, config: Dict[str, Any]):
        prompts = """{prompts_content}"""
        
        super().__init__(
            name="{agent_name}",
            llm=llm,
            tools=tools,
            output_class=output_class or {agent_name.title()}Output,
            system_prompt=prompts,
            dependencies={dependencies},
            config=config
        )
    
    def check_dependencies_ready(self, state: DynamicGlobalState) -> bool:
        """Check if required dependencies have produced outputs."""
        if not self.dependencies:
            return True
        
        current_iteration = state.current_iteration
        
        for dependency in self.dependencies:
            if dependency not in state.agent_outputs:
                return False
            
            # Check if dependency has output for current or previous iteration
            dep_outputs = state.agent_outputs[dependency]
            if not dep_outputs:
                return False
            
            # Dependencies should have output from current or previous iteration
            has_recent_output = any(
                iteration <= current_iteration 
                for iteration in dep_outputs.keys()
            )
            if not has_recent_output:
                return False
        
        return True
    
    def get_dependency_outputs(self, state: DynamicGlobalState) -> Dict[str, Any]:
        """Get outputs from dependent agents."""
        dependency_outputs = {{}}
        
        for dependency in self.dependencies:
            if dependency in state.agent_outputs:
                dep_outputs = state.agent_outputs[dependency]
                if dep_outputs:
                    # Get most recent output
                    latest_iteration = max(dep_outputs.keys())
                    dependency_outputs[dependency] = dep_outputs[latest_iteration]
        
        return dependency_outputs
    
    def _debug_dependency_status(self, state: DynamicGlobalState):
        """Debug dependency status for troubleshooting."""
        print(f"🔍 {{self.name}} dependency debug:")
        for dep in self.dependencies:
            if dep in state.agent_outputs:
                iterations = list(state.agent_outputs[dep].keys())
                print(f"  - {{dep}}: has outputs for iterations {{iterations}}")
            else:
                print(f"  - {{dep}}: no outputs found")
'''
        
        return template
    
    async def _generate_output_model(self, agent_name: str, output_class_content: str) -> str:
        """Generate enhanced output model with messages support."""
        
        # Parse the existing output class and enhance it
        enhanced_model = f'''"""Generated output model for {agent_name} agent."""

from typing import List, Optional
from pydantic import BaseModel, Field

# Import the original output class content
{output_class_content}

class AgentMessage(BaseModel):
    """Message from one agent to another."""
    to_agent: str = Field(description="Target agent to send message to")
    content: str = Field(description="Message content")
    confidence: Optional[float] = Field(None, description="Confidence score for message")
'''
        
        return enhanced_model
    
    def _extract_tool_names(self, tools_content: str) -> List[str]:
        """Extract tool function names from tools file."""
        import ast
        
        try:
            # Check if file is effectively empty (only comments/docstrings)
            if self._is_empty_tools_content(tools_content):
                return []
            
            tree = ast.parse(tools_content)
            tool_names = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function has @tool decorator
                    for decorator in node.decorator_list:
                        if (isinstance(decorator, ast.Name) and decorator.id == 'tool') or \
                           (isinstance(decorator, ast.Attribute) and decorator.attr == 'tool'):
                            tool_names.append(node.name)
                            break
            
            return tool_names
        except:
            return []
    
    def _is_empty_tools_content(self, content: str) -> bool:
        """Check if tools content is effectively empty (only comments/docstrings)."""
        if not content or not content.strip():
            return True
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            # Skip empty lines, comments, and docstrings
            if line and not line.startswith('#') and not line.startswith('"""') and not line.startswith("'''"):
                # Check for actual code (imports, function definitions, etc.)
                if any(keyword in line for keyword in ['import', 'from', 'def', '@tool', 'class']):
                    # But exclude common empty patterns
                    if 'intentionally empty' in line.lower() or 'no tools' in line.lower():
                        continue
                    return False
        return True
    
    def _generate_tool_imports(self, agent_name: str, tool_names: List[str]) -> str:
        """Generate import statements for tools."""
        if not tool_names:
            return "# No tools detected - using empty tools list"
        
        imports = f"from agents.{agent_name}.tools import ("
        imports += ", ".join(tool_names)
        imports += ")"
        
        return imports
    
    def _parse_dependencies(self, dependencies_content: str) -> List[str]:
        """Parse dependencies from file content."""
        try:
            # Try JSON first
            dependencies = json.loads(dependencies_content)
            if isinstance(dependencies, list):
                return dependencies
            elif isinstance(dependencies, dict):
                return list(dependencies.keys())
        except:
            # Try text format (one per line)
            lines = [line.strip() for line in dependencies_content.split('\n') if line.strip()]
            return lines
        
        return []
    
    async def _save_generated_files(
        self,
        agent_name: str,
        agent_class_code: str,
        output_model_code: str
    ) -> Dict[str, str]:
        """Save generated files and return paths."""
        
        # Save agent class
        agent_file_path = self.generated_dir / "agents" / f"{agent_name}.py"
        with open(agent_file_path, 'w', encoding='utf-8') as f:
            f.write(agent_class_code)
        
        # Save output model
        model_file_path = self.generated_dir / "models" / f"{agent_name}_output.py"
        with open(model_file_path, 'w', encoding='utf-8') as f:
            f.write(output_model_code)
        
        return {
            'generated_class_path': str(agent_file_path),
            'generated_model_path': str(model_file_path)
        }
    
    async def update_agent(
        self,
        agent_name: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update existing agent configuration."""
        
        # Load current files if they exist
        current_files = await self.file_processor.load_agent_files(agent_name)
        
        # Apply updates to files if provided
        if 'files' in updates:
            for file_key, content in updates['files'].items():
                current_files[file_key] = content
        
        # Regenerate agent if files changed
        if 'files' in updates:
            # Get agent config from updates
            agent_config = await self.create_agent(
                agent_name=agent_name,
                display_name=updates.get('display_name', ''),
                role=updates.get('role', ''),
                llm_name=updates.get('llm_name', 'gpt-4'),
                temperature=updates.get('temperature', 0.1),
                dependencies=updates.get('dependencies', []),
                files=updates['files']
            )
            
            return agent_config
        
        # Return current config with updates applied
        return {
            'name': agent_name,
            **updates
        }
    
    async def delete_agent(self, agent_name: str) -> bool:
        """Delete agent and all associated files."""
        try:
            # Delete uploaded files
            await self.file_processor.delete_agent_files(agent_name)
            
            # Delete generated files
            agent_file_path = self.generated_dir / "agents" / f"{agent_name}.py"
            model_file_path = self.generated_dir / "models" / f"{agent_name}_output.py"
            
            if agent_file_path.exists():
                agent_file_path.unlink()
            
            if model_file_path.exists():
                model_file_path.unlink()
            
            return True
            
        except Exception as e:
            print(f"Error deleting agent {agent_name}: {e}")
            return False
    
    async def list_available_agents(self) -> List[Dict[str, Any]]:
        """List all available agents."""
        agents = []
        
        agents_dir = Path(settings.upload_dir)
        if not agents_dir.exists():
            return agents
        
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                agent_name = agent_dir.name
                
                # Load agent files
                files = await self.file_processor.load_agent_files(agent_name)
                
                # Parse dependencies
                dependencies = []
                if 'dependencies' in files:
                    dependencies = self._parse_dependencies(files['dependencies'])
                
                agents.append({
                    'name': agent_name,
                    'has_prompts': 'prompts' in files,
                    'has_output_class': 'output_class' in files,
                    'has_tools': 'tools' in files,
                    'dependencies': dependencies,
                    'files_count': len(files)
                })
        
        return agents
    
    async def get_agent_preview(
        self,
        agent_name: str,
        files: Dict[str, str]
    ) -> Dict[str, Any]:
        """Generate preview of agent code without saving."""
        
        # Decode files
        file_contents = {}
        for file_key in ['prompts', 'output_class', 'tools', 'dependencies']:
            if file_key in files:
                import base64
                file_contents[file_key] = base64.b64decode(files[file_key]).decode('utf-8')
        
        # Generate preview code
        dependencies = self._parse_dependencies(file_contents.get('dependencies', '[]'))
        
        agent_class_code = await self._generate_agent_class(
            agent_name, f"Preview agent: {agent_name}", dependencies, file_contents
        )
        
        output_model_code = await self._generate_output_model(
            agent_name, file_contents.get('output_class', '')
        )
        
        # Extract information
        tool_names = self._extract_tool_names(file_contents.get('tools', ''))
        
        return {
            'agent_class_code': agent_class_code,
            'output_model_code': output_model_code,
            'import_statements': self._generate_tool_imports(agent_name, tool_names).split('\n'),
            'tools_detected': tool_names,
            'dependencies_resolved': dependencies
        }
    
    async def load_agent(self, agent_model):
        """Load an agent instance from database model."""
        try:
            # For coordinator, use special loading
            if agent_model.name == "coordinator":
                return await self._load_coordinator_agent(agent_model)
            
            # For other agents, load normally
            # This would be implemented for other agent types
            return None
            
        except Exception as e:
            print(f"Error loading agent {agent_model.name}: {e}")
            return None
    
    async def _load_coordinator_agent(self, agent_model):
        """Load coordinator agent with dynamic capabilities."""
        try:
            from backend.langgraph.dynamic_coordinator import DynamicCoordinator
            
            # Read prompts from file
            prompts_path = Path(agent_model.prompts_file_path)
            if prompts_path.exists():
                with open(prompts_path, 'r') as f:
                    prompts = f.read()
            else:
                prompts = "You are a UAV design coordinator."
            
            # Load output class
            output_class = await self._load_output_class_for_agent(agent_model)
            if not output_class:
                raise Exception("Could not load coordinator output class")
            
            # Create LLM config
            llm_config = {
                'model': agent_model.llm_name,
                'temperature': agent_model.temperature,
                'max_tokens': agent_model.max_tokens
            }
            
            # Create coordinator instance
            coordinator = DynamicCoordinator(
                llm_config=llm_config,
                prompts=prompts,
                output_class=output_class
            )
            
            return coordinator
            
        except Exception as e:
            print(f"Error loading coordinator agent: {e}")
            return None
    
    async def _load_output_class_for_agent(self, agent_model):
        """Load the output class for an agent."""
        try:
            import importlib.util
            import sys
            
            # Load the generated class file
            class_file_path = agent_model.generated_class_path
            if not class_file_path or not Path(class_file_path).exists():
                print(f"Generated class file not found: {class_file_path}")
                return None
            
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(f"{agent_model.name}_output", class_file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"{agent_model.name}_output"] = module
            spec.loader.exec_module(module)
            
            # Get the output class - try common naming patterns
            possible_names = [
                f"{agent_model.name.title().replace('_', '')}Output",
                "CoordinatorOutput",
                "AgentOutput",
                "Output"
            ]
            
            for class_name in possible_names:
                if hasattr(module, class_name):
                    return getattr(module, class_name)
            
            # If no specific class found, look for BaseModel subclasses
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (hasattr(attr, '__bases__') and 
                    any('BaseModel' in base.__name__ for base in attr.__bases__)):
                    return attr
            
            print(f"No suitable output class found in {class_file_path}")
            return None
            
        except Exception as e:
            print(f"Error loading output class: {e}")
            return None
    
    async def update_agent_files(self, agent_name: str, files: Dict[str, str], metadata_updates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Update agent files and regenerate necessary components."""
        try:
            # Load existing config.json if it exists
            agent_dir = Path(self.file_processor.upload_dir) / agent_name
            config_path = agent_dir / "config.json"
            agent_metadata = None
            
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    agent_metadata = json.load(f)
            
            # Update metadata if provided
            if metadata_updates and agent_metadata:
                agent_metadata.update(metadata_updates)
                agent_metadata["updated_at"] = datetime.now().isoformat()
            
            # Save updated files with metadata
            file_paths = await self.file_processor.save_agent_files(agent_name, files, agent_metadata)
            
            # Load file contents for processing
            file_contents = {}
            for file_key in ['prompts', 'output_class', 'tools', 'dependencies']:
                if file_key in files:
                    file_contents[file_key] = self.file_processor.decode_base64(files[file_key])
            
            # If no file contents were provided, don't regenerate
            if not file_contents:
                return file_paths
            
            # Regenerate agent components with updated files
            dependencies = self._parse_dependencies(file_contents.get('dependencies', '[]'))
            
            # Generate updated agent class
            agent_class_code = await self._generate_agent_class(
                agent_name, f"Updated agent: {agent_name}", dependencies, file_contents
            )
            
            # Generate updated output model  
            output_model_code = await self._generate_output_model(
                agent_name, file_contents.get('output_class', '')
            )
            
            # Save generated files
            class_file_path = self.generated_dir / "agents" / f"{agent_name}.py"
            model_file_path = self.generated_dir / "models" / f"{agent_name}_output.py"
            
            with open(class_file_path, 'w') as f:
                f.write(agent_class_code)
            
            with open(model_file_path, 'w') as f:
                f.write(output_model_code)
            
            # Update file paths with generated paths
            updated_config = file_paths.copy()
            updated_config.update({
                'generated_class_path': str(class_file_path),
                'generated_model_path': str(model_file_path),
                'dependencies_data': dependencies
            })
            
            return updated_config
            
        except Exception as e:
            print(f"Error updating agent files: {e}")
            raise e
    
    async def update_agent_metadata(self, agent_name: str, metadata_updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update only the agent's config.json metadata without touching other files."""
        try:
            # Load existing config.json
            agent_dir = Path(self.file_processor.upload_dir) / agent_name
            config_path = agent_dir / "config.json"
            
            current_metadata = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    current_metadata = json.load(f)
            
            # Apply updates to metadata
            updated_metadata = current_metadata.copy()
            updated_metadata.update(metadata_updates)
            updated_metadata["updated_at"] = datetime.now().isoformat()
            
            # Ensure agent directory exists
            agent_dir.mkdir(parents=True, exist_ok=True)
            
            # Save updated config.json
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(updated_metadata, f, indent=2, default=str)
            
            return {
                "success": True,
                "updated_metadata": updated_metadata,
                "config_path": str(config_path)
            }
            
        except Exception as e:
            print(f"Error updating agent metadata for {agent_name}: {e}")
            raise e