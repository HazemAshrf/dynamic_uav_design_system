"""Conversations page for monitoring agent communications."""

import streamlit as st
import requests
import json
from datetime import datetime
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Conversations - Dynamic Agent Dashboard",
    page_icon="💬",
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

# Helper functions
@st.cache_data(ttl=10)
def fetch_workflows():
    """Fetch available workflows."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/", timeout=5)
        if response.status_code == 200:
            return response.json().get('workflows', [])
        else:
            st.error(f"Failed to fetch workflows: {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return []

@st.cache_data(ttl=5)
def fetch_workflow_conversations(workflow_id):
    """Fetch conversations for a specific workflow."""
    try:
        response = requests.get(f"{API_BASE_URL}/workflow/{workflow_id}/conversations", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to fetch conversations: {response.status_code}")
            return {"conversations": [], "total": 0}
    except requests.exceptions.RequestException as e:
        st.error(f"Cannot connect to API: {str(e)}")
        return {"conversations": [], "total": 0}

def format_timestamp(timestamp_str):
    """Format timestamp for display."""
    if not timestamp_str:
        return "N/A"
    try:
        # Handle different timestamp formats
        if 'T' in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return timestamp_str

# Header
st.markdown("""
<div class="main-header">
    <div class="header-content">
        <h1>💬 Agent Conversations</h1>
        <p>Monitor real-time agent-to-agent communications</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar for workflow selection and settings
with st.sidebar:
    st.markdown("### 🎯 Workflow Selection")
    
    # Fetch available workflows
    workflows = fetch_workflows()
    
    if not workflows:
        st.warning("No workflows found. Start a workflow to see conversations.")
        selected_workflow = None
    else:
        # Create workflow options
        workflow_options = {}
        for workflow in workflows:
            status_emoji = {
                'running': '🟢',
                'completed': '✅', 
                'failed': '❌',
                'stopped': '⏹️'
            }.get(workflow.get('status', 'unknown'), '⚪')
            
            label = f"{status_emoji} {workflow.get('workflow_id', 'Unknown ID')[:8]}... ({workflow.get('status', 'unknown')})"
            workflow_options[label] = workflow.get('workflow_id')
        
        selected_label = st.selectbox(
            "Select Workflow:",
            options=list(workflow_options.keys()),
            help="Choose a workflow to view its agent conversations"
        )
        
        selected_workflow = workflow_options[selected_label] if selected_label else None
    
    # Refresh settings
    st.markdown("### ⚙️ Display Settings")
    auto_refresh = st.checkbox("Auto-refresh conversations", value=True)
    if auto_refresh:
        refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 10)
    
    show_system_messages = st.checkbox("Show system messages", value=False)
    max_messages_per_conversation = st.slider("Max messages per conversation", 10, 100, 50)
    
    # Manual refresh button
    if st.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Main content
