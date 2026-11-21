# 0031. An abstract, hand-reviewed problem catalog is the only real-derived release; dev3 is built from it

Status: Accepted
Date: 2026-10-21

## Context

The old fixture matches the real corpus's statistics but its text is generic and its serials do not
form per-vehicle histories. Retrieval work needs believable problems and fixes and vehicles whose
histories exercise same-serial retrieval, near-duplicates and chronology. Real text is under NDA,
and anything an LLM writes after reading real tickets is real-derived, so no real-derived free text
may reach the generator and no per-ticket real text may leave the box. The spec ruled per-ticket
paraphrases and verbatim examples out of scope and chose abstract, hand-reviewed recipes (approach
B). Identity columns stay empty in dev3 (operator ruling, 2026-10-21), and each of the three
vehicles has a different problem profile.

## Decision

Release at the "problem catalog only" level (approach B). In a sealed window (ADR 0032),
`catalog build` removes handover slips and noise, embeds with e5, clusters semantically with
k-means rather than MinHash near-duplicate groups (a plan correction) (fixed K,
capped at eligible tickets divided by k, tickets sorted by a text hash so the result does not depend
on row order), and keeps a cluster as a candidate only if it has at least k = 50 tickets across at
least 5 vehicles and 5 dealers, counted per ticket. A local LLM drafts one abstract recipe per
candidate and refuses a cluster that is not one problem; the draft is scrubbed and checked, the
operator edits it by hand, and only a catalog passing its guard and leak check is released
(ADR 0033). `dev3` reads only that catalog and writes about 450 to 600 invented tickets for three
invented vehicles with ground-truth recipe labels, needing no window.

## Consequences

- The released artifact carries no per-ticket text and no verbatim examples, which makes the
  downstream fixture safe to give to agents.
- The support floor keeps the long tail of rare problems out of any catalog by design, so scores on
  dev3 overstate real recall.
- Real runs yielded only three recipes. Every *incoherent* refusal was "mixed cluster"
  (`gemischt`); other losses were rare words, copied runs and shape problems. Centre-sampling barely
  helped, so the clusters themselves are mixed. A majority rule (at least half the sampled tickets
  agree) and up to three cumulative repair rounds were added along the way. The planner needs at
  least four recipes and the operator has not lowered that, so dev3 runs on an optional invented
  confusable stand-in catalog with four near-twin recipes; that stand-in is what M3 and M4 measured.
- The 2026-11-05 options were: rerun the latest image (built, not shipped), recursively split mixed
  clusters of at least 2k tickets, draft recipes from general domain knowledge flagged by source,
  or build M3 on the stand-in meanwhile. The last was chosen; the others are open, with no schedule
  recorded in the sources.

## References

- `docs/superpowers/specs/2026-10-21-dev3-vehicle-fixture-design.md`
- `docs/handoff-window-e-2026-10-28.md` (updates 2026-11-02 and 2026-11-05)
- `catalog/select.py`, `catalog/build.py`, `dev3/`; commits cf45b40, 1bb7b44, c658bcf, f656ace, eb487f6
