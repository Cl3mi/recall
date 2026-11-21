# 0043. Same-serial history is only reported in M3; using it as a retrieval signal waits for real data

Status: Accepted
Date: 2026-11-05

## Context

The insight reports found that more than half of the vehicles with a serial have repeat tickets, and
over a third of tickets have an earlier ticket on the same serial, many of them within months. Same
vehicle history looks like a strong retrieval signal. The same-serial relationship is also
quasi-identifying, and a boost tuned on invented serials says little about real ones (ADR 0005).
The model id is missing on many recent tickets while the serial stays filled, so the serial is also
the better key for deriving the model.

## Decision

M3 only reports how often a same-serial earlier ticket is relevant (`same_serial_relevant_share` in
the synthetic report). Using the serial as a signal, whether as a boost or a filter, is out of M3
and out of M4, to be judged on real data behind a flag. The serial is stored casefolded in the
`ticket` projection precisely so this remains possible (ADR 0015).

## Consequences

- Retrieval today ignores vehicle history; a technician searching a vehicle's own earlier tickets
  gets no preference for them.
- The report shows how large the missed opportunity could be, on the stand-in only.
- The serial stays in the database although nothing reads it for ranking, which is a privacy cost
  accepted for the option value.
- A boost needs a measured weight and a real-data evaluation that also covers the model-id gap; the
  M3 plan's Task 13 and the M4 spec list it as undone.

## References

- `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` (amendment 3; Task 13)
- `docs/superpowers/specs/2026-11-13-m4-reranker-design.md` (scope); `docs/STATE.md` (recurrence findings)
- `src/recall/eval.py` (`same_serial_relevant_share`); ADR 0015
