# State: M3 retrieval on the dev3 stand-in

Plan: `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md`
Milestone: "fused_query variant in" reached (task 9 of 13, commit 4c76eff); Task 10 done
(897b88f); next is Task 11, which the user runs

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

Task 8 (real-data wrapper, Window C) is deferred on purpose; it needs an operator window and gets
its own plan.

## What's done
M3's plumbing is complete and green. The stand-in was regenerated with the real 32B writer
(510 tickets, 12 recipes with 4 near-twins) and scored with e5 on 2026-11-10; numbers and a
correction are in the plan's Results section. Headline: ceiling lifted (best `full` recall@10 0.82,
dense with the `query:` prefix); the `query:` prefix beats `passage:` by 5 to 13 points.

## What's next
Tasks 9 and 10 are done (`fused_query` = RRF over `query:` dense plus lexical; `--per-group` adds
per-recipe numbers). Next is **Task 11** (the user publishes, pulls on the GPU box and re-runs the
eval with `--per-group`), then Task 12 (apply the fusion and
prefix decision the numbers call for), Task 13 (M4 gate). Why: the only `fused` row so far used the
`passage:` dense arm, so the question "does hybrid beat its best arm" is still open, and
twin-pair separation was never measured. Box mechanics (podman GPU wrapper, Postgres container that
dies with the last ssh session, the eval command) are in
`docs/handoff-hpc-continuation-2026-11-10.md`, evening update.

## Decisions / deviations since the plan was written
- 2026-11-11: the first write-up claimed plain RRF loses to the best single arm. That compared
  `fused` with `dense_query`, which is not one of its inputs. Corrected in the plan; the fusion
  verdict is open until Task 11.
- 2026-11-11: spec amendment 5, query-side prefix `query:` (stored vectors stay `passage:`), applied
  only if Task 11 confirms it.
- Operator rules that still hold: `MIN_RECIPES` stays 4; no real data is read outside an airlock
  window; sync to GitHub only through `make publish`.
