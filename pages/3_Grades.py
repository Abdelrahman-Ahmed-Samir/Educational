import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.sheets import load_results, sheets_configured  # noqa: E402
from utils.ui import apply_theme, render_header  # noqa: E402

st.set_page_config(page_title="Grades", page_icon="📊")
apply_theme()

render_header("Live view of the class results sheet.")

# Optional light gate so students landing on this page by URL can't see everyone's grades.
teacher_password = st.secrets.get("app", {}).get("teacher_password")
if teacher_password:
    entered = st.text_input("Teacher password", type="password")
    if entered != teacher_password:
        st.stop()

if not sheets_configured():
    st.warning(
        "Google Sheet isn't connected yet. Add credentials in `.streamlit/secrets.toml` "
        "(see README.md) to see results here."
    )
    st.stop()

try:
    df = load_results()
except Exception as e:  # noqa: BLE001
    st.error(f"Couldn't read the sheet: {e}")
    st.stop()

if df.empty:
    st.info("No quiz attempts recorded yet.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Attempts", len(df))
col2.metric("Students", df["student_name"].nunique())
col3.metric("Avg score", f"{(df['score'] / df['total']).mean() * 100:.0f}%")

st.divider()
st.subheader("By topic")
by_topic = (
    df.assign(pct=df["score"] / df["total"] * 100)
    .groupby("topic")["pct"]
    .mean()
    .round(0)
    .reset_index()
    .rename(columns={"pct": "avg_score_pct"})
)
st.bar_chart(by_topic.set_index("topic"))

st.divider()
st.subheader("All attempts")
st.dataframe(df, use_container_width=True, hide_index=True)
