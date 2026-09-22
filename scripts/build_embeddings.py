#!/usr/bin/env python3
"""
Offline embedding builder for the Ask AI page.

Run this locally whenever you add, remove, or change a resource file, then
commit the resulting resources/embeddings.npz. The deployed app loads that
file at startup instead of computing embeddings itself on every cold start.

Embeddings are computed locally with fastembed (a small ONNX model) — no
API key, no account, no usage quota, no internet dependency beyond a
one-time model download the first time you run this.

Usage:

    python scripts/build_embeddings.py

This script has no Streamlit dependency and does not read
.streamlit/secrets.toml, so it can be run from a plain terminal or a CI job.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))

from utils.resource_extraction import (  # noqa: E402
    EMBEDDINGS_PATH,
    MANIFEST_PATH,
    iter_source_chunks,
    load_manifest,
    manifest_hash,
)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


def main() -> None:
    try:
        from fastembed import TextEmbedding
    except ImportError:
        print(
            "fastembed isn't installed. Run:\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    if not MANIFEST_PATH.exists():
        print(f"No manifest found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    manifest_json = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = load_manifest()
    source_chunks = iter_source_chunks(manifest)

    if not source_chunks:
        print("No local resource text found to embed — nothing to do.")
        sys.exit(0)

    texts = [c[0] for c in source_chunks]
    titles = [c[1] for c in source_chunks]
    topics = [c[2] for c in source_chunks]

    print(f"Loading local embedding model ({EMBEDDING_MODEL})…")
    print("(First run downloads it, ~130MB — cached locally after that.)")
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)

    print(f"Embedding {len(texts)} chunks from {len(manifest)} manifest entries…")
    embeddings = np.array(list(embedder.embed(texts)), dtype=np.float32)

    EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Plain numpy unicode arrays (not dtype=object) so the app can load this
    # file with allow_pickle=False — no pickle involved, safer to distribute.
    np.savez_compressed(
        EMBEDDINGS_PATH,
        embeddings=embeddings,
        texts=np.array(texts),
        titles=np.array(titles),
        topics=np.array(topics),
        manifest_hash=np.array(manifest_hash(manifest_json)),
        model=np.array(EMBEDDING_MODEL),
    )

    print(f"Saved {len(texts)} embeddings to {EMBEDDINGS_PATH}")
    print("Commit this file to git so the deployed app can load it directly.")


if __name__ == "__main__":
    main()
