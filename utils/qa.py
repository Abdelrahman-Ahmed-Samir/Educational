"""
Retrieval-augmented Q&A over the resource library, backed by the Gemini API.

How it works:
1. Every resource file in resources/ (skipping external `url` links —
   there's no local text to read from those) is extracted to plain text,
   split into overlapping chunks, and embedded with Gemini's
   gemini-embedding-001 model.
2. A student's question is embedded the same way and compared against every
   chunk with cosine similarity to find the most relevant excerpts.
3. Those excerpts (plus the question) are sent to a Gemini chat model with
   instructions to answer only from the provided excerpts, and to say so
   plainly rather than guessing when the answer isn't in them.

Embeddings are cached twice, in layers:
- In memory via st.cache_resource, so within one running app process
  answering a question is just a similarity lookup plus one chat call.
- On disk at .cache/resource_embeddings.json, keyed by a hash of the
  resource files' contents plus the embedding model name. This is what
  actually matters for the free-tier rate limit: without it, every time the
  app process restarts (a redeploy, a Streamlit Cloud sleep/wake, or — most
  relevantly while developing — every `streamlit run` auto-reload after a
  code edit) the whole library would get re-embedded from scratch. The
  free tier's embed_content quota is only 100 requests/minute, and a few
  edit-and-reload cycles in a row is enough to blow through that on its
  own, with no students involved at all. With the disk cache, resources
  are only re-embedded when their content actually changes.

Setup: add a Gemini API key to Streamlit secrets:

    [gemini]
    api_key = "..."

Get a free key at https://aistudio.google.com/apikey. See README.md for the
full walkthrough.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import streamlit as st

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from google.api_core.exceptions import ResourceExhausted
except ImportError:
    ResourceExhausted = None

APP_DIR = Path(__file__).parent.parent
RESOURCES_DIR = APP_DIR / "resources"
MANIFEST_PATH = RESOURCES_DIR / "manifest.json"
CACHE_PATH = APP_DIR / ".cache" / "resource_embeddings.json"

EMBEDDING_MODEL = "models/gemini-embedding-001"  # text-embedding-004 was shut down Jan 14, 2026
CHAT_MODEL = "gemini-2.5-flash"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
TOP_K = 5
EMBED_BATCH_SIZE = 20  # keep well under the free-tier embed_content RPM limit
MAX_RETRIES = 4

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


def _embed_with_retry(*, content, task_type: str):
    """Wraps genai.embed_content with backoff on 429s. Free-tier rate limits
    are tight enough that even a single legitimate indexing pass can get
    momentarily throttled; a few retries with increasing waits handles that
    without surfacing an error to the student for a transient hiccup."""
    delay = 5.0
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return genai.embed_content(
                model=EMBEDDING_MODEL, content=content, task_type=task_type
            )
        except Exception as e:
            is_quota_error = (
                (ResourceExhausted is not None and isinstance(e, ResourceExhausted))
                or "429" in str(e)
                or "quota" in str(e).lower()
            )
            if not is_quota_error or attempt == MAX_RETRIES - 1:
                raise
            last_error = e
            time.sleep(delay)
            delay *= 2
    raise last_error  # pragma: no cover — loop always returns or raises above


def _fingerprint(manifest: list) -> str:
    """Hash of every resource file's bytes plus the embedding model name.
    Changes only when a resource file's actual content changes (or the
    model changes) — not on every app restart — so it's what the disk
    cache is keyed on."""
    hasher = hashlib.sha256()
    hasher.update(EMBEDDING_MODEL.encode())
    for r in sorted(manifest, key=lambda r: r.get("file", "")):
        if "file" not in r:
            continue
        file_path = RESOURCES_DIR / r["file"]
        if file_path.exists():
            hasher.update(r["file"].encode())
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def _load_disk_cache(fingerprint: str) -> Optional[list[Chunk]]:
    if not CACHE_PATH.exists():
        return None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("fingerprint") != fingerprint:
        return None
    return [
        Chunk(
            text=c["text"],
            source_title=c["source_title"],
            source_topic=c["source_topic"],
            embedding=np.array(c["embedding"], dtype=np.float32),
        )
        for c in data.get("chunks", [])
    ]


def _save_disk_cache(fingerprint: str, chunks: list[Chunk]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fingerprint": fingerprint,
        "chunks": [
            {
                "text": c.text,
                "source_title": c.source_title,
                "source_topic": c.source_topic,
                "embedding": c.embedding.tolist(),
            }
            for c in chunks
        ],
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


@st.cache_resource(show_spinner="Reading class resources for the first time…")
def _build_index(manifest_json: str) -> list[Chunk]:
    """Extract, chunk, and embed every resource file — or load them from
    the on-disk cache if nothing's changed since last time (see module
    docstring for why this matters for the free-tier rate limit). Also
    cached in memory per app process via st.cache_resource, so this whole
    function body only runs once per process even across many questions.
    """
    manifest = json.loads(manifest_json)
    fingerprint = _fingerprint(manifest)

    cached = _load_disk_cache(fingerprint)
    if cached is not None:
        return cached

    _configure_client()

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
        result = _embed_with_retry(content=batch, task_type="retrieval_document")
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

    _save_disk_cache(fingerprint, chunks)
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

    q_result = _embed_with_retry(content=question, task_type="retrieval_query")
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
