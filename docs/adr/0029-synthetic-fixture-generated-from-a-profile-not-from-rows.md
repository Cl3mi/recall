# 0029. The synthetic fixture is generated from the gated profile, not by paraphrasing rows

Status: Accepted
Date: 2026-08-17

## Context

Remote and local coding agents need a corpus that behaves like the client's export without being
derived from it. The brief names the failure to avoid: clean, well-formed German tickets make
everything work on synthetic data and collapse on the real corpus, so ugliness is the
specification. It also names the leakiest option: paraphrasing real tickets row by row, because
models retain entities and a reworded real ticket can still identify a customer, dealer or machine.

## Decision

`fixtures/` generates the corpus from `profile.json` (Window A, schema v2, already gated by
`blessing`). `plan.py` is the only place the profile is interpreted and decides every number (group
bands, fill by year, shape mixes) as a pure function; a local LLM writes, per group, one shared
problem text and several distinct resolutions (the 2026-08-19 cluster-structure spec replaced the
earlier "variants in the problem text" design, ADR 0018), with code controlling counts; groups of
50 or more are written as forms; a handover block of about twenty fields is filled all-or-nothing
and seated on the largest group; `render.py` emits the 38-column shape including double-encoded
EAV `customData`; `verify.py` checks the output against the plan. Generation needs no window
because it reads a gated artifact and writes invented text. The LLM responses are cached by client
identity and prompt hash, and since sampling is not reproducible the generated fixture is the
artifact. The large band keeps its ticket share (the fixture has one cluster of 50 or more where the
corpus has several), a user decision recorded in the M2 findings. Generation and the leakage gate are separate commands on purpose, since
merging them would put an LLM in a window.

## Consequences

- Distributions match the real corpus and update when a new profile is produced: the planner's
  bands are within 0.05 percentage points, the generated fixture's measured bands within 0.01
  points (the acceptance tolerance is 1.0), and fill rates and shapes pass.
- Seven generation rounds were needed. Per-batch "voices" only reduced singleton collisions from 173
  to 121; the bands passed once batch dedup through the profiler's LSH, a top-up that avoids faults
  already taken, and group-consistent description blanking were added. Subsystem steering gave a
  small gain (182 to 173) and was kept. Shrinking the mid budget was never tried and is ruled out
  by the divergence rule, because it would inflate synthetic recall (ADR 0005).
- The brief's noise-injection step was never implemented, and the invented product designations
  double as a leak-detection aid.
- The text is still generic LLM prose and its serials do not form per-vehicle histories, which is
  why dev3 was added for retrieval work (ADR 0031).
- A fixture is not cleared for use until the leakage gate has run against real data (ADR 0030).

## References

- `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md`
- `PROJECT_BRIEF.md` section 8; `docs/STATE.md` findings 1-9
- `fixtures/`
