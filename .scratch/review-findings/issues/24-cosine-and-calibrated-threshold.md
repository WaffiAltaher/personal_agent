# 24: Cosine similarity and a calibrated threshold

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 12

**Status:** resolved

**Closes:** M1, M7 (decision (f))

**What to build:** Semantic memory uses cosine distance, so a score is cosine similarity. The threshold is a single setting (no second default in a signature). It is chosen from a labelled Fixture-world set (about 10 remembered facts, about 20 queries each labelled with the fact it should find or "nothing"), and that set is pinned as a test. Existing stores get a one-off re-index.

- [x] Test with fixed embeddings: a text at a given cosine similarity scores that similarity
- [x] The labelled calibration set exists and its test passes at the configured threshold
- [x] The threshold appears in exactly one place
- [x] A re-index path exists for an existing store, with a test

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Chroma `documents` and `memories` collections use cosine space; legacy L2 stores re-index on open. Threshold stays at **0.7** (`memory_score_threshold` only): labelled Fixture-world margin is ~0.29 unrelated vs ~0.999 paraphrase hits on `CalibrationEmbeddings`.
