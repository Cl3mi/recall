# 0011. Queries use the `query:` prefix while stored vectors keep `passage:`

Status: Accepted
Date: 2026-11-12

## Context

e5 expects `query:` and `passage:` prefixes. The M3 spec chose `passage:` on both sides, although
e5's guidance for symmetric tasks is `query:` on both, in order to keep the stored vectors identical
to the ones the leakage gate measured (finding 18). The spec also had the eval A/B the two, so the
choice was meant to be measured. On the dev3 stand-in, `query:` on the query side beat `passage:`
by 6.7 to 13.1 points (full, title and head queries), measured in the first real-writer run.

## Decision

Stored vectors keep the `passage:` prefix. The query side defaults to `query:` (`index.QUERY` is
the default `prefix` of `retrieve.search`). Both dense variants stay in the eval
(`dense_passage`, `dense_query`) so the choice remains measurable, and `fused` keeps the
`passage:` baseline beside `fused_query`.

## Consequences

- The gate's calibration is untouched because only the query side changed.
- The prefixes are asymmetric, which is the mainstream e5 usage for query-to-document search.
- The default rests on stand-in text and is revertible if Window C disagrees (ADR 0005); the
  reranker base variant `fused_query` depends on it.
- Anything that embeds queries elsewhere (a future service) must apply the same prefix and the same
  cleaning (ADR 0013) or recall silently drops.

## References

- `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` (amendment 5, Tasks 11-12)
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 2
- `src/recall/index.py`, `src/recall/eval.py` (`VARIANTS`)
