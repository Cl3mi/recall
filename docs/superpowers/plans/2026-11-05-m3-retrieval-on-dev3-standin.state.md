# State: M3 retrieval on the dev3 stand-in

Plan: `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md`
Milestone: "fusion decision applied" reached (task 12 of 13, 2026-11-12); next is Task 13, the
operator's M4 decision

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
- Task 11 (re-run on the GPU box from the snapshot of 1f9824f; results in the plan,
  "Results, 2026-11-11")
- Task 12 (A: `query:` default, 0f901bc; B: weighted RRF and `fused_dense2`, 38d0403; B4 run
  recorded in the plan, "Results, 2026-11-12")

Task 8 (real-data wrapper, Window C) is deferred on purpose; it needs an operator window and gets
its own plan.

## What's done
M3's plumbing is complete and green. Task 11 answered the plan's three questions (details in the
plan's "Results, 2026-11-11"; the old four variants reproduced exactly, so the runs compare):
1. `query:` beats `passage:` in every mode (6.7 / 13.1 / 10.5 points): Task 12 step A applies.
2. `fused_query` is below dense `query:` on full (0.806 vs 0.820), ties lexical on title, wins on
   head (+3.7): not a win in all three, so Task 12 step B applies.
3. The small side of each twin pair averages 0.60 / 0.33 / 0.45 under `fused_query`, against
   0.95 / 0.98 / 0.98 for the groups without a twin: concentrated loss, the reranker branch of
   Task 13's rule (the operator decides Task 13).

## What's next
Task 12 is done. `fused_dense2` did not beat its best input in every mode either (-0.7 / -0.6 /
+2.1); the fused variants differ by 1 to 2 points while the twin gap is 35 to 66. The code keeps
`query:` plus plain RRF as the `search` default; weights stay available, no tuning on stand-in text.
**Task 13** is next and is the operator's decision (reranker vs Task 8 first); the plan's rule
reads "reranker" from the per-group numbers. Do not start it without the operator.
Full suite: 2251 passed; the 2 failures in `tests/unit/test_window_d_contract.py` predate this work
(they pin `infra/profiler/window.sh --dry-run` output) and are not M3's. Then Task 13, which is the operator's decision. Box mechanics are
in `docs/handoff-hpc-continuation-2026-11-10.md`, evening update; the restart of `recall-eval-pg`
in the same ssh command as the eval keeps the container alive for the run.

## Decisions / deviations since the plan was written
- 2026-11-11: the first write-up claimed plain RRF loses to the best single arm. That compared
  `fused` with `dense_query`, which is not one of its inputs. Corrected in the plan; answered by
  Task 11 on 2026-11-12 (see above).
- 2026-11-11: spec amendment 5, query-side prefix `query:` (stored vectors stay `passage:`), applied
  only if Task 11 confirms it. Task 11 confirmed it.
- Operator rules that still hold: `MIN_RECIPES` stays 4; no real data is read outside an airlock
  window; sync to GitHub only through `make publish`.
