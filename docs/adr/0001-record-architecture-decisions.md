# 0001. Record architecture decisions as ADRs

Status: Accepted
Date: 2026-11-21

## Context

Design decisions in this project have so far been written into per-milestone specs
(`docs/superpowers/specs/`, each with a "Decisions" table), plans and their amendments
(`docs/superpowers/plans/`), and the running findings in `docs/STATE.md`. That worked while one
person held the context, but the reasoning is now spread over dozens of long documents, several
decisions were reversed or amended later (the airlock's retained embeddings, CPU-only embedding,
the query prefix), and a fresh session or a new engineer cannot tell which statement is current.
`docs/ARCHITECTURE.md` describes the system as built but deliberately does not carry the reasons.

## Decision

Significant decisions are recorded as short ADRs in `docs/adr/`, one decision per file, named
`NNNN-short-title.md`, using Context / Decision / Consequences plus a References section. A
decision that replaces an earlier one gets a new ADR; the old one's status becomes
`Superseded by NNNN`. The first batch (0002 onward) was written retroactively from the specs,
plans, STATE findings and commit history; each carries the date the decision was taken, not the
date it was written down, and names its sources. `docs/adr/README.md` is the index.

## Consequences

- A reader gets the current decision and the rejected alternatives in one place, and
  `ARCHITECTURE.md` can link to the reason instead of repeating it.
- Retroactive records are reconstructions. Where the sources record a choice but not the
  comparison behind it, the ADR says so instead of inventing a rationale.
- Specs and plans stay the detailed record; an ADR is a pointer plus the decision, so the two can
  drift. When a spec amendment changes a decision, the ADR must be updated or superseded in the
  same change.
- Maintaining the index and statuses is a small recurring cost.

## References

- `docs/superpowers/specs/*` ("Decisions" tables), `docs/STATE.md`, `docs/ARCHITECTURE.md`
