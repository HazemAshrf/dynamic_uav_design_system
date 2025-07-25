"""Workflow Status page for monitoring and controlling workflows."""

import streamlit as st
import requests
import json
import time
from datetime import datetime
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Workflow - Dynamic Agent Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load custom CSS
css_file = Path(__file__).parent.parent / "assets" / "styles.css"
if css_file.exists():
    with open(css_file) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# API Configuration
API_BASE_URL = "http://localhost:8000/api/v1"

def check_api_health():
    """Check if API is available."""
    try:
        response = requests.get("http://localhost:8000/health", timeout=2)
        return response.status_code == 200
    except:
        return False

# Helper functions
@st.cache_data(ttl=5)  # Short TTL for real-time updates
def fetch_workflows():
    """Fetch all workflows from API."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to fetch workflows: {response.status_code}")
            return {"workflows": []}
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return {"workflows": []}

def fetch_workflow_status(workflow_id):
    """Fetch specific workflow status."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/{workflow_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def fetch_workflow_progress(workflow_id):
    """Fetch workflow progress."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/{workflow_id}/progress", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def start_workflow(user_requirements, max_iterations=10, stability_threshold=3):
    """Start a new workflow."""
    try:
        payload = {
            "user_requirements": user_requirements,
            "max_iterations": max_iterations,
            "stability_threshold": stability_threshold,
            "configuration": {}
        }
        response = requests.post(f"{API_BASE_URL}/workflow/start", json=payload, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to start workflow: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return None

def stop_workflow(workflow_id):
    """Stop a running workflow."""
    try:
        response = requests.post(f"{API_BASE_URL}/workflow/{workflow_id}/stop", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

# Header
st.markdown("""
<div class="main-header">
    <div class="header-content">
        <h1>📊 Workflow</h1>
        <p>Execute and monitor multi-agent workflows</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Check API health
if not check_api_health():
    st.error("❌ Cannot connect to Backend API - make sure it's running on port 8000")
    st.stop()

