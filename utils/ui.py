"""
Shared look-and-feel for every page: the app name/icon, a header component,
small colored badges for tags, and a bit of CSS polish on top of the
Streamlit theme set in .streamlit/config.toml.
"""

import base64
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

APP_NAME = "CodeCraft Hub 🎒"
APP_ICON = "🎓"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Nunito:wght@400;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Nunito', sans-serif;
}

/* Playful page background */
.stApp {
    background: linear-gradient(180deg, #FFFBEB 0%, #FFF7ED 45%, #FDF2F8 100%);
}

/* Header — classroom poster style */
.app-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 18px;
    margin-bottom: 10px;
    background: linear-gradient(135deg, #FBBF24, #FB7185 60%, #A78BFA);
    border-radius: 20px;
    box-shadow: 0 6px 20px rgba(251, 146, 60, 0.25);
    color: white;
}
.app-header-icon {
    width: 52px;
    height: 52px;
    border-radius: 16px;
    background: rgba(255,255,255,0.95);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    flex-shrink: 0;
    transform: rotate(-6deg);
}
.app-header-title {
    font-family: 'Fredoka', sans-serif;
    font-size: 26px;
    font-weight: 700;
    margin: 0;
    line-height: 1.2;
    color: #FFFFFF;
    text-shadow: 0 1px 4px rgba(0,0,0,0.15);
}
.app-header-subtitle {
    font-size: 14px;
    color: #FFF7ED;
    margin: 2px 0 0;
    font-weight: 600;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
    margin-right: 6px;
    border: 2px solid rgba(255,255,255,0.7);
}

/* Cards — sticker-like */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 18px !important;
    background: #FFFFFF !important;
    border: 2px solid #FDE68A !important;
    box-shadow: 0 4px 14px rgba(245, 158, 11, 0.12) !important;
}

/* Buttons: chunky and fun */
.stButton > button, .stFormSubmitButton > button, .stLinkButton > a {
    border-radius: 14px !important;
    font-weight: 800 !important;
    border-bottom: 4px solid rgba(0,0,0,0.12) !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F59E0B, #EF4444) !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(239, 68, 68, 0.3);
}

/* Metrics — score cards */
div[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 2px dashed #FBBF24;
    border-radius: 18px;
    padding: 14px 16px 10px;
}

/* Exam timer banner */
.exam-timer {
    font-family: 'Fredoka', sans-serif;
    font-size: 20px;
    font-weight: 700;
    text-align: center;
    padding: 10px 16px;
    border-radius: 16px;
    background: #ECFDF5;
    border: 2px solid #34D399;
    color: #065F46;
    margin: 8px 0;
}
.exam-timer.low {
    background: #FEF2F2;
    border-color: #F87171;
    color: #991B1B;
    animation: pulse 1.2s infinite;
}
@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.02); }
    100% { transform: scale(1); }
}
</style>
"""

BADGE_COLORS = {
    "video": ("#FEE2E2", "#991B1B"),
    "pdf": ("#FEF3C7", "#92400E"),
    "qa": ("#DBEAFE", "#1E40AF"),
    "article": ("#D1FAE5", "#065F46"),
    "topic": ("#E0E7FF", "#3730A3"),
    "type": ("#FEF3C7", "#92400E"),
    "chapter": ("#DDD6FE", "#5B21B6"),
    "grade": ("#FEF3C7", "#92400E"),
    "activity": ("#FCE7F3", "#9D174D"),
    "assessment": ("#FFEDD5", "#9A3412"),
    "slides": ("#E0F2FE", "#075985"),
    "correct": ("#D1FAE5", "#065F46"),
    "incorrect": ("#FEE2E2", "#991B1B"),
    "review": ("#FEF3C7", "#92400E"),
    "news": ("#DBEAFE", "#1E40AF"),
    "resource": ("#D1FAE5", "#065F46"),
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
    key = str(kind or "type").lower()
    # Map messy manifest values ("PowerPoint", "PDF", "Q&A doc") to colors.
    if "power" in key or "ppt" in key or "slide" in key:
        key = "slides"
    elif key == "pdf":
        key = "pdf"
    elif "activity" in key:
        key = "activity"
    elif "assess" in key:
        key = "assessment"
    bg, color = BADGE_COLORS.get(key, BADGE_COLORS.get(kind, BADGE_COLORS["type"]))
    return f'<span class="badge" style="background:{bg};color:{color};">{text}</span>'


def timer_banner(remaining_sec: int, total_sec: int) -> None:
    """Big playful countdown banner. Turns red + pulsing under 60s."""
    mm = remaining_sec // 60
    ss = remaining_sec % 60
    cls = "exam-timer low" if remaining_sec <= 60 else "exam-timer"
    emoji = "⏰" if remaining_sec > 60 else "🔥"
    st.markdown(
        f"<div class='{cls}'>{emoji} {mm:02d}:{ss:02d} left — keep going, you got this! 💪</div>",
        unsafe_allow_html=True,
    )
    if total_sec > 0:
        st.progress(max(0.0, min(1.0, remaining_sec / total_sec)))


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


def render_review_items(review_items: list) -> None:
    """Student-facing answer review: every question with YOUR answer and
    the CORRECT answer side by side. Shared by the quiz result screen,
    the quiz-list 'review last attempt' expander, and the teacher Grades
    page (which renders saved snapshots from the sheet)."""
    status_labels = {"correct": "Correct", "incorrect": "Incorrect", "review": "Needs review"}
    for i, item in enumerate(review_items or []):
        with st.container(border=True):
            st.markdown(
                f"{badge(status_labels.get(item.get('status', ''), 'review'), item.get('status', 'review'))}",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Q{i + 1}.** {item.get('question', '')}")

            if "sub_lines" in item:
                for line in item["sub_lines"]:
                    st.markdown(line)
            elif item.get("status") == "review":
                st.markdown(f"✏️ Your answer: {item.get('your_answer', '')}")
                st.caption(f"Model answer (for self-checking): {item.get('correct_answer', '')}")
            else:
                st.markdown(f"✏️ Your answer: **{item.get('your_answer', '')}**")
                st.markdown(f"✅ Correct answer: **{item.get('correct_answer', '')}**")