if not selected_workflow:
    st.markdown("""
    <div class="welcome-section">
        <h3>👋 Welcome to Agent Conversations</h3>
        <p>Select a workflow from the sidebar to monitor agent communications in real-time.</p>
        <p>This view allows you to:</p>
        <ul>
            <li>🔍 <strong>Monitor</strong> agent-to-agent conversations</li>
            <li>📊 <strong>Track</strong> communication patterns and dependencies</li>
            <li>🐛 <strong>Debug</strong> agent interactions and workflow issues</li>
            <li>📈 <strong>Analyze</strong> conversation flow and timing</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
else:
    # Fetch conversations for selected workflow
    conversation_data = fetch_workflow_conversations(selected_workflow)
    conversations = conversation_data.get('conversations', [])
    total_conversations = conversation_data.get('total', 0)
    
    # Display header info
    st.markdown(f"### 💬 Conversations for Workflow: `{selected_workflow[:16]}...`")
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Conversations", total_conversations)
    
    with col2:
        if conversations:
            total_messages = sum(len(conv.get('messages', [])) for conv in conversations)
            st.metric("Total Messages", total_messages)
        else:
            st.metric("Total Messages", 0)
    
    with col3:
        if conversations:
            active_participants = set()
            for conv in conversations:
                active_participants.update(conv.get('participants', []))
            st.metric("Active Agents", len(active_participants))
        else:
            st.metric("Active Agents", 0)
    
    with col4:
        if conversations:
            last_activity = max(
                (conv.get('last_activity') for conv in conversations if conv.get('last_activity')),
                default=None
            )
            if last_activity:
                st.metric("Last Activity", format_timestamp(last_activity))
            else:
                st.metric("Last Activity", "N/A")
        else:
            st.metric("Last Activity", "N/A")
    
    if not conversations:
        st.info("📭 No conversations found for this workflow yet. Agents will appear here once they start communicating.")
    else:
        st.markdown("---")
        
        # Display conversations
        for i, conversation in enumerate(conversations):
            participants = conversation.get('participants', [])
            messages = conversation.get('messages', [])
            conversation_key = conversation.get('conversation_key', f'conversation_{i}')
            
            if not messages:
                continue
            
            # Limit messages if needed
            displayed_messages = messages[-max_messages_per_conversation:] if len(messages) > max_messages_per_conversation else messages
            
            with st.expander(
                f"💬 {' ↔️ '.join(participants)} ({len(messages)} messages)",
                expanded=i < 3  # Expand first 3 conversations
            ):
                # Conversation metadata
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown(f"**Participants:** {', '.join(participants)}")
                    st.markdown(f"**Total Messages:** {len(messages)}")
                    if len(messages) > max_messages_per_conversation:
                        st.info(f"Showing last {max_messages_per_conversation} messages (out of {len(messages)} total)")
                
                with col2:
                    if conversation.get('last_activity'):
                        st.markdown(f"**Last Activity:** {format_timestamp(conversation['last_activity'])}")
                
                st.markdown("**Messages:**")
                
                # Display messages
                for msg_idx, message in enumerate(displayed_messages):
                    sender = message.get('sender', 'Unknown')
                    receiver = message.get('receiver', 'Unknown')
                    content = message.get('content', '')
                    timestamp = message.get('timestamp', '')
                    iteration = message.get('iteration', 'N/A')
                    confidence = message.get('confidence')
                    
                    # Skip system messages if not enabled
                    if not show_system_messages and sender.lower() == 'system':
                        continue
                    
                    # Message styling based on sender
                    if sender == 'coordinator':
                        message_style = "background: #e8f4f8; border-left: 4px solid #1f77b4; padding: 10px; margin: 5px 0; border-radius: 5px;"
                    elif 'error' in sender.lower() or 'error' in content.lower():
                        message_style = "background: #ffe8e8; border-left: 4px solid #d62728; padding: 10px; margin: 5px 0; border-radius: 5px;"
                    else:
                        message_style = "background: #f0f0f0; border-left: 4px solid #17becf; padding: 10px; margin: 5px 0; border-radius: 5px;"
                    
                    st.markdown(f"""
                    <div style="{message_style}">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                            <strong>{sender} → {receiver}</strong>
                            <small style="color: #666;">
                                {format_timestamp(timestamp)} (Iteration: {iteration})
                                {f' | Confidence: {confidence:.2f}' if confidence is not None else ''}
                            </small>
                        </div>
                        <div style="white-space: pre-wrap; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                            {content[:500]}{'...' if len(content) > 500 else ''}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Show full content option for long messages
                    if len(content) > 500:
                        if st.button(f"Show full message", key=f"full_msg_{conversation_key}_{msg_idx}"):
                            st.text_area(
                                "Full message content:",
                                content,
                                height=200,
                                key=f"full_content_{conversation_key}_{msg_idx}"
                            )

# Auto-refresh functionality
if auto_refresh and selected_workflow:
    import time
    time.sleep(refresh_interval)
    st.rerun()

# Footer with tips
st.markdown("---")
st.markdown("""
### 💡 Tips
- **Real-time Monitoring:** Enable auto-refresh to monitor conversations as they happen
- **Message Filtering:** Use the sidebar settings to control what messages are displayed
- **Debugging:** Look for error messages or unusual patterns in agent communications
- **Performance:** Long conversations may take time to load - adjust the message limit as needed
""")