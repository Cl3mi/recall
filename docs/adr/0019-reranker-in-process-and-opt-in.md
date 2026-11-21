# 0019. The reranker runs in-process, GPU only, and stays opt-in after M4

Status: Accepted
Date: 2026-11-15

## Context

M3 on the dev3 stand-in showed concentrated failure: the small side of each near-twin recipe pair
scored 0.60 / 0.33 / 0.45 recall@10 (full / title / head) against 0.95 or more for groups without a
twin, while MRR on full queries stayed high. The one fusion weight tried (dense x2) did not close
the gap: fusion variants differed by 1 to 2 points against a twin gap of 35 to 66. The operator
chose a reranker as M4 on 2026-11-12, ahead of the real-data window. The design gated the work on
candidate recall (recall at depth of at least 0.80 in every mode). The gate passed with N = 100
(recall 0.890 / 0.882 / 0.885 at depth 100, but only 0.700 / 0.634 / 0.684 at depth 50). The
bake-off was a two-model comparison (bge-reranker-v2-m3 and
Qwen3-Reranker-4B) with a win bar of a 15-point small-twin lift in every mode and no collateral
damage. Rejected options: reranking the union of both pools, blending reranker and RRF scores
(a weight tuned on invented text), serving the model over vLLM, and jina rerankers (non-commercial).

## Decision

Rerankers are in-process transformers adapters, like the e5 embedder, pinned by revision and loaded
offline. They are GPU only and refuse to run without CUDA; there is no CPU fallback. The final
order is the pure reranker score over the fused top `depth`, ties by fused rank. No cell passed the
win bar: the best averaged small-twin lift was +0.021 (bge, problem plus solution) against a bar
of +0.15 in every mode, the best single-mode lift was +0.09 (Qwen, full queries), and macro
recall@10 also fell in at least one mode in every cell. The best cell, bge with problem plus
solution text, stays in the code as opt-in: `Settings.rerank_model`, `rerank_depth` and
`rerank_text` default to `None`. The Qwen adapter and the problem-only text were deleted.

## Consequences

- The default pipeline has no reranker, no extra GPU dependency and no added latency.
- The null result is stand-in evidence only: the twins are invented text, so it neither proves nor
  disproves a benefit on real tickets (ADR 0005). Window C does not evaluate the reranker.
- Keeping the adapter costs maintenance; the deleted code is in git history before 23011a1.
- The `Settings` rerank fields are declared but not wired into any serving path yet.
- Latency was recorded but never a veto; production load is unmeasured.
- The bge cell lowered some groups (R003 fell from 0.98 to 0.80), so even a future real-data win
  would need a per-group look. The Apache-2.0 licence check for bge at the pinned revision is still
  open for the operator. Also rejected at design time: `gte-multilingual-reranker-base` (needs
  `trust_remote_code`) and Qwen3-Reranker-0.6B.

## References

- `docs/superpowers/specs/2026-11-13-m4-reranker-design.md`
- `docs/superpowers/plans/2026-11-13-m4-reranker.state.md`
- Commits 2810040 (design), 9557885 (gate), 23011a1 (decision), 4efa275 (close)
- `src/recall/rerank.py`, `src/recall/retrieve.py`
