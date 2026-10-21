# Quality score for the corpus builder — design

Date: 2026-10-15. Branch: `feat/insight-quality` (from `feat/insight-view`).

## Problem

The filter tree's "quality score" is the unweighted mean fill rate of a few ticked fields
(solution, description, serial, model id by default). It says little about whether a corpus
would help a technician:

1. **Filled is not good.** A solution that is only a workflow note (such as a callback request) counts as filled; the
   second real run showed the solution field is dominated by such notes.
2. **It averages fields, not tickets.** Half the tickets complete and half empty scores the same
   as every ticket half-filled. Retrieval works per ticket.
3. **Equal weights.** A missing model id costs as much as a missing solution.
4. **Gates feed the score.** A "has serial" step forces serial to 100% and is called a gain.
5. **Most filters have no quality split** (model, Baugruppe, status, lifecycle), so they always
   read "Only shrinks", which is "unknown" dressed as a finding.
6. **No size and no breadth.** a few dozen perfect tickets beat thousands of good ones, and nothing shows a
   path silently dropping whole models or component groups.

## Decisions (taken with the operator)

- **Two scores, kept apart.** A *usable share* (is this ticket retrievable?) and a
  *filterability* score (metadata for narrowing), never blended.
- **Report and view.** A new floored `quality` section in `report.json`; needs one more
  Window D run.
- **Substantive solution = strip, then length** (option B): remove known workflow phrases,
  then require a minimum number of content words and no near-duplicate solution cluster of
  at least k.
- **Verdicts weigh precision, recall and breadth.**
- **Per-dimension tier splits** (option 1), plus: a **threshold ladder** so the minimum word
  count can be changed in the view without another window, and **generic noise** (no category
  id hard-coded).

## Per-ticket grade (report side, `insight/quality.py`)

Computed once per ticket, never released per ticket:

- **problem text**: the cleaned title + description, as `texts` defines it.
- **stripped solution**: the cleaned solution with every `WORKFLOW_PHRASES` match and every
  date removed. The phrase list is our own closed list, written from the floored solution
  trigrams of the second real run (already released, guard-checked), never from raw text. The phrases are workflow boilerplate such as callback
  requests and ticket-closing notices.
- **content words**: tokens of the stripped solution with at least two letters; placeholders
  such as `[TEL]` do not count.
- **noise**: blank problem text, OR problem text in a near-duplicate cluster of at least k
  (`templated`; this is what catches the handover slip without naming its category), OR zero
  content words (no solution, or a solution that is only workflow).
- **near-duplicate solution**: not noise, and the stripped solution sits in a near-duplicate
  cluster of at least k (same MinHash clustering as the problem text, over sorted documents).
- **retrievable at N**: not noise, not a near-duplicate solution, and at least N content words.
  `LADDER = (3, 5, 8, 12)`, default 5.
- **thin** is everything else and is derived (count − noise − retrievable), not released.

## Report section `quality`

Every group has one shape:

```
{ "count": n, "noise": int, "near_duplicate": int,
  "retrievable": [{"min_words": N, "tickets": int} for N in LADDER],
  "fields": {"description": int, "solutions": int, "serial": int, "model_id": int,
             "baugruppe": int, "fehlercode": int, "hours": int, "delivery": int} }
```

`fields` counts tickets in the group whose field is filled, with the meaning of
`timeline._FILLED`. Layout:

```
quality:
  default_min_words: 5
  phrases: <number of workflow phrases>
  overall: group
  by_year: [{year, ...group}], by_year_withheld
  by_field: {<field>: group of the tickets where the field is filled}
  by_dimension:
    <each dimensions.COLUMNS column>, model_id, baugruppe:
      values: [{value, ...group}], withheld,
      by_year: [{value, year, ...group}], by_year_withheld
  by_lifecycle:
    hours / days_since_delivery: buckets: [{bucket, ...group}], buckets_withheld
    warranty: states: [{state, ...group}], states_withheld
```

Floors: every released label (value, year cell, bucket, state) goes through `release.release`
with the usual sweep, so its `count` is at least k. Counts inside a group (noise, retrievable, a
field) may be below k: a count is not personal data (spec amendment 8 of the stage-1 report).
Baugruppe is multi-valued: a ticket counts once under each id it carries. The model dimension is
keyed `model_id` because `model` is a released field name the guard refuses as a dict key.

