"""Duplicate and related-item detection (no vector DB).

Duplicates and near-duplicates are found lexically. "Related" links use local
sentence embeddings when available and fall back to the lexical score
otherwise. See docs/semantic-linking.md for the measurements behind this.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.retrieval import embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Rescaled embedding similarity at or above which two items are "related".
# 0.40 was the best-F1 cutoff on both labelled evaluation sets.
SEMANTIC_RELATED_THRESHOLD = 0.40
_MAX_EMBED_CHARS = 1000


def normalize_text(text: str) -> str:
    return " ".join(_TOKEN_RE.findall((text or "").lower()))


def token_set(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity_score(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    seq = SequenceMatcher(None, left_norm, right_norm).ratio()
    jac = jaccard(token_set(left), token_set(right))
    return max(seq, jac)


def classify_relation(score: float) -> str | None:
    if score >= 0.92:
        return "duplicate"
    if score >= 0.78:
        return "near_duplicate"
    if score >= 0.45:
        return "related"
    return None


def _embedding_text(item: dict) -> str:
    """Text to embed: the body, plus the title only when it adds something.

    Stored items usually have a title identical to their text. Embedding that
    twice inflates similarity between unrelated notes (measured: 4 -> 20 false
    links on the held-out set), so repeated titles are dropped.
    """
    title = (item.get("title") or "").strip()
    body = (item.get("raw_text") or "").strip()
    if not body:
        return title
    if title and normalize_text(title) not in normalize_text(body):
        return f"{title} {body}"
    return body


def _semantic_matrix(texts: list[str]):
    """Pairwise rescaled similarity, or None when embeddings are unavailable."""
    if len(texts) < 2:
        return None
    vectors = embeddings.embed_passages([t[:_MAX_EMBED_CHARS] for t in texts])
    if vectors is None:
        return None
    return embeddings.pairwise_similarity(vectors)


def find_item_relations(items: list[dict]) -> list[dict]:
    """Return undirected relation candidates for inbox items with text.

    Each relation carries a ``method``: ``lexical`` (character/word overlap) or
    ``semantic`` (local embeddings, AI-inferred).
    """
    enriched = []
    for item in items:
        text = " ".join(
            part
            for part in (item.get("title") or "", item.get("raw_text") or "")
            if part
        ).strip()
        if text:
            enriched.append({**item, "_cmp": text})

    semantic = _semantic_matrix([_embedding_text(item) for item in enriched])

    relations = []
    for index, left in enumerate(enriched):
        for offset, right in enumerate(enriched[index + 1 :], start=index + 1):
            score = similarity_score(left["_cmp"], right["_cmp"])
            relation_type = classify_relation(score)
            method = "lexical"
            if relation_type in (None, "related") and semantic is not None:
                # Lexical overlap is a poor signal for "related"; trust the
                # embedding score whenever it is available.
                score = float(semantic[index, offset])
                relation_type = (
                    "related" if score >= SEMANTIC_RELATED_THRESHOLD else None
                )
                method = "semantic"
            if not relation_type:
                continue
            a, b = sorted((left["id"], right["id"]))
            relations.append(
                {
                    "item_id_a": a,
                    "item_id_b": b,
                    "relation_type": relation_type,
                    "score": f"{score:.4f}",
                    "method": method,
                }
            )
    return relations
