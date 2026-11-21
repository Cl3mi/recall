# 0023. Anything an AI may read must be structurally incapable of carrying corpus values

Status: Accepted
Date: 2026-08-04

## Context

Artifacts that leave a window are read by an AI agent. A discipline rule ("do not put names in the
report") fails silently the first time it is forgotten. The first real run and the adversarial
reviews that followed found exactly that kind of gap: a first name in released title tokens
(report v2 spec), a floor that counted occurrences instead of tickets, so one ticket repeating a name
60 times would have released it (STATE.md, report v2 hardening), and a raw dimension value emitted
with no floor or sweep (`dimension_hints[].id`, Window A plan). The profiler's own code notes that a
frequent dealer or person name clears a frequency floor easily. A renamed export carrying the
client's name into the artifact was a design-time precaution, not an observed leak. Each leak would
have cost a window.

## Decision

Every released artifact is built under constraints enforced by code, not habit. The principle dates
from the 2026-08-04 planning session (`profiler.safety`); the whole-artifact catch-all
(`profiler.blessing`) landed on 2026-08-13 (commit 53ed800), `insight.guard` and `insight.release`
(k = 50) on 2026-10-11/12 (commit 5c35ee4), and `catalog.guard` on 2026-10-21. `insight.guard` was deliberately built beside `profiler.blessing`
rather than extending it, because changing a safety control is the operator's call.

- **Closed allowlists.** `profiler.blessing` and `selfcheck` refuse any string that has no declared
  reason to exist; `insight.guard` accepts a released string only at its declared path and refuses
  non-string released fields, non-finite numbers, malformed shapes and tuples; `catalog.guard` does
  the same for recipes. Dict keys come from a closed list (no all-digit key except a four-digit
  year under a key named `year`, since a serial could travel as a key), entries are lists of dicts
  and never dicts keyed by a value, and a bare string in a list is refused. The catch-all blesses by
  path, not by value, and a failure aborts the run (exit 2) with nothing written. Shapes use a
  closed alphabet, and `source.filename` is withheld as `<non-conforming>` unless it is the
  expected name. Nothing is written unless the guard passes, and a failed run leaves no report
  behind.
- **Floors.** Every released label, value and cell needs at least k = 50 tickets, counted per
  ticket and not per occurrence (per vehicle for serial-prefix buckets, which are opt-in and off in
  real windows because the serial is on the never-emit list). Counts inside a floored group may be
  smaller, since a count below k is not personal data (stage-1 amendments 8 and 10), and cells under
  the floor are withheld and tallied, not folded into `other`. `insight.release` is the single
  definition shared by builders and guard. A floor below k needs `--allow-weak-floor`, which a real
  window never passes.
- **Entity sweeps.** Tokens are checked against surname and first-name lists and entity patterns;
  rejected tokens are counted, not logged.
- **Hidden values.** `insight.extract.Ticket` marks free text, serials, ids and dates `repr=False`,
  so a ticket formatted into an exception or a log cannot print raw text. Errors carry a code and a
  schema path, never a value, and `profiler.safety.run_scrubbed` keeps raw tracebacks off stdout.
- **Provenance and suppression ledger.** Every report records what was withheld and why, with zeros
  emitted as zeros, so an empty result is distinguishable from a suppressed one.

## Consequences

- A leak requires a code defect that survives a guard with adversarial tests, not one forgotten
  rule; every review round found something real and each fix has a test that fails on the old code.
- Every new section a builder adds must also be declared in the guard's released paths, or the real
  run is refused: nothing leaks and the window is spent. This is the recurring cost of the design.
- Name deny-lists cannot be complete; an uncommon name that clears 50 tickets would pass. The human
  review on the box is the last control, not the only one.
- Several figures are deliberately coarse or withheld, which limits what the reports can answer.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 1; `profiler/safety.py`
- `docs/superpowers/specs/2026-10-12-insight-report-v2-design.md`; `docs/STATE.md` (Report v2 hardening)
- `insight/guard.py`, `insight/release.py`, `catalog/guard.py`
