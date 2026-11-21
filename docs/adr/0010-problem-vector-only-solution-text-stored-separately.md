# 0010. The searchable vector represents the problem only; solution text is stored separately

Status: Accepted
Date: 2026-10-11

## Context

Query-to-problem is a symmetric similarity task: a technician describes a fault and wants earlier
tickets about the same fault. The `solutions` field is the load-bearing resolution text, but mixing
it into the primary vector dilutes the match; the brief's first design decision was not to embed
the raw row. The M3 stand-in was built with near-twin recipes that share component and symptom but
differ in cause and fix (the fix lives in the solution text), and its small twins failed retrieval;
that is a constructed premise, not an observed fact about real tickets.

## Decision

`ticket.problem_text` is the cleaned title plus description and is the only text that is embedded
into the searched vector (`problem_vec`) and indexed for full text (`problem_tsv`).
`solution_text` is stored cleaned, and a `solution_vec` is stored but not indexed or queried.
Solution text is read only after retrieval: the reranker reads problem and solution together
(ADR 0019).

## Consequences

- Retrieval is driven by how the fault is described, not by how it was closed.
- The fix still reaches the reranker when one is enabled. No display layer exists yet, so how the
  fix is shown with a hit is undecided.
- `solution_vec` costs embedding time and storage today for no query; it is kept so a solution
  arm or a later study does not need a re-index. It can be dropped if it never earns its cost.
- Window A found that about a third of tickets have only a title and that the typical problem text
  is short (around ten tokens), with the solution often longer than the problem, so the problem
  vector is thin for many tickets; title weighting is a recorded idea, not built.
- Enrichment fields (canonical problem, symptoms, components) that the brief wanted in the problem
  vector are not built; the M3 vector is the baseline without them.

## References

- `PROJECT_BRIEF.md` section 6, decision 1; `src/recall/db/migrations/0003_index.sql`
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 1
- `docs/superpowers/specs/2026-11-13-m4-reranker-design.md` (candidate text)
