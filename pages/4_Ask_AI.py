import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.qa import ai_configured, answer_question  # noqa: E402
from utils.ui import apply_theme, render_header  # noqa: E402

st.set_page_config(page_title="Ask AI", page_icon="🤖")
apply_theme()

render_header("Ask about the class resources in English or Arabic — answered any time! 🤖")

if not ai_configured():
    st.info(
        "The AI assistant isn't set up yet. Add a free API key in "
        "`.streamlit/secrets.toml` (or your Streamlit Cloud app secrets) — "
        "either Gemini (`[gemini] api_key`, get one at "
        "https://aistudio.google.com/apikey) or Groq (`[groq] api_key`, get "
        "one at https://console.groq.com/keys). Adding both gives you an "
        "automatic fallback. See README.md for the full walkthrough."
    )
    st.stop()

st.caption(
    "Answers come from the class resources in the Library — in your own "
    "language (English or Arabic). If something isn't covered there, it'll "
    "say so instead of guessing."
)

if "qa_history" not in st.session_state:
    st.session_state.qa_history = []

for entry in st.session_state.qa_history:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        st.write(entry["answer"])
        footer = []
        if entry.get("sources"):
            footer.append("Sources: " + ", ".join(entry["sources"]))
        if entry.get("provider", "none") != "none":
            footer.append(f"via {entry.get('provider')}")
        if footer:
            st.caption(" · ".join(footer))

question = st.chat_input('اسأل بالعربية أو English — e.g. "What is a variable?"')
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Checking the class resources…"):
            try:
                answer, sources, provider = answer_question(question)
            except Exception as e:
                detail = str(e)
                busy = any(
                    marker in detail
                    for marker in ("503", "429", "UNAVAILABLE", "high demand", "rate limit", "RateLimit")
                )
                if busy:
                    answer = (
                        "The AI is busier than usual right now — your question was "
                        "not lost. Please wait a minute and ask again, or ask "
                        "your teacher."
                    )
                else:
                    answer = (
                        "Something went wrong reaching the AI assistant. Please "
                        "try again in a moment, or ask your teacher."
                    )
                sources, provider = [], "none"
                st.caption(f"(Error detail for debugging: {e})")
        st.write(answer)
        footer = []
        if sources:
            footer.append("Sources: " + ", ".join(sources))
        if provider != "none":
            footer.append(f"via {provider}")
        if footer:
            st.caption(" · ".join(footer))

    st.session_state.qa_history.append(
        {"question": question, "answer": answer, "sources": sources, "provider": provider}
    )

if st.session_state.qa_history:
    st.divider()
    if st.button("Clear conversation"):
        st.session_state.qa_history = []
        st.rerun()
