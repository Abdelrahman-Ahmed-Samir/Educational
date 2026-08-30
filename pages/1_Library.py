import json
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.ui import APP_ICON, apply_theme, badge, render_header  # noqa: E402

st.set_page_config(page_title="Library", page_icon="📚")
apply_theme()

RESOURCES_DIR = APP_DIR / "resources"
MANIFEST_PATH = RESOURCES_DIR / "manifest.json"

TYPE_LABELS = {"video": "Video", "pdf": "PDF", "qa": "Q&A doc", "article": "Article"}


def load_resources():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


render_header("Learning resources and Q&A documents for the class.")

resources = load_resources()
topics = sorted({r["topic"] for r in resources})

col1, col2 = st.columns(2)
type_filter = col1.selectbox("Type", ["All"] + list(TYPE_LABELS.values()))
topic_filter = col2.selectbox("Topic", ["All"] + topics)

for r in resources:
    if type_filter != "All" and TYPE_LABELS.get(r["type"]) != type_filter:
        continue
    if topic_filter != "All" and r["topic"] != topic_filter:
        continue

    with st.container(border=True):
        st.markdown(
            f"**{r['title']}**  \n"
            f"{badge(TYPE_LABELS.get(r['type'], r['type']), r['type'])} {badge(r['topic'], 'topic')}",
            unsafe_allow_html=True,
        )

        if "url" in r:
            st.link_button("Open", r["url"])
        elif "file" in r:
            file_path = RESOURCES_DIR / r["file"]
            if file_path.exists():
                with open(file_path, "rb") as f:
                    st.download_button("Download", f, file_name=r["file"])
            else:
                st.caption("File not uploaded to the repo yet.")

st.divider()
st.caption(
    "To add a resource: commit a small file to the `resources/` folder in the "
    "repo (or add a link for videos), then add an entry to `resources/manifest.json`."
)
