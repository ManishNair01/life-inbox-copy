"""Local open-source sentence embeddings for retrieval (no API, no quota).

Uses fastembed (ONNX) with a small retrieval-tuned model. Everything degrades
gracefully: if the model cannot be loaded, callers get ``None`` and fall back
to the TF-IDF scorer in ``search.py``.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# bge-small cosine for unrelated short English text sits around 0.45; rescale
# so "unrelated" maps to ~0 and "same meaning" to ~1.
SIMILARITY_FLOOR = 0.45
_MAX_CACHED_TEXTS = 20000

_lock = threading.Lock()
# Guards _cache only. Kept separate from _lock so a slow model load never blocks
# cache reads; never held while the model runs.
_cache_lock = threading.Lock()
_model = None
_model_name: Optional[str] = None
_load_failed = False
_cache: dict[tuple[str, str], np.ndarray] = {}


def _disabled() -> bool:
    return os.getenv("LIFE_INBOX_DISABLE_EMBEDDINGS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def model_name() -> str:
    return os.getenv("LIFE_INBOX_EMBEDDING_MODEL", "").strip() or DEFAULT_MODEL


def status() -> str:
    """Current state without loading anything (safe for health checks).

    disabled: turned off by env. ready: model loaded. unavailable: loading
    failed, so callers use the fallbacks. not_loaded: not needed yet.
    """
    if _disabled():
        return "disabled"
    if _model is not None:
        return "ready"
    if _load_failed:
        return "unavailable"
    return "not_loaded"


def _load_model():
    """Load (once) the embedding model, or return None if unavailable."""
    global _model, _model_name, _load_failed
    if _disabled():
        return None
    name = model_name()
    with _lock:
        if _model is not None and _model_name == name:
            return _model
        if _load_failed and _model_name == name:
            return None
        try:
            from fastembed import TextEmbedding

            _model = TextEmbedding(name)
            _model_name = name
            _load_failed = False
            with _cache_lock:
                _cache.clear()
        except Exception:
            logger.warning(
                "Embedding model %s unavailable; using TF-IDF fallback",
                name,
                exc_info=True,
            )
            _model = None
            _model_name = name
            _load_failed = True
            return None
    return _model


def _unit(vector) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr if norm == 0 else arr / norm


def embed_passages(texts: list[str]) -> Optional[list[np.ndarray]]:
    """Unit vectors for passages, cached by text. None if embeddings are off."""
    model = _load_model()
    if model is None:
        return None
    key = _model_name or model_name()
    try:
        # Work from a local snapshot: another request may clear the shared
        # cache at any point, and a lookup must never depend on it afterwards.
        with _cache_lock:
            found = {
                t: _cache[(key, t)]
                for t in dict.fromkeys(texts)
                if (key, t) in _cache
            }
        missing = [t for t in dict.fromkeys(texts) if t not in found]
        if missing:
            fresh = {
                text: _unit(vec)
                for text, vec in zip(missing, model.passage_embed(missing))
            }
            found.update(fresh)
            with _cache_lock:
                if len(_cache) + len(fresh) > _MAX_CACHED_TEXTS:
                    _cache.clear()
                for text, vec in fresh.items():
                    _cache[(key, text)] = vec
        return [found[t] for t in texts]
    except Exception:
        logger.warning("Embedding passages failed; using fallback", exc_info=True)
        return None


def embed_query(query: str) -> Optional[np.ndarray]:
    model = _load_model()
    if model is None:
        return None
    try:
        return _unit(next(iter(model.query_embed([query]))))
    except Exception:
        logger.warning("Embedding query failed; using fallback", exc_info=True)
        return None


def similarity(query_vec: np.ndarray, passage_vec: np.ndarray) -> float:
    """Cosine rescaled to 0..1 relative to SIMILARITY_FLOOR."""
    raw = float(np.dot(query_vec, passage_vec))
    return min(1.0, max(0.0, (raw - SIMILARITY_FLOOR) / (1.0 - SIMILARITY_FLOOR)))


def pairwise_similarity(vectors: list[np.ndarray]) -> np.ndarray:
    """Matrix of ``similarity`` for every pair of unit vectors (n x n)."""
    matrix = np.vstack(vectors)
    raw = matrix @ matrix.T
    return np.clip((raw - SIMILARITY_FLOOR) / (1.0 - SIMILARITY_FLOOR), 0.0, 1.0)
