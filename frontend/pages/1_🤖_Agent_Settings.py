"""Agent Settings page for managing dynamic agents."""

import streamlit as st
import requests
import json
import base64
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Agent Settings - Dynamic Agent Dashboard",
    page_icon="🤖",
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
@st.cache_data(ttl=30)
def fetch_agents():
    """Fetch agents from API."""
    try:
        response = requests.get(f"{API_BASE_URL}/agents/", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to fetch agents: {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return []

@st.cache_data(ttl=5)
def check_agents_running():
    """Check if any agents are currently running."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/agents-running", timeout=5)
        if response.status_code == 200:
            return response.json().get("agents_running", False)
        else:
            return False
    except requests.exceptions.RequestException:
        return False

def get_dependency_report():
    """Get dependency report from API."""
    try:
        response = requests.get(f"{API_BASE_URL}/agents/dependencies/report", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def analyze_deletion_impact(agent_name):
    """Analyze impact of deleting an agent."""
    try:
        response = requests.get(f"{API_BASE_URL}/agents/{agent_name}/deletion-impact", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def upload_agent(agent_data):
    """Upload new agent to API."""
    try:
        response = requests.post(f"{API_BASE_URL}/agents/", json=agent_data, timeout=30)
        return response
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return None

def delete_agent(agent_id, force_cascade=False):
    """Delete agent via API with cascade option."""
    try:
        params = {"force_cascade": force_cascade} if force_cascade else {}
        response = requests.delete(f"{API_BASE_URL}/agents/{agent_id}", params=params, timeout=10)
        return response
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return None

def toggle_agent_status(agent_id, action):
    """Activate or deactivate agent."""
    try:
        response = requests.post(f"{API_BASE_URL}/agents/{agent_id}/{action}", timeout=10)
        return response
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return None

# Header
st.markdown("""
<div class="main-header">
    <div class="header-content">
        <h1>🤖 Agent Settings</h1>
        <p>Manage and configure dynamic agents</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar for statistics and system status
with st.sidebar:
    # System Status
    agents_running = check_agents_running()
    if agents_running:
        st.error("🚨 Workflow Running")
        st.warning("Agent operations blocked")
    else:
        st.success("✅ System Ready")
        st.info("Agents available for modification")
    
    # Agent statistics
    agents = fetch_agents()
    if agents:
        inactive_count = sum(1 for agent in agents if agent.get('status') == 'inactive')
        running_count = sum(1 for agent in agents if agent.get('status') == 'running')
        st.markdown("### 📊 Statistics")
        st.metric("Total Agents", len(agents))
        st.metric("Inactive Agents", inactive_count)
        st.metric("Running Agents", running_count)
        
        # Dependency report
        if st.button("📊 Dependency Report"):
            report = get_dependency_report()
            if report:
                st.json(report.get('statistics', {}))
    else:
        st.markdown("### 📊 Statistics")
        st.metric("Total Agents", 0)
        st.metric("Inactive Agents", 0)
        st.metric("Running Agents", 0)

# Check API health before displaying content
if not check_api_health():
    st.error("❌ Backend API is not available. Please ensure the system is running.")
    st.info("💡 Run `python run_system.py` to start the system.")
    st.stop()

# Edit Agent Modal (Show at top for visibility)
if hasattr(st.session_state, 'edit_agent') and st.session_state.edit_agent:
    agent = st.session_state.edit_agent
    
    st.markdown("---")
    st.markdown("## ✏️ Edit Agent")
    st.markdown(f"**Editing: {agent['display_name']}**")
    st.info("💡 Scroll up to see the edit form clearly. All changes will be saved when you click 'Update Agent'.")
    
    with st.form("edit_agent_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        
        with col1:
            edit_agent_name = st.text_input(
                "Agent Name *",
                value=agent['name'], 
                help="Unique identifier for the agent (lowercase, underscore separated)"
            )
            edit_display_name = st.text_input(
                "Display Name *",
                value=agent['display_name'],
                help="Human-readable name for the agent"
            )
            edit_role = st.text_area(
                "Role Description *",
                value=agent['role'],
                help="Describe what this agent does"
            )
        
        with col2:
            # Available LLM models
            llm_options = ["gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
            current_llm = agent.get('llm_name', 'gpt-4')
            
            # If current LLM is not in the list, add it to preserve the value
            if current_llm not in llm_options:
                llm_options.append(current_llm)
                
            edit_llm_name = st.selectbox(
                "LLM Model *",
                llm_options,
                index=llm_options.index(current_llm)
            )
            edit_temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=2.0,
                value=float(agent.get('temperature', 0.1)),
                step=0.1,
                help="Controls randomness: 0.0 = deterministic, 2.0 = very random"
            )
        
        # Dependencies
        st.markdown("### 🔗 Dependencies")
        existing_deps = agent.get('dependencies', [])
        edit_dependencies_text = st.text_area(
            "Agent Dependencies (one per line)",
            value='\n'.join(existing_deps) if existing_deps else '',
            help="List other agent names that this agent depends on",
            placeholder="mission_planner\naeorodynamics"
        )
        
        # File uploads with current content preview
        st.markdown("### 📁 Agent Files")
        st.info("💡 Leave file fields empty to keep existing files, or upload new files to replace them.")
        
        edit_file_tabs = st.tabs(["Prompts", "Output Class", "Tools"])
        
        edit_uploaded_files = {}
        
        with edit_file_tabs[0]:
            # Show current prompts file preview
            if agent.get('prompts_file_path'):
                with st.expander("📄 Current Prompts File"):
                    try:
                        with open(agent['prompts_file_path'], 'r') as f:
                            current_prompts = f.read()
                        st.code(current_prompts[:500] + "..." if len(current_prompts) > 500 else current_prompts, language="python")
                    except:
                        st.error("Could not load current prompts file")
            
            edit_prompts_file = st.file_uploader(
                "Upload New Prompts File (optional)",
                type=['py'],
                help="Python (.py) file containing agent prompts as string constants (e.g., SYSTEM_PROMPT)"
            )
            if edit_prompts_file:
                edit_uploaded_files['prompts'] = base64.b64encode(edit_prompts_file.read()).decode()
                st.success(f"✅ New prompts file uploaded: {edit_prompts_file.name}")
        
        with edit_file_tabs[1]:
            # Show current output class file preview
            if agent.get('output_class_file_path'):
                with st.expander("📄 Current Output Class File"):
                    try:
                        with open(agent['output_class_file_path'], 'r') as f:
                            current_output = f.read()
                        st.code(current_output[:500] + "..." if len(current_output) > 500 else current_output, language="python")
                    except:
                        st.error("Could not load current output class file")
            
            edit_output_class_file = st.file_uploader(
                "Upload New Output Class File (optional)",
                type=['py'],
                help="Python file containing Pydantic model for agent output"
            )
            if edit_output_class_file:
                edit_uploaded_files['output_class'] = base64.b64encode(edit_output_class_file.read()).decode()
                st.success(f"✅ New output class file uploaded: {edit_output_class_file.name}")
        
        with edit_file_tabs[2]:
            # Show current tools file preview
            if agent.get('tools_file_path'):
                with st.expander("📄 Current Tools File"):
                    try:
                        with open(agent['tools_file_path'], 'r') as f:
                            current_tools = f.read()
                        st.code(current_tools[:500] + "..." if len(current_tools) > 500 else current_tools, language="python")
                    except:
                        st.error("Could not load current tools file")
            
            edit_tools_file = st.file_uploader(
                "Upload New Tools File (optional)",
                type=['py'],
                help="Python file containing LangChain tools for the agent"
            )
            if edit_tools_file:
                edit_uploaded_files['tools'] = base64.b64encode(edit_tools_file.read()).decode()
                st.success(f"✅ New tools file uploaded: {edit_tools_file.name}")
        
        # Form submission
        col1, col2, col3 = st.columns([1, 1, 2])
        
        agents_running = check_agents_running()
        edit_submit_disabled = agents_running
        
        if agents_running:
            st.warning("⚠️ Cannot update agent while workflow is running")
        
        with col1:
            if st.form_submit_button("💾 Update Agent", use_container_width=True, disabled=edit_submit_disabled):
                # Validate required fields
                if not all([edit_agent_name, edit_display_name, edit_role]):
                    st.error("Please fill in all required fields marked with *")
                else:
                    # Process dependencies
                    edit_dependencies = [dep.strip() for dep in edit_dependencies_text.split('\n') if dep.strip()]
                    
                    # Create dependencies JSON file from text input if needed
                    if edit_uploaded_files or edit_dependencies != existing_deps:
                        dependencies_json = {
                            "dependencies": edit_dependencies,
                            "communicates_with": edit_dependencies,
                            "description": f"Dependencies for {edit_agent_name} agent"
                        }
                        edit_uploaded_files['dependencies'] = base64.b64encode(
                            json.dumps(dependencies_json, indent=2).encode()
                        ).decode()
                    
                    # Create update data
                    update_data = {
                        "name": edit_agent_name,
                        "display_name": edit_display_name,
                        "role": edit_role,
                        "llm_name": edit_llm_name,
                        "temperature": edit_temperature,
                        "max_tokens": 4000,
                        "dependencies": edit_dependencies,
                        "files": edit_uploaded_files if edit_uploaded_files else None
                    }
                    
                    # Submit to API
                    with st.spinner("Updating agent..."):
                        try:
                            response = requests.put(
                                f"{API_BASE_URL}/agents/{agent['id']}", 
                                json=update_data, 
                                timeout=30
                            )
                            
                            if response.status_code == 200:
                                result = response.json()
                                operation_id = result.get('operation_id')
                                st.success(f"✅ Agent '{edit_agent_name}' updated successfully!")
                                if operation_id:
                                    st.info(f"📝 Operation ID: {operation_id}")
                                st.session_state.edit_agent = None
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                try:
                                    error_detail = response.json().get('detail', 'Unknown error')
                                    st.error(f"❌ Failed to update agent: {error_detail}")
                                except:
                                    st.error(f"❌ Failed to update agent: HTTP {response.status_code}")
                        except requests.exceptions.RequestException as e:
                            st.error(f"❌ Failed to connect to API: {str(e)}")
        
        with col2:
            if st.form_submit_button("❌ Cancel", use_container_width=True):
                st.session_state.edit_agent = None
                st.rerun()
    
    st.markdown("---")

# Main content
elif hasattr(st.session_state, 'show_add_agent') and st.session_state.show_add_agent:
    # Add Agent Modal
    st.markdown("## ➕ Add New Agent")
    
    with st.form("add_agent_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        
        with col1:
            agent_name = st.text_input(
                "Agent Name *",
                help="Unique identifier for the agent (lowercase, underscore separated)"
            )
            display_name = st.text_input(
                "Display Name *",
                help="Human-readable name for the agent"
            )
            role = st.text_area(
                "Role Description *",
                help="Describe what this agent does"
            )
        
        with col2:
            llm_name = st.selectbox(
                "LLM Model *",
                ["gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
                index=0
            )
            temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=2.0,
                value=0.1,
                step=0.1,
                help="Controls randomness: 0.0 = deterministic, 2.0 = very random"
            )
        
        # Dependencies
        st.markdown("### 🔗 Dependencies")
        dependencies_text = st.text_area(
            "Agent Dependencies (one per line)",
            help="List other agent names that this agent depends on",
            placeholder="mission_planner\naeorodynamics"
        )
        
        # File uploads
        st.markdown("### 📁 Agent Files")
        
        file_tabs = st.tabs(["Prompts", "Output Class", "Tools"])
        
        uploaded_files = {}
        
        with file_tabs[0]:
            prompts_file = st.file_uploader(
                "Upload Prompts File",
                type=['py'],
                help="Python (.py) file containing agent prompts as string constants (e.g., SYSTEM_PROMPT)"
            )
            if prompts_file:
                uploaded_files['prompts'] = base64.b64encode(prompts_file.read()).decode()
                st.success(f"✅ Prompts file uploaded: {prompts_file.name}")
        
        with file_tabs[1]:
            output_class_file = st.file_uploader(
                "Upload Output Class File",
                type=['py'],
                help="Python file containing Pydantic model for agent output"
            )
            if output_class_file:
                uploaded_files['output_class'] = base64.b64encode(output_class_file.read()).decode()
                st.success(f"✅ Output class file uploaded: {output_class_file.name}")
        
        with file_tabs[2]:
            tools_file = st.file_uploader(
                "Upload Tools File",
                type=['py'],
                help="Python file containing LangChain tools for the agent"
            )
            if tools_file:
                uploaded_files['tools'] = base64.b64encode(tools_file.read()).decode()
                st.success(f"✅ Tools file uploaded: {tools_file.name}")
        
        
        # Form submission
        col1, col2, col3 = st.columns([1, 1, 2])
        
        agents_running = check_agents_running()
        submit_disabled = agents_running
        
        if agents_running:
            st.warning("⚠️ Cannot create agent while workflow is running")
        
        with col1:
            if st.form_submit_button("✅ Create Agent", use_container_width=True, disabled=submit_disabled):
                # Validate required fields
                if not all([agent_name, display_name, role]):
                    st.error("Please fill in all required fields marked with *")
                elif len(uploaded_files) < 3:
                    st.error("Please upload all 3 required files (prompts, output class, tools)")
                else:
                    # Process dependencies
                    dependencies = [dep.strip() for dep in dependencies_text.split('\n') if dep.strip()]
                    
                    # Create dependencies JSON file from text input
                    dependencies_json = {
                        "dependencies": dependencies,
                        "communicates_with": dependencies,  # For now, assume can communicate with dependencies
                        "description": f"Dependencies for {agent_name} agent"
                    }
                    uploaded_files['dependencies'] = base64.b64encode(
                        json.dumps(dependencies_json, indent=2).encode()
                    ).decode()
                    
                    # Create agent data
                    agent_data = {
                        "name": agent_name,
                        "display_name": display_name,
                        "role": role,
                        "llm_name": llm_name,
                        "temperature": temperature,
                        "max_tokens": 4000,  # Required field for API schema
                        "dependencies": dependencies,
                        "files": uploaded_files
                    }
                    
                    # Submit to API
                    with st.spinner("Creating agent..."):
                        response = upload_agent(agent_data)
                        
                        if response and response.status_code == 200:
                            result = response.json()
                            operation_id = result.get('operation_id')
                            st.success(f"✅ Agent '{agent_name}' created successfully!")
                            if operation_id:
                                st.info(f"📝 Operation ID: {operation_id}")
                            st.session_state.show_add_agent = False
                            st.cache_data.clear()
                            st.rerun()
                        elif response:
                            try:
                                error_detail = response.json().get('detail', 'Unknown error')
                                st.error(f"❌ Failed to create agent: {error_detail}")
                            except:
                                st.error(f"❌ Failed to create agent: HTTP {response.status_code}")
                        else:
                            st.error("❌ Failed to connect to API")
        
        with col2:
            if st.form_submit_button("❌ Cancel", use_container_width=True):
                st.session_state.show_add_agent = False
                st.rerun()

else:
    # Agent List View
    agents = fetch_agents()
    
    if not agents:
        st.markdown("""
        <div class="welcome-section">
            <h3>No agents configured yet</h3>
            <p>Click "Add New Agent" below to create your first dynamic agent.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Add New Agent button for empty state
        st.markdown("---")
        agents_running = check_agents_running()
        
        if agents_running:
            st.button("🚫 Cannot Add Agent (Workflow Running)", disabled=True, use_container_width=True)
            st.info("Wait for workflow to complete before adding new agents")
        else:
            if st.button("➕ Add New Agent", use_container_width=True, type="primary"):
                st.session_state.show_add_agent = True
                st.rerun()
    else:
        st.markdown(f"### 🤖 Configured Agents ({len(agents)})")
        
        # Agent grid
        for i, agent in enumerate(agents):
            with st.container():
                # Agent card header
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                
                with col1:
                    # Expandable agent info
                    expanded_key = f"expanded_{agent['id']}"
                    is_expanded = st.session_state.get(expanded_key, False)
                    
                    if st.button(
                        f"{'▲' if is_expanded else '▼'} {agent['display_name']}", 
                        key=f"toggle_{agent['id']}",
                        use_container_width=True
                    ):
                        st.session_state[expanded_key] = not is_expanded
                        st.rerun()
                    
                    st.caption(f"**Role:** {agent['role'][:100]}...")
                
                with col2:
                    # Status badge with correct colors per DYNAMIC_WORKFLOW.md plan
                    status = agent.get('status', 'unknown')
                    status_color = {
                        'inactive': '🔴', # INACTIVE = red circle (as per plan)
                        'running': '🟢',  # RUNNING = green circle (as per plan)
                        'error': '🔴',
                        'configuring': '🟡'
                    }.get(status, '⚪')
                    
                    st.markdown(f"{status_color} **{status.title()}**")
                    st.caption(f"Model: {agent.get('llm_name', 'unknown')}")
                
                with col3:
                    # Status control (blocked during workflow)
                    agents_running = check_agents_running()
                    
                    if agents_running:
                        st.button("🚫", disabled=True, help="Operations blocked - workflow running")
                    elif status == 'inactive':
                        if st.button("▶️", key=f"activate_{agent['id']}", help="Activate agent"):
                            response = toggle_agent_status(agent['id'], 'activate')
                            if response and response.status_code == 200:
                                st.success("Agent activated")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Failed to activate agent")
                    elif status == 'running':
                        st.button("🔄", disabled=True, help="Agent is running in workflow")
                    else:
                        if st.button("⏸️", key=f"deactivate_{agent['id']}", help="Deactivate agent"):
                            response = toggle_agent_status(agent['id'], 'deactivate')
                            if response and response.status_code == 200:
                                st.success("Agent deactivated")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Failed to deactivate agent")
                
                with col4:
                    # Delete button with dependency checking
                    agents_running = check_agents_running()
                    
                    if agents_running:
                        st.button("🚫", disabled=True, help="Operations blocked - workflow running")
                    elif st.button("🗑️", key=f"delete_{agent['id']}", help="Delete agent"):
                        deletion_state_key = f"deletion_state_{agent['id']}"
                        current_state = st.session_state.get(deletion_state_key, "initial")
                        
                        if current_state == "initial":
                            # Analyze deletion impact
                            with st.spinner("Analyzing dependencies..."):
                                impact = analyze_deletion_impact(agent['name'])
                                if impact:
                                    st.session_state[f"deletion_impact_{agent['id']}"] = impact
                                    if impact.get("can_delete_safely", False):
                                        st.session_state[deletion_state_key] = "confirm_safe"
                                    else:
                                        st.session_state[deletion_state_key] = "show_dependencies"
                                    st.rerun()
                                else:
                                    st.error("Failed to analyze deletion impact")
                        
                        elif current_state == "confirm_safe":
                            # Safe deletion - just confirm
                            response = delete_agent(agent['id'])
                            if response and response.status_code == 200:
                                st.success("Agent deleted safely")
                                st.session_state.pop(deletion_state_key, None)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Failed to delete agent")
                                st.session_state[deletion_state_key] = "initial"
                        
                        elif current_state == "show_dependencies":
                            # Show dependency warning with cascade option
                            impact = st.session_state.get(f"deletion_impact_{agent['id']}")
                            if impact:
                                dependent_agents = impact.get("dependent_agents", [])
                                st.error(f"⚠️ Cannot delete: {len(dependent_agents)} agents depend on this one")
                                st.write(f"Dependent agents: {', '.join(dependent_agents)}")
                                
                                col_cancel, col_cascade = st.columns(2)
                                with col_cancel:
                                    if st.button("❌ Cancel", key=f"cancel_delete_{agent['id']}"):
                                        st.session_state[deletion_state_key] = "initial"
                                        st.rerun()
                                with col_cascade:
                                    if st.button("💥 Delete All", key=f"cascade_delete_{agent['id']}", help="Delete this agent and all dependents"):
                                        response = delete_agent(agent['id'], force_cascade=True)
                                        if response and response.status_code == 200:
                                            st.success("Agent and dependents deleted")
                                            st.session_state.pop(deletion_state_key, None)
                                            st.cache_data.clear()
                                            st.rerun()
                                        else:
                                            st.error("Failed to delete agents")
                                            st.session_state[deletion_state_key] = "initial"
                
                # Expanded details
                if is_expanded:
                    st.markdown("---")
                    
                    detail_col1, detail_col2 = st.columns(2)
                    
                    with detail_col1:
                        st.markdown("**Configuration:**")
                        st.write(f"• **Name:** {agent['name']}")
                        st.write(f"• **LLM:** {agent.get('llm_name', 'N/A')}")
                        st.write(f"• **Temperature:** {agent.get('temperature', 'N/A')}")
                        
                        dependencies = agent.get('dependencies', [])
                        if dependencies:
                            st.write(f"• **Dependencies:** {', '.join(dependencies)}")
                        else:
                            st.write("• **Dependencies:** None")
                    
                    with detail_col2:
                        st.markdown("**Timestamps:**")
                        st.write(f"• **Created:** {agent.get('created_at', 'N/A')}")
                        st.write(f"• **Updated:** {agent.get('updated_at', 'N/A')}")
                        st.write(f"• **Last Executed:** {agent.get('last_executed_at', 'Never')}")
                        
                        st.markdown("**Actions:**")
                        if st.button(f"✏️ Edit Agent", key=f"edit_{agent['id']}"):
                            st.session_state.edit_agent = agent
                            st.rerun()
                        
                        if st.button(f"📋 View Details", key=f"details_{agent['id']}"):
                            st.info("Detailed view coming soon!")
                
                st.markdown("---")
        
        # Add New Agent button under the agent list
        st.markdown("---")
        agents_running = check_agents_running()
        
        if agents_running:
            st.button("🚫 Cannot Add Agent (Workflow Running)", disabled=True, use_container_width=True)
            st.info("Wait for workflow to complete before adding new agents")
        else:
            if st.button("➕ Add New Agent", use_container_width=True, type="primary"):
                st.session_state.show_add_agent = True
                st.rerun()


# Footer
st.markdown("""
### 💡 Tips
- **Agent Name:** Must be unique and use lowercase with underscores (e.g., `thermal_management`)
- **Dependencies:** List other agent names that must complete before this agent runs
- **Temperature:** Lower values (0.0-0.3) for focused tasks, higher (0.7-1.0) for creative tasks
- **File Requirements:** All 3 files (prompts, output class, tools) are required
""")

# Clear confirmation states after a delay
for key in list(st.session_state.keys()):
    if key.startswith("confirm_delete_"):
        # Reset confirmation after page interaction
        pass