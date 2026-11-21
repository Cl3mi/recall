# 0027. One window driver enforces each window's contract: allowlisted outputs, shred list, human review gate

Status: Accepted
Date: 2026-08-13 (`window.sh` first committed; windows B to E, the thread cap and provenance were added from 2026-09-07 to 2026-11)

## Context

Windows are run by a human with no AI available, often late and under time pressure. Several risks
are design-time: copying the export or a detail log back by accident, leaving inputs on the box, and
running a window before the review gate. Defects actually found by rehearsals and real runs were a
shred list that missed staged files (finding 16), a `--threads` larger than the host's core count
making the runtime refuse to start (seen on a 6-core workstation; the box has 256 cores), a mount
over `/work` that hid the image's venv and cost a cycle, and a stale image shipped.

## Decision

`infra/profiler/window.sh` drives every window and defines a per-window contract: the input file,
the only files that may cross out (`WINDOW_OUT`), what must be shredded (`WINDOW_SHRED`), the file
the operator must read in full first (`WINDOW_REVIEW`), an optional GPU claim and the sealed
command. `fetch` can copy only the allowlist, by loop rather than wildcard. `all` stops at the
review gate and never fetches. Window C is stricter: it refuses `all` and `fetch --clean`, requires
explicit `preflight`, `push`, `run`, `verify`, `fetch`, `release` and `clean` steps, and `--yes`
cannot answer its review prompt. Placeholder paths and images make a real run refuse while
`--dry-run` still works. Provenance (`--code-commit`, `--image-digest`) is passed into every
manifest-producing window, `ship` refuses a dirty tree, and CPU threads are capped and clamped on
the box.

## Consequences

- What may leave the box is a property of the code and of the contract tests
  (`test_window_{c,d,e}_contract.py` pin the sealed commands from `--dry-run`), not of operator
  memory.
- The script is large and shell-based, and every new window adds a branch to it; E and C have their
  own run paths.
- `ship` sends whatever image exists locally and never rebuilds, which cost one wasted ship; the
  rehearsal's stale-image guard exists for that (ADR 0028).
- The human review gate cannot be automated away; that is intended.

## References

- `infra/profiler/window.sh`; `docs/airlock-runbook.md`
- `docs/STATE.md` findings 14, 16, 19; `docs/handoff-window-e-2026-10-28.md`
- Specs `2026-10-12-insight-window-d-design.md`, `2026-10-21-window-e-design.md`
