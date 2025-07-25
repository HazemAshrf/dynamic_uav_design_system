"""Dependency Management System for Agent Operations"""

from typing import Dict, List, Set, Tuple, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from dataclasses import dataclass

from backend.models.agent import Agent, AgentStatus


@dataclass
class DependencyNode:
    """Represents an agent and its dependencies."""
    name: str
    id: int
    dependencies: List[str]
    dependents: List[str]  # Agents that depend on this one


@dataclass
class DependencyValidationResult:
    """Result of dependency validation."""
    is_valid: bool
    issues: List[str]
    warnings: List[str]
    circular_dependencies: List[List[str]]
    orphaned_dependencies: List[str]


@dataclass
class DeletionPlan:
    """Plan for agent deletion with dependency handling."""
    target_agent: str
    can_delete_safely: bool
    dependent_agents: List[str]
    cascade_deletion_required: bool
    deletion_order: List[str]
    warnings: List[str]


class DependencyManager:
    """Manages agent dependencies and safe deletion operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_dependency_graph(self) -> Dict[str, DependencyNode]:
        """Build complete dependency graph for all agents."""
        
        # Get all agents
        result = await self.db.execute(
            select(Agent).where(Agent.status.in_([AgentStatus.INACTIVE, AgentStatus.RUNNING]))
        )
        agents = result.scalars().all()
        
        # Build nodes
        nodes = {}
        agent_names = {agent.name for agent in agents}
        
        for agent in agents:
            dependencies = [dep for dep in (agent.dependencies or []) if dep in agent_names]
            nodes[agent.name] = DependencyNode(
                name=agent.name,
                id=agent.id,
                dependencies=dependencies,
                dependents=[]  # Will be populated below
            )
        
        # Populate dependents (reverse dependencies)
        for agent_name, node in nodes.items():
            for dependency in node.dependencies:
                if dependency in nodes:
                    nodes[dependency].dependents.append(agent_name)
        
        return nodes
    
    def detect_circular_dependencies(self, nodes: Dict[str, DependencyNode]) -> List[List[str]]:
        """Detect circular dependencies in the graph."""
        circular_deps = []
        visited = set()
        path = []
        
        def dfs(node_name: str):
            if node_name in path:
                # Found a cycle
                cycle_start = path.index(node_name)
                cycle = path[cycle_start:] + [node_name]
                circular_deps.append(cycle)
                return
            
            if node_name in visited:
                return
            
            visited.add(node_name)
            path.append(node_name)
            
            node = nodes.get(node_name)
            if node:
                for dependency in node.dependencies:
                    dfs(dependency)
            
            path.pop()
        
        for node_name in nodes:
            dfs(node_name)
        
        return circular_deps
    
    def find_orphaned_dependencies(self, nodes: Dict[str, DependencyNode]) -> List[str]:
        """Find dependencies that reference non-existent agents."""
        orphaned = []
        agent_names = set(nodes.keys())
        
        for node in nodes.values():
            for dependency in node.dependencies:
                if dependency not in agent_names:
                    orphaned.append(f"{node.name} depends on non-existent agent: {dependency}")
        
        return orphaned
    
    async def validate_dependencies(self) -> DependencyValidationResult:
        """Validate the entire dependency system."""
        
        nodes = await self.get_dependency_graph()
        issues = []
        warnings = []
        
        # Check for circular dependencies
        circular_deps = self.detect_circular_dependencies(nodes)
        if circular_deps:
            for cycle in circular_deps:
                issues.append(f"Circular dependency detected: {' -> '.join(cycle)}")
        
        # Check for orphaned dependencies
        orphaned = self.find_orphaned_dependencies(nodes)
        warnings.extend(orphaned)
        
        # Check for long dependency chains
        for node_name, node in nodes.items():
            chain_length = self._calculate_dependency_chain_length(node_name, nodes)
            if chain_length > 5:
                warnings.append(f"Agent {node_name} has very long dependency chain ({chain_length} levels)")
        
        return DependencyValidationResult(
            is_valid=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            circular_dependencies=circular_deps,
            orphaned_dependencies=orphaned
        )
    
    def _calculate_dependency_chain_length(self, agent_name: str, nodes: Dict[str, DependencyNode], visited: Set[str] = None) -> int:
        """Calculate the maximum dependency chain length for an agent."""
        if visited is None:
            visited = set()
        
        if agent_name in visited:
            return 0  # Avoid infinite recursion
        
        visited.add(agent_name)
        node = nodes.get(agent_name)
        
        if not node or not node.dependencies:
            return 1
        
        max_depth = 0
        for dependency in node.dependencies:
            depth = self._calculate_dependency_chain_length(dependency, nodes, visited.copy())
            max_depth = max(max_depth, depth)
        
        return max_depth + 1
    
    async def analyze_deletion_impact(self, agent_name: str) -> DeletionPlan:
        """Analyze the impact of deleting a specific agent."""
        
        nodes = await self.get_dependency_graph()
        
        if agent_name not in nodes:
            return DeletionPlan(
                target_agent=agent_name,
                can_delete_safely=False,
                dependent_agents=[],
                cascade_deletion_required=False,
                deletion_order=[],
                warnings=[f"Agent {agent_name} not found"]
            )
        
        target_node = nodes[agent_name]
        dependent_agents = target_node.dependents.copy()
        
        # Check if agent can be deleted safely
        can_delete_safely = len(dependent_agents) == 0
        
        if can_delete_safely:
            return DeletionPlan(
                target_agent=agent_name,
                can_delete_safely=True,
                dependent_agents=[],
                cascade_deletion_required=False,
                deletion_order=[agent_name],
                warnings=[]
            )
        
        # Calculate cascade deletion order
        deletion_order = self._calculate_cascade_deletion_order(agent_name, nodes)
        
        warnings = []
        if len(deletion_order) > 5:
            warnings.append(f"Cascade deletion would affect {len(deletion_order)} agents")
        
        return DeletionPlan(
            target_agent=agent_name,
            can_delete_safely=False,
            dependent_agents=dependent_agents,
            cascade_deletion_required=True,
            deletion_order=deletion_order,
            warnings=warnings
        )
    
    def _calculate_cascade_deletion_order(self, agent_name: str, nodes: Dict[str, DependencyNode]) -> List[str]:
        """Calculate the order in which agents must be deleted for cascade deletion."""
        
        # Find all agents that would be affected by deleting the target agent
        affected_agents = set()
        to_process = [agent_name]
        
        while to_process:
            current = to_process.pop()
            if current in affected_agents:
                continue
                
            affected_agents.add(current)
            
            # Add all agents that depend on the current agent
            if current in nodes:
                to_process.extend(nodes[current].dependents)
        
        # Calculate deletion order (dependents first, then dependencies)
        deletion_order = []
        processed = set()
        
        def add_to_order(agent: str):
            if agent in processed or agent not in affected_agents:
                return
                
            # First, add all dependents
            if agent in nodes:
                for dependent in nodes[agent].dependents:
                    if dependent in affected_agents:
                        add_to_order(dependent)
            
            # Then add the agent itself
            if agent not in processed:
                deletion_order.append(agent)
                processed.add(agent)
        
        for agent in affected_agents:
            add_to_order(agent)
        
        return deletion_order
    
    async def execute_safe_deletion(self, agent_name: str, force_cascade: bool = False) -> Dict[str, Any]:
        """Execute safe agent deletion with dependency handling."""
        
        # Analyze deletion impact
        plan = await self.analyze_deletion_impact(agent_name)
        
        if not plan.can_delete_safely and not force_cascade:
            return {
                "success": False,
                "error": f"Cannot delete agent {agent_name}: has dependent agents {plan.dependent_agents}",
                "deletion_plan": plan,
                "requires_cascade": True
            }
        
        if force_cascade and plan.cascade_deletion_required:
            # Execute cascade deletion
            try:
                deleted_agents = []
                for agent_to_delete in plan.deletion_order:
                    result = await self.db.execute(
                        select(Agent).where(Agent.name == agent_to_delete)
                    )
                    agent = result.scalar_one_or_none()
                    
                    if agent:
                        await self.db.delete(agent)
                        deleted_agents.append(agent_to_delete)
                
                await self.db.commit()
                
                return {
                    "success": True,
                    "deleted_agents": deleted_agents,
                    "cascade_deletion": True,
                    "deletion_plan": plan
                }
                
            except Exception as e:
                await self.db.rollback()
                return {
                    "success": False,
                    "error": f"Cascade deletion failed: {str(e)}",
                    "deletion_plan": plan
                }
        
        else:
            # Simple deletion (no dependencies)
            try:
                result = await self.db.execute(
                    select(Agent).where(Agent.name == agent_name)
                )
                agent = result.scalar_one_or_none()
                
                if not agent:
                    return {
                        "success": False,
                        "error": f"Agent {agent_name} not found"
                    }
                
                await self.db.delete(agent)
                await self.db.commit()
                
                return {
                    "success": True,
                    "deleted_agents": [agent_name],
                    "cascade_deletion": False,
                    "deletion_plan": plan
                }
                
            except Exception as e:
                await self.db.rollback()
                return {
                    "success": False,
                    "error": f"Deletion failed: {str(e)}"
                }
    
    async def update_agent_dependencies(self, agent_name: str, new_dependencies: List[str]) -> Dict[str, Any]:
        """Update an agent's dependencies with validation."""
        
        # COORDINATOR PROTECTION: Coordinator cannot have dependencies
        if agent_name.lower() == "coordinator" and new_dependencies:
            return {
                "success": False,
                "error": "The coordinator agent cannot have dependencies. It must coordinate all other agents independently."
            }
        
        # Get current dependency graph
        nodes = await self.get_dependency_graph()
        
        if agent_name not in nodes:
            return {
                "success": False,
                "error": f"Agent {agent_name} not found"
            }
        
        # Create temporary updated graph to test for circular dependencies
        test_nodes = nodes.copy()
        test_nodes[agent_name].dependencies = new_dependencies
        
        # Recalculate dependents
        for node in test_nodes.values():
            node.dependents = []
        
        for name, node in test_nodes.items():
            for dependency in node.dependencies:
                if dependency in test_nodes:
                    test_nodes[dependency].dependents.append(name)
        
        # Check for circular dependencies
        circular_deps = self.detect_circular_dependencies(test_nodes)
        if circular_deps:
            return {
                "success": False,
                "error": "Update would create circular dependencies",
                "circular_dependencies": circular_deps
            }
        
        # Update the agent in database
        try:
            result = await self.db.execute(
                select(Agent).where(Agent.name == agent_name)
            )
            agent = result.scalar_one_or_none()
            
            if not agent:
                return {
                    "success": False,
                    "error": f"Agent {agent_name} not found"
                }
            
            agent.dependencies = new_dependencies
            await self.db.commit()
            
            return {
                "success": True,
                "updated_dependencies": new_dependencies,
                "previous_dependencies": nodes[agent_name].dependencies
            }
            
        except Exception as e:
            await self.db.rollback()
            return {
                "success": False,
                "error": f"Failed to update dependencies: {str(e)}"
            }
    
    async def get_dependency_report(self) -> Dict[str, Any]:
        """Get comprehensive dependency report."""
        
        nodes = await self.get_dependency_graph()
        validation = await self.validate_dependencies()
        
        # Calculate statistics
        total_agents = len(nodes)
        agents_with_dependencies = sum(1 for node in nodes.values() if node.dependencies)
        agents_with_dependents = sum(1 for node in nodes.values() if node.dependents)
        
        # Find isolated agents (no dependencies or dependents)
        isolated_agents = [
            name for name, node in nodes.items() 
            if not node.dependencies and not node.dependents
        ]
        
        # Find root agents (no dependencies but have dependents)
        root_agents = [
            name for name, node in nodes.items() 
            if not node.dependencies and node.dependents
        ]
        
        # Find leaf agents (have dependencies but no dependents)
        leaf_agents = [
            name for name, node in nodes.items() 
            if node.dependencies and not node.dependents
        ]
        
        return {
            "validation": validation,
            "statistics": {
                "total_agents": total_agents,
                "agents_with_dependencies": agents_with_dependencies,
                "agents_with_dependents": agents_with_dependents,
                "isolated_agents": len(isolated_agents),
                "root_agents": len(root_agents),
                "leaf_agents": len(leaf_agents)
            },
            "agent_categories": {
                "isolated": isolated_agents,
                "root": root_agents,
                "leaf": leaf_agents
            },
            "dependency_graph": {
                name: {
                    "dependencies": node.dependencies,
                    "dependents": node.dependents
                }
                for name, node in nodes.items()
            }
        }