import streamlit as st
import os
import time
from db_connection import setup_database
from intent import identify_intent
from retrieve import ask_sql_ai, ask_rag_ai, ask_both_ai, validate_query,reformulate_question, handle_small_talk
from ingest import ingest_to_knowledge_base
from logger import log_transaction
from logger import system_log
from memory_manager import save_message,clear_history,get_chat_history

# Page Configuration
st.set_page_config(page_title="POS RAG Intelligence", page_icon="🤖", layout="wide")

# Initialize DB once
@st.cache_resource
def init_system():
    setup_database()
    return True

init_system()
system_log(" Application Started.")

session_id = "user_123"
# --- Sidebar Admin Controls ---
with st.sidebar:
    st.header("⚙️ Admin Controls")
    
    # 1. Data Ingestion Button
    if st.button(" Sync Knowledge Base"):
        files_to_process = [
            '../data/all_product_specs.txt', 
            '../data/all_warranties.txt', 
            '../data/delivery_koombiyo.txt'
        ]
        
        with st.status("Ingesting Data...", expanded=True) as status:
            st.write("Reading text files from /data...")
            # Check if files exist first to prevent crashes
            valid_files = [f for f in files_to_process if os.path.exists(f)]
            
            if valid_files:
                ingest_to_knowledge_base(valid_files)
                status.update(label="Sync Complete!", state="complete", expanded=False)
                st.success(f"Synced {len(valid_files)} files to Pos_dbc.")
            else:
                status.update(label="Sync Failed!", state="error")
                st.error("No source files found in /data folder.")

    st.divider()

    # 2. Clear Chat & Cache Button
    if st.button("🗑️ Clear Chat & Cache"):
        st.session_state.messages = []
        clear_history(session_id)
        st.cache_resource.clear()
        st.rerun()

    st.header("📊 System Monitor")
    st.status("Database Connected", state="complete")
    st.info("Knowledge Base: Ready")

# --- Chat Interface Logic ---
st.title("🛡️ POS AI Thought Partner")
st.markdown("Ask about inventory, technical specs, or order statuses.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input Box
if query := st.chat_input("Ex: Why is order 118 delayed?"):
    start_time = time.time()
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)
    
    with st.chat_message("assistant"):
        standalone_query = reformulate_question(query, session_id)

# 2. Identify Intent
        intent = identify_intent(standalone_query)

        # 3. Execution Path
        if intent in ["GREETING", "ABOUT", "CLOSURE"]:
            answer = handle_small_talk(intent)
            # Skip the expensive DB/RAG calls
            latency = 0.05


            # 2. LOG it (Using your new logger)
            system_log(f" Original: {query} -> Standalone: {standalone_query}")
            with st.spinner("Analyzing Pos_dbc & Knowledge Base..."):
                is_safe, error_message = validate_query(standalone_query)
                
                    

                save_message(session_id, "user", query)
                save_message(session_id, "assistant", answer)
                system_log(get_chat_history(session_id, window_size=6))
                latency = time.time() - start_time
                log_transaction(query, intent, latency, answer) 
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                system_log(f" Response delivered in {latency:.2f} seconds via {intent} route.")
                
        else:    

            # 2. LOG it (Using your new logger)
            system_log(f" Original: {query} -> Standalone: {standalone_query}")
            with st.spinner("Analyzing Pos_dbc & Knowledge Base..."):
                is_safe, error_message = validate_query(standalone_query)
                if not is_safe:
                    answer = f"⚠️ **Guardrail Triggered:** {error_message}"
                    route = "BLOCKED"
                else:
                    
                    route = intent
                    
                    if "BOTH" in route:
                        st.caption("🔀 Path: BOTH (SQL + RAG)")
                        answer = ask_both_ai(standalone_query)
                    elif "SQL" in route:
                        st.caption("🔍 Path: SQL")
                        answer = ask_sql_ai(standalone_query)
                    else:
                        st.caption("📚 Path: RAG")
                        answer = ask_rag_ai(standalone_query)

                save_message(session_id, "user", query)
                save_message(session_id, "assistant", answer)
                system_log(get_chat_history(session_id, window_size=6))
                latency = time.time() - start_time
                log_transaction(query, route, latency, answer) 
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                system_log(f" Response delivered in {latency:.2f} seconds via {route} route.")