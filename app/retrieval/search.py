"""Keyword + lightweight semantic retrieval (local, no vector DB)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from app.retrieval import embeddings
from app.retrieval.documents import TextPassage, _tokenize, load_passages

# Keyword vs. semantic weight. The embedding scorer understands paraphrase, so
# keywords are only a booster for exact names/numbers; the TF-IDF scorer needs
# keywords to carry more of the score.
KEYWORD_WEIGHT_EMBEDDING = 0.30
KEYWORD_WEIGHT_TFIDF = 0.55


@dataclass
class RankedPassage:
    score: float
    passage: TextPassage
    keyword_score: float
    semantic_score: float


def _idf(doc_freq: int, corpus_size: int) -> float:
    return math.log((1 + corpus_size) / (1 + doc_freq)) + 1.0


def _build_tfidf_vectors(
    passages: list[TextPassage],
) -> tuple[list[Counter[str]], dict[str, int], int]:
    doc_tokens = [_tokenize(f"{p.title} {p.passage}") for p in passages]
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))
    corpus_size = len(passages)
    vectors: list[Counter[str]] = []
    for tokens in doc_tokens:
        tf = Counter(tokens)
        vec: Counter[str] = Counter()
        for term, count in tf.items():
            vec[term] = count * _idf(df[term], corpus_size)
        vectors.append(vec)
    return vectors, dict(df), corpus_size


def _build_query_vector(
    query_tokens: list[str],
    df: dict[str, int],
    corpus_size: int,
) -> Counter[str]:
    """TF-IDF weight the query in the same space as the document vectors.

    Terms absent from every passage can never match, so they are dropped
    rather than inflating the query norm and uniformly deflating every score.
    """
    vec: Counter[str] = Counter()
    for token, count in Counter(query_tokens).items():
        if token in df:
            vec[token] = count * _idf(df[token], corpus_size)
    return vec


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b.get(t, 0) for t in a)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keyword_score(query_tokens: list[str], passage: TextPassage) -> float:
    if not query_tokens:
        return 0.0
    hay = f"{passage.title} {passage.passage}".lower()
    hits = sum(1 for token in query_tokens if token in hay)
    return hits / len(query_tokens)


def search_passages(
    query: str,
    *,
    limit: int = 8,
    item_type: Optional[str] = None,
    processing_status: Optional[str] = "ready",
    min_score: float = 0.12,
) -> list[RankedPassage]:
    q = query.strip()
    if not q:
        return []
    query_tokens = _tokenize(q)
    passages = load_passages(
        item_type=item_type,
        processing_status=processing_status,
    )
    if not passages:
        return []

    passage_texts = [f"{p.title} {p.passage}" for p in passages]
    embedded = embeddings.embed_passages(passage_texts)
    query_embedding = embeddings.embed_query(q) if embedded is not None else None

    if embedded is not None and query_embedding is not None:
        semantic = [
            embeddings.similarity(query_embedding, vec) for vec in embedded
        ]
        keyword_weight = KEYWORD_WEIGHT_EMBEDDING
    else:
        vectors, df, corpus_size = _build_tfidf_vectors(passages)
        query_vec = _build_query_vector(query_tokens, df, corpus_size)
        semantic = [_cosine(query_vec, vec) for vec in vectors]
        keyword_weight = KEYWORD_WEIGHT_TFIDF

    ranked: list[RankedPassage] = []
    for passage, sem in zip(passages, semantic):
        kw = _keyword_score(query_tokens, passage)
        score = keyword_weight * kw + (1.0 - keyword_weight) * sem
        if score < min_score:
            continue
        ranked.append(
            RankedPassage(
                score=score,
                passage=passage,
                keyword_score=kw,
                semantic_score=sem,
            )
        )
    ranked.sort(key=lambda row: row.score, reverse=True)
    return ranked[:limit]
