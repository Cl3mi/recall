# 0030. The leakage gate demands zero shingle overlap, calibrates in-window, and signs with a hash manifest

Status: Accepted
Date: 2026-08-27

## Context

Before synthetic data is trusted, something must show it is not derived from the real corpus. Four
checks were proposed: shared 8-token content-bearing shingles, nearest-neighbour cosine from the
synthetic to the real corpus, a regex/NER sweep over the synthetic text, and an entity allowlist
against a fictional roster. Thresholds are tempting to relax later, and the first versions of the
neighbour check were degenerate: the baseline was saturated by near-duplicates, and the original
neighbour calibration (finding 12) had been measured with the hashing stub rather than e5.

## Decision

The gate (`profiler/gate`, run as Window B) runs all four checks in the window and emits one
`gate_report.json`. The shingle bar is zero, not a tolerance, because a threshold is something that
would later be relaxed and a single hit deserves investigation. The neighbour threshold is
calibrated in the same window: the synthetic-to-real p99 must not exceed a synthetic-versus-synthetic
baseline taken at the 95th percentile (the spec started with p99 against p99; finding 12 changed it,
chosen against the one independent corpus available), with a `baseline_saturated` flag. Shingles are
8 content tokens after stopword removal and the shingle set never leaves the box. Reports carry a
hash manifest (input SHA-256s, embedder identity, code commit, image digest), with no signing keys,
an operator ruling of 2026-08-27. The PII sweep implements three
of the six pattern families and prints which, so a green cannot read as "no PII of any kind". The
report records `embedder_is_a_model` and `values_traced` so vacuity is visible.

## Consequences

- A fixture can be rejected for one shared shingle; this is intended and costs a regeneration.
- The p95 choice survived the re-measurement with e5 (margin +0.032, down from +0.068), but the
  headroom is thin and the twin fraction (3.5%) is nearer the 5% saturation limit than first
  believed; a fixture with more cluster mass may saturate sooner.
- The roster check is still vacuous: the name it traces (`ansprechpartner`) is a key inside
  `customData`, not a column, reading `customData` is barred (ADR 0017), and the name-bearing
  columns are empty in the fixture. An operator ruling of 2026-09-14 (commit 7c64cb4) made this
  visible through `values_traced` instead of fixing it, and the runbook says three of the four
  checks are proven. Plates, surnames and addresses are not covered by patterns.
- Calibration rests on the e5 vectors, tying the gate to ADR 0009.
- Hash manifests give provenance and no signing keys; they are not proof of authenticity (an
  inference from the design, not a recorded finding).

## References

- `docs/superpowers/plans/2026-08-27-window-b-leakage-gate.md`; `profiler/gate/`
- `docs/STATE.md` findings 12-18; commits a78e0f5, a7540b7 (p95), 0f5b937 (saturation flag),
  7ecdc38 (finding 18), 7c64cb4 (`values_traced`)
- `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md`
