"""
Monday.com Business Intelligence Agent - Streamlit Web Application

A clean, intuitive web interface for querying monday.com data through an AI agent.
"""

import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from agent import answer_user_message


# Load environment variables
load_dotenv()


# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Monday BI Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# CUSTOM STYLING
# ============================================================================

st.markdown(
    """
    <style>
        /* Main container spacing */
        .block-container {
            padding-top: 1rem;
            padding-bottom: 2rem;
        }
        
        /* Sidebar styling */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
            color: white;
        }
        
        [data-testid="stSidebar"] * {
            color: white !important;
        }

        /* Ensure main content and chat text remain readable regardless of theme */
        .stMarkdown, .stMarkdown *,
        .stChatMessage, .stChatMessage *,
        .stInfo, .stInfo * {
            color: #0f172a !important;
        }
        
        /* Chat message styling */
        .stChatMessage {
            background: #f8fafc !important;
            border-radius: 8px;
            padding: 1rem;
        }
        
        /* Status badge */
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
            margin-top: 0.5rem;
        }
        
        .status-ok {
            background: #dcfce7;
            color: #166534;
        }
        
        .status-warning {
            background: #fef3c7;
            color: #92400e;
        }
        
        .status-error {
            background: #fee2e2;
            color: #991b1b;
        }
        
        /* Markdown tables */
        .stMarkdown table {
            margin: 1rem 0;
            border-collapse: collapse;
        }
        
        .stMarkdown table th {
            background: #e2e8f0;
            padding: 0.75rem;
            text-align: left;
            font-weight: 600;
        }
        
        .stMarkdown table td {
            padding: 0.75rem;
            border-bottom: 1px solid #cbd5e1;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "monday_api_token" not in st.session_state:
    st.session_state.monday_api_token = os.getenv("MONDAY_API_TOKEN", "")

if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = os.getenv("GEMINI_API_KEY", "")


# ============================================================================
# SIDEBAR - CONFIGURATION & CONTROLS
# ============================================================================

with st.sidebar:
    st.markdown("# 📊 Monday BI Agent")
    st.markdown("---")
    
    # Connection Section
    st.subheader("🔌 Connection")
    
    monday_token_input = st.text_input(
        "MONDAY_API_TOKEN",
        value=st.session_state.monday_api_token,
        type="password",
        help="Your monday.com API token. Get it from: https://monday.com/account",
        key="monday_input",
    )
    
    openai_key_input = st.text_input(
        "GEMINI_API_KEY",
        value=st.session_state.gemini_api_key,
        type="password",
        help="Your Google Gemini API key. Get it from: https://aistudio.google.com/apikey",
        key="gemini_input",
    )
    
    # Update session state
    st.session_state.monday_api_token = monday_token_input
    st.session_state.gemini_api_key = openai_key_input
    
    st.markdown("---")
    
    # Session Controls
    st.subheader("🗂️ Conversation")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear History", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    
    with col2:
        if st.button("New Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.monday_api_token = ""
            st.session_state.gemini_api_key = ""
            st.rerun()
    
    st.markdown("---")
    
    # Quick Actions
    st.subheader("⚡ Quick Queries")
    
    if st.button("📈 Generate Leadership Update", use_container_width=True, help="Generate a full executive summary"):
        st.session_state.quick_query = "Generate a leadership update"
        st.rerun()
    
    if st.button("💰 Pipeline Health", use_container_width=True, help="Analyze pipeline stages and revenue"):
        st.session_state.quick_query = "How healthy is our pipeline?"
        st.rerun()
    
    if st.button("⚠️ Operational Issues", use_container_width=True, help="Find bottlenecks and delays"):
        st.session_state.quick_query = "What work orders are blocked or overdue?"
        st.rerun()
    
    st.markdown("---")
    
    # Status Indicator
    st.subheader("✅ Status")
    
    token_ok = bool(st.session_state.monday_api_token.strip())
    key_ok = bool(st.session_state.gemini_api_key.strip())
    
    if token_ok and key_ok:
        st.markdown('<span class="status-badge status-ok">✓ Ready</span>', unsafe_allow_html=True)
    elif token_ok or key_ok:
        st.markdown('<span class="status-badge status-warning">⚠ Partial</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-badge status-error">✗ Offline</span>', unsafe_allow_html=True)
    
    if not token_ok:
        st.warning("Add your monday.com API token to enable data access.", icon="📋")
    if not key_ok:
        st.warning("Add your Google Gemini API key to enable the agent.", icon="🔑")
    
    st.markdown("---")
    st.markdown(
        "**Tips:**\n"
        "- Ask specific questions for best results\n"
        "- Use 'leadership update' for full reports\n"
        "- The agent will ask for clarification if needed\n"
        "- Data quality notes are always included"
    )


# ============================================================================
# MAIN CHAT INTERFACE
# ============================================================================

st.markdown("# 📊 Monday BI Agent")
st.markdown("Ask questions about your pipeline, work orders, and business metrics.")

# Display chat history
if st.session_state.messages:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
else:
    st.info(
        "**Welcome!** Try queries like:\n"
        "- 'How healthy is the pipeline?'\n"
        "- 'What work orders are overdue?'\n"
        "- 'Generate a leadership update'\n"
        "- 'Show me sector performance'\n"
        "- 'Who has the most open tasks?'"
    )


# ============================================================================
# CHAT INPUT & PROCESSING
# ============================================================================

# Handle quick query from sidebar
if "quick_query" in st.session_state:
    user_input = st.session_state.quick_query
    del st.session_state.quick_query
else:
    user_input = None

# Chat input box
if not user_input:
    user_input = st.chat_input("Ask about pipeline health, work orders, or request a leadership update...")

if user_input:
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Generate and display response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing monday.com data..."):
            try:
                result = answer_user_message(
                    user_message=user_input,
                    history=st.session_state.messages[:-1],
                    monday_api_token=st.session_state.monday_api_token or None,
                    gemini_api_key=st.session_state.gemini_api_key or None,
                )
                
                response_content = result.content
                
                # Display the response
                st.markdown(response_content)
                
                # Add to history
                st.session_state.messages.append({"role": "assistant", "content": response_content})
                
                # Show metadata if in development mode
                if os.getenv("DEBUG_MODE"):
                    with st.expander("🔧 Debug Info"):
                        st.json(result.metadata)
                
            except Exception as exc:
                error_message = f"❌ **Error**: {str(exc)}"
                st.error(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})


# ============================================================================
# FOOTER
# ============================================================================

st.markdown("---")
st.markdown(
    "<p style='text-align: center; font-size: 0.85rem; color: #94a3b8;'>"
    "Powered by LangChain + Google Gemini | Data from monday.com<br>"
    f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    "</p>",
    unsafe_allow_html=True,
)
