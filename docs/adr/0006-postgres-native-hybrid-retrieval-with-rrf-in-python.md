# 0006. Hybrid retrieval is Postgres-native, with RRF fused in Python

Status: Accepted
Date: 2026-10-11

## Context

The domain is full of exact tokens (error codes, part numbers, model designations) whose dense
vectors are near-identical while the faults differ, so dense-only retrieval is not enough. The
lexical side must be the real German full-text configuration with compound splitting (ADR 0008),
which exists only as Postgres configuration. The reranker planned for later wants candidates in
Python. The M3 spec weighed an in-memory retriever and RRF inside one SQL CTE.

## Decision

Both arms run in Postgres: a dense arm (pgvector, cosine, HNSW) and a lexical arm (`de_tech`
`tsvector` with `ts_rank_cd`), each returning a pool of 100. Reciprocal rank fusion
(`score = sum of weight / (60 + rank)`) is a pure Python function with deterministic tie-breaks.
Each hit carries its per-arm ranks so a result is explainable and each arm can be scored alone.

## Consequences

- The evaluated lexical arm is the one that ships; an in-memory stand-in would have measured an
  arm that never exists in production.
- Fusion is unit-testable (ties, one-arm-only documents, empty arms) and the fused list is
  available in Python for reranking (ADR 0019).
- Two round trips per search instead of one CTE; acceptable at this scale and not measured.
- RRF fuses ranks, not scores, so a weak lexical scorer (no IDF) is partly masked; the evidence
  that fusion helps on stand-in text is thin and real data must confirm it (ADR 0005).
- The 2026-11-12 fusion decision kept plain RRF: `weights` exists but is unused by default, and
  `fused_dense2` stays in the eval only as a comparison. The August design's weights (1.0 / 1.0 /
  1.5 with an identifier arm) were not built (ADR 0007).
- Dense and lexical results are filtered identically in SQL (self-exclusion, date cutoff), so a
  date cutoff cannot be bypassed by one arm.

## References

- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` sections 1-2
- `src/recall/retrieve.py`; commits 3f948fe (design), `ae352df` (fusion)
- `PROJECT_BRIEF.md` section 6, decision 3
- ADR 0007, 0008, 0012
