# 0007. Native Postgres full text instead of a BM25 extension; identifier arm deferred

Status: Accepted
Date: 2026-08-04

## Context

The brief asked for BM25. Candidate Postgres extensions (VectorChord-bm25, ParadeDB `pg_search`)
bring their own analyzer chains and, for `pg_search`, a licence that needed checking. The German
dictionary work (compound splitting, synonyms) is the highest-value lexical lever and is shaped
like a Postgres text search configuration. `ts_rank_cd` has no inverse document frequency, so an
exact code such as `F1247` does not outweigh a common word like `defekt`.

## Decision

Use native `de_tech` full text search, with no BM25 extension in v1. The IDF weakness is to be
fixed by a dedicated third arm doing exact identifier matching (a normalised identifier table with
btree/GIN and `pg_trgm` for near misses), not by a better scorer. A deferred upgrade path exists
without an extension: take candidates from the GIN-indexed tsvector and compute true BM25 in SQL
over the top ~200 from a materialised IDF table, triggered if lexical recall@50 trails dense badly
after the identifier arm exists.

## Consequences

- Proper compound splitting is kept; BM25 without it was judged a worse trade than `ts_rank_cd`
  with it.
- The identifier arm and the `fehlercode` arm are **not built**. Window A (2026-08-10) measured
  identifiers inline in only about 1% of tickets, so the identifier arm was dropped from v1's
  critical path and not weighted up; M3 then omitted both arms on purpose and M4 went to the
  reranker. The IDF weakness is therefore unaddressed: exact-code queries rely on the lexical arm
  and `de_tech` handling of code-like tokens, unmeasured on real data, and real `fehlercode` values
  use a hyphenated numeric shape that the identifier regex the code knows does not match.
- No third-party extension to track for licence or upgrade risk.
- The deferred BM25 upgrade is a recorded option, not scheduled work.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 2 (section 12.7)
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` ("Absent from M3")
- `docs/superpowers/plans/2026-11-13-m4-reranker.state.md` (out of scope and undone)
