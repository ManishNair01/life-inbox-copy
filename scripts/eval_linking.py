"""Evaluate note-to-note similarity scorers against labelled link pairs.

Usage (from the project root):

    python -m scripts.eval_linking
    python -m scripts.eval_linking --csv tests/fixtures/linking_eval_notes.csv --top 8

Reads the labelled notes CSV, scores every pair of notes with each scorer
(local embeddings and the TF-IDF fallback), and reports how well each one
separates pairs that should link from pairs that should not. It touches no
database and calls no external API.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import re
from collections import Counter
from pathlib import Path

from app.retrieval import embeddings
from app.retrieval.documents import _tokenize
from app.retrieval.search import _cosine, _idf
from app.similarity import similarity_score

DEFAULT_CSV = Path("tests/fixtures/linking_eval_notes.csv")
THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


def load_notes(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def label_pairs(notes: list[dict]) -> dict[tuple[int, int], str]:
    """Map (i, j) index pairs to 'positive', 'hard_negative' or 'negative'."""
    labels: dict[tuple[int, int], str] = {}
    for i, j in itertools.combinations(range(len(notes)), 2):
        a, b = notes[i], notes[j]
        if a["group_id"] == b["group_id"]:
            labels[(i, j)] = "positive"
        elif (
            a["hard_negative_group"] == b["group_id"]
            or b["hard_negative_group"] == a["group_id"]
        ):
            labels[(i, j)] = "hard_negative"
        else:
            labels[(i, j)] = "negative"
    return labels


def tfidf_scores(notes: list[dict]) -> dict[tuple[int, int], float]:
    tokens = [_tokenize(n["text"]) for n in notes]
    df: Counter[str] = Counter()
    for toks in tokens:
        df.update(set(toks))
    size = len(notes)
    vectors = []
    for toks in tokens:
        vec: Counter[str] = Counter()
        for term, count in Counter(toks).items():
            vec[term] = count * _idf(df[term], size)
        vectors.append(vec)
    return {
        (i, j): _cosine(vectors[i], vectors[j])
        for i, j in itertools.combinations(range(size), 2)
    }


def embedding_scores(notes: list[dict]) -> dict[tuple[int, int], float] | None:
    vectors = embeddings.embed_passages([n["text"] for n in notes])
    if vectors is None:
        return None
    return {
        (i, j): embeddings.similarity(vectors[i], vectors[j])
        for i, j in itertools.combinations(range(len(notes)), 2)
    }


def char_ngram_scores(
    notes: list[dict], sizes: tuple[int, ...] = (3, 4, 5)
) -> dict[tuple[int, int], float]:
    """TF-IDF cosine over character n-grams (robust to typos and word forms)."""
    grams = []
    for note in notes:
        text = " ".join(_tokenize(note["text"]))
        padded = f" {text} "
        grams.append(
            [padded[k : k + n] for n in sizes for k in range(len(padded) - n + 1)]
        )
    df: Counter[str] = Counter()
    for g in grams:
        df.update(set(g))
    size = len(notes)
    vectors = []
    for g in grams:
        vec: Counter[str] = Counter()
        for gram, count in Counter(g).items():
            vec[gram] = count * _idf(df[gram], size)
        vectors.append(vec)
    return {
        (i, j): _cosine(vectors[i], vectors[j])
        for i, j in itertools.combinations(range(size), 2)
    }


ENTITY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z]*(?:'s)?")
ENTITY_STOPWORDS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "nov", "dec",
}
ENTITY_MAX_DOC_FREQ = 4


def note_entities(notes: list[dict]) -> list[set[str]]:
    """Rare proper nouns per note, derived from the corpus.

    A capitalised word counts only if it is never seen in lowercase (so "Rust"
    the language is an entity but "rust" on a gate is not) and, when it opens a
    note, only if it is capitalised mid-sentence somewhere else. Weekdays and
    months are ignored (numbers too: times and dates collide), and anything in more than a few notes is too common
    to be a useful link.
    """
    tokenised = [
        [t.removesuffix("'s") for t in ENTITY_TOKEN_RE.findall(n["text"])]
        for n in notes
    ]
    lowercase_seen = {t for toks in tokenised for t in toks if t.islower()}
    capitalised_mid = {
        t.lower() for toks in tokenised for t in toks[1:] if t[:1].isupper()
    }
    entities: list[set[str]] = []
    for toks in tokenised:
        found = set()
        for idx, tok in enumerate(toks):
            low = tok.lower()
            if low in ENTITY_STOPWORDS:
                continue
            if tok[0].isupper() and low not in lowercase_seen:
                if idx > 0 or low in capitalised_mid:
                    found.add(low)
        entities.append(found)
    df: Counter[str] = Counter()
    for found in entities:
        df.update(found)
    return [{e for e in found if df[e] <= ENTITY_MAX_DOC_FREQ} for found in entities]


def entity_boosted(
    base: dict[tuple[int, int], float],
    notes: list[dict],
    bonus: float,
) -> dict[tuple[int, int], float]:
    entities = note_entities(notes)
    return {
        (i, j): min(1.0, score + (bonus if entities[i] & entities[j] else 0.0))
        for (i, j), score in base.items()
    }


def app_lexical_scores(notes: list[dict]) -> dict[tuple[int, int], float]:
    """The scorer the app shipped with (app/similarity.py): the baseline."""
    return {
        (i, j): similarity_score(notes[i]["text"], notes[j]["text"])
        for i, j in itertools.combinations(range(len(notes)), 2)
    }


RARE_WORD_MIN_LEN = 4
RARE_WORD_MAX_DOC_FREQ = 3


def rare_word_boosted(
    base: dict[tuple[int, int], float],
    notes: list[dict],
    bonus: float,
) -> dict[tuple[int, int], float]:
    """Case-insensitive variant of the entity bonus: any shared rare word."""
    word_sets = [
        {w for w in _tokenize(n["text"]) if len(w) >= RARE_WORD_MIN_LEN}
        for n in notes
    ]
    df: Counter[str] = Counter()
    for words in word_sets:
        df.update(words)
    rare = [{w for w in words if df[w] <= RARE_WORD_MAX_DOC_FREQ} for words in word_sets]
    return {
        (i, j): min(1.0, score + (bonus if rare[i] & rare[j] else 0.0))
        for (i, j), score in base.items()
    }


def blend(
    a: dict[tuple[int, int], float],
    b: dict[tuple[int, int], float],
    weight_b: float,
) -> dict[tuple[int, int], float]:
    return {pair: (1 - weight_b) * a[pair] + weight_b * b[pair] for pair in a}


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability a random positive pair outscores a random negative pair."""
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def prf(
    scores: dict[tuple[int, int], float],
    labels: dict[tuple[int, int], str],
    threshold: float,
) -> tuple[float, float, float, int, int]:
    tp = fp = fn = 0
    for pair, label in labels.items():
        predicted = scores[pair] >= threshold
        if label == "positive":
            tp += predicted
            fn += not predicted
        else:
            fp += predicted
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, tp, fp


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(
    scores: dict[tuple[int, int], float],
    labels: dict[tuple[int, int], str],
) -> dict:
    by_label: dict[str, list[float]] = {"positive": [], "hard_negative": [], "negative": []}
    for pair, label in labels.items():
        by_label[label].append(scores[pair])
    best = max(THRESHOLDS, key=lambda t: prf(scores, labels, t)[2])
    precision, recall, f1, tp, fp = prf(scores, labels, best)
    return {
        "auc_all": auc(by_label["positive"], by_label["hard_negative"] + by_label["negative"]),
        "auc_hard": auc(by_label["positive"], by_label["hard_negative"]),
        "threshold": best,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "links": tp,
        "false_links": fp,
    }


