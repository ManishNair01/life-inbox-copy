# Semantic linking between entries

How Life Inbox decides that two notes are related, how that decision was
improved, and the measurements behind each step.

**Result:** on a hand-labelled set of 52 notes, the app's original scorer found
2 of 24 true links (F1 0.121). Local sentence embeddings find 12 of 24 with
2 false links (F1 0.632). On a second, held-out set of 47 notes the same
cutoff finds 11 of 17 with 4 false links (F1 0.688), against 2 of 17 before
(F1 0.182).

## What the feature does

`POST /api/analyze` refreshes the `item_relations` table. Each row links two
inbox items and records:

| Field | Meaning |
| --- | --- |
| `relation_type` | `duplicate`, `near_duplicate` or `related` |
| `score` | The score that produced the link |
| `method` | `lexical` (word/character overlap) or `semantic` (local embeddings, AI-inferred) |
| `dismissed` | Set by the user; dismissed pairs never come back |

Duplicates and near-duplicates are still detected lexically. `related` links
use local embeddings (`BAAI/bge-small-en-v1.5` through `fastembed`) with a
rescaled-similarity cutoff of **0.40**
(`SEMANTIC_RELATED_THRESHOLD` in [app/similarity.py](../app/similarity.py)).
If the embedding model cannot load, `related` falls back to the original
lexical rule, so the app still works offline.

`GET /api/relations` and the dashboard's "Related Items" list return the
`method` and `score`; the UI labels each link "AI-inferred" or "text match".
This keeps AI-inferred links distinguishable, as the data-safety rules in
[AGENTS.md](../AGENTS.md) require.

## How it was measured

Two labelled note sets live in [tests/fixtures/](../tests/fixtures/):

| File | Notes | True link pairs | Hard-negative pairs | Style |
| --- | --- | --- | --- | --- |
| `linking_eval_notes.csv` | 52 | 24 | 17 | Mostly capitalised, used to develop and tune |
| `linking_eval_notes_heldout.csv` | 47 | 17 | 17 | Different names, mostly lowercase and messy, written after the tuning, not tuned against |

Each row has a `group_id`. Notes in the same group should link; notes in
different groups should not. Rows with a `hard_negative_group` are decoys that
share words with that group but mean something different (for example "rust on
the garden gate" against "the Rust book", or "Atlas of the Himalayas" against
"Project Atlas"). Singletons should link to nothing.

Run the comparison yourself:

```bash
python -m scripts.eval_linking --summary                      # first set
python -m scripts.eval_linking --summary --csv tests/fixtures/linking_eval_notes_heldout.csv
python -m scripts.eval_linking --top 8                        # per-threshold detail and worst cases
```

The script scores every pair of notes, touches no database and calls no
external API. The first run downloads the embedding model (about 130 MB).

Columns in the tables below:

- **AUC**: chance that a true link outscores a random non-link (1.0 is perfect,
  0.5 is chance).
- **AUC hard**: the same, against the decoys only.
- **Best F1**: the best precision/recall balance over thresholds 0.05 to 0.95,
  with the threshold that achieved it.
- **Found / false**: true links found out of the total, and wrongly linked pairs.

## The journey

### Step 0: the scorer the app shipped with

`SequenceMatcher` ratio or word Jaccard, "related" at 0.45 or above. It is good
at catching copy-pasted duplicates and almost useless for anything else.

| Set | AUC | AUC hard | Best F1 (threshold) | Found / false |
| --- | --- | --- | --- | --- |
| First | 0.506 | 0.460 | 0.121 (0.45) | 2/24, 7 false |
| Held-out | 0.716 | 0.517 | 0.182 (0.50) | 2/17, 3 false |

On the first set this is barely better than a coin flip.

### Step 1: word TF-IDF

The cosine scorer already used by search. It needs shared words, so the
paraphrase pairs (bouquet / flowers, insomnia / sleeping badly) score 0.

| Set | AUC | AUC hard | Best F1 (threshold) | Found / false |
| --- | --- | --- | --- | --- |
| First | 0.778 | 0.569 | 0.417 (0.15) | 10/24, 14 false |
| Held-out | 0.743 | 0.457 | 0.400 (0.20) | 6/17, 7 false |

Kept as the offline fallback for search; not enough for linking.

### Step 2: character n-grams (3 to 5)

Meant to handle word forms ("renew" / "renewal") and typos.

| Set | AUC | AUC hard | Best F1 (threshold) | Found / false |
| --- | --- | --- | --- | --- |
| First | 0.811 | 0.591 | 0.458 (0.10) | 11/24, 13 false |
| Held-out | 0.822 | 0.478 | 0.400 (0.20) | 5/17, 3 false |

A small gain, still far from usable. Character overlap cannot connect notes
that share no letters.

### Step 3: local sentence embeddings (adopted)

`BAAI/bge-small-en-v1.5`, cosine similarity rescaled so unrelated text is
about 0. Runs on the user's machine: no API key, no quota, and notes are not
sent anywhere.

| Set | AUC | AUC hard | Best F1 (threshold) | Found / false |
| --- | --- | --- | --- | --- |
| First | 0.982 | 0.936 | 0.632 (0.40) | 12/24, 2 false |
| Held-out | 0.994 | 0.965 | 0.741 (0.50) | 10/17, 0 false |

