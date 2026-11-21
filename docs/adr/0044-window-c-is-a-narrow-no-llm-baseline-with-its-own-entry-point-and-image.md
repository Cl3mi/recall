# 0044. Window C is a narrow no-LLM baseline with a guarded entry point and its own image

Status: Proposed (the Window C plan calls these details proposals pending operator review)
Date: 2026-11-16

## Context

The airlock runbook described Window C as a full-pipeline real evaluation, and its command block was
empty. The approved M3 spec says Window C has no LLM. `index.build` truncates its tables, so running
it against the wrong database would destroy data. The catalog modules beyond four are not published,
and the existing images either bake e5 for another purpose (the profiler image) or mount weights at
run time (the M4 eval image).

## Decision

Window C is narrowed to the baseline: evaluate the existing retrieval against earlier same-code
tickets and release aggregate metrics only. Enrichment, a reranker comparison, a same-serial boost,
an exact-code arm and synthesis are separate follow-ups. `python -m recall.window_c` accepts only the
fixed disposable DSN (no inherited DSN, label override or `recall.config` import) and requires
`RECALL_WINDOW_C=1`; it validates the exact 38-column header, discards all library output, writes
only through `recall.sealed`, and reports failures as fixed codes. Window C has a dedicated
`infra/eval/Dockerfile.window-c` with e5 baked in, built on the box from the clean published
snapshot. Only `eval_real.json` can be staged, validated and released, through the unchanged
numbers-only exporter (ADR 0024).

## Consequences

- The first real number arrives without waiting for an LLM stage or an enrichment design, and it is
  small enough to review in full on the box.
- The runbook's older wording is superseded, and the plan asks that this be confirmed in review.
- A fourth image must be built and kept in step on the box.
- Anything beyond the baseline needs a new window design; the reranker's real-data value is not
  measured here (ADR 0019).
- The fixed DSN and the sentinel make an accidental run against another database fail closed.

## References

- `docs/superpowers/plans/2026-11-16-m3-window-c.md` (scope, constraints, review focus)
- `src/recall/window_c.py`, `infra/eval/Dockerfile.window-c`
- ADR 0021, 0022, 0024, 0027
