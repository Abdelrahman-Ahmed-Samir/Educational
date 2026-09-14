"""
Retrieval-augmented Q&A over the resource library.

Embeddings are computed locally with fastembed — a small ONNX model that
runs on CPU with no external API, no API key, and no usage quota. Only the
final answer-generation step calls the Gemini chat API.

How it works:
1. Preferred path: resources/embeddings.npz was precomputed offline (see
   scripts/build_embeddings.py) and committed to the repo. On startup we
   just load it — no embedding to do at all. We check it against a hash of
   manifest.json (and the embedding model name) so a stale file (resources
   changed but embeddings weren't rebuilt) is detected rather than
   silently used.
2. Fallback path: if embeddings.npz is missing or stale, every resource
   file in resources/ (skipping external `url` links — there's no local
   text to read from those) is extracted to plain text, split into
   overlapping chunks, and embedded locally with fastembed. This is cached
   with st.cache_resource so it only runs once per process, not once per
   question. It costs no API quota either way, but running
   scripts/build_embeddings.py ahead of time avoids repeating this work
   (and the one-time model download) on every fresh process.
3. A student's question is embedded the same way, locally, and compared
   against every chunk with cosine similarity to find the most relevant
   excerpts.
4. Those excerpts (plus the question) are sent to a Gemini chat model with
   instructions to answer only from the provided excerpts, and to say so
   plainly rather than guessing when the answer isn't in them. This is the
   only step that calls an external API and needs a key.

Setup: add a Gemini API key to Streamlit secrets (only needed for the chat
step — embeddings need no key at all):

    [gemini]
    api_key = "..."

Get a free key at https://aistudio.google.com/apikey. See README.md for the
full walkthrough.

To (re)generate the offline embeddings file after adding or changing a
resource, run locally (no API key required):

    python scripts/build_embeddings.py

then commit the updated resources/embeddings.npz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import numpy as np
import streamlit as st

from utils.resource_extraction import (
    EMBEDDINGS_PATH,
    MANIFEST_PATH,
    RESOURCES_DIR,
    iter_source_chunks,
    manifest_hash,
)

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # local, via fastembed — no API key
CHAT_MODEL = "gemini-3.5-flash"
TOP_K = 10


SYSTEM_INSTRUCTION = """
You are Little Champo, a helpful teaching assistant for this course.

Your primary source of knowledge is the course resources provided in the context.
Use those resources to help students learn, understand, review, and organize their studies.

Allowed tasks include:
- Answering questions about the course content.
- Summarizing lessons, chapters, or topics.
- Creating study plans and revision schedules.
- Explaining concepts in simpler language.
- Creating quizzes, flashcards, exercises, and practice questions.
- Comparing topics that appear in the course materials.
- Recommending what to study next based on the provided content.
- Helping students prepare for exams using the course resources.

Rules:
1. Treat the provided course resources as the authoritative source of course knowledge.
2. Do not introduce course facts, definitions, formulas, code examples, or technical details that are not supported by the provided resources.
3. You may reorganize, summarize, simplify, structure, or transform information from the resources to help the student learn.
4. You may use general reasoning and educational assistance skills (planning, scheduling, summarizing, tutoring, formatting, studying strategies, and organization) even when those are not explicitly written in the resources.
5. If a student asks for information that cannot be answered from the provided resources, clearly state that the answer is not covered in the course materials.
6. Never pretend information exists in the resources when it does not.
7. When relevant, mention which resource(s) were used.
8. Be concise, clear, and student-friendly.

When creating plans or schedules, base them on the topics available in the provided resources and make reasonable educational recommendations without inventing course content.
"""


@dataclass
class Chunk:
    text: str
    source_title: str
    source_topic: str
    embedding: np.ndarray


def gemini_configured() -> bool:
    """True if the chat library and an API key are both present, so pages
    can degrade gracefully (show a setup message) instead of crashing.
    Note: this only gates the chat step — embeddings run locally and need
    no key at all."""
    return (
        genai is not None
        and "gemini" in st.secrets
        and bool(st.secrets["gemini"].get("api_key"))
    )


def _configure_client() -> None:
    genai.configure(api_key=st.secrets["gemini"]["api_key"])


@st.cache_resource(show_spinner=False)
def _get_embedder() -> "TextEmbedding":
    """Loads the local embedding model once per process. First call
    downloads the (small, ~130MB) model from Hugging Face if it isn't
    already cached on disk; every call after that is instant."""
    return TextEmbedding(model_name=EMBEDDING_MODEL)


def _load_offline_index(expected_hash: str) -> Optional[list[Chunk]]:
    """Load resources/embeddings.npz if it exists and matches both the
    current manifest contents and the embedding model in use. Returns None
    (rather than raising) for any mismatch or read failure, so the caller
    can transparently fall back to embedding live."""
    if not EMBEDDINGS_PATH.exists():
        return None
    try:
        data = np.load(EMBEDDINGS_PATH, allow_pickle=False)
        if str(data["manifest_hash"]) != expected_hash:
            return None
        if str(data["model"]) != EMBEDDING_MODEL:
            return None
        embeddings = data["embeddings"]
        texts = data["texts"]
        titles = data["titles"]
        topics = data["topics"]
    except Exception:
        return None

    return [
        Chunk(
            text=str(texts[i]),
            source_title=str(titles[i]),
            source_topic=str(topics[i]),
            embedding=embeddings[i].astype(np.float32),
        )
        for i in range(len(texts))
    ]


def _build_live_index(manifest: list[dict]) -> list[Chunk]:
    """Extract, chunk, and embed every resource file locally. No API key
    or quota involved — only used when no valid offline embeddings.npz is
    found, to avoid repeating the work (and the one-time model download)
    on every process start."""
    source_chunks = iter_source_chunks(manifest)
    if not source_chunks:
        return []

    texts = [c[0] for c in source_chunks]
    embedder = _get_embedder()
    vectors = list(embedder.embed(texts))

    return [
        Chunk(
            text=texts[i],
            source_title=source_chunks[i][1],
            source_topic=source_chunks[i][2],
            embedding=np.array(vectors[i], dtype=np.float32),
        )
        for i in range(len(texts))
    ]


@st.cache_resource(show_spinner="Reading class resources for the first time…")
def _build_index(manifest_json: str) -> list[Chunk]:
    """Return the indexed chunks for the current manifest, preferring the
    precomputed offline file and only embedding live if it's missing or
    stale. Cached per app process, keyed on the manifest's raw contents."""
    expected_hash = manifest_hash(manifest_json)

    offline_chunks = _load_offline_index(expected_hash)
    if offline_chunks is not None:
        return offline_chunks

    manifest = json.loads(manifest_json)
    return _build_live_index(manifest)


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
    callers should catch and show a friendly message (see pages/4_Ask_AI.py).
    """
    _configure_client()
    manifest_json = MANIFEST_PATH.read_text(encoding="utf-8")
    chunks = _build_index(manifest_json)

    if not chunks:
        return (
            "I don't have any resource content indexed yet — ask your "
            "teacher to check that resource files are uploaded correctly.",
            [],
        )

    embedder = _get_embedder()
    q_embed = np.array(next(iter(embedder.query_embed(question))), dtype=np.float32)

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
