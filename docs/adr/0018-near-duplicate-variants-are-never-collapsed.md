# 0018. Different approaches to the same problem are never collapsed to one answer

Status: Accepted
Date: 2026-08-19

## Context

The same fault in the field gets solved in different ways: a different repair, a workaround, a part
swap. A search product that deduplicates to one representative per cluster hides the alternatives
the technician may need. The rule was stated as a user decision on 2026-08-19 (STATE.md, decisions
already made): a group is one problem text with several distinct resolutions, and every resolution
must reach the technician. The 2026-08-19 cluster-structure spec replaced the M2 spec's earlier
wording (variants as different approaches written into the problem text). The M3 spec defines
relevance as "same problem" partly so evaluation matches "every variant resolution must reach the
technician".

## Decision

Retrieval returns near-duplicate and variant tickets; it does not deduplicate, merge or choose a
representative. Relevance in both evaluations is "same problem", so every other member of the
group counts as relevant. Recall is divided by `min(k, |relevant|)` so a large group is not
penalised for being large (ADR 0020). Retrieval is the product and the source list is always
visible; any generated summary is garnish and may not replace it.

## Consequences

- Result lists can contain many near-identical tickets, which costs screen space; presentation
  (grouping with all variants one click away) is a UI decision that has not been made.
- The reranker is judged on whether it separates near-twin recipes without losing members.
- Near-duplicate problem clusters of at least k tickets are nevertheless graded as templated noise
  by the insight quality section, and the catalog's candidate selection reuses that grade (a
  duplicate template adds no information about a problem). That is a corpus-quality judgement,
  deliberately separate from this retrieval rule, which still indexes and returns such tickets.
- The rule covers variant groups of real faults, not the dominant handover cluster, which is a
  form rather than a problem.
- Any later "promote verified suggestions to a curated knowledge base" feature must keep variants
  too.

## References

- `docs/STATE.md` ("Decisions already made"); `docs/superpowers/specs/2026-08-19-cluster-structure-shared-problem-design.md`
- `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md` (Decisions)
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` (Relevance row)
- `PROJECT_BRIEF.md` section 6, decision 7
