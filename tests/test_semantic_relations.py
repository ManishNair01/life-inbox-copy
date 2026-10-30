"""Related-item detection: semantic when embeddings exist, lexical otherwise."""

import numpy as np
import pytest

from app import similarity
from app.retrieval import embeddings
from tests.test_api import client  # noqa: F401  (shared app fixture)


def _items(*texts):
    return [{"id": i + 1, "title": "", "raw_text": t} for i, t in enumerate(texts)]


def _fake_vectors(monkeypatch, mapping):
    def embed(texts):
        # Stored items may carry a generated title, so match by containment.
        def vector(text):
            key = max((k for k in mapping if k.strip() in text), key=len)
            return np.asarray(mapping[key], dtype=np.float32)

        return [vector(t) for t in texts]

    monkeypatch.setattr(embeddings, "embed_passages", embed)


def test_semantic_relation_links_paraphrases_without_shared_words(monkeypatch):
    _fake_vectors(
        monkeypatch,
        {
            "Mom's birthday is on 12 June, order flowers.": [1.0, 0.0],
            "Get a bouquet for Mum before her big day.": [0.9, 0.436],
            "Cancel the gym membership.": [0.0, 1.0],
        },
    )

    relations = similarity.find_item_relations(
        _items(
            "Mom's birthday is on 12 June, order flowers.",
            "Get a bouquet for Mum before her big day.",
            "Cancel the gym membership.",
        )
    )

    assert [(r["item_id_a"], r["item_id_b"]) for r in relations] == [(1, 2)]
    assert relations[0]["relation_type"] == "related"
    assert relations[0]["method"] == "semantic"
    assert float(relations[0]["score"]) >= similarity.SEMANTIC_RELATED_THRESHOLD


def test_semantic_scoring_replaces_lexical_related_but_keeps_duplicates(monkeypatch):
    # Lexically "related" (shared words) but semantically unrelated: dropped.
    # Exact duplicate: still reported as a lexical duplicate.
    _fake_vectors(
        monkeypatch,
        {
            "Read the Rust book on ownership": [1.0, 0.0, 0.0],
            "Scrape the rust off the garden gate": [0.0, 1.0, 0.0],
            "Call the plumber": [0.0, 0.0, 1.0],
        },
    )

    relations = similarity.find_item_relations(
        _items(
            "Read the Rust book on ownership",
            "Scrape the rust off the garden gate",
            "Call the plumber",
            "Call the plumber ",
        )
    )

    assert [(r["item_id_a"], r["item_id_b"], r["relation_type"], r["method"])
            for r in relations] == [(3, 4, "duplicate", "lexical")]


def test_falls_back_to_lexical_related_when_embeddings_unavailable(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_passages", lambda _texts: None)

    relations = similarity.find_item_relations(
        _items("Renew car insurance soon", "Renew the car insurance soon")
    )

    assert relations
    assert all(r["method"] == "lexical" for r in relations)


def test_single_item_needs_no_embeddings(monkeypatch):
    def boom(_texts):
        raise AssertionError("must not embed fewer than two items")

    monkeypatch.setattr(embeddings, "embed_passages", boom)

    assert similarity.find_item_relations(_items("only one")) == []


def test_pairwise_similarity_matches_scalar_similarity():
    a, b = np.array([1.0, 0.0]), np.array([0.7, 0.714])
    b = b / np.linalg.norm(b)

    matrix = embeddings.pairwise_similarity([a, b])

    assert matrix[0, 1] == pytest.approx(embeddings.similarity(a, b))
    assert matrix[0, 0] == pytest.approx(1.0)


def test_analyze_persists_and_exposes_relation_method(client, monkeypatch):
    texts = {
        "Order flowers for Mom": [1.0, 0.0],
        "Get a bouquet for Mum": [0.92, 0.39],
        "Pay the electricity bill": [0.0, 1.0],
    }
    _fake_vectors(monkeypatch, texts)
    for text in texts:
        client.post("/api/items", json={"raw_text": text})

    client.post("/api/analyze")
    relations = client.get("/api/relations").json()

    assert len(relations) == 1
    assert relations[0]["method"] == "semantic"
    assert {relations[0]["item_id_a"], relations[0]["item_id_b"]} == {1, 2}
    dismissed = client.post(f"/api/relations/{relations[0]['id']}/dismiss").json()
    assert dismissed["method"] == "semantic"

    client.post("/api/analyze")
    assert client.get("/api/relations").json() == []


def test_title_repeating_the_body_is_not_embedded_twice(monkeypatch):
    seen = []

    def capture(texts):
        seen.extend(texts)
        return [np.asarray([1.0, 0.0], dtype=np.float32) for _ in texts]

    monkeypatch.setattr(embeddings, "embed_passages", capture)

    similarity.find_item_relations(
        [
            {"id": 1, "title": "Call the bank", "raw_text": "Call the bank"},
            {"id": 2, "title": "Bank", "raw_text": "Call the bank about fees"},
            {"id": 3, "title": "Receipt", "raw_text": "Taxi to the airport"},
        ]
    )

    assert seen == [
        "Call the bank",  # identical title dropped
        "Call the bank about fees",  # title contained in body, dropped
        "Receipt Taxi to the airport",  # title adds information, kept
    ]