def print_summary(rows: list[tuple[str, dict]], total_positive: int) -> None:
    print(
        f"\n{'scorer':<44} {'AUC':>6} {'AUCh':>6} {'thr':>5} "
        f"{'prec':>6} {'recall':>6} {'F1':>6}  links  false"
    )
    for name, m in rows:
        print(
            f"{name:<44} {m['auc_all']:>6.3f} {m['auc_hard']:>6.3f} "
            f"{m['threshold']:>5.2f} {m['precision']:>6.3f} {m['recall']:>6.3f} "
            f"{m['f1']:>6.3f}  {m['links']:>2}/{total_positive:<3} {m['false_links']:>4}"
        )


def report(
    name: str,
    scores: dict[tuple[int, int], float],
    labels: dict[tuple[int, int], str],
    notes: list[dict],
    top: int,
) -> None:
    by_label: dict[str, list[float]] = {"positive": [], "hard_negative": [], "negative": []}
    for pair, label in labels.items():
        by_label[label].append(scores[pair])
    everything_neg = by_label["hard_negative"] + by_label["negative"]

    print(f"\n=== {name} ===")
    print(f"AUC (all negatives):  {auc(by_label['positive'], everything_neg):.3f}")
    print(f"AUC (hard negatives): {auc(by_label['positive'], by_label['hard_negative']):.3f}")
    print(
        "Mean score: "
        f"positive={mean(by_label['positive']):.3f}  "
        f"hard_negative={mean(by_label['hard_negative']):.3f}  "
        f"negative={mean(by_label['negative']):.3f}"
    )

    print("\nthreshold  precision  recall    F1     links  false_links")
    best = max(THRESHOLDS, key=lambda t: prf(scores, labels, t)[2])
    for t in THRESHOLDS:
        p, r, f1, tp, fp = prf(scores, labels, t)
        mark = "  <- best F1" if t == best else ""
        print(f"{t:>8.2f}  {p:>9.3f}  {r:>6.3f}  {f1:>5.3f}  {tp:>5}  {fp:>11}{mark}")

    def show(pair: tuple[int, int]) -> str:
        i, j = pair
        return (
            f"  {scores[pair]:.3f}  [{notes[i]['note_id']}] {notes[i]['text'][:48]}"
            f"  <->  [{notes[j]['note_id']}] {notes[j]['text'][:48]}"
        )

    misses = sorted(
        (p for p, l in labels.items() if l == "positive"), key=lambda p: scores[p]
    )[:top]
    false_links = sorted(
        (p for p, l in labels.items() if l != "positive"),
        key=lambda p: scores[p],
        reverse=True,
    )[:top]
    print(f"\nLowest-scoring true links (would be missed):")
    print("\n".join(show(p) for p in misses))
    print(f"\nHighest-scoring non-links (would be wrongly linked):")
    print("\n".join(show(p) + f"  ({labels[p]})" for p in false_links))


