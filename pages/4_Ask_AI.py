import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.qa import answer_question, gemini_configured  # noqa: E402
from utils.ui import apply_theme, render_header  # noqa: E402

st.set_page_config(page_title="Ask AI", page_icon="🤖")
apply_theme()

render_header("Ask a question about the class resources — answered any time, even when I'm offline.")

if not gemini_configured():
    st.info(
        "The AI assistant isn't set up yet. Add a Gemini API key under "
        "`[gemini] api_key` in `.streamlit/secrets.toml` (or your "
        "Streamlit Cloud app secrets) to turn this on. Get a free key at "
        "https://aistudio.google.com/apikey — see README.md for the full "
        "walkthrough."
    )
    st.stop()

st.caption(
    "Answers are generated from the class resources in the Library, not a "
    "general chatbot — if something isn't covered there, it'll say so "
    "instead of guessing."
)

if "qa_history" not in st.session_state:
    st.session_state.qa_history = []

for entry in st.session_state.qa_history:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        st.write(entry["answer"])
        if entry["sources"]:
            st.caption("Sources: " + ", ".join(entry["sources"]))

question = st.chat_input('Ask about a topic, e.g. "What is a variable?"')
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Checking the class resources…"):
            try:
                answer, sources = answer_question(question)
            except Exception as e:
                answer, sources = (
                    "Something went wrong reaching the AI assistant. Please "
                    "try again in a moment, or ask your teacher.",
                    [],
                )
                st.caption(f"(Error detail for debugging: {e})")
        st.write(answer)
        if sources:
            st.caption("Sources: " + ", ".join(sources))

    st.session_state.qa_history.append(
        {"question": question, "answer": answer, "sources": sources}
    )

if st.session_state.qa_history:
    st.divider()
    if st.button("Clear conversation"):
        st.session_state.qa_history = []
        st.rerun()
