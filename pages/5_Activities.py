import json
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.auth import require_login  # noqa: E402
from utils.ui import apply_theme, badge, embed_pdf, render_header  # noqa: E402

st.set_page_config(page_title="Activities", page_icon="🎯")
apply_theme()
require_login()

ACTIVITIES_DIR = APP_DIR / "activities"
MANIFEST_PATH = ACTIVITIES_DIR / "manifest.json"


def _norm(text: str) -> str:
    import re

    s = str(text or "").lower()
    s = s.replace("_", " ").replace("-", " ").replace("&", " and ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _nospace(text: str) -> str:
    return _norm(text).replace(" ", "")


def _chapter_number(r: dict):
    import re

    hay = f"{r.get('title', '')} {r.get('topic', '')} {r.get('file', '')}"
    m = re.search(r"chapter[\s\-_]*(\d+)", hay, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _pretty(s: str) -> str:
    return str(s or "").replace("_", " ").replace("-", " ").strip()


def load_items():
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


render_header("Hands-on activities and assessments — practice what you learned! 🎉")

items = load_items()
for it in items:
    it["_chapter"] = _chapter_number(it)

search = st.text_input(
    "🔍 Search activities",
    placeholder="e.g. Chapter-2, activity, assessment...",
)
search_norm = _norm(search)
search_nospace = _nospace(search)

chapters = sorted({i["_chapter"] for i in items if i["_chapter"] is not None})
chapter_opts = ["All chapters"] + [f"Chapter {n}" for n in chapters]
kinds = sorted({_pretty(i.get("type", "activity")) for i in items})

c1, c2 = st.columns(2)
chapter_filter = c1.selectbox("Chapter", chapter_opts)
kind_filter = c2.selectbox("Kind", ["All"] + kinds if kinds else ["All"])


def _matches(it: dict) -> bool:
    if chapter_filter != "All chapters":
        try:
            want = int(chapter_filter.split()[-1])
        except ValueError:
            want = None
        if it["_chapter"] != want:
            return False
    if kind_filter != "All" and _pretty(it.get("type")) != kind_filter:
        return False
    if not search_norm:
        return True
    hay = _norm(f"{it.get('title', '')} {it.get('topic', '')} {it.get('file', '')} {it.get('type', '')}")
    hay_ns = _nospace(f"{it.get('title', '')} {it.get('topic', '')} {it.get('file', '')}")
    if search_norm in hay or (search_nospace and search_nospace in hay_ns):
        return True
    return all(t in hay or t in hay_ns for t in search_norm.split())


shown = [it for it in items if _matches(it)]
st.caption(f"Showing {len(shown)} of {len(items)} activities & assessments.")

if not items:
    st.info(
        "No activities yet. Drop PDFs into the `activities/` folder and list them in "
        "`activities/manifest.json` — same format as `resources/manifest.json` "
        "(`title`, `type` like `activity`/`assessment`, `topic` like `Chapter 1`, "
        "`file`, optional `date_added`).",
        icon="🎯",
    )
    st.stop()

if not shown:
    st.warning("Nothing matches — try clearing the search.")
    if st.button("Clear search"):
        st.rerun()

for it in shown:
    with st.container(border=True):
        ch_badge = f" {badge('Chapter ' + str(it['_chapter']), 'chapter')}" if it.get("_chapter") else ""
        st.markdown(
            f"**🎯 {it.get('title', 'Untitled')}**  \n"
            f"{badge(_pretty(it.get('type', 'activity')), 'activity')} "
            f"{badge(_pretty(it.get('topic', '')), 'topic')}{ch_badge}",
            unsafe_allow_html=True,
        )
        file_path = ACTIVITIES_DIR / it.get("file", "")
        if it.get("file") and file_path.exists():
            if file_path.suffix.lower() == ".pdf":
                with st.expander("Preview", expanded=False):
                    embed_pdf(file_path)
            with open(file_path, "rb") as f:
                st.download_button(
                    "Download PDF", f, file_name=it["file"], key=f"act_{it.get('title', '')}"
                )
        elif it.get("url"):
            st.link_button("Open", it["url"])
        else:
            st.caption("📄 PDF not uploaded yet — add the file to `activities/` (see note below).")

st.divider()
st.caption(
    "To add an activity: commit the PDF to `activities/` then add an entry to "
    "`activities/manifest.json` with `title`, `type` (`activity` or `assessment`), "
    "`topic` (e.g. `Chapter 2`), and `file`."
)
