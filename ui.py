"""
Shared look-and-feel for every page: the app name/icon, a header component,
small colored badges for tags, and a bit of CSS polish on top of the
Streamlit theme set in .streamlit/config.toml.
"""

import base64
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

APP_NAME = "CodeCraft Hub"
APP_ICON = "🚀"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* Header */
.app-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 6px 0 18px;
    margin-bottom: 6px;
    border-bottom: 1px solid #EDEBF7;
}
.app-header-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    background: linear-gradient(135deg, #6C5CE7, #9B8CFB);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    flex-shrink: 0;
}
.app-header-title {
    font-size: 22px;
    font-weight: 700;
    margin: 0;
    line-height: 1.2;
    color: #1B1F23;
}
.app-header-subtitle {
    font-size: 14px;
    color: #6B7280;
    margin: 2px 0 0;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 3px 11px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 6px;
}

/* Cards (st.container(border=True)) feel a bit softer */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
}

/* Buttons: slightly bolder, friendlier */
.stButton > button, .stFormSubmitButton > button, .stLinkButton > a {
    border-radius: 10px !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    box-shadow: 0 2px 10px rgba(108, 92, 231, 0.25);
}

/* Metrics */
div[data-testid="stMetric"] {
    background: #F5F3FF;
    border-radius: 14px;
    padding: 14px 16px 10px;
}
</style>
"""

BADGE_COLORS = {
    "video": ("#FEE2E2", "#991B1B"),
    "pdf": ("#FEF3C7", "#92400E"),
    "qa": ("#DBEAFE", "#1E40AF"),
    "article": ("#D1FAE5", "#065F46"),
    "topic": ("#EEF2FF", "#4338CA"),
    "type": ("#F5F3FF", "#6C5CE7"),
    "correct": ("#D1FAE5", "#065F46"),
    "incorrect": ("#FEE2E2", "#991B1B"),
    "review": ("#FEF3C7", "#92400E"),
}


def apply_theme():
    """Call once near the top of every page, right after st.set_page_config."""
    st.markdown(CSS, unsafe_allow_html=True)
    logo_path = ASSETS_DIR / "logo.svg"
    if logo_path.exists():
        try:
            st.logo(str(logo_path), size="large")
        except Exception:
            pass  # older Streamlit versions without st.logo just skip the sidebar mark


def render_header(subtitle: str = ""):
    """A friendly header bar with the app's name, used consistently on every page."""
    st.markdown(
        f"""
        <div class="app-header">
            <div class="app-header-icon">{APP_ICON}</div>
            <div>
                <p class="app-header-title">{APP_NAME}</p>
                <p class="app-header-subtitle">{subtitle}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "type") -> str:
    """Small colored pill, e.g. badge('PDF', 'pdf') or badge('Loops', 'topic')."""
    bg, color = BADGE_COLORS.get(kind, BADGE_COLORS["type"])
    return f'<span class="badge" style="background:{bg};color:{color};">{text}</span>'


def embed_pdf(file_path: Path, height: int = 600):
    """Render a local PDF inline using the browser's own PDF viewer.

    Works by base64-encoding the file into a data URI and dropping it into
    an <embed> tag — there's no native st.pdf widget, so this is the
    standard workaround. Fine for classroom-sized PDFs; very large files
    will be slow since the whole file is inlined into the page.
    """
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    components.html(
        f'<embed src="data:application/pdf;base64,{b64}" '
        f'type="application/pdf" width="100%" height="{height}" '
        f'style="border:1px solid #E3E1DA; border-radius:8px;">',
        height=height,
    )
