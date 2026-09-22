"""
Retrieval-augmented Q&A over the resource library, in Arabic and English.

Embeddings are computed locally with fastembed — a small ONNX model that
runs on CPU with no external API, no API key, and no usage quota. Only the
final answer-generation step calls an external chat API.

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
   question.
3. A student's question is embedded the same way, locally, and compared
   against every chunk with cosine similarity to find the most relevant
   excerpts. Arabic questions are first translated to English (one cheap
   chat call) so the small English-only embedding model keeps working —
   this avoids a 4x-bigger multilingual model that wouldn't fit Streamlit
   Cloud's ~1GB RAM. The student's ORIGINAL question is what gets
   answered, in the student's own language.
4. Those excerpts (plus the question) are sent to a chat model with
   instructions to answer only from the provided excerpts, in the
   student's language, and to say so plainly rather than guessing when
   the answer isn't in them.

Chat providers — Gemini first, Groq fallback (both free, no credit card):
  - Gemini (Google AI Studio key): best free quality, huge context.
  - Groq (console.groq.com key): very fast, doesn't train on your data.
  If Gemini fails or its key is missing, Groq is tried automatically.

Setup: add either key (or both) to Streamlit secrets:

    [gemini]
    api_key = "..."

    [groq]
    api_key = "..."

    # Optional model overrides (tried in order — first working model wins):
    # [ai]
    # gemini_models = ["gemini-3.6-flash"]
    # groq_models = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]

Get free keys at https://aistudio.google.com/apikey and
https://console.groq.com/keys. See README.md for the full walkthrough.

To (re)generate the offline embeddings file after adding or changing a
resource, run locally (no API key required):

    python scripts/build_embeddings.py

then commit the updated resources/embeddings.npz.
"""

from __future__ import annotations

import json
import re
import time
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
    from google import genai as google_genai
except ImportError:
    google_genai = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None

# Small (~130MB) English embedding model — deliberately kept so the app
# fits Streamlit Cloud's ~1GB RAM. Arabic questions are translated to
# English before retrieval (see _translate_for_retrieval), so no bigger
# multilingual model is needed. embeddings.npz stays valid as long as
# this value is unchanged.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # local, via fastembed — no API key
# Model chains, tried in order — first working model wins. Providers
# retire/rename free models often (we've seen it twice already), so the
# app walks a list instead of depending on a single name. Override in
# secrets with [ai] gemini_models / groq_models (TOML arrays), or the
# legacy single-string gemini_model / groq_model.
DEFAULT_GEMINI_MODELS = ["gemini-3.6-flash"]
# gpt-oss models back it up if Qwen is ever unavailable on the account.
DEFAULT_GROQ_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
TOP_K = 10
TOP_SOURCES = 3  # only the 3 most relevant titles are shown as Sources


SYSTEM_INSTRUCTION = (
    "You are Little Champo, a friendly teaching assistant for a beginner programming class. "
    "Rules:\n"
    "1. Reply in the SAME language the student used — Arabic if they asked in Arabic, "
    "English if they asked in English. For mixed questions, match the dominant language.\n"
    "2. Use ONLY the class resource excerpts below. Do not use outside knowledge and do not guess.\n"
    "3. If the excerpts don't contain the answer, say so plainly in the student's language "
    "and suggest asking the teacher — never invent an answer.\n"
    "4. Teach, don't just tell: give a short, clear explanation with one tiny example when it "
    "helps. Beginner-friendly and encouraging, 1–2 short paragraphs, not an essay.\n"
    "5. At the end, name ONLY the resource(s) you actually used, by title. If none were "
    "useful, say so instead of listing titles."
)


@dataclass
class Chunk:
    text: str
    source_title: str
    source_topic: str
    embedding: np.ndarray


def _secret(section: str, key: str, default: str = "") -> str:
    """Read an optional secrets value without ever raising, so pages can
    degrade gracefully when secrets are missing."""
    try:
        return st.secrets.get(section, {}).get(key, default) or default
    except Exception:
        return default


def _ai_section() -> dict:
    try:
        section = st.secrets.get("ai", {})
        return dict(section) if section else {}
    except Exception:
        return {}


def _as_list(value, default_list: list[str]) -> list[str]:
    """Secrets may hold a TOML array or a single string — accept both."""
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items or list(default_list)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(default_list)


def gemini_model_names() -> list[str]:
    ai = _ai_section()
    if ai.get("gemini_model"):
        return [str(ai["gemini_model"]).strip()]
    return _as_list(ai.get("gemini_models"), DEFAULT_GEMINI_MODELS)


