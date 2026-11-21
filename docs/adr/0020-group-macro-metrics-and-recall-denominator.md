# 0020. Evaluation uses group-macro metrics and divides recall by min(k, |relevant|)

Status: Accepted
Date: 2026-10-11

## Context

Real corpora contain a few very large problem groups (one group is hundreds of near-identical
tickets) and many small ones. Per-query averaging would let the large group contribute hundreds of
near-identical queries and dominate. Plain recall (hits divided by the number of relevant tickets)
would cap a member of a 216-ticket group at 10/215 and read as failure at k = 10.

## Decision

One scoring core (`recall.eval.score`) serves both the synthetic and real harnesses. Recall@k is
hits divided by `min(k, |relevant|)`; MRR and nDCG@k use the usual definitions; each is averaged
per problem group first and then across groups. Queries with no relevant document are counted in
`n_unscored` and otherwise ignored. Dense (both prefixes), lexical and fused variants are scored
separately across three query modes (full, title, first 8 words) so the report shows whether hybrid
retrieval earns its complexity. Per-group output exists for synthetic data only.

## Consequences

- One large group cannot hide failures in small ones, and large groups are not scored as failures
  for being large.
- Macro averaging weights a 20-ticket group like a 200-ticket one, so a poor result on a rare
  problem moves the headline as much as one on a common problem; a per-ticket view is not reported.
- Recall at deeper depths (`--depths`) was added for the M4 candidate gate; MRR and nDCG stay at the
  entry's own k. MRR only sees the retrieved top 10, so it should be read as MRR@10.
- On real data a "group" is a `fehlercode`, which is why per-group output stays off there.
- Identical code in both harnesses makes the synthetic and real numbers comparable, per the brief's
  divergence rule.

## References

- `src/recall/eval.py`; `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 3
- `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` (Tasks 9-10)
