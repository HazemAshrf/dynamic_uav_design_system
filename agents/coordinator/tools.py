"""Tools for the coordinator agent."""

from langchain_core.tools import tool
from typing import List, Dict, Any
import json


@tool
def get_agent_capabilities() -> str:
    """Get information about agent capabilities and their roles.
    
    Returns:
        JSON string containing agent capability information
    """
    capabilities = {
        "mission_planner": {
            "role": "Defines mission requirements, estimates MTOW, sets overall design constraints",
            "outputs": ["mtow", "range_km", "payload_kg", "endurance_hours", "altitude_m"],
            "dependencies": []
        },
        "aerodynamics": {
            "role": "Designs wing geometry, calculates lift/drag properties, determines flight performance",
            "outputs": ["wing_area_m2", "aspect_ratio", "airfoil_type", "lift_to_drag_ratio", "stall_speed_ms"],
            "dependencies": ["mission_planner"]
        },
        "propulsion": {
            "role": "Selects engine type, calculates power requirements, estimates fuel consumption",
            "outputs": ["engine_power_kw", "thrust_n", "engine_type", "fuel_consumption_rate", "engine_weight_kg"],
            "dependencies": ["mission_planner"]
        },
        "structures": {
            "role": "Designs fuselage and wing structure, selects materials, ensures structural integrity",
            "outputs": ["fuselage_length_m", "wing_spar_material", "fuselage_material", "safety_factor", "structural_weight_kg"],
            "dependencies": ["mission_planner", "aerodynamics"]
        },
        "manufacturing": {
            "role": "Analyzes production feasibility, estimates costs, identifies manufacturing constraints",
            "outputs": ["total_cost_usd", "production_time_hours", "material_cost_usd", "labor_cost_usd", "feasibility_score"],
            "dependencies": ["structures"]
        },
        "thermal_management": {
            "role": "Designs cooling systems, analyzes heat dissipation, ensures thermal stability",
            "outputs": ["cooling_system_type", "heat_dissipation_w", "operating_temp_range", "thermal_mass_kg"],
            "dependencies": ["propulsion", "avionics"]
        },
        "avionics": {
            "role": "Designs electronic systems, navigation, flight control, communication systems",
            "outputs": ["flight_controller", "navigation_system", "communication_range_km", "power_consumption_w", "avionics_weight_kg"],
            "dependencies": ["mission_planner"]
        },
        "payload": {
            "role": "Integrates payload systems, manages weight distribution, designs mounting systems",
            "outputs": ["payload_bay_volume", "mounting_system", "weight_distribution", "payload_power_w"],
            "dependencies": ["mission_planner", "structures"]
        }
    }
    
    return json.dumps(capabilities, indent=2)


@tool
def analyze_workflow_dependencies(available_agents: List[str]) -> str:
    """Analyze the dependency workflow for available agents.
    
    Args:
        available_agents: List of available agent names
        
    Returns:
        JSON string with workflow analysis
    """
    # Get capabilities
    capabilities_str = get_agent_capabilities()
    capabilities = json.loads(capabilities_str)
    
    # Filter to only available agents
    available_capabilities = {
        agent: capabilities[agent] 
        for agent in available_agents 
        if agent in capabilities
    }
    
    # Determine execution order
    execution_order = []
    remaining_agents = set(available_agents)
    
    while remaining_agents:
        # Find agents with no unmet dependencies
        ready_agents = []
        for agent in remaining_agents:
            if agent in capabilities:
                deps = capabilities[agent]["dependencies"]
                if all(dep in execution_order or dep not in available_agents for dep in deps):
                    ready_agents.append(agent)
        
        if not ready_agents:
            # Break circular dependencies or add remaining agents
            ready_agents = list(remaining_agents)
        
        execution_order.extend(ready_agents)
        remaining_agents -= set(ready_agents)
    
    analysis = {
        "available_agents": available_agents,
        "execution_order": execution_order,
        "agent_capabilities": available_capabilities,
        "workflow_feasible": len(available_agents) > 0
    }
    
    return json.dumps(analysis, indent=2)


@tool  
def check_design_compatibility(agent_outputs: Dict[str, Any]) -> str:
    """Check compatibility between different agent outputs.
    
    Args:
        agent_outputs: Dictionary of agent names to their output data
        
    Returns:
        JSON string with compatibility analysis
    """
    compatibility_issues = []
    warnings = []
    
    # Check MTOW consistency
    if "mission_planner" in agent_outputs and "structures" in agent_outputs:
        mtow = agent_outputs["mission_planner"].get("mtow", 0)
        structural_weight = agent_outputs["structures"].get("structural_weight_kg", 0)
        
        if structural_weight > mtow * 0.6:  # Structural weight should be < 60% of MTOW
            compatibility_issues.append(
                f"Structural weight ({structural_weight}kg) is too high relative to MTOW ({mtow}kg)"
            )
    
    # Check power requirements
    if "propulsion" in agent_outputs and "avionics" in agent_outputs:
        engine_power = agent_outputs["propulsion"].get("engine_power_kw", 0)
        avionics_power = agent_outputs["avionics"].get("power_consumption_w", 0) / 1000  # Convert to kW
        
        if avionics_power > engine_power * 0.1:  # Avionics should use < 10% of engine power
            warnings.append(
                f"Avionics power consumption ({avionics_power:.1f}kW) is high relative to engine power ({engine_power}kW)"
            )
    
    # Check wing loading
    if "mission_planner" in agent_outputs and "aerodynamics" in agent_outputs:
        mtow = agent_outputs["mission_planner"].get("mtow", 0)
        wing_area = agent_outputs["aerodynamics"].get("wing_area_m2", 0)
        
        if wing_area > 0:
            wing_loading = mtow / wing_area
            if wing_loading > 500:  # Wing loading > 500 N/m² may be excessive
                warnings.append(
                    f"Wing loading ({wing_loading:.1f} N/m²) is high, may affect performance"
                )
    
    analysis = {
        "compatibility_issues": compatibility_issues,
        "warnings": warnings,
        "overall_compatible": len(compatibility_issues) == 0
    }
    
    return json.dumps(analysis, indent=2)