The guard gains the new keys, the new withheld sections, `RELEASED_AT` paths, year paths and
bucket/state literals. Nothing else in the report changes.

## View (corpus builder)

When `quality` is present:

- **Usable share** (precision): estimated retrievable tickets / tickets, at the chosen N.
  Single-step nodes are measured exactly for every dimension, every year, and every field gate
  (`by_field`); year × dimension uses the cross cells. Several constraints combine the way
  `filledOf` already combines year and category (product of rates over the overall rate). Steps
  with no split (repeat ticket, identifiers, words) contribute nothing and mark the node estimated.
- **Usable kept** (recall): the node's retrievable tickets / all retrievable tickets.
- **Filterability**: the mean fill of the fields ticked above the tree, now measured per group
  instead of only for year and category. It is shown but does not feed the verdict.
- **Breadth**: models and Baugruppen with at least one estimated retrievable ticket in the node,
  against the root ("most of the models").
- **Verdict** (parent → child): *No effect*; *Lowers usable share*; *Strong gain* (usable share
  up and at least 95% of the usable tickets kept); *Good trade* (up, at least 80% kept); *Costly*
  (up, less than 80% kept); *Only shrinks* (flat and measured); *Effect unknown* (flat and not
  measured). A step that drops a model or Baugruppe entirely adds a breadth warning.
- **N selector**: "a real solution has at least 3 / 5 / 8 / 12 words", default from the report.
- Suggestions rank steps by usable-share gain per usable ticket given up.

Without a `quality` section (an older report), the view keeps the old fill-based score under its
old name.

## Testing

- `tests/unit/test_insight_quality.py`: hand-computed grades on a small set (workflow-only
  solution is noise, templated problem is noise, short solution is thin at 5 and retrievable at 3,
  near-duplicate solutions are thin, dates and placeholders do not count); group shape; floors and
  withheld tallies; multi-valued Baugruppe; row-order independence; the stand-in report passes
  the guard.
- Guard tests: the new keys are accepted only at their paths; a released value in `quality` below
  the floor is refused.
- `tests/integration/insight_view_model.js`: usable share in [0, 1]; single-step nodes equal the
  report's group exactly; recall ≤ 1 and monotone along a chain; the verdict for an include of
  only noise-free values is never "Lowers"; no NaN over the random chains.

## Out of scope

LLM judgement of solution substance (stage 2), category × dimension crosses, a tier cube.

## Amendments from review (2026-10-15)

1. **Noise reasons are released** for `overall` and every `by_year` entry as
   `noise_reasons: {blank, templated, no_solution}` (first rule that applies). A short-title
   problem text can cluster at Jaccard 0.7 and be called templated although its solution is good;
   without the split the real run could not show that happening.
2. **A leading greeting is removed before cleaning.** `pipeline.clean` cuts a signature from its
   sign-off to the end, so a greeting followed by a short repair note used to become empty and be graded noise.
3. **Overlapping Baugruppen.** Excluding several ids is one part per id (combined like separate
   steps); summing them double-subtracted tickets carrying both and could show a 100% usable
   share. Including several ids sums overlapping groups and is marked as an estimate.
4. **A withheld year cell is missing, not zero.** The year-cross path marks the node as an estimate
   when a chosen value's cell in a chosen year is under the floor, and a node is only exact if its
   ticket count is exact too.
5. **Cached profiles keep their own copy of the steps**, because the tree edits steps in place.
6. **Residual, accepted:** a released value's group minus its released by-year cells gives the group
   vector (grade and fill counts) of the withheld cells, possibly one ticket. The attributes are fill
   booleans and a grade, within amendment 8 of the stage-1 spec.
7. **Known limits:** Baugruppe values are not capped in `quality` (the view's dimension list stops at
   100, so breadth counts at most 100); `quality.py` reuses private helpers of `timeline`,
   `dimensions` and `lifecycle` rather than duplicating their definitions. Workflow phrases cost a
   word or two of technical text in rare cases (a phrase that is both workflow wording and a technical symptom).
