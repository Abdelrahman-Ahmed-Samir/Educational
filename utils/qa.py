"""
Retrieval-augmented Q&A over the resource library, backed by the Gemini API.

How it works:
1. The first time this is used in an app process, every resource file in
   resources/ (skipping external `url` links — there's no local text to
   read from those) is extracted to plain text, split into overlapping
   chunks, and embedded with Gemini's text-embedding-004 model. This is
   cached with st.cache_resource so it only runs once per process, not once
   per question — after that, answering is just a similarity lookup plus
   one chat call.
2. A student's question is embedded the same way and compared against every
   chunk with cosine similarity to find the most relevant excerpts.
3. Those excerpts (plus the question) are sent to a Gemini chat model with
   instructions to answer only from the provided excerpts, and to say so
   plainly rather than guessing when the answer isn't in them.

Setup: add a Gemini API key to Streamlit secrets:

    [gemini]
    api_key = "..."

Get a free key at https://aistudio.google.com/apikey. See README.md for the
full walkthrough.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import streamlit as st

try:
    import google.generativeai as genai
except ImportError:
    genai = None

APP_DIR = Path(__file__).parent.parent
RESOURCES_DIR = APP_DIR / "resources"
MANIFEST_PATH = RESOURCES_DIR / "manifest.json"

EMBEDDING_MODEL = "models/gemini-embedding-2"
CHAT_MODEL = "gemini-3.5-flash"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
TOP_K = 5
EMBED_BATCH_SIZE = 100

SYSTEM_INSTRUCTION = (
    "You are a helpful teaching assistant for a programming class. Answer "
    "the student's question using ONLY the excerpts from the class "
    "resources provided below — do not use outside knowledge, and do not "
    "guess. If the excerpts don't contain the answer, say plainly that "
    "it isn't covered in the class resources and the student should ask "
    "their teacher, rather than making something up. Keep answers concise "
    "and mention which resource(s) you used by title."
)


@dataclass
class Chunk:
    text: str
    source_title: str
    source_topic: str
    embedding: np.ndarray


def gemini_configured() -> bool:
    """True if the library and an API key are both present, so pages can
    degrade gracefully (show a setup message) instead of crashing."""
    return (
        genai is not None
        and "gemini" in st.secrets
        and bool(st.secrets["gemini"].get("api_key"))
    )


def _configure_client() -> None:
    genai.configure(api_key=st.secrets["gemini"]["api_key"])


def _extract_text(file_path: Path) -> str:
    """Best-effort plain-text extraction for pptx, docx, pdf, txt, and md
    resources. Returns "" (rather than raising) for anything that fails to
    parse, so one bad file can't break indexing for the rest of the library.
    """
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pptx":
            from pptx import Presentation

            prs = Presentation(str(file_path))
            parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        parts.append(shape.text_frame.text)
                    if shape.has_table:
                        for row in shape.table.rows:
                            parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)

        if suffix == ".docx":
            import docx

            doc = docx.Document(str(file_path))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)

        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(file_path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)

        if suffix in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return ""


def _chunk_text(text: str) -> list[str]:
    """Split into overlapping character chunks. Simple and good enough for
    slide-deck / Q&A-doc sized resources — no sentence-boundary awareness
    needed for this scale of content."""
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


@st.cache_resource(show_spinner="Reading class resources for the first time…")
def _build_index(manifest_json: str) -> list[Chunk]:
    """Extract, chunk, and embed every resource file. Cached per app
    process, keyed on the manifest's raw contents — edit a resource or add
    a new one and the next fresh process rebuilds the index automatically.
    """
    _configure_client()
    manifest = json.loads(manifest_json)

    texts_to_embed: list[str] = []
    meta: list[tuple[str, str]] = []

    for r in manifest:
        if "file" not in r:
            continue  # external links have no local text to read
        file_path = RESOURCES_DIR / r["file"]
        if not file_path.exists():
            continue
        text = _extract_text(file_path)
        for piece in _chunk_text(text):
            texts_to_embed.append(piece)
            meta.append((r["title"], r.get("topic", "")))

    if not texts_to_embed:
        return []

    chunks: list[Chunk] = []
    for i in range(0, len(texts_to_embed), EMBED_BATCH_SIZE):
        batch = texts_to_embed[i : i + EMBED_BATCH_SIZE]
        result = genai.embed_content(
            model=EMBEDDING_MODEL, content=batch, task_type="retrieval_document"
        )
        for j, emb in enumerate(result["embedding"]):
            title, topic = meta[i + j]
            chunks.append(
                Chunk(
                    text=batch[j],
                    source_title=title,
                    source_topic=topic,
                    embedding=np.array(emb, dtype=np.float32),
                )
            )

    return chunks


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-8
    return float(np.dot(a, b) / denom)


def index_size() -> int:
    """Number of indexed chunks, mostly useful for a teacher-facing status
    line ('42 chunks indexed from 3 resources')."""
    if not MANIFEST_PATH.exists():
        return 0
    return len(_build_index(MANIFEST_PATH.read_text(encoding="utf-8")))


def answer_question(question: str) -> tuple[str, list[str]]:
    """Returns (answer_text, source_titles_used). Raises on API errors —
    callers should catch and show a friendly message (see pages/4_Ask_AI.py)."""
    _configure_client()
    manifest_json = MANIFEST_PATH.read_text(encoding="utf-8")
    chunks = _build_index(manifest_json)

    if not chunks:
        return (
            "I don't have any resource content indexed yet — ask your "
            "teacher to check that resource files are uploaded correctly.",
            [],
        )

    q_result = genai.embed_content(
        model=EMBEDDING_MODEL, content=question, task_type="retrieval_query"
    )
    q_embed = np.array(q_result["embedding"], dtype=np.float32)

    scored = sorted(chunks, key=lambda c: _cosine_sim(c.embedding, q_embed), reverse=True)
    top = scored[:TOP_K]

    context = "\n\n".join(f"[From: {c.source_title}]\n{c.text}" for c in top)
    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"--- Class resource excerpts ---\n{context}\n\n"
        f"--- Student question ---\n{question}"
    )

    model = genai.GenerativeModel(CHAT_MODEL)
    response = model.generate_content(prompt)

    sources = sorted({c.source_title for c in top})
    return response.text, sources
