import pytest

from app.retrieval import search
from app.retrieval.documents import TextPassage


def _passages(*texts):
    return [
        TextPassage(
            item_id=index,
            item_type="text",
            title=f"Entry {index}",
            passage=text,
            source_kind="raw_text",
        )
        for index, text in enumerate(texts, start=1)
    ]


@pytest.fixture()
def corpus(monkeypatch):
    def use(*texts):
        passages = _passages(*texts)
        monkeypatch.setattr(search, "load_passages", lambda **_kw: passages)

    return use


def _by_item(results):
    return {row.passage.item_id: row for row in results}


def test_query_terms_are_idf_weighted_like_document_terms(corpus):
    # Passage 2 matches both query terms; passage 1 only repeats one of them.
    # With a raw-count query vector the single-term passage wins on norm alone.
    corpus(
        "yacht yacht",
        "budget note tax yacht",
        "note tax tax yacht",
        "tax car gym car",
    )

    results = search.search_passages("note yacht", min_score=0.0)

    assert results[0].passage.item_id == 2


def test_unknown_query_terms_do_not_dilute_semantic_score(corpus):
    corpus(
        "renew car insurance",
        "buy groceries",
    )

    plain = _by_item(search.search_passages("insurance", min_score=0.0))
    padded = _by_item(
        search.search_passages("insurance zzzqqq xylophonic", min_score=0.0)
    )

    assert plain[1].semantic_score == pytest.approx(padded[1].semantic_score)


def test_semantic_score_stays_within_unit_interval(corpus):
    corpus("renew car insurance", "renew car insurance renew car insurance")

    for row in search.search_passages("renew car insurance", min_score=0.0):
        assert 0.0 <= row.semantic_score <= 1.0 + 1e-9


def test_query_with_no_known_terms_scores_zero(corpus):
    corpus("renew car insurance")

    results = search.search_passages("zzzqqq", min_score=0.0)

    assert all(row.semantic_score == 0.0 for row in results)


def test_embedding_scorer_finds_paraphrase_without_shared_words(corpus, monkeypatch):
    import numpy as np

    from app.retrieval import embeddings

    corpus("Vet checkup for Max on Tuesday", "Buy oat milk and coffee beans")
    vectors = {
        "Entry 1 Vet checkup for Max on Tuesday": np.array([1.0, 0.0]),
        "Entry 2 Buy oat milk and coffee beans": np.array([0.0, 1.0]),
    }
    monkeypatch.setattr(
        embeddings, "embed_passages", lambda texts: [vectors[t] for t in texts]
    )
    monkeypatch.setattr(
        embeddings, "embed_query", lambda _q: np.array([0.95, 0.31225])
    )

    results = search.search_passages("pet", min_score=0.0)

    assert results[0].passage.item_id == 1
    assert results[0].semantic_score > results[1].semantic_score
    assert results[0].keyword_score == 0.0


def test_search_falls_back_to_tfidf_when_embeddings_unavailable(corpus, monkeypatch):
    from app.retrieval import embeddings

    corpus("renew car insurance", "buy groceries")
    monkeypatch.setattr(embeddings, "embed_passages", lambda _texts: None)

    results = search.search_passages("insurance", min_score=0.0)

    assert results[0].passage.item_id == 1
    assert results[0].semantic_score > 0


def test_embedding_similarity_is_rescaled_to_unit_interval():
    import numpy as np

    from app.retrieval import embeddings

    a = np.array([1.0, 0.0])
    assert embeddings.similarity(a, np.array([1.0, 0.0])) == pytest.approx(1.0)
    assert embeddings.similarity(a, np.array([0.0, 1.0])) == 0.0
    mid = embeddings.similarity(a, np.array([0.7, 0.714]))
    assert 0.0 < mid < 1.0


def test_embeddings_disabled_via_env(monkeypatch):
    from app.retrieval import embeddings

    monkeypatch.setenv("LIFE_INBOX_DISABLE_EMBEDDINGS", "1")

    assert embeddings.embed_passages(["hello"]) is None
    assert embeddings.embed_query("hello") is None
