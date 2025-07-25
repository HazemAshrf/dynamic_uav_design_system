"""Main dashboard for Dynamic Agent System."""

import streamlit as st
import requests
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Dynamic Agent Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load custom CSS
css_file = Path(__file__).parent / "assets" / "styles.css"
if css_file.exists():
    with open(css_file) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <div class="header-content">
        <h1>🤖 Dynamic Agent Dashboard</h1>
        <p>Multi-Agent UAV Design System Management Platform</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Welcome section
st.markdown("""
<div class="welcome-section">
    <h3>Welcome to the Dynamic Agent Dashboard!</h3>
    <p>Manage and orchestrate dynamic multi-agent workflows for UAV design and engineering.</p>
</div>
""", unsafe_allow_html=True)

# Feature overview
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    ### 🛠️ **Key Features**
    
    - **🤖 Dynamic Agent Management** - Create, configure, and manage specialized agents
    - **💬 Real-time Conversations** - Monitor agent-to-agent communications  
    - **📊 Workflow Orchestration** - Control and monitor complex multi-agent workflows
    - **📁 File Management** - Upload and manage agent configuration files
    - **🔄 Checkpointing** - Persistent state management and workflow resumption
    """)

with col2:
    st.markdown("""
    ### 📖 **Available Pages**
    
    - **🤖 Agent Settings** - Configure and manage dynamic agents
    - **💬 Conversations** - Monitor real-time agent conversations
    - **📊 Workflow Status** - Track workflow execution and progress
    - **📁 File Management** - Manage agent configuration files
    """)

# API Status Check
st.markdown("### 🔍 System Status")

try:
    response = requests.get("http://localhost:8000/health", timeout=2)
    if response.status_code == 200:
        st.success("✅ Backend API is running and healthy")
        
        # Try to get agent count
        try:
            agents_response = requests.get("http://localhost:8000/api/v1/agents/", timeout=2)
            if agents_response.status_code == 200:
                agents = agents_response.json()
                agent_count = len(agents)
                st.info(f"📊 System has {agent_count} registered agents")
            else:
                st.warning("⚠️ Could not fetch agent information")
        except:
            st.warning("⚠️ Could not connect to agents endpoint")
    else:
        st.error("❌ Backend API returned error status")
except requests.exceptions.RequestException:
    st.error("❌ Cannot connect to Backend API - make sure it's running on port 8000")
except Exception as e:
    st.error(f"❌ Unexpected error checking API status: {str(e)}")

# Quick actions
st.markdown("### 🚀 Quick Actions")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🤖 Manage Agents", use_container_width=True):
        st.switch_page("pages/1_🤖_Agent_Settings.py")

with col2:
    if st.button("💬 View Conversations", use_container_width=True):
        st.switch_page("pages/2_💬_Conversations.py")

with col3:
    if st.button("📊 Workflow Status", use_container_width=True):
        st.switch_page("pages/3_📊_Workflow_Status.py")

with col4:
    if st.button("📁 File Management", use_container_width=True):
        st.switch_page("pages/4_📁_File_Management.py")

# Getting started guide
with st.expander("🎯 Getting Started Guide"):
    st.markdown("""
    ### Step-by-Step Setup
    
    **1. 🤖 Create Your First Agent**
    - Navigate to Agent Settings
    - Click "Add Agent" 
    - Upload your agent configuration files (prompts, output class, tools, dependencies)
    - Configure LLM settings (model, temperature, etc.)
    
    **2. 📊 Start a Workflow**
    - Go to Workflow Status
    - Click "Start New Workflow"
    - Enter your project requirements
    - Monitor execution in real-time
    
    **3. 💬 Monitor Conversations**
    - View agent-to-agent communications
    - Track workflow progress
    - Debug agent interactions
    
    **4. 📁 Manage Files**
    - View and edit agent configuration files
    - Backup and restore agent settings
    - Version control for agent configurations
    """)

# Footer with links
st.markdown("---")
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**🔗 Quick Links**")
    st.markdown("- [API Documentation](http://localhost:8000/docs)")
    st.markdown("- [OpenAPI Schema](http://localhost:8000/api/v1/openapi.json)")

with col2:
    st.markdown("**📚 Resources**")
    st.markdown("- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)")
    st.markdown("- [FastAPI Documentation](https://fastapi.tiangolo.com/)")

with col3:
    st.markdown("**ℹ️ About**")
    st.markdown("- Dynamic Agent Dashboard v1.0")
    st.markdown("- Built with Streamlit & FastAPI")

# System information
with st.expander("🔧 System Information"):
    import sys
    import platform
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Environment**")
        st.code(f"""
Python Version: {sys.version.split()[0]}
Platform: {platform.system()} {platform.release()}
Architecture: {platform.machine()}
        """)
    
    with col2:
        st.markdown("**Configuration**")
        st.code(f"""
Backend URL: http://localhost:8000
API Prefix: /api/v1
Database: SQLite (Development)
        """)