The ranking is excellent. The best cutoff differs between the sets (0.40 and
0.50), so no single value is perfect. At the shipped cutoff of **0.40** the
held-out set gives F1 0.688 (11/17 found, 4 false). The practical reading:
about 0.40 and up is "possibly related", about 0.50 and up is rarely wrong.

### Step 4: blend in character n-grams (rejected)

| Blend | First set best F1 | Held-out best F1 | AUC hard (first / held-out) |
| --- | --- | --- | --- |
| Embeddings alone | 0.632 | 0.741 | 0.936 / 0.965 |
| + 15% character | 0.632 | 0.733 | 0.936 / 0.962 |
| + 30% character | 0.650 | 0.733 | 0.917 / 0.927 |

No reliable gain, and it makes the decoys harder to reject. Character search is
still worth having for typed Search queries (typos, partial identifiers), but
not for linking.

### Step 5: capitalised-entity bonus (rejected)

Add a bonus when two notes share a capitalised name that is never seen in
lowercase (Atlas, Lisbon, Raj).

| Bonus | First set best F1 | Held-out best F1 |
| --- | --- | --- |
| none | 0.632 | 0.741 |
| 0.10 | 0.732 | 0.741 |
| 0.20 | 0.750 | 0.741 |
| 0.30 | 0.756 | 0.741 |

It looked like a large win on the first set, which was partly an artifact: the
extractor had been adjusted after seeing that set's failures. On the held-out
set, where most notes are lowercase, it found nothing to boost and changed no
result. It also pushed the "Atlas of the Himalayas" decoy toward the real Atlas
notes as the bonus grew. Not shipped.

### Step 6: shared rare-word bonus (rejected)

The case-insensitive version of step 5: a bonus for any shared word that
appears in at most three notes.

| Bonus | First set best F1 | Held-out best F1 | False links (first / held-out) |
| --- | --- | --- | --- |
| none | 0.632 | 0.741 | 2 / 0 |
| 0.10 | 0.638 | 0.733 | 8 / 2 |
| 0.20 | 0.622 | 0.686 | 7 / 6 |

Worse on both sets: shared ordinary words ("appointment", "bill", "transfer")
create false links. Not shipped.

### Step 7: integrating into the app, and the bug the end-to-end run caught

The scorer was wired into `find_item_relations`. A first end-to-end run (real
app, temporary database, real model, notes loaded through `POST /api/items`,
then `POST /api/analyze`) did not match the offline evaluation:

| Set | Offline eval at 0.40 | First integration | After fix |
| --- | --- | --- | --- |
| First | 12/24, 2 false | 13/24, 1 false | 12/24, 2 false |
| Held-out | 11/17, 4 false | **12/17, 20 false (F1 0.490)** | 11/17, 4 false (F1 0.688) |

Cause: stored items usually have a title identical to their text, and the code
embedded `title + text`, so every note was embedded twice. Doubling the text
raises the similarity between unrelated notes, which flooded the held-out set
with false links. The fix embeds the title only when it adds information
(`_embedding_text`), and a regression test covers it. The offline evaluation
alone would not have found this, which is why the real pipeline is also run.

## Shipped accuracy

| Set | Found / total | False links | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| First (52 notes) | 12/24 | 2 | 0.857 | 0.500 | 0.632 |
| Held-out (47 notes) | 11/17 | 4 | 0.733 | 0.647 | 0.688 |
| Original app scorer, first set | 2/24 | 7 | 0.222 | 0.083 | 0.121 |
| Original app scorer, held-out | 2/17 | 3 | 0.400 | 0.118 | 0.182 |

These come from the real pipeline with the real model, measured at the shipped
0.40 cutoff.

## Known limits

- **Recall is about 50 to 65%.** The links still missed are mostly notes about
  the same project or event that use different wording (for example "Atlas
  kickoff meeting" and "Atlas vendor shortlist"). Embeddings capture topic, not
  shared entities.
- **Some decoys still link.** "Physio appointment for right knee" and "dad's
  blood pressure appointment" score 0.51: the model matches the shape of the
  note ("appointment") more than who it is about.
- **Small, hand-written evaluation sets.** Both sets were written by the same
  author, 24 and 17 true pairs respectively, so differences of one or two links
  are noise. The cutoff is a starting point; recheck it on real notes.
- **The cutoff belongs to this model.** Another embedding model, or the TF-IDF
  fallback, needs its own threshold. When embeddings are unavailable the
  original lexical rule is used.
- **Embeddings are cached in memory only.** After a restart they are recomputed
  on the next Analyze or search. Persisting them in a migrated table is the
  obvious next step if inboxes grow large.
- **No confirm action yet.** Links can be dismissed but not confirmed; `method`
  records provenance, and a user-confirmed state would be the next addition.
- **The first use downloads about 130 MB** (`fastembed` model cache).

## Configuration

| Variable | Effect |
| --- | --- |
| `LIFE_INBOX_EMBEDDING_MODEL` | Use a different fastembed model (re-evaluate the cutoff) |
| `LIFE_INBOX_DISABLE_EMBEDDINGS=1` | Force the lexical fallback (the test suite does this) |

## Reproducing the numbers

```bash
python -m pip install -r requirements-dev.txt
python -m scripts.eval_linking --summary
python -m scripts.eval_linking --summary --csv tests/fixtures/linking_eval_notes_heldout.csv
python -m pytest -q          # includes tests/test_semantic_relations.py
```
