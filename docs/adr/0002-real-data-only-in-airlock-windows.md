# 0002. Real ticket data is handled only in manual, AI-free airlock windows on the box

Status: Accepted
Date: 2026-08-04

## Context

The client's ticket export is under NDA. The original brief assumed one client machine with a
dedicated GPU; the planning session found two machines instead: a workstation where an AI coding
agent works, and a shared H100 box where inference and indexing run. Anything an agent can read can
end up in a prompt, a log or a commit, so the workstation is meant to hold no real data. In
practice the export sat on the workstation until each window (the preflight reads its shape there),
so protection cannot assume the workstation is empty. Yet the
project cannot answer its central questions (what the corpus looks like, whether the synthetic
fixture is faithful, whether retrieval works) without running code over the real rows.

## Decision

Real data may exist on the box only inside a sealed window: the export is copied into quarantine,
a prepared script runs by hand with no AI assistance, it writes an artifact, and the export and
its derivatives are shredded before any AI touches that filesystem again. Windows A to D run their
containers with `--network=none` (Window E's two containers share a private `--internal` network,
ADR 0032), with no core dumps (`ulimit -c 0`), and verbatim values go only to a detail log that
stays on the box. A human-run `airlock open` marker makes the guard deny every AI tool call while a
window is open, which is what actually enforces "AI-free". The 2026-08-04 session defined windows
A (profile), B (leakage gate) and C (real eval); D (insight report, 2026-10-12) and E (problem
catalog, 2026-10-21) were added later, and C's scope was narrowed in November. Each window states
in advance what may cross out.

## Consequences

- AI sessions never need access to real rows. The guard (ADR 0025) and the airlock marker defend a
  workstation that may still hold the export between windows, so the operator must resolve the
  export before closing a window.
- Permission deny rules and the sandbox stop accidents but are not the boundary; the boundaries are
  the AI-free window and an empty `local/quarantine/` (checked by `make check-clean`).
- Every real-data question costs a full manual cycle (ship, push, run, verify, human review,
  fetch, shred). Code is therefore built and rehearsed on synthetic data first, and a bug found
  inside a window costs the window.
- Errors inside a window cannot be debugged with AI help, so every failure is a short code with
  no values, and each window has a rehearsal (ADR 0028).
- The operator must be present for each window; the project's schedule is bounded by that.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 1
- `docs/airlock-runbook.md`, `PROJECT_BRIEF.md` invariants 1-2
- ADR 0003, 0023, 0027
