"""File Management page for managing agent configuration files."""

import streamlit as st
import requests
import json
import base64
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

# Page configuration
st.set_page_config(
    page_title="File Management - Dynamic Agent Dashboard",
    page_icon="📁",
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

def get_agent_files(agent_name: str) -> Dict[str, str]:
    """Get agent configuration files."""
    try:
        response = requests.get(f"{API_BASE_URL}/agents/{agent_name}/files", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {}
    except requests.exceptions.RequestException:
        return {}

def update_agent_file(agent_name: str, file_type: str, content: str) -> bool:
    """Update a specific agent file."""
    try:
        # Encode content to base64
        encoded_content = base64.b64encode(content.encode()).decode()
        
        payload = {
            "file_type": file_type,
            "content": encoded_content
        }
        
        response = requests.put(f"{API_BASE_URL}/agents/{agent_name}/files", json=payload, timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def download_agent_files(agent_name: str) -> Optional[Dict]:
    """Download all agent files as a package."""
    try:
        response = requests.get(f"{API_BASE_URL}/agents/{agent_name}/export", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def backup_agent(agent_name: str) -> bool:
    """Create a backup of agent configuration."""
    try:
        response = requests.post(f"{API_BASE_URL}/agents/{agent_name}/backup", timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

# Header
st.markdown("""
<div class="main-header">
    <div class="header-content">
        <h1>📁 File Management</h1>
        <p>Manage and edit agent configuration files</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Check API health
if not check_api_health():
    st.error("❌ Cannot connect to Backend API - make sure it's running on port 8000")
    st.stop()

# Fetch agents
agents = fetch_agents()

if not agents:
    st.info("No agents found. Create agents first in the Agent Settings page.")
    if st.button("🤖 Go to Agent Settings"):
        st.switch_page("pages/1_🤖_Agent_Settings.py")
    st.stop()

# Agent Selection
st.markdown("### 🎯 Select Agent")
agent_names = [agent["name"] for agent in agents]
selected_agent = st.selectbox("Choose an agent to manage files for:", agent_names)

if selected_agent:
    # Agent Info
    agent_info = next((agent for agent in agents if agent["name"] == selected_agent), None)
    if agent_info:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Agent Name", selected_agent)
        with col2:
            st.metric("Status", agent_info.get("status", "Unknown"))
        with col3:
            st.metric("Created", agent_info.get("created_at", "Unknown")[:10] if agent_info.get("created_at") else "Unknown")
        with col4:
            if st.button("🔄 Refresh Files"):
                st.cache_data.clear()
                st.rerun()

    # File Management Section
    st.markdown("### 📝 File Editor")
    
    # Get agent files
    agent_files = get_agent_files(selected_agent)
    
    if not agent_files:
        st.warning("Could not retrieve agent files. Files may not exist or API endpoint may not be implemented.")
        
        # Show simulated file structure based on storage layout
        st.markdown("#### 📂 Expected File Structure")
        expected_files = {
            "prompts": "Agent prompts and instructions",
            "output_class": "Pydantic output model definition", 
            "tools": "Agent tools and functions",
            "dependencies": "Agent dependency configuration"
        }
        
        for file_type, description in expected_files.items():
            st.markdown(f"- **{file_type}.py/md/json**: {description}")
        
    else:
        # File tabs for editing
        file_types = list(agent_files.keys())
        if file_types:
            tab_labels = [f"📄 {file_type.title()}" for file_type in file_types]
            tabs = st.tabs(tab_labels)
            
            for i, (file_type, content) in enumerate(agent_files.items()):
                with tabs[i]:
                    st.markdown(f"#### Edit {file_type.title()} File")
                    
                    # Decode base64 content if needed
                    try:
                        if isinstance(content, str) and content:
                            try:
                                decoded_content = base64.b64decode(content).decode()
                            except:
                                decoded_content = content
                        else:
                            decoded_content = ""
                    except:
                        decoded_content = "Error loading file content"
                    
                    # File editor
                    new_content = st.text_area(
                        f"Content ({file_type})",
                        value=decoded_content,
                        height=400,
                        key=f"editor_{file_type}_{selected_agent}"
                    )
                    
                    col1, col2, col3 = st.columns([1, 1, 2])
                    
                    with col1:
                        if st.button(f"💾 Save {file_type.title()}", key=f"save_{file_type}"):
                            if update_agent_file(selected_agent, file_type, new_content):
                                st.success(f"✅ {file_type.title()} file saved successfully!")
                                st.cache_data.clear()
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"❌ Failed to save {file_type} file")
                    
                    with col2:
                        if st.button(f"↩️ Revert", key=f"revert_{file_type}"):
                            st.cache_data.clear()
                            st.rerun()
                    
                    # File statistics
                    lines = len(new_content.split('\n'))
                    chars = len(new_content)
                    words = len(new_content.split())
                    
                    st.caption(f"📊 Stats: {lines} lines, {words} words, {chars} characters")

    # File Operations Section
    st.markdown("### 🛠️ File Operations")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 📥 Download Files")
        if st.button("📦 Download All Files", use_container_width=True):
            with st.spinner("Preparing download..."):
                files_data = download_agent_files(selected_agent)
                if files_data:
                    # Create downloadable JSON
                    json_str = json.dumps(files_data, indent=2)
                    st.download_button(
                        label="💾 Download Agent Package",
                        data=json_str,
                        file_name=f"{selected_agent}_config.json",
                        mime="application/json"
                    )
                    st.success("✅ Files ready for download!")
                else:
                    st.error("❌ Failed to prepare download")
    
    with col2:
        st.markdown("#### 💾 Backup")
        if st.button("🔒 Create Backup", use_container_width=True):
            with st.spinner("Creating backup..."):
                if backup_agent(selected_agent):
                    st.success("✅ Backup created successfully!")
                else:
                    st.error("❌ Failed to create backup")
    
    with col3:
        st.markdown("#### 📤 Upload Files")
        uploaded_files = st.file_uploader(
            "Upload configuration files",
            accept_multiple_files=True,
            type=['py', 'md', 'txt', 'json'],
            help="Upload agent configuration files to replace current ones"
        )
        
        if uploaded_files:
            if st.button("📤 Upload Files", use_container_width=True):
                success_count = 0
                for uploaded_file in uploaded_files:
                    file_content = uploaded_file.read().decode()
                    file_name = uploaded_file.name
                    
                    # Determine file type from name
                    if 'prompt' in file_name.lower():
                        file_type = 'prompts'
                    elif 'output' in file_name.lower() or 'class' in file_name.lower():
                        file_type = 'output_class'
                    elif 'tool' in file_name.lower():
                        file_type = 'tools'
                    elif 'depend' in file_name.lower():
                        file_type = 'dependencies'
                    else:
                        # Default based on extension
                        ext = file_name.split('.')[-1]
                        if ext == 'md':
                            file_type = 'prompts'
                        elif ext == 'json':
                            file_type = 'dependencies'
                        else:
                            file_type = 'tools'
                    
                    if update_agent_file(selected_agent, file_type, file_content):
                        success_count += 1
                
                if success_count == len(uploaded_files):
                    st.success(f"✅ All {len(uploaded_files)} files uploaded successfully!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning(f"⚠️ {success_count}/{len(uploaded_files)} files uploaded successfully")

    # File Browser Section
    st.markdown("### 🗂️ File Browser")
    
    # Simulated file browser based on storage structure
    with st.expander("📂 Agent File Structure", expanded=True):
        st.markdown(f"""
        ```
        📁 {selected_agent}/
        ├── 📄 prompts.py (or .md)
        ├── 📄 output_class.py
        ├── 📄 tools.py
        └── 📄 dependencies.json
        ```
        """)
        
        # Show file sizes and modification dates if available
        if agent_info:
            st.markdown("#### 📊 File Information")
            file_info = {
                "prompts": {"size": "2.3 KB", "modified": "2 hours ago"},
                "output_class": {"size": "1.1 KB", "modified": "2 hours ago"},
                "tools": {"size": "3.7 KB", "modified": "2 hours ago"},
                "dependencies": {"size": "0.2 KB", "modified": "2 hours ago"}
            }
            
            cols = st.columns(4)
            for i, (file_type, info) in enumerate(file_info.items()):
                with cols[i]:
                    st.metric(
                        label=f"{file_type}.py",
                        value=info["size"],
                        delta=info["modified"]
                    )

    # Version Control Section (Future Feature)
    st.markdown("### 🕒 Version Control")
    st.info("🚧 Version control features (git integration, file history, rollback) will be available in a future update.")
    
    # Recent Activity
    st.markdown("### 📈 Recent Activity")
    with st.expander("Recent File Changes", expanded=False):
        # Simulated recent activity
        activities = [
            {"timestamp": "2 hours ago", "action": "Modified prompts.py", "user": "System"},
            {"timestamp": "2 hours ago", "action": "Created output_class.py", "user": "System"},
            {"timestamp": "2 hours ago", "action": "Updated tools.py", "user": "System"},
            {"timestamp": "2 hours ago", "action": "Added dependencies.json", "user": "System"}
        ]
        
        for activity in activities:
            st.text(f"🕐 {activity['timestamp']} - {activity['action']} by {activity['user']}")

# Footer
st.markdown("---")
st.markdown("**Note:** File operations require the backend API to support file management endpoints. Some features may be simulated pending full implementation.")