# Agent Status Check (moved to function)
@st.cache_data(ttl=5)
def check_agent_status():
    """Check if agents are available for workflow execution."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/agents-status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            agent_status = data.get("agent_status", {})
            running_agents = data.get("running_agents", [])
            inactive_agents = data.get("inactive_agents", [])
            
            return {
                "total_agents": data.get("total_agents", 0),
                "inactive_agents": len(inactive_agents),
                "running_agents": len(running_agents),
                "can_start_workflow": len(inactive_agents) > 0 and len(running_agents) == 0,
                "agent_details": agent_status,
                "running_agent_names": running_agents,
                "inactive_agent_names": inactive_agents
            }
        return {"total_agents": 0, "inactive_agents": 0, "running_agents": 0, "can_start_workflow": False, "agent_details": {}}
    except:
        return {"total_agents": 0, "inactive_agents": 0, "running_agents": 0, "can_start_workflow": False, "agent_details": {}}

# Get agent status for workflow controls
agent_status = check_agent_status()

# MAIN WORKFLOW SECTION - MOVED TO TOP
st.markdown("## 🚀 Start New Workflow")

# Show workflow form prominently 
with st.form("start_workflow_form"):
    user_requirements = st.text_area(
        "Project Requirements",
        placeholder="Describe what you want the agents to work on...",
        help="Enter detailed requirements for the multi-agent system to work on",
        height=100
    )
    
    col1, col2 = st.columns(2)
    with col1:
        max_iterations = st.number_input("Max Iterations", min_value=1, max_value=50, value=10)
    with col2:
        stability_threshold = st.number_input("Stability Threshold", min_value=1, max_value=10, value=3)
    
    # Status check for form submission
    if not agent_status["can_start_workflow"]:
        if agent_status["running_agents"] > 0:
            st.warning("⚠️ Cannot start workflow: Agents are currently running. Please wait for current workflow to complete or stop it.")
        elif agent_status["inactive_agents"] == 0:
            st.warning("⚠️ Cannot start workflow: No agents available. Please create agents first in Agent Settings.")
        else:
            st.warning("⚠️ Cannot start workflow: Unknown agent status issue.")
    
    submitted = st.form_submit_button(
        "🚀 Start Workflow", 
        use_container_width=True,
        disabled=not agent_status["can_start_workflow"],
        type="primary"
    )
    
    if submitted:
        if user_requirements.strip():
            with st.spinner("Starting workflow..."):
                result = start_workflow(user_requirements, max_iterations, stability_threshold)
                if result:
                    st.success(f"✅ Workflow started successfully! ID: {result.get('workflow_id', 'Unknown')}")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Failed to start workflow")
        else:
            st.error("Please enter project requirements")

# SIDEBAR: Agent Status (moved from main area)
with st.sidebar:
    st.markdown("### 📊 System Status")
    
    # Auto-refresh toggle
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=True)
    if st.button("🔄 Refresh Now"):
        st.cache_data.clear()
    
    # Agent metrics
    st.metric("Total Agents", agent_status["total_agents"])
    st.metric("Available", agent_status["inactive_agents"])
    st.metric("Running", agent_status["running_agents"])
    
    # System status indicator
    if agent_status["can_start_workflow"]:
        st.success("🟢 Ready to Start")
    elif agent_status["running_agents"] > 0:
        st.info("🔄 Workflow Running")
    else:
        st.warning("⚪ No Agents")
    
    # Individual Agent Status
    if agent_status.get("agent_details"):
        st.markdown("#### 🤖 Agent Status")
        agent_details = agent_status["agent_details"]
        
        for agent_name, status in agent_details.items():
            if status == "inactive":
                st.markdown(f"🔴 **{agent_name}** - INACTIVE")
            elif status == "running": 
                st.markdown(f"🟢 **{agent_name}** - RUNNING")
            else:
                st.markdown(f"⚪ **{agent_name}** - {status.upper()}")

# Auto-refresh functionality
if auto_refresh:
    time.sleep(5)
    st.rerun()

# WORKFLOW MONITORING SECTION

# Active Workflows Section
st.markdown("### 📋 Active Workflows")

workflows_data = fetch_workflows()
workflows = workflows_data.get("workflows", [])

if not workflows:
    st.info("No workflows found. Start a new workflow above to begin.")
else:
    # Filter options
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox("Filter by Status", ["All", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
    with col2:
        sort_by = st.selectbox("Sort by", ["Created Date", "Status", "Progress"])
    with col3:
        show_count = st.selectbox("Show", [10, 25, 50, "All"])

    # Filter and sort workflows
    filtered_workflows = workflows
    if status_filter != "All":
        filtered_workflows = [w for w in workflows if w.get("status") == status_filter]
    
    # Display workflows
    for workflow in filtered_workflows[:show_count if show_count != "All" else len(filtered_workflows)]:
        workflow_id = workflow.get("id")
        status = workflow.get("status", "Unknown")
        created_at = workflow.get("created_at", "Unknown")
        user_requirements = workflow.get("user_requirements", "No requirements specified")
        
        # Status color coding
        status_colors = {
            "RUNNING": "🟢",
            "COMPLETED": "✅", 
            "FAILED": "❌",
            "CANCELLED": "🟡",
            "PENDING": "🔵"
        }
        status_icon = status_colors.get(status, "⚪")
        
        with st.expander(f"{status_icon} Workflow {workflow_id} - {status}", expanded=status=="RUNNING"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown(f"**Requirements:** {user_requirements[:200]}...")
                st.markdown(f"**Created:** {created_at}")
                st.markdown(f"**Status:** {status}")
                
                # Get detailed status and progress
                workflow_status = fetch_workflow_status(workflow_id)
                workflow_progress = fetch_workflow_progress(workflow_id)
                
                if workflow_status:
                    current_iteration = workflow_status.get("current_iteration", 0)
                    max_iterations = workflow_status.get("max_iterations", 10)
                    st.markdown(f"**Progress:** {current_iteration}/{max_iterations} iterations")
                    
                    if current_iteration > 0:
                        progress_percent = (current_iteration / max_iterations) * 100
                        st.progress(progress_percent / 100, f"{progress_percent:.1f}% Complete")
                
                if workflow_progress:
                    agent_progress = workflow_progress.get("agent_progress", {})
                    if agent_progress:
                        st.markdown("**Agent Progress:**")
                        for agent_name, progress in agent_progress.items():
                            tasks_completed = progress.get("tasks_completed", 0)
                            total_tasks = progress.get("total_tasks", 1)
                            st.text(f"  • {agent_name}: {tasks_completed}/{total_tasks} tasks")
            
            with col2:
                if status == "RUNNING":
                    if st.button(f"⏹️ Stop", key=f"stop_{workflow_id}", use_container_width=True):
                        if stop_workflow(workflow_id):
                            st.success("Workflow stopped")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Failed to stop workflow")
                
                if st.button(f"📊 View Details", key=f"details_{workflow_id}", use_container_width=True):
                    # Store selected workflow in session state for detailed view
                    st.session_state.selected_workflow = workflow_id
                    st.rerun()
                
                if st.button(f"💬 Conversations", key=f"conv_{workflow_id}", use_container_width=True):
                    st.switch_page("pages/2_💬_Conversations.py")

# Detailed Workflow View
if hasattr(st.session_state, 'selected_workflow') and st.session_state.selected_workflow:
    workflow_id = st.session_state.selected_workflow
    
    st.markdown(f"### 🔍 Detailed View - Workflow {workflow_id}")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("❌ Close Details"):
            del st.session_state.selected_workflow
            st.rerun()
    
    # Fetch detailed information
    workflow_status = fetch_workflow_status(workflow_id)
    workflow_progress = fetch_workflow_progress(workflow_id)
    
    if workflow_status:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Current Iteration", workflow_status.get("current_iteration", 0))
        with col2:
            st.metric("Max Iterations", workflow_status.get("max_iterations", 10))
        with col3:
            st.metric("Active Agents", len(workflow_status.get("active_agents", [])))
        
        # Execution Timeline
        st.markdown("#### 📅 Execution Timeline")
        execution_history = workflow_status.get("execution_history", [])
        if execution_history:
            for entry in execution_history[-10:]:  # Show last 10 entries
                timestamp = entry.get("timestamp", "Unknown")
                event = entry.get("event", "Unknown event")
                st.text(f"{timestamp}: {event}")
        else:
            st.info("No execution history available")
        
        # Agent Outputs
        st.markdown("#### 🤖 Agent Outputs")
        agent_outputs = workflow_status.get("agent_outputs", {})
        if agent_outputs:
            for agent_name, outputs in agent_outputs.items():
                with st.expander(f"Agent: {agent_name}"):
                    if isinstance(outputs, dict):
                        for iteration, output in outputs.items():
                            st.markdown(f"**Iteration {iteration}:**")
                            st.json(output)
                    else:
                        st.json(outputs)
        else:
            st.info("No agent outputs available")

# System Statistics
st.markdown("### 📈 System Statistics")
col1, col2, col3, col4 = st.columns(4)

total_workflows = len(workflows)
running_workflows = len([w for w in workflows if w.get("status") == "RUNNING"])
completed_workflows = len([w for w in workflows if w.get("status") == "COMPLETED"])
failed_workflows = len([w for w in workflows if w.get("status") == "FAILED"])

with col1:
    st.metric("Total Workflows", total_workflows)
with col2:
    st.metric("Running", running_workflows, delta=f"{running_workflows} active")
with col3:
    st.metric("Completed", completed_workflows)
with col4:
    st.metric("Failed", failed_workflows)

# Footer
st.markdown("---")
st.markdown("*Workflow Status updates every 5 seconds when auto-refresh is enabled*")