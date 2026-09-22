import json
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.ui import APP_ICON, apply_theme, badge, embed_pdf, render_header  # noqa: E402

st.set_page_config(page_title="Library", page_icon="📚")
apply_theme()

RESOURCES_DIR = APP_DIR / "resources"
MANIFEST_PATH = RESOURCES_DIR / "manifest.json"

TYPE_LABELS = {"video": "Video", "pdf": "PDF", "qa": "Q&A doc", "article": "Article"}


def _norm(text: str) -> str:
    """Lowercase, unify separators so 'Chapter-2', 'chapter_2' and
    'Chapter 2' all match. Also turns 'CyberSecurity' matching easier
    via a nospace variant in the search itself."""
    import re

    s = str(text or "").lower()
    s = s.replace("_", " ").replace("-", " ").replace("&", " and ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _nospace(text: str) -> str:
    return _norm(text).replace(" ", "")


def _chapter_number(r: dict):
    """Extract chapter number from title/topic/file, e.g. 2 for
    'Chapter-2-Cyber Security'. Returns int or None."""
    import re

    hay = f"{r.get('title', '')} {r.get('topic', '')} {r.get('file', '')}"
    m = re.search(r"chapter[\s\-_]*(\d+)", hay, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _pretty_topic(topic: str) -> str:
    return str(topic or "").replace("_", " ").replace("-", " ").strip()


def _display_type(rtype: str) -> str:
    # Manifest uses mixed values ("PowerPoint", "PDF", ...); map them
    # to the friendly labels instead of requiring exact lowercase keys.
    key = str(rtype or "").lower()
    if "power" in key or "ppt" in key:
        return "Slides"
    if "pdf" in key:
        return "PDF"
    if "q" in key and "a" in key:
        return "Q&A doc"
    return TYPE_LABELS.get(key, str(rtype))


def load_resources():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


render_header("Learning resources and Q&A documents for the class.")

resources = load_resources()

# Precompute chapter numbers once so filters + cards stay consistent.
for r in resources:
    r["_chapter"] = _chapter_number(r)

# ---- Search + filters (same structure, fixed) ----
search = st.text_input(
    "🔍 Search by chapter name or number",
    placeholder="e.g. Chapter-2, Chapter 2 Cyber Security, loops...",
)
search_norm = _norm(search)
search_nospace = _nospace(search)

import re as _re

_search_chapter_num = None
if search:
    _m = _re.search(r"chapter[\s\-_]*(\d+)", search, _re.IGNORECASE)
    if _m:
        _search_chapter_num = int(_m.group(1))

# Chapter dropdown built from actual data: "Chapter 2 — CyberSecurity ..."
_chapters = sorted({r["_chapter"] for r in resources if r["_chapter"] is not None})
_chapter_options = ["All chapters"]
_chapter_label_to_num = {}
for num in _chapters:
    topics_for_ch = sorted({_pretty_topic(r.get("topic", "")) for r in resources if r["_chapter"] == num})
    hint = topics_for_ch[0] if topics_for_ch else ""
    # Keep label short but recognizable: "Chapter 2 — CyberSecurity ..."
    label = f"Chapter {num}" + (f" — {hint[:40]}" if hint else "")
    _chapter_options.append(label)
    _chapter_label_to_num[label] = num

type_options = ["All"] + sorted({_display_type(r.get("type", "")) for r in resources})
topics = sorted({_pretty_topic(r.get("topic", "")) for r in resources})

col1, col2 = st.columns(2)
type_filter = col1.selectbox("Type", type_options)
chapter_filter = col2.selectbox("Chapter", _chapter_options)

topic_filter = st.selectbox("Topic", ["All"] + topics)

def _matches_search(r: dict) -> bool:
    if not search_norm:
        return True
    hay = _norm(f"{r.get('title', '')} {r.get('topic', '')} {r.get('file', '')} {r.get('type', '')}")
    hay_nospace = _nospace(f"{r.get('title', '')} {r.get('topic', '')} {r.get('file', '')}")
    # 1) direct substring ("chapter 2" matches "chapter 2 ...")
    if search_norm in hay:
        return True
    # 2) nospace match ("cyber security" matches "cybersecurity")
    if search_nospace and search_nospace in hay_nospace:
        return True
    # 3) "chapter N" in query matches chapter number even if wording differs
    if _search_chapter_num is not None and r["_chapter"] == _search_chapter_num:
        # require at least one other token to also match, or just chapter match
        other_tokens = [t for t in search_norm.split() if t != "chapter" and t != str(_search_chapter_num)]
        if not other_tokens:
            return True
        return all(t in hay or t in hay_nospace for t in other_tokens)
    # 4) every word appears somewhere (lets "Chapter-2-Cyber Security" work)
    tokens = [t for t in search_norm.split() if t]
    return bool(tokens) and all(t in hay or t in hay_nospace for t in tokens)


filtered = []
for r in resources:
    if type_filter != "All" and _display_type(r.get("type")) != type_filter:
        continue
    if chapter_filter != "All chapters" and r["_chapter"] != _chapter_label_to_num[chapter_filter]:
        continue
    if topic_filter != "All" and _pretty_topic(r.get("topic")) != topic_filter:
        continue
    if not _matches_search(r):
        continue
    filtered.append(r)

st.caption(f"Showing {len(filtered)} of {len(resources)} resources.")
if len(filtered) != len(resources):
    if st.button("Clear search & filters"):
        st.rerun()

for r in filtered:

    with st.container(border=True):
        _ch = r.get("_chapter")
        chapter_badge = f" {badge(f'Chapter {_ch}', 'chapter')}" if _ch else ""
        st.markdown(
            f"**{r['title']}**  \n"
            f"{badge(_display_type(r.get('type')), r.get('type', ''))} {badge(_pretty_topic(r.get('topic')), 'topic')}{chapter_badge}",
            unsafe_allow_html=True,
        )

        if "url" in r:
            if r["type"] == "video":
                st.video(r["url"])
            else:
                st.link_button("Open (opens in a new tab)", r["url"])
                st.caption("External articles can't be shown inline — most sites block embedding.")
        elif "file" in r:
            file_path = RESOURCES_DIR / r["file"]
            if file_path.exists():
                suffix = file_path.suffix.lower()

                if suffix == ".pdf":
                    with st.expander("Preview", expanded=False):
                        embed_pdf(file_path)
                elif suffix in (".txt", ".md"):
                    with st.expander("Preview", expanded=False):
                        st.markdown(file_path.read_text(encoding="utf-8"))

                with open(file_path, "rb") as f:
                    st.download_button("Download", f, file_name=r["file"], key=f"dl_{r['title']}")
            else:
                st.caption("File not uploaded to the repo yet.")

st.divider()
st.caption(
    "To add a resource: commit a small file to the `resources/` folder in the "
    "repo (or add a link for videos), then add an entry to `resources/manifest.json`."
)
