# Filter tree v2 — exact branches, better editing, exploration and comparison — design

Date: 2026-10-16. Branch: `feat/insight-quality`. Builds on
`2026-10-15-insight-quality-score-design.md` (usable share, filterability, breadth, the 3/5/8/12
word ladder).

## Problem

The corpus builder (`insight/view.py`, view "Corpus builder") works, but on the third real run four
things hurt:

1. **Setting filters is clumsy.** Steps are added from the ⋯ menu or a suggestion and edited in a
   pill; values show no count or quality before they are chosen.
2. **Managing the tree is thin.** Nodes have no names or notes, nothing can be moved, there is one
   tree (in the URL hash) and deltas are always against the parent.
3. **Exploring is manual.** No preview of a step before adding it, no general split, no search for
   good next steps, no view of how branches behave under a stricter word threshold.
4. **Comparing is weak, and mostly estimated.** The quality section is split one dimension at a
   time, so any path combining category, Baugruppe, model or gates is an independence estimate with
   a range. The comparison ranks such guesses as if they were facts and does not show dominance,
   two-path differences or which Baugruppen and models a path drops.

## Decisions (taken with the operator)

- All four areas in one design, built in five stages, each with its own plan and review.
- **A joint quality cube in the report** so common paths get exact numbers; it needs one more
  Window D run.
- **Cube axes:** category, Baugruppe, model and three field gates (error code, description, serial).
- **Adjustable as a lattice:** every combination of up to three axes is released as its own floored
  cut; the view picks the finest released cut that answers a path. (The page cannot recompute
  anything: tickets never leave the airlock.)
- ~~Complementary suppression~~, superseded by **amendment A1**: subtraction is accepted as
  amendment 8 of the stage-1 spec accepts inner counts, and an LP measures how many withheld cells
  the cube newly exposes (`scipy`, already locked).
- **Inline composer per node** for adding and editing steps.
- Management: **named saved trees, node names and notes, drag to move or reorder, pin a baseline.**
- Exploration: **split by every value, ghost preview, auto-explore, threshold sensitivity.**
- Comparison: **Pareto frontier, diff two paths, coverage loss, a certainty grade on every number.**
- **Code split, cube first:** `insight/cube.py` for the report side; the view's model and builder
  move out of `view.py` into `insight/view_model.js` and `insight/view_lab.js`, inlined at render so
  the page stays one offline file.

## 1. The joint quality cube (report side, `insight/cube.py`)

### Axes

| axis | values | notes |
|---|---|---|
| `cat` | released category ids + `other` | single-valued |
| `baug` | the released Baugruppe ids + `none` | **multi-valued**: a ticket counts under each id it carries |
| `model` | models clearing k on their own + `other` + `none` | single-valued |
| `gates` | 8 patterns of (error code, description, serial) present | one axis, three bits |

### Cuts and cells

