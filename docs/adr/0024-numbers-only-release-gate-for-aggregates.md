# 0024. Aggregates leave the sealed root only through a numbers-only release gate

Status: Accepted
Date: 2026-10-16

## Context

Code that can see real rows writes under a sealed root that the agent guard denies (ADR 0025). Some
of what it computes is useful to the agent, for example the real-data retrieval metrics. A manual
copy out of the sealed root has no check on what it carries, and a JSON report can hold free text
or a numeric field that is really an id or a code.

## Decision

`tools/guard/export_aggregate.py <name>` is the only sanctioned way to move information out of the
sealed root. It accepts a JSON document of numbers, booleans, nulls and lists or objects of them,
rejects free-text strings, checks nesting depth (at most 8), list length (at most 10,000),
finiteness, and that object keys are snake_case identifiers (a key could otherwise carry a value),
and writes to `local/released/`, which agents may read. There is no check on value ranges. A numeric leaf type is not sufficient on its own: a producer must also validate that
values are derived counts and metrics, never numeric ticket ids or codes; Window C does so with an
exact-schema `validate_report` before writing and again before release. The Window C `release` step
invalidates any stale or partial release first.

## Consequences

- Releasing the real-data baseline is one reviewed command, and an invalid report never reaches
  `local/released/`.
- Anything that is not numeric (catalogs, reports with strings) needs its own guarded path with its
  own gate, not a loosening of this one. The catalog does not use this gate: it has its own release
  gate (ADR 0033) and lands in `local/artifacts/`, which is also a readable zone. Modifying this gate to accept strings is
  explicitly out of bounds for agents.
- Per-group or per-query numbers keyed by an opaque id can still leak by their key; producers must
  not emit them for real data.
- The gate and the guard are operator-maintained; an agent that finds them wrong must tell the
  operator rather than work around them.

## References

- `docs/superpowers/specs/2026-10-16-recall-guard-design.md` ("Sealed outputs and the release gate")
- `tools/guard/recall_guard/release.py`; commit db458a4
- `docs/superpowers/plans/2026-11-16-m3-window-c.md` (global constraints)