def build_scorers(notes: list[dict]) -> list[tuple[str, dict]]:
    chars = char_ngram_scores(notes)
    scorers = [
        ("0 app baseline (SequenceMatcher/Jaccard)", app_lexical_scores(notes)),
        ("1 word TF-IDF", tfidf_scores(notes)),
        ("2 character 3-5 grams", chars),
    ]
    emb = embedding_scores(notes)
    if emb is None:
        print(
            "\nEmbeddings unavailable (model failed to load or "
            "LIFE_INBOX_DISABLE_EMBEDDINGS is set); embedding rows skipped."
        )
        return scorers
    scorers.append((f"3 embeddings ({embeddings.model_name()})", emb))
    scorers.append(("4 embeddings + 15% character n-grams", blend(emb, chars, 0.15)))
    scorers.append(("4 embeddings + 30% character n-grams", blend(emb, chars, 0.30)))
    for bonus in (0.10, 0.20, 0.30):
        scorers.append(
            (f"5 embeddings + capitalised-entity bonus {bonus:.2f}",
             entity_boosted(emb, notes, bonus))
        )
    for bonus in (0.10, 0.20):
        scorers.append(
            (f"6 embeddings + rare-word bonus {bonus:.2f}",
             rare_word_boosted(emb, notes, bonus))
        )
    return scorers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--top", type=int, default=6, help="examples to list per section")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="one compact row per scorer instead of full per-threshold reports",
    )
    args = parser.parse_args()

    notes = load_notes(args.csv)
    labels = label_pairs(notes)
    counts = Counter(labels.values())
    print(
        f"{len(notes)} notes, {len(labels)} pairs: "
        f"{counts['positive']} should link, "
        f"{counts['hard_negative']} hard negatives, "
        f"{counts['negative']} other non-links"
    )

    scorers = build_scorers(notes)
    if args.summary:
        print_summary(
            [(name, evaluate(scores, labels)) for name, scores in scorers],
            counts["positive"],
        )
        return
    for name, scores in scorers:
        report(name, scores, labels, notes, args.top)


if __name__ == "__main__":
    main()
