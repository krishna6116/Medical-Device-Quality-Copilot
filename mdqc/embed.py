"""Embed every report text with bge-small-en-v1.5 on CPU (free, local).

Run:  python -m mdqc.embed            -> data/processed/embeddings_bge_small.npy (float16) + _keys.txt
      (git-ignored; ~120 MB; resumes from finished chunks)

What an embedding is: a list of 384 numbers that places a text in a 'meaning space', so texts about the
same thing (e.g. 'cannula bent' and 'kinked cannula') land close together even with different words.
Cosine similarity between two embeddings measures that closeness. Vectors are L2-normalised, so the
cosine similarity is just a dot product.

Settings (fixed, not tuned): max 256 tokens per text (the event description comes first in the report
text, see mdqc/textprep.py), batch 64, normalise_embeddings=True, one CPU thread pool as torch decides.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv

from mdqc.textprep import load_texts

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_TOKENS, BATCH, CHUNK = 256, 64, 10000


def load_model():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    model.max_seq_length = MAX_TOKENS
    return model


def model_revision(model) -> str:
    """The exact Hugging Face commit of the downloaded model (recorded with every result)."""
    try:
        cfg = model[0].auto_model.config
        found = getattr(cfg, "_commit_hash", None)
        if found:
            return found
        from huggingface_hub import scan_cache_dir  # fall back to the local cache: .../snapshots/<commit>
        for repo in scan_cache_dir().repos:
            if repo.repo_id == MODEL_NAME:
                return sorted(r.commit_hash for r in repo.revisions)[-1]
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def encode(model, texts: list[str], query: bool = False) -> np.ndarray:
    prefix = QUERY_PREFIX if query else ""
    return model.encode([prefix + t for t in texts], batch_size=BATCH, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False).astype(np.float32)


def main() -> None:
    load_dotenv(ROOT / ".env")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        texts = load_texts(con)
    keys = sorted(texts)
    (OUT_DIR / "embeddings_bge_small_keys.txt").write_text("\n".join(keys) + "\n", encoding="utf-8")
    model = load_model()
    print(f"model {MODEL_NAME} revision {model_revision(model)}; {len(keys):,} reports", flush=True)
    parts = []
    t0 = time.monotonic()
    for start in range(0, len(keys), CHUNK):
        part = OUT_DIR / f"emb_chunk_{start:06d}.npy"
        if not part.exists():
            np.save(part, encode(model, [texts[k] for k in keys[start:start + CHUNK]]).astype(np.float16))
        parts.append(part)
        done = min(start + CHUNK, len(keys))
        print(f"  {done:,}/{len(keys):,} ({time.monotonic() - t0:.0f}s)", flush=True)
    emb = np.concatenate([np.load(p) for p in parts])
    np.save(OUT_DIR / "embeddings_bge_small.npy", emb)
    for p in parts:
        p.unlink()
    (OUT_DIR / "embeddings_bge_small_meta.txt").write_text(
        f"model={MODEL_NAME}\nrevision={model_revision(model)}\nmax_tokens={MAX_TOKENS}\nrows={len(keys)}\n", encoding="utf-8")
    print(f"done: {emb.shape} in {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
