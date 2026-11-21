# 0021. The first real evaluation is a temporal holdout using normalised `fehlercode` as the relevance proxy

Status: Proposed (the temporal holdout is in the approved M3 spec; the calendar rule and the report
schema below are the Window C plan's proposals, awaiting operator review, and the code is unrehearsed)
Date: 2026-11-16 (holdout approved in the M3 spec, 2026-10-11)

## Context

Real tickets have no hand-labelled "same problem" judgements, and the client is not to be contacted
until a strong prototype exists. Two things are available on the real export: creation dates and a
`fehlercode` field, filled for a minority of tickets and sometimes holding several codes. A
production system only ever searches the past, so a fair real test must not let the future help.

## Decision

Window C (`recall.eval_real`) takes the latest creation date, subtracts six calendar months
(clamping to the target month's last day) and treats labelled tickets from that point on as queries.
Candidates are strictly earlier tickets, enforced in SQL by the `before` filter on every variant;
reranking cannot repair leakage. Relevance is the same normalised `fehlercode`; a composite code is
one label. Tickets without a date stay indexed and count toward coverage but enter neither side.
The report is a frozen numeric schema (`schema_version` 1, `k` 10, `coded_faults_only` true, counts
and metrics only), validated before writing and again before release, and coverage counts are
reported before quality.

## Consequences

- The metric measures retrieval of earlier tickets with the same code, which is a proxy: same code
  is not proof of the same successful solution, and the coded minority may not represent uncoded
  faults.
- A query with no earlier same-code ticket is counted and not scored as zero.
- The baseline has no LLM and no reranker, keeps all six variants and three query modes, and
  releases no per-group, per-query, id, code or date output.
- A catalog-based relevance baseline was an alternative; code-based relevance was kept as the
  approved real-eval spec requires. The operator's catalog prerequisite from the stand-in plan is
  still open, and the plan asks the reviewer to confirm that code-based relevance is intended.
- Coverage will show how much of the corpus is evaluable at all, since only a minority of tickets
  carry a code.
- The CLI's `--out` argument was amended to the basename `eval_real.json` (the output goes through
  `recall.sealed`). `mrr` is MRR@10 here and a group is a code (ADR 0020).
- Postgres integration, image builds and the Docker and Podman rehearsals are unverified, and the
  new code is not yet committed.

## References

- `docs/superpowers/plans/2026-11-16-m3-window-c.md` ("Decisions for operator review", Report v1)
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` sections 3-4
- `src/recall/eval_real.py`, `tests/unit/test_eval_real.py`
