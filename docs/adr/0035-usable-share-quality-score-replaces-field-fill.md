# 0035. Corpus quality is a per-ticket "usable share", kept apart from filterability

Status: Accepted
Date: 2026-10-15

## Context

The filter tree's first quality score was the mean fill rate of a few ticked fields. It counted a
solution that is only a workflow note (a callback request, a ticket-closing notice) as filled,
averaged fields instead of tickets, weighted every field equally, let "has serial" gates raise the
score to 100%, had no quality split for most filters, and showed neither size nor breadth. The
second real run showed that the solution field is dominated by workflow notes (this design was
written after that run). The third and fourth runs, after the score was built, showed that delivery
date, warranty and the apparent quality of Baugruppe were the handover-slip category in disguise.

## Decision

Per ticket, and never released per ticket, `insight/quality.py` grades: noise (blank problem text,
or problem text in a near-duplicate cluster of at least k, which catches handover slips without
naming a category, or no content words in the solution once workflow phrases are stripped),
near-duplicate solution, or retrievable at N content words on a ladder of 3, 5, 8 and 12 (default
5). The workflow phrase list is closed and was written from floored, already released solution
trigrams, never from raw text. The usable share is kept apart from a filterability score (metadata
for narrowing) and never blended with it. Verdicts weigh the share against usable tickets given up
and breadth (models and component groups still covered). The report supports a threshold ladder so
the minimum word count can change in the view without another window.

## Consequences

- Dropping the handover category and filtering per ticket on the usable grade became the
  recommendation, rather than filtering on metadata proxies.
- The phrase list is tied to this client's wording and must be maintained when a new run shows new
  boilerplate; the catalog's candidate selection reuses the resulting grade (`quality.grades`: not
  noise, enough content words), not the list directly (ADR 0031). Dates and placeholders such as
  `[TEL]` do not count as content words, and in rare cases a workflow phrase costs a word or two of
  technical text.
- Alternatives set aside: filtering on field fill, and a per-dimension tier split without the
  ladder. Noise reasons (blank, templated, no solution) are released, and a short title can cluster
  as "templated" even when its solution is good.
- A near-duplicate cluster of problem text is judged noise even if it contains a useful solution,
  a deliberate corpus-quality choice distinct from retrieval (ADR 0018).
- One more window run was needed to see the real numbers, and the view falls back to the old score
  for reports without the section.

## References

- `docs/superpowers/specs/2026-10-15-insight-quality-score-design.md`
- `docs/STATE.md` (quality score v2, fourth real run)
- `insight/quality.py`
