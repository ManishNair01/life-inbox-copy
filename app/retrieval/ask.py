"""Grounded answers with source citations."""

from __future__ import annotations

from typing import Optional

from app.retrieval.documents import passages_to_dict
from app.retrieval.search import RankedPassage, search_passages

INSUFFICIENT = (
    "I do not have enough matching information in your inbox to answer that."
)


def _citation_id(item_id: int, index: int) -> str:
    return f"item-{item_id}-{index}"


def build_grounded_answer(
    question: str,
    *,
    limit: int = 5,
    item_type: Optional[str] = None,
) -> dict:
    ranked = search_passages(
        question,
        limit=limit,
        item_type=item_type,
        min_score=0.15,
    )
    if not ranked:
        return {
            "question": question,
            "answer": INSUFFICIENT,
            "confidence": "insufficient",
            "citations": [],
            "answer_kind": "model_generated",
        }

    top = ranked[0]
    if top.score < 0.2 and top.keyword_score < 0.25:
        return {
            "question": question,
            "answer": INSUFFICIENT,
            "confidence": "insufficient",
            "citations": [],
            "answer_kind": "model_generated",
        }

    citations = []
    seen: set[tuple[int, str]] = set()
    for idx, row in enumerate(ranked, start=1):
        key = (row.passage.item_id, row.passage.passage[:80])
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "id": _citation_id(row.passage.item_id, idx),
                "item_id": row.passage.item_id,
                "item_type": row.passage.item_type,
                "title": row.passage.title,
                "excerpt": row.passage.passage[:320],
                "source_kind": row.passage.source_kind,
                "preview_url": row.passage.preview_url,
                "score": round(row.score, 4),
            }
        )

    lead = ranked[0].passage
    supporting = ranked[1:3]
    parts = [
        f"Based on your inbox item “{lead.title}” ({lead.source_kind}): "
        f"{lead.passage[:280]}{'…' if len(lead.passage) > 280 else ''}"
    ]
    for row in supporting:
        parts.append(
            f"Also related: “{row.passage.title}” — {row.passage.passage[:160]}"
            f"{'…' if len(row.passage.passage) > 160 else ''}"
        )
    answer = " ".join(parts)

    confidence = "high" if top.score >= 0.45 else "medium"

    return {
        "question": question,
        "answer": answer,
        "confidence": confidence,
        "citations": citations,
        "answer_kind": "grounded_summary",
    }
