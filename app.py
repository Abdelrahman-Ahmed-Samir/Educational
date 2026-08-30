import json
from pathlib import Path

import streamlit as st

from utils.ui import APP_ICON, APP_NAME, apply_theme, badge, render_header

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON, layout="centered")
apply_theme()

RESOURCES_PATH = Path(__file__).parent / "resources" / "manifest.json"
QUESTIONS_PATH = Path(__file__).parent / "quizzes" / "questions.json"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


render_header("Resources, Q&A docs and quizzes for your class, all in one place.")

resources = load_json(RESOURCES_PATH)
questions = load_json(QUESTIONS_PATH)

col1, col2 = st.columns(2)
col1.metric("Resources", len(resources))
col2.metric("Quiz topics", len(questions))

st.write("")
st.subheader("Recently added")
for r in resources[:3]:
    with st.container(border=True):
        st.markdown(
            f"**{r['title']}**  \n"
            f"{badge(r['type'].upper(), r['type'])} {badge(r['topic'], 'topic')}",
            unsafe_allow_html=True,
        )

st.write("")
st.subheader("Jump in")
c1, c2, c3 = st.columns(3)
with c1:
    with st.container(border=True):
        st.markdown("### 📚")
        st.write("**Library**")
        st.caption("Browse resources & Q&A docs")
        st.page_link("pages/1_Library.py", label="Open", icon="➡️")
with c2:
    with st.container(border=True):
        st.markdown("### 📝")
        st.write("**Quizzes**")
        st.caption("Take a topic exam")
        st.page_link("pages/2_Quizzes.py", label="Open", icon="➡️")
with c3:
    with st.container(border=True):
        st.markdown("### 📊")
        st.write("**Grades**")
        st.caption("Teacher results dashboard")
        st.page_link("pages/3_Grades.py", label="Open", icon="➡️")
