import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.auth import get_current_user, get_video_access, load_video_catalog, require_login  # noqa: E402
from utils.ui import apply_theme, badge, render_header  # noqa: E402

st.set_page_config(page_title="Recordings", page_icon="🎥")
apply_theme()
require_login()
user = get_current_user() or {}

render_header("Paid lesson recordings — only your assigned videos appear here. 🎥")

catalog = load_video_catalog()
allowed = get_video_access(user.get("username", ""))

mine = [v for v in catalog if str(v.get("id", "")).strip().lower() in allowed]

if not catalog:
    st.info("No recordings uploaded yet — check back soon!")
elif not mine:
    st.info(
        "No recordings assigned to your account yet. If you've paid, "
        "ask your teacher to activate them."
    )
else:
    st.caption(f"Showing {len(mine)} of {len(catalog)} recordings.")
    for v in mine:
        with st.container(border=True):
            st.markdown(
                f"**🎥 {v.get('title', 'Untitled')}**  \n"
                f"{badge(v.get('lesson', ''), 'chapter') if v.get('lesson') else ''}",
                unsafe_allow_html=True,
            )
            st.link_button("▶ Watch on Google Drive (opens in a new tab)", v.get("url", ""))
            st.caption("Plays on Google Drive — use your Gmail if it asks you to sign in.")