Every non-empty subset of the four axes with at most three axes: 4 + 6 + 4 = **14 cuts**. A cell
has the shape of `quality._group` without noise reasons: `count`, `noise`, `near_duplicate`,
`retrievable` (tickets usable at 3/5/8/12 words) and `fields`. A cell with `count < k` is withheld
(`k = 50`, the report's floor) and counted in its cut's tally, which has the `release.release`
shape, so the suppression ledger picks it up unchanged. Released under `quality.cube`:

```json
{"gates": "fehlercode+description+serial",
 "measurement": {"withheld_cells": 1000, "checked": 1000, "newly_derivable": 10, "stopped": null},
 "cuts": [{"axes": "cat+baug",
           "cells": [{"cat": "cat-A", "baug": "id-1", "count": 2000, "noise": 30, "...": "..."}],
           "withheld": {"below_floor": {"distinct": 40, "rows": 600},
                        "entity_like": {"distinct": 0, "rows": 0}}}]}
```

The axis values are exactly the values `quality.by_dimension` released (`categoryId`, `baugruppe`,
`model_id`), plus two sentinels: `_other` (a value that is not released there) and `_none` (no
value). The gate pattern is a three-character bit string in the order of `gates` (`"101"`: error
code and serial present, no description).

### Subtraction: accepted, measured (amendment A1)

Overlapping cuts let a reader subtract: a two-axis cell minus the released three-axis cells under
it can be a withheld one. **This is accepted on the same grounds as amendment 8 of the stage-1
spec**: what can be worked out is a count below k, never a ticket or a person, and the existing
report already publishes inner counts of that kind (a Baugruppe's field fills).

It is measured, not gated. `cube.measure` runs an LP over every combination of axis values
(Baugruppe sets up to pairs, plus every combination that occurs) and counts the withheld cells
below k whose value is pinned by the released numbers but was **not** pinned by the report without
the cube. It is published as `quality.cube.measurement` (`withheld_cells`, `checked`,
`newly_derivable`) and printed by the CLI. `--cube-budget` caps its exact LPs (the window pins
1800 s; one pass took 869 s on synthetic data of the real shape); a budget of 0 skips it, and
`checked < withheld_cells` marks a partial measurement. Neither slowness nor a solver failure stops
a run.

### Guard, stand-in, run

- `insight/guard.py` gains rules for `quality.cube`:
  - the cut names, the gate order and the gate patterns are closed literals
  - every released cell has `count ≥ k`
  - every axis value is a released `quality.by_dimension` value or a sentinel
- The stand-in already gives released and withheld cells at `K_TEST`. No new planted rows.
- `scipy` becomes a declared dependency. It is already in `uv.lock` at 1.18.0 through
  `datasketch`, so the image already carries it.
- The Window D rehearsal checks the cube section. Then one real run.

**Expected cost:** most three-axis cells involving `model` will be withheld. That is acceptable;
the view falls back to coarser cuts.

## 2. Estimator and certainty grades (`insight/view_model.js`)

The model code between `(MODEL-BEGIN)` and `(MODEL-END)` moves to `view_model.js`, keeping the
markers so `tests/integration/insight_view_model.js` still extracts it. `profile(steps)` keeps its
signature and resolves a path in three tiers.

1. **Map onto the cube.** Category, Baugruppe and model steps become axis constraints. "Has / has
   no" error code, description and serial become gate-pattern constraints. Filters commute, so step
   order does not matter.
2. **Pick a cut.** Use the cut whose axes equal the constrained cube axes. When all four are
   constrained, use the three-axis cut with the fewest withheld cells among those matching. Sum
   the matching cells for count, usable tickets per threshold, noise and field fills.
   - All matching cells released: **exact**.
   - Some withheld: **bounded**. The low end is the sum of released matches. The high end is the
     coarser cut's total minus its released non-matching cells, and at most k − 1 per withheld
     cell (every withheld cell is below the floor).
   - Baugruppe: "include an id" and "ignore an id" are exact. Including two ids is a union, bounded between
     the larger single value and the sum, and tightened by the released Baugruppe pairs.
3. **Everything else** (year, other dimensions, text terms, other gates) is applied on top of the
   cube result with today's independence estimate and range. The grade becomes **estimated**.

**Grades.** Every displayed number (tickets, usable tickets, usable share, each field, breadth)
carries `exact | bounded | estimated`. A path's grade is its weakest number. Display:

- exact: plain number
- bounded: `lo–hi`
- estimated: `≈ n` with a dotted underline; the tooltip names the estimated steps

**Ranking** (verdicts, frontier, auto-explore) uses the **low end** by default. A toggle switches to
point estimates.

**No cube** (reports from the first three runs): behaviour and output are exactly today's, plus one
note: "exact branch numbers need a report with a quality cube".

Results are cached per canonical path key (sorted steps), because the composer, ghosts and
auto-explore call `profile` many times.

## 3. Setting filters and managing the tree (`insight/view_lab.js`)

### Inline composer

- A "+ step" line under every node, and an edit action on every step chip, open the same composer
  in place. Only one composer is open at a time.
- **Contents:**
  - a kind picker: any dimension, year, field gate or text term
  - an include/ignore toggle
  - a value list in which each value shows count and usable share for *this path plus that value*,
    with its grade
  - a result line for what is ticked
- **Add** appends one step. **Add as branches** adds one child per ticked value.
- Keyboard: Enter adds, Esc closes, arrow keys move through values.
- The pill editor leaves the builder. The global filter drawer is unchanged.

### Names and notes

Each node gets an optional `label` and a one-line `note`. Both appear in the tree, comparison
legends, the table and copy-as-text, and both are encoded (escaped) in the URL hash.

### Baseline

"Pin as baseline" in the ⋯ menu; the root can be the baseline. While one is pinned, every delta
and verdict is measured against it instead of the parent, and a badge marks it. Stored in the hash.

### Move and reorder

- Drag a node onto another node to move its subtree. Dropping onto the node's own subtree is
  refused. Implemented with pointer events.
- "Move up" swaps a node's step with its parent's step. Leaf counts are unchanged; the
  intermediate node changes.
- "Move to…" in the ⋯ menu is the keyboard route for every drag.

### Saved trees

- Save, load, rename and delete named trees in `localStorage` (key `insight.trees.v1`). Every
  access is wrapped in try/catch, and the page works without it.
- Export and import a JSON file through a Blob download and a file input. No network, so the CSP
  holds.
- Each saved tree records a report fingerprint (row count, generated-at). Loading against a
  different run shows a warning. Values missing from the report are flagged on their node, never
  dropped.
- Saved trees hold only released values.

**Undo** covers every action above.

## 4. Exploring branches

### Split by every value

"Split by…" in the ⋯ menu generalises `splitInto` to any dimension, the gate set or year. It shows
all children as ghosts first, then offers **Keep all** or **Keep ticked**. Values with withheld
cells are merged into one "rest (below floor)" child.

### Ghost preview

Hovering or focusing a composer value, suggestion or split option draws a faded, dashed child with
its tickets, usable share and grade. A ghost never touches the tree, the hash or undo.

### Auto-explore

"Find best next steps" on any node.

- **Goal:** at least N usable tickets kept (default a fixed ticket count set in the view); optional breadth floor ("keep every
  Baugruppe with ≥ X tickets").
- **Objective:** maximise usable share at the current threshold, ranked on the low end.
- **Candidates:** single-value include/ignore steps on the cube axes and gates. Other dimensions
  are optional and are marked estimated.
- **Search:** depth 1 or 2, beam width 20. Paths equal up to step order are de-duplicated. The
  search runs in `setTimeout` chunks to keep the page responsive.
- **Output:** up to five distinct proposals as ghost branches, each with a one-line reason (e.g.
  "drops cat-B: −N tickets, +N pts usable, exact"). **Accept** adds one. If nothing meets the
  goal, the page says so and shows the closest proposal.

### Threshold sensitivity

- A 3 / 5 / 8 / 12-word slider above the tree re-scores every node.
- Each compared node shows a mini row of its usable share at all four thresholds.
- Nodes whose rank among the compared paths changes across thresholds are flagged "rank depends
  on threshold".

## 5. Comparing quality

- **Frontier.** The scatter plots usable tickets kept (x) against usable share (y).
  - Bounded and estimated nodes are drawn as boxes.
  - A is dominated by B only if B's worst case beats A's best case on both axes, strictly on at
    least one. Dominated nodes are greyed and labelled "beaten by B".
  - Overlapping nodes are labelled "can't separate".
  - A line joins the non-dominated nodes.
- **Diff two paths.** A Diff button, or Shift-click, picks two nodes. It shows:
  - the shared prefix, the steps only in A and the steps only in B
  - a table of tickets, usable tickets, usable share, models and Baugruppen covered, and each
    field, with deltas and grades
- **Coverage loss.** For each compared node, every Baugruppe and model is marked kept, thinned (lost
  more than half against the baseline) or dropped, with counts. Withheld values show as "< 50",
  never 0. The numbers are exact when the cut used contains that axis, otherwise estimated.
- The heatmap, table and copy-as-text get grade marks, node names and notes.

## Error handling

- **Guard refusal of the cube** (a cell below k, an axis value not released elsewhere, a bad
  literal): the CLI writes nothing, as for any other section.
- **`scipy` missing.** The run fails loudly; the measurement is never silently skipped.
- **Bad import.** An invalid or foreign saved-tree file shows a message, and the current tree is
  untouched.
- **`localStorage` unavailable.** Save and load show "not available in this browser". Export and
  import still work.

## Testing

**Python unit tests**
- cut enumeration and flooring
- the measurement counts a hand-built cell that only the cube makes derivable, and does not count
  one the report already pinned
- the guard rejects a tampered cube (an extra cell, a count below k, an unknown axis value)
- an end-to-end stand-in run

**Node model tests (ground truth)**
- Python writes the true counts for about 200 random paths over the stand-in tickets. `profile()`
  must match them:
  - exact numbers equal the truth
  - bounded ranges contain it
  - estimated ranges contain it wherever their bounds are claimed as guaranteed
- With no cube, the output is identical to today's.

**Node smoke tests**
- composer: add, add as branches, edit
- drag, Move to… and Move up, including a refused drop
- baseline deltas
- saved trees, with `localStorage` stubbed both working and throwing, plus the import round-trip
  and the fingerprint warning
- split, ghosts leaving the hash unchanged
- auto-explore finding the known best path on the stand-in
- frontier dominance and the diff

**Window D rehearsal** covers the cube section.

## Stages

1. **Cube:** `cube.py`, the derivability measurement, guard, rehearsal, runbook. Then the Window D
   run.
2. **Estimator:** the `view_model.js` split, the cube lookup, grades, the no-cube fallback.
3. **Editing and management:** the `view_lab.js` split, composer, names and notes, baseline, move,
   saved trees.
4. **Exploration:** split, ghosts, auto-explore, threshold sensitivity.
5. **Comparison:** frontier, diff, coverage loss, graded table and copy.

Stages 2–5 can be developed against the stand-in while stage 1's window is pending. Each stage gets
its own plan, review and merge.

## Out of scope

- Year as a cube axis (the existing per-year quality split stays the source for year).
- Any per-ticket output, or anything stage 2 of the insight window covers (embeddings, clusters).
- Publishing the page anywhere. It stays a local file (NDA-derived).

## Amendments from planning

- **A1 (2026-10-16, operator decision after prototyping).** Complementary suppression with an LP
  gate was prototyped on the stand-in and did not converge. Cells stayed pinned even with whole
  cuts withheld, because the existing quality section already publishes inner counts (a
  Baugruppe's field fills) that combine with any joint cut. The operator chose to accept
  subtraction on the grounds of stage-1 amendment 8 and to measure it instead: see "Subtraction:
  accepted, measured". The measurement models a reader who does not know which combinations are
  empty (the observed-atoms-only model pinned cells purely from the stand-in's tidy structure).
- **A2 (2026-10-16, review findings during stage 1 execution).** The measurement's reader is given,
  for every combination a cut does not show, only what a reader knows: the cut's withheld tally
  sums over all of them (not just the occupied ones, which would tell it which are empty) and each
  is below k. The result is an LP-reader estimate with no bound in either direction. It records
  why it stopped early (`stopped`: `budget` or `solver`). The guard's cube cross-check follows the
  same path rule as its scan, so a reshaped report cannot skip it.
- **A3 (2026-10-16, stage 2 built).** How the estimator answers from the cube, as decided while
  prototyping and in review:
  - *Swap rule.* A path's cube steps (category, model, Baugruppe, the gates error code /
    description / serial, "has a model id", "names a Baugruppe") are answered from the one cut that
    holds exactly those axes. Other steps keep the independence estimate as a correction,
    `new = old(path) x cube(part) / old(part)`. The range is the old guaranteed range intersected
    with the cube part's (Frechet for the lower end), and estimates never rise above the step
    before.
  - A path the quality section already answers exactly keeps that answer. Ranges are capped by
    the step above. Four constrained cube axes fall back to today's estimate.
  - Worst-case usable comes from the cube where it applies, otherwise from
    `usable(all) - (tickets(all) - tickets(path).lo)`, which is often 0 for year paths. That is
    honest: such a path never wins on a guess.
  - Suggestions are offered when their estimate helps and ordered by the worst case. Filtering on
    the worst case hid every suggestion on uncertain paths.
  - Only the ticket count's grade is displayed. The usable count carries its range for ranking;
    showing it is stage 5's comparison work.
  - A union of several Baugruppen is bounded between the largest part and the sum of parts. The
    tightening by released pairs is not done.
  - Without `provenance.min_frequency` the cube is not used. A cut that withheld a cell as
    entity-like allows its whole tally in any missing cell. `__rest` comes from the cube only
    while every named value is a cube value.
  - *Verdicts are computed on the estimate.* With a cube and "worst case" on, a gain whose
    worst case does not rise above the step before's estimate becomes "Uncertain gain" (exact as a
    guarantee only under an exact parent). The worst case never creates a loss; the
    first version did, calling every unmeasured step "Lowers usable share". The worst-case share
    is guaranteed usable over the most tickets the path can hold. Suggestions are offered on the
    estimate and ordered on that share.
  - *Not done, on purpose:*
    - The dotted underline with its tooltip is on the tree node's count only; other places show
      ≈ without the tooltip.
    - The scenario table's data export carries the point estimate, without its grade.
    - The model's cache is keyed by the steps as given, not the spec's canonical, sorted key.
  - "No cube, no change" is pinned by running the pre-cube model, kept as code
    (`tests/integration/insight_view_model_v1.js`), beside the current one. The plan's frozen
    report and golden answers would have been stored data, which `.gitignore`'s data-safety
    policy forbids.

