import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.sheets import load_results, sheets_configured  # noqa: E402
from utils.ui import apply_theme, badge, render_header  # noqa: E402

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
st.subheader("🎓 By student")
st.caption("Pick a student to see their average, progress over time, and per-topic strengths.")


def _norm_name(name) -> str:
    return str(name or "").strip().lower()


def _grade_letter(pct: float) -> str:
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


_scored = df.copy()
_scored["score"] = pd.to_numeric(_scored["score"], errors="coerce")
_scored["total"] = pd.to_numeric(_scored["total"], errors="coerce")
_scored = _scored.dropna(subset=["score", "total"])
_scored = _scored[_scored["total"] > 0]
_scored["pct"] = _scored["score"] / _scored["total"] * 100
_scored["_name_norm"] = _scored["student_name"].map(_norm_name)
_scored = _scored[_scored["_name_norm"] != ""]

if _scored.empty:
    st.info("No valid scored attempts yet.")
    st.stop()

# Display name = most-used spelling per normalized name (students retype names).
_display = (
    _scored.groupby("_name_norm")["student_name"]
    .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0])
    .to_dict()
)
student_norm = st.selectbox(
    "Student",
    sorted(_display.keys(), key=lambda n: _display[n].lower()),
    format_func=lambda n: _display[n],
)
sdf = _scored[_scored["_name_norm"] == student_norm].copy()
sdf["timestamp"] = pd.to_datetime(sdf["timestamp"], errors="coerce")

avg_pct = sdf["pct"].mean()
with st.container(border=True):
    st.markdown(
        f"## 🎓 {_display[student_norm]}  {badge(f'Grade {_grade_letter(avg_pct)}', 'grade')}",
        unsafe_allow_html=True,
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Attempts", len(sdf))
    m2.metric("Average", f"{avg_pct:.0f}%")
    m3.metric("Topics tried", sdf["topic"].nunique())
    m4.metric("Best score", f"{sdf['pct'].max():.0f}%")

per_topic = (
    sdf.groupby("topic")["pct"]
    .agg(attempts="count", avg="mean", best="max")
    .round(0)
    .reset_index()
    .sort_values("avg", ascending=False)
)
if not per_topic.empty:
    strongest = per_topic.iloc[0]
    weakest = per_topic.iloc[-1]
    st.caption(
        f"💪 Strongest: **{strongest['topic']}** ({strongest['avg']:.0f}%) · "
        f"🎯 Needs work: **{weakest['topic']}** ({weakest['avg']:.0f}%)"
    )
    st.bar_chart(per_topic.set_index("topic")["avg"])
    st.dataframe(
        per_topic.rename(columns={"topic": "Topic", "attempts": "Attempts", "avg": "Avg %", "best": "Best %"}),
        use_container_width=True,
        hide_index=True,
    )

trend = sdf.dropna(subset=["timestamp"]).sort_values("timestamp")
if len(trend) >= 2:
    st.caption("Progress over time")
    st.line_chart(trend.set_index("timestamp")["pct"])
elif len(trend) == 1:
    st.caption("Only one attempt so far — the progress line appears after the second.")

st.caption("Attempt history (newest first)")
st.dataframe(
    sdf.sort_values("timestamp", ascending=False)[
        ["timestamp", "topic", "score", "total", "pct"]
    ].rename(columns={
        "timestamp": "When", "topic": "Topic", "score": "Score",
        "total": "Total", "pct": "%",
    }),
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.subheader("All attempts")
st.dataframe(df, use_container_width=True, hide_index=True)