def groq_model_names() -> list[str]:
    ai = _ai_section()
    if ai.get("groq_model"):
        return [str(ai["groq_model"]).strip()]
    return _as_list(ai.get("groq_models"), DEFAULT_GROQ_MODELS)


def gemini_configured() -> bool:
    """True if the Gemini library and an API key are both present."""
    return google_genai is not None and bool(_secret("gemini", "api_key"))


def groq_configured() -> bool:
    """True if the Groq library and an API key are both present."""
    return Groq is not None and bool(_secret("groq", "api_key"))


def ai_configured() -> bool:
    """True if at least one chat provider is usable, so the Ask AI page
    can degrade gracefully (show a setup message) instead of crashing.
    Note: this only gates the chat step — embeddings run locally and need
    no key at all."""
    return gemini_configured() or groq_configured()


def _ask_gemini(prompt: str, model: str) -> str:
    client = google_genai.Client(api_key=_secret("gemini", "api_key"))
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()


def _ask_groq(prompt: str, model: str) -> str:
    client = Groq(api_key=_secret("groq", "api_key"))
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=800,
    )
    return (completion.choices[0].message.content or "").strip()


def _is_transient(err: Exception) -> bool:
    """Overload/rate-limit errors are worth one retry — spikes are usually
    temporary. A 404 (retired model) is not: move straight to the next
    model in the chain."""
    text = str(err)
    return any(
        marker in text
        for marker in (
            "503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
            "overloaded", "high demand", "rate limit", "RateLimit", "timeout",
        )
    )


def _ask_chat(prompt: str) -> tuple[str, str]:
    """Walk Gemini models, then Groq models — first working model wins.
    Returns (answer, provider_label). Raises RuntimeError if everything
    fails — callers should catch and show a friendly message
    (see pages/4_Ask_AI.py)."""
    errors = []
    if gemini_configured():
        for model in gemini_model_names():
            try:
                return _ask_gemini(prompt, model), f"Gemini ({model})"
            except Exception as e:  # noqa: BLE001
                errors.append(f"Gemini/{model}: {e}")
                if _is_transient(e):
                    time.sleep(2)
                    try:
                        return _ask_gemini(prompt, model), f"Gemini ({model})"
                    except Exception as e2:  # noqa: BLE001
                        errors.append(f"Gemini/{model} retry: {e2}")
    if groq_configured():
        for model in groq_model_names():
            try:
                return _ask_groq(prompt, model), f"Groq ({model})"
            except Exception as e:  # noqa: BLE001
                errors.append(f"Groq/{model}: {e}")
                continue
    raise RuntimeError("; ".join(errors) or "No AI provider configured")


_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_RE.search(text or ""))


def _translate_for_retrieval(question: str) -> str:
    """Translate an Arabic (or mixed) question to English for the
    English-only embedding index. Returns the translation, or the
    original question on any failure so retrieval still runs."""
    try:
        translated, _ = _ask_chat(
            "Translate this student question to English. "
            "Return ONLY the translation, nothing else.\n\n"
            f"Question: {question}"
        )
        return translated or question
    except Exception:
        return question


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


def answer_question(question: str) -> tuple[str, list[str], str]:
    """Returns (answer_text, source_titles, provider_label). The answer is
    written in the student's own language (Arabic or English). Raises on
    API errors — callers should catch and show a friendly message
    (see pages/4_Ask_AI.py).
    """
    manifest_json = MANIFEST_PATH.read_text(encoding="utf-8")
    chunks = _build_index(manifest_json)

    if not chunks:
        return (
            "I don't have any resource content indexed yet — ask your "
            "teacher to check that resource files are uploaded correctly.",
            [],
            "none",
        )

    # Arabic questions are translated for retrieval only — the student
    # still gets their answer in Arabic (see SYSTEM_INSTRUCTION rule 1).
    retrieval_query = _translate_for_retrieval(question) if _has_arabic(question) else question

    embedder = _get_embedder()
    q_embed = np.array(next(iter(embedder.query_embed(retrieval_query))), dtype=np.float32)

    scored = sorted(chunks, key=lambda c: _cosine_sim(c.embedding, q_embed), reverse=True)
    top = scored[:TOP_K]

    context = "\n\n".join(f"[From: {c.source_title}]\n{c.text}" for c in top)
    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"--- Class resource excerpts ---\n{context}\n\n"
        f"--- Student question ---\n{question}"
    )

    answer, provider = _ask_chat(prompt)

    sources = sorted({c.source_title for c in top[:TOP_SOURCES]})
    return answer, sources, provider
