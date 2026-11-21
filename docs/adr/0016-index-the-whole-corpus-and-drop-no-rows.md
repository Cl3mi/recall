# 0016. The index contains the whole corpus; no rows are dropped

Status: Accepted
Date: 2026-10-11

## Context

The insight reports found that a large minority of tickets are noise for a troubleshooting system:
one category is almost entirely handover slips with templated titles and administrative solution
notes, tickets with a delivery date behave the same way, and a share of tickets have no usable
solution. Dropping them would improve any quality ratio. But the brief's invariant is that rows are
never dropped, and an old ticket with the right fix is still the right fix.

## Decision

M3 indexes every row from every year, with no filter on category, solution presence, status or age.
Noise is handled later and by measurement: weak years or empty solutions get a completeness penalty
at rerank time, not exclusion (the spec names weak years only; empty solutions are named as having
no filter, and no completeness penalty has been built). The one place where exclusion is applied is the problem catalog,
where handover slips and noise are removed before clustering (ADR 0031), because there the goal is
recipes rather than retrieval coverage.

## Consequences

- Retrieval can return a handover slip for a query that resembles one; the dense arm may rank noise
  that a filtered index would hide. The first real measurement (ADR 0021) will show how much that
  costs.
- Window C evaluates the whole corpus as well, keeping empty-solution candidates. Its report has no
  text field, so the limitation (it does not measure whether a technician receives a usable fix)
  must be stated when the results are interpreted.
- The insight finding "drop the handover category and filter per ticket on the usable grade" is a
  recorded recommendation that becomes a decision only after real retrieval numbers exist.
- Index size and build time scale with the full export.

## References

- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` (Decisions table)
- `docs/STATE.md` (fourth real run recommendation)
- `docs/superpowers/plans/2026-11-16-m3-window-c.md` (empty-solution candidates)
