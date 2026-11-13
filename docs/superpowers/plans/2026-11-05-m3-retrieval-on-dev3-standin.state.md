# State: M3 retrieval on the dev3 stand-in

Plan: `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md`
Milestone: all open tasks done (task 13 of 13, 2026-11-12). Only Task 8 (real data, Window C) remains,
deferred by design.

## Completed task IDs
- Task 1 (migration and tables)
- Task 2 (RRF)
- Task 3 (OR-query)
- Task 4 (index builder)
- Task 5 (search)
- Task 6 (scoring)
- Task 7 (synthetic wrapper, label loader, CLI, query modes)
- Task 9 (`fused_query` variant, 4c76eff)
- Task 10 (opt-in per-group metrics, `--per-group`, 897b88f)
- Task 11 (re-run on the GPU box from the snapshot of 1f9824f; plan, "Results, 2026-11-11")
- Task 12 (A: `query:` default, 0f901bc; B: weighted RRF and `fused_dense2`, 38d0403; B4 run in the
  plan, "Results, 2026-11-12")
- Task 13 (M4 gate: the operator chose a reranker, 2026-11-12)

Task 8 (real-data wrapper, Window C) is deferred on purpose; it needs an operator window and gets
its own plan.

## What's done
M3 on the stand-in is closed. `search` defaults to `query:` plus plain RRF; no fused variant beats
its best input in every mode, and the fused variants differ by 1 to 2 points. The small side of each
twin pair scores 0.60 / 0.33 / 0.45 recall@10 against 0.95+ for groups without a twin.

## What's next
A new plan for **M4: a reranker**. It opens by measuring recall at the candidate depth it will rerank
(only recall@10 is measured so far) on the same `dev3-confusable` fixture, then budgets GPU time
(60 GB fair-use cap), latency and shipping the model into the sealed environment. Same-serial boost
and the `fehlercode` arm stay out of its first plan. Box mechanics are in
`docs/handoff-hpc-continuation-2026-11-10.md` (updates of 2026-11-10 evening and 2026-11-12); the
eval Postgres container was removed and must be recreated.

Full suite: 2251 passed; the 2 failures in `tests/unit/test_window_d_contract.py` predate this work
(they pin `infra/profiler/window.sh --dry-run` output) and are not M3's.

## Decisions / deviations since the plan was written
- 2026-11-11: the first write-up claimed plain RRF loses to the best single arm. That compared
  `fused` with `dense_query`, which is not one of its inputs. Corrected; answered by Task 11.
- 2026-11-11: spec amendment 5, query-side prefix `query:` (stored vectors stay `passage:`). Task 11
  confirmed it; applied in 0f901bc.
- 2026-11-12: fusion kept as plain RRF; `weights` exists but is not tuned on stand-in text.
- 2026-11-12: operator decision, M4 starts with a reranker (Task 13).
- Operator rules that still hold: `MIN_RECIPES` stays 4; no real data is read outside an airlock
  window; sync to GitHub only through `make publish`.
