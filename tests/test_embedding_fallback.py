import numpy as np
import pytest

from app import similarity
from app.retrieval import embeddings, search


@pytest.fixture
def enabled(monkeypatch):
    """Re-enable embeddings with a fresh module state; restore afterwards."""
    monkeypatch.delenv("LIFE_INBOX_DISABLE_EMBEDDINGS", raising=False)
    monkeypatch.setattr(embeddings, "_model", None)
    monkeypatch.setattr(embeddings, "_model_name", None)
    monkeypatch.setattr(embeddings, "_load_failed", False)
    monkeypatch.setattr(embeddings, "_cache", {})


def _break_fastembed(monkeypatch):
    import fastembed

    calls = []

    def boom(name):
        calls.append(name)
        raise OSError("no network, model cannot be downloaded")

    monkeypatch.setattr(fastembed, "TextEmbedding", boom)
    return calls


def test_disabled_env_returns_none(monkeypatch):
    assert embeddings.embed_passages(["a"]) is None
    assert embeddings.embed_query("a") is None


def test_model_load_failure_returns_none_and_is_not_retried(enabled, monkeypatch):
    calls = _break_fastembed(monkeypatch)

    assert embeddings.embed_passages(["a", "b"]) is None
    assert embeddings.embed_query("a") is None
    assert embeddings.embed_passages(["c"]) is None
    assert len(calls) == 1


def test_embedding_runtime_error_returns_none(enabled, monkeypatch):
    class Flaky:
        def passage_embed(self, texts):
            raise RuntimeError("onnx failure")

        def query_embed(self, texts):
            raise RuntimeError("onnx failure")

    monkeypatch.setattr(embeddings, "_load_model", lambda: Flaky())
    assert embeddings.embed_passages(["a"]) is None
    assert embeddings.embed_query("a") is None


def test_search_uses_tfidf_when_model_unavailable(enabled, monkeypatch):
    _break_fastembed(monkeypatch)
    passages = [
        search.TextPassage(
            item_id=1, item_type="note", title="Dentist",
            passage="dentist appointment on friday", source_kind="raw_text",
        ),
        search.TextPassage(
            item_id=2, item_type="note", title="Groceries",
            passage="buy milk and eggs", source_kind="raw_text",
        ),
    ]
    monkeypatch.setattr(search, "load_passages", lambda **kw: passages)

    results = search.search_passages("dentist friday", limit=5, min_score=0.05)

    assert results
    assert results[0].passage.item_id == 1


def test_relations_fall_back_to_lexical_when_model_unavailable(enabled, monkeypatch):
    _break_fastembed(monkeypatch)
    items = [
        {"id": 1, "title": "Pay rent", "raw_text": "Pay the rent by the first of the month"},
        {"id": 2, "title": "Pay rent", "raw_text": "Pay the rent by the first of the month"},
        {"id": 3, "title": "Garden", "raw_text": "Plant tomatoes along the south fence"},
    ]

    relations = similarity.find_item_relations(items)

    assert relations
    assert {r["method"] for r in relations} == {"lexical"}
    assert all({r["item_id_a"], r["item_id_b"]} == {1, 2} for r in relations)


def test_pairwise_similarity_maps_identical_to_one_and_orthogonal_to_zero():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    matrix = embeddings.pairwise_similarity([a, b])
    assert matrix[0, 0] == pytest.approx(1.0)
    assert matrix[0, 1] == 0.0
