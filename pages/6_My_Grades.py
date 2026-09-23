import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.auth import change_password, get_current_user, require_login  # noqa: E402
from utils.sheets import load_results, sheets_configured  # noqa: E402
from utils.ui import apply_theme, badge, render_header  # noqa: E402

st.set_page_config(page_title="My Grades", page_icon="🎓")
apply_theme()
require_login()
user = get_current_user() or {}
username = (user.get("username") or "").strip().lower()
display = user.get("display_name") or user.get("username") or "you"

render_header("Your own grades — only you can see this page. 🎓")


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


if not sheets_configured():
    st.warning("Grades aren't connected yet — ask your teacher.")
    st.stop()

try:
    df = load_results()
except Exception as e:  # noqa: BLE001
    st.error(f"Couldn't read grades: {e}")
    st.stop()

# Own rows only: new rows save under username, older ones under the typed
# display name — match both so history never "disappears".
mine = pd.DataFrame()
if not df.empty and "student_name" in df.columns:
    names = df["student_name"].astype(str)
    mine = df[
        (names.str.strip().str.lower() == username)
        | (names.str.strip().str.lower() == str(display).strip().lower())
    ].copy()

if mine.empty:
    st.info("No quiz attempts yet — take a quiz and your grades will appear here! 📝")
else:
    mine["score"] = pd.to_numeric(mine["score"], errors="coerce")
    mine["total"] = pd.to_numeric(mine["total"], errors="coerce")
    mine = mine.dropna(subset=["score", "total"])
    mine = mine[mine["total"] > 0]
    mine["pct"] = mine["score"] / mine["total"] * 100
    mine["timestamp"] = pd.to_datetime(mine["timestamp"], errors="coerce")

    avg_pct = mine["pct"].mean()
    with st.container(border=True):
        st.markdown(
            f"## 🎓 {display}  {badge(f'Grade {_grade_letter(avg_pct)}', 'grade')}",
            unsafe_allow_html=True,
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Attempts", len(mine))
        m2.metric("Average", f"{avg_pct:.0f}%")
        m3.metric("Topics tried", mine["topic"].nunique())
        m4.metric("Best score", f"{mine['pct'].max():.0f}%")

    st.divider()
    st.subheader("By topic")
    st.caption("Attempts = how many times you took each quiz.")
    per_topic = (
        mine.groupby("topic")["pct"]
        .agg(attempts="count", avg="mean", best="max")
        .round(0)
        .reset_index()
        .sort_values("avg", ascending=False)
    )
    st.bar_chart(per_topic.set_index("topic")["avg"])
    st.dataframe(
        per_topic.rename(columns={"topic": "Topic", "attempts": "Attempts", "avg": "Avg %", "best": "Best %"}),
        use_container_width=True,
        hide_index=True,
    )

    trend = mine.dropna(subset=["timestamp"]).sort_values("timestamp")
    if len(trend) >= 2:
        st.caption("Progress over time")
        st.line_chart(trend.set_index("timestamp")["pct"])

    st.caption("Attempt history (newest first)")
    st.dataframe(
        mine.sort_values("timestamp", ascending=False)[["timestamp", "topic", "score", "total", "pct"]]
        .rename(columns={"timestamp": "When", "topic": "Topic", "score": "Score", "total": "Total", "pct": "%"}),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("🔑 Change password")
with st.form("change_pw"):
    current = st.text_input("Current password", type="password")
    new1 = st.text_input("New password (min 6 characters)", type="password")
    new2 = st.text_input("Repeat new password", type="password")
    ok = st.form_submit_button("Change password")
if ok:
    if new1 != new2:
        st.error("New passwords don't match.")
    else:
        try:
            if change_password(user.get("username", ""), current, new1):
                st.success("Password changed!")
            else:
                st.error("Current password is wrong.")
        except ValueError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't change password: {e}")
