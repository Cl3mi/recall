# Project state — 2026-08-19

**Read this first**, then `PROJECT_BRIEF.md`, then `docs/airlock-runbook.md`. This is the
resume point after a context clear. Last updated 2026-08-19 after finding 3 was closed, four
real H100 generation rounds ran, and findings 7, 8 and 9 were opened - 7 and 8 closed, 9 open -
on `feat/m2-fixture-generator`.

## Binding constraint

**Never read anything under `local/quarantine/` or `<export-dir>/`.** Those hold the
client's real ticket export under NDA. `local/artifacts/` IS readable — it holds profile
artifacts that have passed the safety gate.

Before reading any artifact, gate it:

```bash
uv run python -c "
import json, pathlib, sys; sys.path.insert(0,'.')
from profiler import blessing
p = json.loads(pathlib.Path('local/artifacts/profile.json').read_text())
print('unblessed:', len(blessing.unblessed(p)))"
```

`0` means every string in it is accounted for and it is safe to read. Non-zero means
stop — print paths only, never the offending values.

## Insight window, Plan 1 — BUILT 2026-10-11, merged with v2 (2026-10-13)

`python -m insight --csv <export> --out report.json` reads the 38-column export and writes a
`report.json` an AI may read: where tickets come from (Baugruppe, vehicles, title tokens, one
Baugruppe x model x year cross-tab) plus model-free text evidence. Every released value is floored
(`k = 50`) and swept by `insight/release.py`; `insight/guard.py` re-checks the finished report as a
closed allowlist and the CLI writes nothing unless it passes. It is **stage 1 only**: no model, no
GPU, no clusters, no labels. Design: `docs/superpowers/specs/2026-10-11-insight-window-report-design.md`
(its "Amendments from planning" lists 14 deviations found against the code). Plan:
`docs/superpowers/plans/2026-10-11-insight-stage1-deterministic-report.md`.

**Verified, not asserted:** 176 new tests pass; the full suite is **507 passed, 7 skipped, 0 failed**
in a pristine worktree (the baseline before this work was 331); `ruff` is clean repo-wide; all 19
code blocks in the plan are byte-identical to the committed tree. Run it with
`.venv/bin/python -m pytest` (`uv` is gone); the two Postgres files need `PG_DSN` and were excluded.

**Operator decisions still open — none were taken for you:**

1. **`--serial-prefixes` is off by default.** `vehicleSerialNo` is on `DENYLISTED_COLUMNS`; a prefix
   bucket is a loosening only you may allow. Buckets need k distinct *vehicles*, never more than half
   of any serial, never more than 8 characters.
2. **`insight.guard` sits beside `profiler.blessing`**, because `blessing` is bound to
   `profiler/schema.json`. Say so if you would rather extend `blessing`.
3. **The floor is a CLI argument.** `--min-frequency` below 50 is refused unless `--allow-weak-floor`
   is passed, but Plan 3's `window.sh` must still pin `50` and leave serial prefixes to your ruling.

**Known residuals, accepted and written down (spec amendments 8, 10, 12):** margins, cells and the
withheld tally are all published, so one withheld cell in a margin can be inferred (a count below k,
not personal data); `tickets_per_serial_quantiles.max` is unfloored; an uncommon lowercase name in a
free-text token that clears k would pass `profiler.entities`, which is an inherited limit.

**A finding about your data, not only about the code (amendment 11):** the cleaning pipeline's phone
pattern redacts a part number such as `1234.56789` as `[TEL]`. The report now gives identifier density
raw and after cleaning, so that loss will show up as a number on the first real run.

**Process:** every task went through implement -> spec check -> review, and every review found
something real: a bucket floor counting tickets instead of vehicles, a guard that accepted tuples and
all-digit keys, `--out` overwriting the input, row-order-dependent clustering, a part number lost to
the phone pattern. Each fix has a test that fails on the old code or under mutation.

### Report v2 — BUILT 2026-10-13, RUN FOR REAL 2026-10-13, MERGED; findings below

**The first real run (2026-10-12) worked except Baugruppe, which came back EMPTY (almost no
ticket had one).** Cause, now fixed: a Baugruppe value is a LIST of numeric id strings (`['5', '12']`,
sometimes `[]`), and the extractor only accepted a plain string. The stand-in had encoded the same
wrong assumption, so the tests agreed with the bug. Findings from that run that stand: handover
forms are a small minority of tickets; about three quarters of tickets are singletons; the cleaning
step destroys every part number (the identifier counts drop to zero after cleaning); real
`fehlercode` values look like `1234-5`, not the `[A-Z]{1,3}\d{3,5}` the identifier regex knows; about
a third of tickets have no model id and most have no `vehicleYear`; more than half of tickets are on
vehicles with another ticket; a first name slipped through the name sweep (it was released in the
title tokens). Design: `docs/superpowers/specs/2026-10-12-insight-report-v2-design.md`.

v2 keeps Baugruppe (fixed) and adds ten aggregate sections, all floored at k=50, swept and guarded:
formats (shapes of serial/model/vehicle id/ticket number/codes/dates, distinct-value floored for the
identifier columns), volume and fill over time, dimensions by year and category, concentration of
dealers/customers/users as NUMBERS ONLY (no id is released: operator ruling), vehicle lifecycle
(hours, days since delivery, warranty), recurrence, the `fehlercode` field, title and solution
n-grams plus per-category words, and RAG-readiness counts (templated, usable, duplicate solutions).

Hardening that the adversarial review forced, each with a test that fails on the old code:
the floor counts TICKETS not occurrences (one ticket repeating a name 60 times used to release it);
surname list and 1,100+ first names, applied to free text AND to code fields; shapes of identifier
columns need k distinct values; quantiles never release `p1`/`max` and are whole numbers; the guard
accepts a released string only at its declared path, refuses non-string released fields, non-finite
numbers, malformed shapes and years outside declared paths; the extractor drops implausible hours and
years and no longer aborts on a 128 KiB cell. Window A's `profiler/stats/clusters.py` gained a public
`groups()`; its `profile()` output is byte-identical.

**Verified:** 818 insight and related tests pass; the whole repo is 1,029 passed, 7 skipped, plus one
environment failure (`test_the_test_suite_does_not_dirty_the_quarantine`, see below); `ruff` clean;
`make window-d-rehearsal` is **46 passed, 0 failed** against an image built from a pristine checkout
of this branch; `report.build` takes ~16 s and ~240 MB for the full export and scales linearly.

**Residuals, accepted and written down:** a deny-list of names cannot be complete (an uncommon name
that clears 50 tickets would pass); extremes are bounded not hidden; every NEW entry list a builder adds
must also be declared in `guard.RELEASED_AT`, or the real run is refused (nothing leaks, the window is
spent); ids are opaque, so which Baugruppe or model an id is needs the client's lookup tables.

**Second real run, 2026-10-13: done.** Guard passed (`unaccounted: 0`), `selfcheck` passed,
`min_frequency` 50, serial prefixes off, full export, Baugruppe coverage about a quarter (fixed). The workstation
quarantine was shredded and `make check-clean` is clean. `report.json` is in `local/artifacts/`
(gitignored). No person, dealer or customer name appeared in any released token list.

#### What the report says (decisions for the RAG strategy)

- **Where tickets come from.** Category cat-A is about three quarters of tickets; cat-B is about a
  sixth and is ONLY the handover slip (title always the same; about a third of them have a solution,
  holding administrative notes about creating forms or extending the warranty): noise for a
  troubleshooting RAG. cat-C (a separate product line) and cat-D are small. Baugruppe: only about a
  quarter filled (a bit more in the export's last year), about ten distinct opaque ids, two ids
  dominate, a minority of tickets carry 2-3 ids. Weak as a filter without the client's lookup table.
  Models: dozens of distinct ids, about two thirds filled, no model dominates. Serial number is
  filled for over 90% of tickets, across thousands of vehicles.
- **Model id collapsed recently:** fill fell from over 90% to about a quarter over the last three
  years while the serial stays filled. Derive the model from the serial/`vehicleId` at ingestion.
  `vehicleId` is NOT a clean key: a sizeable number of vehicle ids span several serials.
- **Serial shapes:** a letter plus 12 digits and 8 digits dominate; the rest are three letters plus
  9 digits and a 16-char variant. More than half of vehicles with a serial have repeat tickets, and
  over a third of tickets have an earlier ticket on the same serial. About a third of repeats come
  within 30 days, about half within 90 days and most within a year; the median gap is about three
  months. Same-serial history is a strong retrieval signal.
- **Concentration:** about a thousand dealers with no dominant one, thousands of end customers (about
  half filled), a few dozen creating users of which the top five create nearly all tickets. None is
  a useful narrowing key.
- **Solutions are mostly workflow notes, not fixes.** The most frequent trigrams are workflow
  boilerplate such as callback requests, ticket-closing notices, warranty-extension notes, goodwill
  approvals and duplicate-ticket references. Technical content is thinner (dealer checks,
  connectors, sensors, wiring, replaced parts). Strip this boilerplate before embedding.
- **Readiness:** nearly nine in ten tickets have a solution; about 60% have title+description+solution;
  a small minority are templated; about 80% are "usable"; blank problem text 0. Description fill is
  about half in the two middle years but about 80% in the earliest and latest two: about half of the
  older tickets are title-only. Volume is flat, hundreds of tickets per month.
- **Sparse fields:** `fehlercode` is filled for under a fifth of tickets (rising over the years; shapes
  `DDDD-DD`, `DDDD-D`, `ALL_DD`; about a fifth of those tickets hold several codes), hours for a small
  minority, delivery/warranty dates for the handover-slip minority (nearly all in warranty, shortly
  after delivery), resolution timing for a few percent (useless). Inline identifiers in free text are
  rare (a few percent).
- **Suspect, check before relying on it:** `readiness.duplicate_solution_share` is 0.0 although the
  solutions are heavily templated.

**Strategy implications, in order:** (1) filter category cat-B and optionally empty-solution tickets
(most of the corpus remains as clean technical tickets); (2) strip workflow boilerplate from solutions
before embedding; (3) filter on vehicle model and serial, derive missing models, add a same-serial
history step; (4) keep `fehlercode` as a list-valued exact-match field; (5) title-weight tickets
without description; (6) ask the client for the Baugruppe and model lookup tables once there is a prototype.

**HTML view (2026-10-13, branch `feat/insight-view`):** `python -m insight.view report.json report.html`
writes one offline, self-contained page: 12 views grouped in a side nav (overview with computed
"what stands out", time, categories, vehicles, Baugruppe, lifecycle, text, concentration, data quality, withheld,
raw), chart type chosen per data job (line, columns, stacked mix, heatmaps, box plots, part-to-whole, bars,
tables), a description and "how to read" under each heading, and a sticky GLOBAL FILTER bar (year, category,
Baugruppe, model, search, min count; click bars/cells/legend to set; per-filter x and Reset all; state lives in the
URL hash). Filters are one ordered list of steps (G.steps) shared by the sticky filter bar and the builder: dimensions (category, status,
priority, sub-status, vehicle status, handover-slip flag, model, Baugruppe, warranty, hours/day buckets), year, yes/no facts (field filled
or missing, repeat ticket, ids in text) and frequent title/solution terms; each has "only"/"without" (or require/exclude).
The bar shows the live impact (tickets left, quality score, field fills), each filter pill shows what it removed, and a step
search (press /, or + Add filter / + Step) previews every candidate's effect; clicking bars, columns, terms and fields adds
filters. The filters travel in the address (#g=...). "Open in builder" and "→ Filters" copy steps both ways. Every filter has a three-state control (Include / Ignore / Not set) in the drawer rows, the active-filter list, the pill editor and each builder node; the state is always read from the steps (choiceSteps/rowState, property-tested in node). The builder tree has connectors, a node menu (branch, duplicate, flip, collapse, remove-keep-below), undo and compare shortcuts. Every builder node shows the fill of each chosen quality field (and its change vs. the step above) plus a verdict (strong gain / good trade / costly gain / only shrinks / lowers quality); a Decision guide card explains the selected step (before/after per field, each value on its own, best next steps) and a ladder card shows tickets and fields along the whole path. LIMIT: the report splits solution/description only by category and every field only by year; there is NO quality split by vehicle model, Baugruppe, status etc., so those filters change size but quality stays at the overall rate (marked with *). A field-by-model table would need a report extension (airlock window, not started). The "Corpus builder" view (group Decide) is for the RAG decision: a tree of steps (category in/out,
year, require-field gates), branches, ranked next-step suggestions, and a comparison of ticked nodes (size vs quality
scatter, quality heatmap, table, copy as text). The report has no joint distribution, so counts are exact for one
category or year alone, otherwise a guaranteed range plus an independence estimate; known totals (complete_triple,
usable) tighten the root. Exact counts for any combination need a joint quality cube in a later report (another
airlock window, not started). The model and every view/flow are tested in node (tests/integration/insight_view_model.js and insight_view_smoke.js, stub DOM). A filter only slices what the report already split that way; every card says which filters it
responds to or ignores. It runs the guard first and refuses a report the guard rejects. The page is a LOCAL file: no network (CSP forbids it),
values reach the DOM only via `textContent`, never publish it as a hosted artifact (NDA-derived).

**Next, not started:** stage 2 (embeddings, clusters, labels, review) needs another airlock window;
an HTML view of `report.json` needs no real data.

### Filter tree v2, stage 1 (joint quality cube) — BUILT 2026-10-16 on `feat/insight-cube` (from `feat/insight-quality`), NOT RUN FOR REAL

The filter tree's branches are estimates because the quality section splits one dimension at a
time. Stage 1 of the filter tree v2 spec adds `quality.cube` to `report.json`: 14 cuts (every
combination of up to three of category, Baugruppe, model and a 3-bit gate pattern - error code,
description, serial), each cell shaped like a quality group and floored at k. Axis values are
exactly what `quality.by_dimension` released, plus `_other` and `_none`; the guard cross-checks
that for every shape `_scan` reaches. Spec:
`docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md` (section 1, amendment A1);
plan: `docs/superpowers/plans/2026-10-16-insight-filter-tree-v2-stage1-cube.md` (see its
"Amendments during execution").

**Amendment A1 (operator decision, 2026-10-16):** complementary suppression with an LP gate was
prototyped and did not converge on the stand-in - the quality section's inner counts already pin
cells once any joint cut exists. Subtraction across cuts is accepted as stage-1 amendment 8
accepts inner counts, and MEASURED: `quality.cube.measurement` = withheld cells below k, how many
were checked, how many the cube newly pins (an LP-reader estimate, no bound either way), and
`stopped` (`budget`, `solver` or null). `--cube-budget` (window: 1800 s) caps it; it never fails a
run. One pass took 869 s on synthetic data of the real shape. On the stand-in (k=20): 80 withheld,
24 newly derivable.

**Review findings fixed during execution (each with a test that fails on the old code):** a guard
bypass - a report reshaped with dicts or nested lists skipped the cube's value cross-check; the
measurement's tallies told the solver which combinations are empty; solver failures were
swallowed with no trace; the budget did not cover the screens; a released value spelled like a
sentinel; a blank Baugruppe id; the guard did not floor gates-only cube cells; `checked` counted a
cell whose LP failed.

**Operator to do before the next Window D:** `uv.lock` was edited by hand to declare scipy (it
was already locked through datasketch) because `uv` is not installed on the workstation - run
`uv lock --check` where uv exists. Then rebuild and ship the image (`infra/profiler/window.sh
ship`) and `make window-d-rehearsal`. One Window D run gives the real cube.

**Next:** stages 2-5 of the spec (estimator and certainty grades, composer and tree management,
exploration, comparison) are view work and can be built against the stand-in now.

#### Fourth real run (Window D, 2026-10-16): done

Floor 50, full export, guard passed, `unaccounted: 0` with this branch's guard, quarantine
shredded. `local/artifacts/report.json`; the third run is kept as `report.run3-2026-10-15.json`.
Run took 32 min; the measurement stopped on its budget after checking most of the withheld cells,
and only a small share of those were newly derivable. Cube: one-axis cuts withhold nothing; two-axis
cuts release a few dozen cells; `baug+model+gates` withholds many cells (a small share of rows), as
expected.

What the cube says (usable share at >= 5 words):
- **Drop cat-B and nothing else is needed at category level.** cat-A is about 85% usable and cat-C
  about three quarters; together they are the bulk of the corpus and mostly usable. cat-D and
  `_other` are small and mostly unusable - negligible either way.
- **The gates only looked useful because of the handover slips.** Overall "serial only" (`001`) is
  about half usable, but nearly half of its tickets are cat-B; inside cat-A it is about 85%, about
  the same as having a description (`011`, `111` about 90%). Error code without a description
  (`101`) is the one weak pattern in cat-A: about two thirds usable, about a quarter noise.
- **Baugruppe is a filter for narrowing a search, not a quality gate.** In cat-A: without one about
  85% usable, with one somewhat higher; requiring it would cost about two thirds of the tickets for
  a few points. cat-C has no Baugruppe at all. (The third run's "Baugruppe is the best quality
  signal" was the handover category in disguise.)
- **Models are fine after the drop.** About thirty released models in cat-A, most 70-90% usable;
  only one stands out (noisier, few tickets).
- Recommendation: corpus = everything except cat-B, and filter per ticket with the usable grade
  itself (`insight/quality.py`'s rule) rather than with metadata proxies.

### Filter tree v2, stage 2 (certainty grades) — BUILT 2026-10-16 on `feat/filter-tree-grades` (from `feat/insight-quality`)

The view's corpus model now lives in `insight/view_model.js` (inlined at render; the page is
byte-identical for the same report). It answers a path's cube steps from `quality.cube`, and the
other steps keep the old independence estimate as a correction. Every count is graded **exact**,
**bounded** (a guaranteed from-to range from withheld cells) or **estimated** (≈, with the
estimated steps in a tooltip). Verdicts and suggestions rank on the worst case while the report
has a cube; a "Rank on" toggle switches to the estimate (`rk=e` in the address). A report without
a cube behaves exactly as before. Spec: section 2 and amendment A3.
Plan: `docs/superpowers/plans/2026-10-16-insight-filter-tree-v2-stage2-grades.md`.

Pinned by tests:
- "No cube, no change": the pre-cube model, kept as code in
  `tests/integration/insight_view_model_v1.js`, runs beside the current one. No data file is
  stored, per `.gitignore`.
- Ground truth: 1,500 paths of up to four steps at every word threshold, counted from the
  stand-in's tickets.
- Two drifted-report cases: a missing floor, and entity-like withheld cells.
- A reviewer ran about 25,000 further generated paths: 0 violations.
- Page checks (`tests/integration/insight_view_checks.js`, run inside the page): an unmeasured step is
  never a loss, an uncertain gain is never promised, a range reads from-to, and the page without a
  cube behaves as before.

On the real fourth-run report the model and smoke harnesses pass. Exact: dropping cat-B, cat-A
alone, and cat-A plus description. Bounded: dropping cat-B plus one Baugruppe id (a narrow range).

**Open minors from the re-review (not needed for correctness):** a check for the cube-only
`guessNote` and the tile's "· range"; mark uncertain suggestions ("· uncertain") in the palette;
`page_check` runs its section twice (the "with filters" view also matches `ONLY`).

**Next:** stage 3 (inline composer, node names and notes, baseline, move, saved trees).

### Quality score v2 — BUILT 2026-10-15 on `feat/insight-quality` (from `feat/insight-view`), RUN FOR REAL 2026-10-15

The filter tree's "quality score" (mean fill of a few fields) is replaced by a **usable share**: per
ticket, real problem text and a solution of at least N words once workflow notes are stripped
(`insight/quality.py`, phrase list written from the second run's floored trigrams). Filterability
(field fill), usable tickets kept and breadth (models/Baugruppen still covered) stand beside it;
verdicts weigh usable share against usable tickets given up. Spec with review amendments:
`docs/superpowers/specs/2026-10-15-insight-quality-score-design.md`.

**Third real run, 2026-10-15: done.** Commit `d3bdc8a`, floor 50, full export, selfcheck passed, guard
`unaccounted: 0`, box quarantine holds only aggregates, `make check-clean` clean. `report.json` in
`local/artifacts/` (the second run is kept as `report.run2-2026-10-13.json`); `report.html` rendered from it.

#### What the quality section says

- **Usable share, all tickets:** about three quarters at >=3 words, **about 70% at 5**, falling to
  about half at 12. The old "usable" (solution present, not templated) said about 80%: stripping
  workflow notes removes a few percent more. Noise is about a fifth, mostly templated, plus tickets
  with no solution left, and no blank problem text. Near-duplicate solutions are rare.
- **Category cat-B is almost all noise** (nearly none usable at 5): drop it. cat-A is about 85%
  usable, cat-C about three quarters, cat-D about 40% (very few tickets). Without cat-B: most of the
  corpus, about 85% usable.
- **Delivery date and warranty are handover-slip fields.** Tickets with a delivery date are almost
  all noise and have the same usable counts as cat-B; warranty "in" likewise. They are no filter for
  a troubleshooting corpus. Hours present: about half noise.
- **Models look noisy only because handover slips carry model ids** (the top models look a third to
  nearly half noise; `model_id` present about a quarter noise). Re-judge per model after dropping
  cat-B.
- **Baugruppe looked like the best quality signal:** tickets with one are more usable than average
  and every one of the ids is high (later shown to be the handover category in disguise, see the
  fourth run). Error code present and description present are both high.
- **Status is useless** (one value on nearly all tickets). The earliest year holds very few
  tickets, mostly without solution.
- A few dozen models and about ten Baugruppen released in the quality split.

**Earlier note, kept for context:** this needed one more Window D run (the report gains a `quality` section; the view falls back to the old
score without it). Rebuild and re-ship the image first: `insight/quality.py` must be baked in. On that
run, read first: `quality.overall.noise_reasons` (is `templated` eating good tickets?), the retrievable
ladder at 3/5/8/12 words, and whether category cat-B comes out almost all noise.

**Stale tests, not caused by this work:** `test_on_the_first_real_run_exactly_one_released_title_token_is_a_first_name`
and `test_real_title_tokens_are_swept_when_the_artifact_is_present` expect the FIRST run's artifact
(a first name in the title tokens); `local/artifacts/report.json` now holds the second run. Suite otherwise
green (1,060+ passed).

### Window D — RUN FOR REAL (2026-10-12 and 2026-10-13), merged with v2

`window.sh --window d` runs the report on the box in the existing sealed image. Decisions taken
with the operator: code **baked into the image**, serial prefixes **off**, floor 50, no GPU. Spec:
`docs/superpowers/specs/2026-10-12-insight-window-d-design.md`; runbook: "Window D" in
`docs/airlock-runbook.md`. **`make window-d-rehearsal` is green: 45 passed, 0 failed**, run in a
pristine checkout against a freshly built image, offline. An 11-test contract file
(`tests/unit/test_window_d_contract.py`) pins the sealed command, the one-file allowlist and the
shred list from `--dry-run`.

**What is left is yours, and AI-free** (the runbook has the full checklist):
1. `<export-dir>/`: a real export must not stay on this workstation. Resolve it first.
2. `infra/profiler/window.sh ship` — about an hour (the 9.3 GB image CHANGED: `insight` is baked in).
   The local `recall/profiler:pinned` is already the rehearsed build.
3. `window.sh --window d --csv <export> push`, then `run`, then `verify`. **Not `all`**: it ships
   the image a second time.
4. Read `report.json` in full on the box, then `fetch --clean`, then `make check-clean` unsandboxed.
5. Before an AI reads it: `.venv/bin/python -c "import json; from insight import guard; ..."` must
   print `unaccounted: 0` (exact command in the runbook).

**What the first real run will tell you that the stand-in cannot:** whether `baugruppe` is found in
the real `customData` (coverage of about a quarter expected; 0.0 means the window was spent), how many part
numbers the cleaning pipeline loses (`tickets` vs `tickets_after_cleaning`), and the real shape of
the title vocabulary. A rehearsal false positive worth remembering: floored title words ARE released on purpose; the property that matters is that no contiguous raw phrase
is (finding of 2026-10-12, fixed in both the rehearsal and the pytest check).

**Next:** Plan 2 (stage 2: e5 embeddings, clusters, LLM labels, your review step, leave-one-out
coverage and field ablation) and the HTML view. Plan 2 should write its label-scrub tests first.

**A warning about a dirty directory:** `.worktrees/feat-insight-stage1/local/quarantine` showed
leftovers after review agents ran probe scripts outside pytest (the detail log's default path is
relative to the cwd). The suite itself is clean. Inspect with `make check-clean` and shred it yourself,
without an AI tool; it is gitignored and holds synthetic strings only.

## READ FIRST IF IT IS THE MORNING OF 2026-09-08 — an overnight test ran on the box

Launched 2026-09-08 ~00:25 local (22:25 UTC), **detached** on `hpc` under `setsid` (its own
session leader, no controlling terminal), so it survived the workstation being shut down. It is
**synthetic-only** and never touched `<data-dir>/recall-quarantine`.

Scratch dir on the box: **`<data-dir>/recall-window-b-overnight`**

```bash
ssh hpc 'cat  <data-dir>/recall-window-b-overnight/SUMMARY.txt'
ssh hpc 'tail -120 <data-dir>/recall-window-b-overnight/overnight.log'
scp hpc:<data-dir>/recall-window-b-overnight/overnight.log local/artifacts/
scp hpc:<data-dir>/recall-window-b-overnight/q/gate_report.json \
    local/artifacts/gate_report.overnight.json
# when finished with it:
ssh hpc 'rm -rf <data-dir>/recall-window-b-overnight'
```

**The box now has the real image.** `window.sh ship` transferred it in 24m48s; `podman images`
shows `recall/profiler:pinned` at **3.55 GB**, replacing the stale 415 MB pre-weights build, and
`podman run --rm --network=none recall/profiler:pinned` loads
`e5:intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` on the box.

**FINISHED 2026-09-07 22:45 UTC — 13 passed, 1 failed.** The one failure is finding 16 below and
is a real result, not a script bug. Artifacts already pulled to the workstation:
`local/artifacts/overnight-window-b.log`, `overnight-window-b-SUMMARY.txt`,
`gate_report.overnight.json` (all uncommitted, `git ls-files local/` is still 0).

Gate on 1500+1500 `--fake` rows, 32 of 256 threads, **exit 0 after 173s**:

| | |
|---|---:|
| `embedder_is_a_model` | **true** — first time from a sealed container |
| `verdict` | green |
| `cross_p99` | 0.989657 |
| `baseline_p95` | 0.99727 |
| `baseline_saturated` | false |
| embedding width / cuda build | 1024 / `None` |
| `manifest.code_commit` | **`unknown`** |
| `manifest.image_digest` | **`unknown`** |
| corpus tokens found in the report | **none** |

Note how little that green means on `--fake` data: the baseline is 0.99727, just under the 0.999
saturation flag, against a cross tail of 0.989657. Both corpora are templated stub text sitting
almost on top of each other. This is exactly why the rehearsal **records** the verdict rather than
asserting it — a green here would have been green for the wrong reason.

### 18. Finding 12's calibration was measured with the STUB — re-measured with e5, and p95 SURVIVES

Done 2026-09-08, the first thing that was checkable only after Plan B existed. Plan A had no
model, so **every number in finding 12 is a `HashingEmbedder` number** — including the p75/p50
"would fail a clean fixture" conclusions that settled `BASELINE_PERCENTILE = 95`. The real e5 has
a different cosine distribution entirely (it scores unrelated German high), so whether that choice
transfers was an open question that nobody had asked.

**Premise verified first, not assumed.** Re-running the stub reproduces finding 12 essentially
exactly: `cross_p99` 0.898644 (recorded: 0.898644), baseline p95 0.966890 (recorded: 0.96689),
41 of 1500 rows twinned at >0.999 (recorded: 41, 2.7%). So they are indeed stub numbers.

Then the same computation with `E5Embedder`, round 7 (`local/fixtures/export.csv`) against round 3
— the only genuinely independent parked corpus, 0.1% document overlap:

| | HashingEmbedder | **E5Embedder** |
|---|---:|---:|
| `cross_p99`, the clean comparison | 0.898644 | **0.965460** |
| baseline p99 | 1.000000 (saturated) | 1.000000 (saturated) |
| **baseline p95 — in use** | 0.966890 | **0.997127** |
| **margin at p95** | **+0.068246** | **+0.031668** |
| baseline p90 | 0.944651 | 0.991641 |
| baseline p75 | 0.859467 (**FAIL**, −0.039) | 0.970393 (**pass**, +0.0049) |
| baseline p50 | 0.764122 (FAIL, −0.135) | 0.942928 (FAIL, −0.023) |
| rows twinned at >0.999 | 41 of 1500 (2.7%) | **53 of 1500 (3.5%)** |

**The decision holds: p95 is still correct and still not saturated. Do not relitigate it.** But
three things moved and matter for the window:

1. **The margin halved**, 0.068 → 0.032. Less headroom than finding 12 believed.
2. **The twin fraction rose from 2.7% to 3.5%**, against the 5% that saturates p95 — so
   `baseline_saturated` is roughly 30% closer to firing than finding 12's figure implied. e5 sees
   more near-duplicates than a character-trigram hash does. A future fixture with more cluster
   mass will hit that guard sooner than 2.7% suggested.
3. **Finding 12's argument for rejecting p75 and p50 does not transfer.** Under e5, p75 clears a
   clean comparison (barely) and only p50 would false-alarm. The conclusion survives; the
   reasoning behind it was stub-specific and should not be quoted as if it were embedder-agnostic.

**A hypothesis of mine that was wrong, recorded as such:** I expected the calibration might not
transfer — possibly saturating or inverting under e5, leaving the gate miscalibrated inside a
sealed window. It does transfer. The check passes, the flag stays off, and no code change is
needed. The investigation was still worth its 8 minutes for the three deltas above.

**Incidental but useful:** round 7's documents have a **median of 166 chars** (max 834), against
the real corpus's mean of several hundred chars for title+description+solutions. The synthetic side
is much shorter than the real side, so a window's encode cost is dominated by the real documents,
not the 3,000 synthetic passes. e5 managed 6.11 docs/s on round-7-length text on the workstation.

### 17. Thread oversubscription makes the gate SLOWER, and nothing caps it — OPEN

Measured on the box, real-length documents (mean ~600 chars, built to the real corpus's token mix),
256 documents per probe:

| threads | stub-length | real-length | implied time for a full window (~20,000 encodes) |
|---:|---:|---:|---:|
| 8 | 8.99 docs/s | 0.77 docs/s | **6.9 h** |
| **32** | **26.76 docs/s** | **2.08 docs/s** | **2.5 h** |
| 128 | 1.80 docs/s | 1.10 docs/s | **4.8 h** |

**128 threads is roughly half the speed of 32**, and on stub-length text it is 15x worse. The box
was at load ~194 of 256 with 22 users, so asking for 128 oversubscribes badly and the run spends
its time context-switching. **Nothing caps threads today** — not the gate, not `E5Embedder`, not
`window.sh`'s podman line — so a real window would default to all 256, i.e. deeper into the regime
that measured *worse*, not better. Whoever books the window should pass `--cpus`/`OMP_NUM_THREADS`
deliberately; 32 was the best of the three tested.

**Caveat, stated because it matters:** these are single samples on a shared box whose external load
this project does not control, and the three probes ran minutes apart under different contention.
The *direction* is well supported — more threads is not faster, and the peak is nearer 32 than 128
— but treat the individual figures as one run each, not as a calibrated curve.

Also note the box at 32 threads (2.08 docs/s) is only ~1.7x the workstation's 6 cores (1.21
docs/s): EPYC cores are slower per-core and the box is busy. The box is not the speedup it looks.

### 16. Window B's shred list does not name the files Phase 0 must stage — OPEN

The rehearsal's teardown step caught this on the box. After shredding window b's `WINDOW_SHRED`,
quarantine still held `gate_report.json`, `roster.txt` **and** `synthetic.csv`. `WINDOW_SHRED` names
`export.csv profiler_detail.log shingles.bin neighbours.bin` — two of which this gate never writes
— but neither of the two files Phase 0 must stage. Both survive a `fetch --clean`. They are
synthetic, so this is hygiene rather than a leak, but a real window leaves them on the box and the
next window starts against stale inputs. Adding them is a change to a safety control and therefore
the operator's call.

**Finding 14 is worse than first recorded:** the report shows `image_digest: "unknown"` as well as
`code_commit: "unknown"`. `WINDOW_CMD` passes neither, so the hash manifest pins only the two input
SHA-256s and the embedder identity — two of its four provenance anchors are absent in exactly the
run the manifest exists for. Fix both together: add `--code-commit "$(git rev-parse --short HEAD)"`
and `--image-digest "$(podman image inspect --format '{{.Digest}}' "$IMAGE")"` to window b.

**GPU 0 was NOT used, deliberately.** The operator asked for the test to run on GPU 0. The sealed
image carries the **CPU-only** torch wheel (`torch.version.cuda is None`, verified inside the
image), so attaching `--device` would hand the container a device torch cannot address: it would
run on CPU while appearing accelerated, which is the green-for-the-wrong-reason failure this
project keeps paying for. Using GPU 0 for real means baking CUDA torch into the image, which
reverses the 2026-09-07 CPU-only decision and changes the airlock footprint — so it was left as an
open question rather than done silently. No GPU was claimed via fairuse either, since reserving
one we cannot use would be unfair on a box with 22 other users.

### The four decisions — taken 2026-09-11

**Three are done and the rehearsal is green on them: `34 passed, 0 failed` (`2a4126b`).**

2. **Thread cap — DONE (finding 17).** `window.sh` gains `--threads`, default **32**, overridable
   via `RECALL_WINDOW_THREADS`; the sealed run carries `--cpus` plus `OMP_NUM_THREADS` and
   `MKL_NUM_THREADS`. A fair-use control as much as a speed one.
3. **Manifest provenance — DONE (finding 14).** The window command now passes `--code-commit` and
   `--image-digest`, and the rehearsal **asserts** both are pinned rather than merely noting them.
4. **Shred list — DONE (finding 16).** The synthetic corpus and the roster are on `WINDOW_SHRED`,
   so `fetch --clean` now leaves only the artifact. They are re-staged every window.

**1. GPU 0 — DONE (`877fc98`), rehearsal green at `36 passed, 0 failed`.** The operator chose on
2026-09-11 to use GPU 0, **reversing the 2026-09-07 "CPU only, no `--device`, do not install CUDA
torch" ruling.** That earlier entry is superseded, not forgotten: it was right when the gate had no
measured cost, and the reversal was made once that cost was measured at ~2.2 h per window.

- **cu126 is forced, not preferred.** It is the only pytorch index carrying torch 2.14.0; cu124
  and cu128 have no 2.14 build at all. The box's driver is **550.163.01**, older than CUDA 12.6's
  toolkit requirement, which is fine because the wheels bundle their runtime and need only driver
  `>= 525.60.13`. **Verified on the box before committing** that CDI injection works there under
  `--network=none`, and that the card it exposes is the same UUID `gpu-fairuse2.sh claim 0` hands
  out — so the fair-use guard and the device spec cannot disagree.
- **`E5Embedder` had no device concept at all** — CPU by construction, not configuration. It now
  picks `cuda` when present and falls back to CPU otherwise. **The fallback is load-bearing:** the
  image's own build-time self-check runs with no GPU attached.
- **The device is deliberately not part of `identity`.** Only defensible because the two agree
  numerically, now pinned by `test_the_device_does_not_change_the_vectors`: vectors within `1e-4`,
  and the cosines the gate compares within `1e-5`. That matters because finding 18 left only
  **+0.032** of margin, so a device-dependent shift of a few thousandths would change what the
  threshold means.
- **`WINDOW_GPU` is per-window.** Window B claims GPU 0 by UUID; Window A claims nothing, because
  profiling text has no use for a card and holding an unused one is unfair on a shared box.

**Measured cost of the trade, and it is worse than estimated when the decision was taken:** the
sealed image went from 3.51 GB to **9.32 GB**, not the ~6 GB projected, so a `ship` is about **an
hour** at the measured 2.5 MB/s rather than the ~45 min quoted. Build itself is only 6m26s.

**Measured benefit, same workstation and corpora, end to end including container start, model
load, shingles and the PII sweep:**

| | wall clock, 4,500 encode passes | rate |
|---|---:|---:|
| CPU, 6 threads | 284 s | 15.85 encodes/s |
| GPU, GTX 1660 SUPER | **50 s** | **90.00 encodes/s** |

**5.7x on a modest consumer card**, with fixed overheads included, so the embedding alone is faster
still.

#### Measured on the box, on GPU 0 — `10 passed, 0 failed` (2026-09-13)

Sealed image, `--network=none`, CDI device pinned by UUID, on **NVIDIA H100 PCIe**, driver
**550.163.01**, cuda build 12.6. **The driver question is now settled by a real run rather than by
documentation:** cu126 wheels work on a 550 driver, as minor-version compatibility promised.

| | real-length rate | window, ~20,000 encode passes |
|---|---:|---:|
| CPU, box at load ~200 (2026-09-07) | 2.08 docs/s | 2.55 h |
| **CPU, box idle** (2026-09-13) | **4.97 docs/s** | **1.07 h** |
| **GPU H100, box idle** | **96.24 docs/s** | **~3.4 min** |

**The honest speedup is 19.4x, not the 46x a careless reading gives.** The original CPU figure was
taken at load 194–226 and the GPU run happened on an idle box (load 0.83), so comparing them
directly conflates the card with the contention. Re-measuring CPU on the idle box separates the
two: **contention alone costs 2.4x**, which independently reinforces finding 17. The same caution
applies to the gate run itself — 22 s on GPU against 173 s on CPU is a 7.9x that carries the same
confound.

**A result worth more than the timings:** the GPU run produced `cross_p99` **0.989657** and
`baseline_p95` **0.99727** — *identical to six decimal places* to the CPU run of 2026-09-07 on the
same corpora. That is independent corroboration, at corpus scale on real hardware, of what
`test_the_device_does_not_change_the_vectors` pins at unit scale. The verdict does not depend on
where the window runs, which is what justifies `identity` naming only the weights.

The teardown step also passed on the box, confirming finding 16's fix works there and not just
locally: after the shred list ran, `gate_report.json` was the only thing left.

### 13 (update). The roster check is now HONEST, still not fixed — `7c64cb4`

Operator ruling 2026-09-14: make the vacuity visible rather than repoint the column.
`report.build` now emits **`checks.roster.values_traced`** beside the verdict, exactly as
`baseline_saturated` sits beside check 2's, so a reader can tell a check that traced 1,500
names from one that traced none. Without it the two artifacts are byte-identical.

**Repointing was measured out, not argued away.** The generator fills only **13 of the 38
columns**, and every name-bearing one is empty across 1,500 rows:

| candidate | is a column | non-blank |
|---|---|---:|
| `merchantName` | yes | **0** |
| `endCustomerName` | yes | **0** |
| `lastModifiedUser` | yes | **0** |
| `ansprechpartner` | **no** | 0 |

So pointing `ROSTER_COLUMN` anywhere else would leave check 4 just as vacuous under a
better-looking name. The only names in the fixture are inside `customData` (1,256 of 1,500
rows), which the 2026-08-17 parked decision forbids reading. **Check 4 remains unproven; the
report no longer overclaims.** Two tests pin it, one of which drives the CLI and asserts
`values_traced == 0` — **that test will start failing the day the column carries values, which
is the signal the finding is fixed rather than a regression.**

### The airlock runbook's Window B section — REWRITTEN `7c64cb4`

It had controls but no procedure, and it is the document read with **no AI available**. It now
mirrors Window A's shape: Phase 0 staging of all **three** inputs (nothing in `window.sh` does
this — `WINDOW_IN` names only the export), the GPU claim and why `claim` rather than `check`,
the thread cap with its measurement, and the three report fields that decide whether a green
means anything.

**One statement in it had become false** and was corrected: it said the Phase 0 `git archive`
is "for Windows B and C, which run scripts that are not baked into this image". Window B's gate
lives under `profiler/gate/` and `COPY profiler` bakes it in — which is why it was put there.

**A trap the rewrite exposed:** in a REAL window the `--synthetic` side is the **candidate
fixture** (`local/fixtures/export.csv`), not a `--fake` corpus. The rehearsal uses two `--fake`
corpora because it has no real side, so the two differ in exactly the place someone would copy
from muscle memory.

### 20. A `--quick` rehearsal can pass while testing the WRONG CODE — CLOSED (`b62353a`, `db2b6b9`)

Found 2026-09-14 by the rehearsal disagreeing with itself: `report.py` gained `values_traced`,
the rehearsal was re-run with `--quick`, and the new field printed **empty** while the summary
still said `36 passed, 0 failed`. `--quick` skips the image build, so every assertion was being
made about an image that predated the change under test.

This is the project's recurring failure mode in a new place: not a test that cannot fail, but a
**whole rehearsal** that can pass against the wrong code. `--quick` is what makes iteration
bearable, so the fix is a guard, not its removal. The rehearsal now hashes `profiler/` inside
the image and compares it to the working tree.

**The first version of that guard was itself broken, and in the worse direction:** it sorted the
file list under the ambient locale on the host and C in the container, so identical content
hashed differently and it failed on *every* build. A guard that always fails gets muted rather
than fixed. `LC_ALL=C` on both sides now, and it was verified to discriminate in **both**
directions rather than merely agreeing — identical content matches at `e5388f5f48edd7bd`, while
`profiler/` at the previous commit hashes `fa6aa69a6da49bc4`. That second value is exactly what
the stale image had reported, which confirms the image side was always correct and only the host
side was wrong.

**Why it slipped through at all:** `values_traced` was printed as a *note*, not asserted. Each of
the assertions the rehearsal already makes — `embedder_is_a_model`, the embedding width, the two
provenance fields — would have caught the staleness on its own.

### 19. Asking for more CPUs than exist makes the container refuse to start — CLOSED (`2a4126b`)

Caught by the rehearsal while verifying decision 2, on the workstation. `--cpus 32` on a 6-core
machine makes the runtime exit **125** with *"range of CPUs is from 0.01 to 6.00"* — no container,
no report. **The box has 256 cores, so this could never fail there**; it fails on a workstation,
which is exactly where a rehearsal runs and nowhere near where the number was chosen. Both sides
now clamp to the local core count, `window.sh` doing it **on the box** so a mis-set `--threads`
cannot kill a sealed run where nobody can read the error. The rehearsal prints a note when it
clamps, so a timing measured on fewer cores is not mistaken for the box's.

Also worth recording: the rehearsal's drift check was **strengthened** rather than merely updated.
It used to keep its own copy of the gate command and grep `window.sh` for it — which detects drift
but still lets the two disagree for a commit, and cannot represent a command carrying runtime
substitutions, which this one now does. It now reads the command back out of `window.sh --dry-run`,
so rehearsing a command the window does not run is impossible by construction.

## Where things stand

**M1 is done. M2's generator is built and findings 1-9 are closed. Every acceptance dimension
passes.** Seven rounds of real generation have run. Round 7 reproduces all three cluster bands
within ±0.0001 of the real ones, with no intended singleton colliding, every intended group
clustering, `verify` clean and padding 1 of 1,500. **The fixture is the acceptance candidate and is
deliberately still uncommitted**, because the Window B leakage gate has not run.

The whole `fixtures/` package exists on `feat/m2-fixture-generator` (42 commits, not
merged): a pure planner, shape→value synthesis, the 38-column renderer with double-encoded
EAV `customData`, a cached LLM client with a GPU-free fake, the generator, a verifier and
a CLI. 274 tests pass, lint clean, tree clean. `uv run python -m fixtures --profile
local/artifacts/profile.json --out <path> --rows 1500 --fake` writes 1,500 verified rows
on any seed.

**The GPU path is no longer poisoned.** Finding 1 is fixed and was re-verified against the
scenario that found it: a model client pointed at the dead port `127.0.0.1:9`, after a
`--fake` run had filled the cache, now raises `ConnectError` instead of returning
byte-identical stub German. The two clients write to separate cache directories
(`cache/fake-seed-7/`, `cache/vllm-Qwen-Qwen2.5-32B-Instruct-t0.8/`).

**No fixture is accepted and none is committed.** Three rounds of real model output are kept
under `local/fixtures/`, none at the shipped path so nothing can mistake one for the accepted
artifact. The current best is `export.round3-no-padding-2026-08-19.csv`: padding 0, `verify`
clean, all 51 groups clustering, large band within tolerance of the real one. See finding 9.

Window A v2 shipped earlier: all 9 plan tasks landed, the sealed image is built and
verified offline on the box, and three real-data windows have run.

The profiler emits `schema_version: 2` with `custom_data`, `discovered_identifier_shapes`,
`clusters.largest`, `temporal.fill_by_month`, and a whole-artifact catch-all
(`profiler/blessing.py`) wired into `selfcheck.assert_safe`.

### The immediate next action

**Updated 2026-08-26. Finding 9 is CLOSED and every acceptance dimension now passes.** The
fixture at `local/fixtures/export.csv` is the acceptance candidate: cluster bands within ±0.0001 of
the real ones, no intended singleton colliding, every intended group clustering, `customData` field
shares 26/26, `fehlercode` shape mix 10/10, fill-by-year 12/12, descriptor quantiles all matching,
`verify` clean, padding 1 of 1,500. `make test` is **294 passed** with the acceptance test green for
the first time.

**Plan B is IMPLEMENTED and REHEARSED as of 2026-09-08.** All seven tasks committed, the rehearsal
green apart from the one real finding it caught (16), and the gate proven in a sealed
`--network=none` container both locally and on the box. **Window B is ready to book**, subject to
the four operator decisions listed at the end of this block. Commits, in order:
`c4e16e2` (CPU-only torch + transformers), `830f9b6` (`E5Embedder`), `27e3877` (`--embedder e5`),
`52091b6` (the two wrong-reason tests in Plan B's own test file, closed), `79f9f94` (weights baked
into the sealed image), `9215362` (window b's `WINDOW_CMD`), `1bc4cc7` (`rehearse-window-b.sh`).

What is **verified by direct measurement**: `make test` is `1 failed, 345 passed, 1 skipped,
2 xfailed` — baseline +7, the one failure being the operator's quarantine file — and `make lint`
is clean at 80 files. `torch 2.14.0+cpu` with `torch.version.cuda is None` and `grep -c nvidia
uv.lock` of 0, both on the host and **inside the image**. The sealed image is 3.51 GB and, run
with `--network=none`, loads the model offline and reports
`e5:intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` at dim **1024**;
`hunspell -d de_DE` still exits 0 in it and all four HF offline env vars are live at run time.
Driving the CLI with `--embedder e5` produces a report whose **`embedder_is_a_model` is `true`**
for the first time in this project.

**The rehearsal has now run and validates — `22 passed, 1 failed` (2026-09-08, `--quick`).** The
single failure is finding 16 and is a real result, not a script defect. Everything else passed:
`make test` showing only the operator's quarantine failure, `make lint`, offline import, German
dictionary in the image, the model loading offline at dim 1024 with a CPU-only torch, both
stand-in corpora built, all three Phase 0 inputs staged, the command matching `window.sh`
verbatim, the gate reaching exit 0, `gate_report.json` valid, **`embedder_is_a_model` true**, ten
corpus tokens probed with zero appearing in the report, no traceback, the tree clean and no git
remote. It was also run end to end on the box under a separate driver: `13 passed, 1 failed`, same
single failure.

**The box holds a STALE image.** `hpc` currently has `recall/profiler:pinned` at 415 MB — the
pre-weights build. A Window B run against it would fail on `--embedder e5` *inside a sealed
window*. `window.sh ship` must precede `run`, and `cmd_all` does sequence them, but the box's
current state is a trap for anyone running the steps by hand.

**Superseded — the plan text is ready but was written before these were known:**
`docs/superpowers/plans/2026-09-07-window-b-plan-b-sealed-embedder.md`, seven tasks — torch on
the CPU index, an `E5Embedder` satisfying Plan A's existing protocol, `--embedder e5` on the
CLI, the weights baked into the sealed image at build time (the window runs `--network=none`),
`window.sh`'s window-b command block, and a `rehearse-window-b.sh` mirroring the Window A
rehearsal that has already caught six cycle-costing defects. `docs/NEXT-SESSION-PROMPT.md`
carries the handoff prompt.

**Two errors in the plan text itself, corrected during execution — do not follow it literally:**

- It says `podman build` / `podman run` for the local steps. **podman is not installed on the
  workstation**; docker is (29.7.2). Podman is the *box's* runtime — `rehearse-window-a.sh` uses
  docker throughout and `window.sh` bridges them with `docker save | ssh HOST 'podman load'`. Use
  docker locally, podman on the box.
- Its Task 5 verification says `./infra/profiler/window.sh b run --dry-run`. That **cannot work**:
  the argument parser treats any non-`-` argument as *the command*, so `b` is taken as the command
  and `run` then trips `die "more than one command given"`. The correct invocation is
  `./infra/profiler/window.sh --window b run --dry-run`, which I verified prints the sealed
  command with `--network=none`, no `--device` and `ulimit -c 0` intact, while `--window c` still
  correctly refuses.

**Operator decision 2026-09-07: CPU only, no GPU in the window container, an overnight run is
acceptable.** That removes the one branch the plan would otherwise have had, and the airlock
contract is unchanged — do not add `--device` to `window.sh` and do not install CUDA torch.

**Window B's gate logic is now built and tested — Plan A is complete.**
`docs/superpowers/plans/2026-08-27-window-b-leakage-gate.md`, seven tasks, all four of
`PROJECT_BRIEF.md` §8's checks behind `python -m profiler.gate`, emitting `gate_report.json`
with a hash manifest. **336 tests pass.** It needs no model, no GPU, no network and no window,
because the embedder is injected — which is what let two design defects surface in CI rather
than inside a sealed window (findings 12 and the `sweep` coverage note below).

**It has NOT run against real data and the fixture is therefore not cleared.** Every report it
can currently produce carries `embedder_is_a_model: false`, because the real
`intfloat/multilingual-e5-large` integration is Plan B along with baking its weights into the
sealed image (`--network=none` means nothing resolves at run time) and writing `window.sh`'s
`WINDOW_CMD` for window b, which is still empty and correctly refuses to run.

Two things in the gate ship less than §8 asks, both deliberate and both visible in the report
rather than hidden:

- **The PII sweep implements 3 of §8's 6 pattern families** — email, phone, IBAN. `sweep.PATTERNS`
  is printed in the report so a green `pii` verdict cannot read as "no PII of any kind". Plates
  are absent because `entities._PLATE` unanchored matches `TX-2200`, `LR-2200` and `VG-2210` —
  every designation of the fixture's own invented product line, present in essentially every
  row; disambiguating that needs the roster, not a regex. Surnames are absent because
  `COMMON_SURNAMES` holds ordinary German words like `bauer` and `braun`. Addresses have no
  pattern in the repo.
- ~~**Check 2's baseline is degenerate on this fixture**~~ — **fixed 2026-09-07 (`a7540b7`)**,
  finding 12. `BASELINE_PERCENTILE` is 95, chosen against a measured clean comparison; the check
  now goes red against a derived corpus and green against an independent one, where both
  previously passed vacuously.

The fixture stays uncommitted until the gate is green *against real data*; re-gating a committed
fixture costs another window.

**Three things are waiting on the operator, none of them blocking the gate:**

1. **Shred `local/quarantine/profiler_detail.log`.** It is the only red test
   (`test_the_test_suite_does_not_dirty_the_quarantine`, correctly). Left by the plan's
   Appendix A script, which does not redirect `safety.DETAIL_LOG` outside pytest — see the
   lesser findings. `make check-clean` says to inspect and shred it without an AI tool, and the
   session hook denies the assistant that path anyway.
2. ~~**`llm.Fake.identity` does not version the stub's content.**~~ **Fixed 2026-08-27
   (`de5a5dd`)** on the operator's ruling. The identity is now
   `fake:<8-hex fingerprint>:seed=N`, hashed over the stub's word lists, `BLOCKS`, the alphabet
   and **the source of `__call__`** — source included because the change that caused the bug
   was to the block template, not the vocabulary, so a data-only fingerprint would have missed
   it. `test_every_client_declares_who_it_is` moved from an equality to a pattern, which the
   operator authorised explicitly.
3. ~~**Window question 1** for Task 3.~~ **Task 3 dropped 2026-08-27** by operator ruling; see
   its own subsection. No sealed window is needed for it.

Where things actually stand after four generation rounds: padding **0**, `verify` clean, all 51
groups cluster, large band within tolerance of the real one, and `customData` field shares (26/26),
`fehlercode` shape mix (10/10), fill-by-year (12/12) and descriptor quantiles all pass. The single
remaining defect is that 173 intended singletons accidentally near-duplicate each other, which
deflates the singleton band and inflates mid by about a tenth each.

Two cautions, both measured rather than assumed:

- **Subsystem steering has been tried and is not the fix** (182 -> 173). It moved collisions from
  across batches to within them. Do not retry it.
- **Do not absorb the collisions by shrinking the planner's mid budget.** The bands would match
  while relevance density stayed near double the real corpus, which is what §9's divergence rule
  exists to prevent.

Also open and needing a judgement, not a measurement: description blanking splits a
shared-problem group in two (group 0 comes out 141 + 75), because a blanked row's token set is the
title alone. Both halves clear 50 so the large band passes, but the real corpus does not split this
way despite a middling-to-high description fill - which implies its handover paperwork has an empty or
boilerplate description. That is a question about the client's data that nothing here answers.

Everything else in the generation path is proven working and does not need redoing:

- **The box and the serving setup work.** The fair-use guard gates it correctly: it returned
  DEFER for ~5 hours on 2026-08-18 while another job held both GPUs (that job ran under our
  own shared `<box-user>` account — the guard counts *any* process as foreign, regardless of
  owner), then GO once it finished. It was never overridden.
- **A working vLLM recipe**, on the box, reusable as-is:
  ```
  podman run -d --name vllm-recall \
    --device nvidia.com/gpu=<UUID from gpu-fairuse2.sh claim> \
    -v <data-dir>/hf-cache:/root/.cache/huggingface:Z \
    -p 8000:8000 --ipc=host docker.io/vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-32B-Instruct-AWQ --no-enable-log-requests \
    --gpu-memory-utilization 0.75 --max-model-len 32768
  ```
  Then `ssh -N -L 8000:localhost:8000 hpc`, because the CLI's `--base-url` default is
  `http://localhost:8000`.
- **Two gotchas that cost time.** vLLM 0.27.1 **removed `--disable-log-requests`**; the
  equivalent is `--no-enable-log-requests`, and request logging is off by default anyway.
  And the CLI's default `Qwen/Qwen2.5-32B-Instruct` is bf16 at ~65 GB, which **breaches the
  60 GB cap** — use the AWQ variant (~19 GB weights, ~40 GB KV, exactly `PROJECT_BRIEF.md`
  §12.6). The model id is part of the cache identity, so this choice is visible in the
  provenance directory name.
- **230 model responses are cached** under
  `local/fixtures/cache/vllm-Qwen-Qwen2.5-32B-Instruct-AWQ-t0.8/`, so a regeneration only pays
  for prompts whose text actually changes. Four rounds of generation do not have to be repeated.
- **A foreground Bash command is capped at 10 minutes** in this harness. A full generation run
  exceeds that when many prompts are new, so run it with `run_in_background: true`. A run killed
  mid-request can leave the next request stalling past the client's 120s timeout; the cache makes
  a resume free, so just re-run it.

Still binding when you regenerate:

1. `./infra/fairuse/gpu-fairuse2.sh check` — must be GO before anything else.
2. **Drive the CLI through pytest, not a shell.** The session hook rejects any Bash command
   containing `.csv` and the CLI's `--out` ends in it. Put the path *inside* the Python file,
   as the committed integration tests do; passing it as an argv on the command line trips the
   hook. Do not evade it.
3. **Confirm the model answered, not the cache.** A model run writes under
   `local/fixtures/cache/vllm-<model>-t<temperature>/`, a fake run under `fake-seed-N/`.
   Finding 1 was exactly the failure that looks like success here.
4. Read the padding WARNING before believing the output. It is the one that mattered.
5. **Do not commit anything under `local/`,** and do not leave an unverified fixture at
   `local/fixtures/export.csv` — a later run would mistake it for the accepted artifact.
   The fixture stays uncommitted until the Window B leakage gate is green.

Only a model-generated fixture **without padding** can answer the cluster-band question.
`--fake` collapses into one cluster of 1,500 (singles 0.000 / mid 0.000 / large 1.000), and a
padded run is just as worthless in the other direction — round 1's "passing" large band was 202
byte-identical padded rows. `test_the_generated_fixture_profiles_like_the_real_corpus` skips
until `local/fixtures/export.csv` exists and then checks the bands within 0.01, so it is red
whenever an unaccepted fixture sits at the shipped path — which is why the three rounds are
parked under other names.

Work continues on `feat/m2-fixture-generator` — 42 commits, split from `main` at `2554e62`,
**deliberately not merged** because the generator is not accepted. `main` is unchanged.

### M2 decisions, already made

| Decision | Choice |
|---|---|
| Fidelity | Generated from `profile.json`, so M3's metrics transfer |
| Text source | Local LLM on the H100, ~32 GB model, via vLLM |
| Cluster structure | LLM writes themes and variants; code controls the counts |
| Rows | 1,500 |
| PII fields | Present in the fixture, excluded from the pipeline (deferred, below) |
| Cluster bands (2026-08-18) | The ≥50 band keeps its measured **ticket share**, not its group membership |
| Order of work (2026-08-18) | Close finding 3 **first**, then generate the fixture, in one session |

Three defects were found while writing the plan and were already fixed in it. All three
held up under implementation: one prompt per group collapses the singletons into ten
identical tickets; the fake client emitted a format the parser cannot read; and templated
stub text near-duplicates itself, so `--fake` cannot prove cluster bands — only the
model-generated fixture can. That last one was measured rather than assumed: profiling the
1,500-row fake fixture gives bands of singles 0.000 / mid 0.000 / large 1.000, one cluster
of 1,500. The stub does produce distinct singleton *strings*, but they differ only by
an embedded random number inside one template, so distinct strings are not distinct
clusters.

Implementation needed four further corrections, all committed. The plan's `group_sizes`
failed its own two tests (unscaled mid groups outranked scaled large ones; a `max(2, …)`
floor manufactured the exact case the row-count guard existed to refuse); that guard then
had to relax from 2 to 1 when it collided with the CLI test's 200-row case; `Fake.BLOCKS`
was 40 against a largest planned group of 190, sending 70 tickets through the padding path
and dropping solutions fill below the plan; and per-row coin flips for `customData`
shares aborted `verify.check` on 8 of 10 seeds, so shares are now assigned exactly.

**The Window B leakage gate is deliberately NOT in that plan.** Its nearest-neighbour
threshold is calibrated against a synthetic-vs-synthetic baseline measured in the same
window, which cannot be written before a fixture exists. It gets its own plan, and the
fixture stays uncommitted to git until that gate is green.

## M2 findings — 1-10, 12, 14, 16, 17, 19 and 20 closed; 11, 13 and 15 open, none blocking the gate's code

Found by measurement during implementation. Five were closed between `5934178` and
`3ffeeac` under `docs/superpowers/plans/2026-08-17-m2-findings.md`; finding 3 was closed on
2026-08-18 between `1695332` and `aead5f2` under
`docs/superpowers/plans/2026-08-18-m2-finding-3-joint-masks.md`.
Findings 7, 8 and 9 were opened on 2026-08-19 by the first real model runs; 7 and 8 are
closed and 9 is open.
Every number here was observed, not inferred.

### 1. The response cache made `--fake` a lie — CLOSED (`7e2321e`)

`fixtures/llm.py`'s `Cached` keyed on `sha256(prompt)` alone, with nothing identifying
which client answered, and consulted the cache **before** the inner client. Prompts are
fully determined by profile, rows and seed, and carried no trace of `--fake`, so a stub run
poisoned every entry. Verified end to end at the time: a non-`--fake` run pointed at a dead
port (`http://127.0.0.1:9`) exited 0 with byte-identical stub output, no warning, no
provenance marker.

Every client now declares an identity — `llm.Fake` as `fake:seed=N`, the new `llm.VLLM`
class as `vllm:<model>@t<temperature>` — and `Cached` requires one. The identity goes into
the cache key *and* into each entry, and entries live in a per-client subdirectory, so a
hand-moved file cannot be served to the wrong client either. Re-verified against the
original scenario: the dead-port run now raises `ConnectError`.

**The old plan's Task 10 Step 3 must still not be run as written** — it wrote `--fake` and
model output to the same path, which is a different mistake the cache fix does not undo.

### 2. The cluster bands could not pass, even with perfect model prose — CLOSED (`cf43a98`)

Computed from `fixtures.plan.group_sizes` against the real artifact — no generation
involved, so a model run cannot change it: the planner's singleton band passed, but its mid band came
out too high and its large band too low, each by under a point against the test tolerance of 0.01
(real figures omitted).

Cause: the planner kept the dominant group intact (scaled down, still ≥50) but scaled the next three
large groups down to a handful of members each, which land in the fixture's *mid* band. That shorted
`large` and inflated `mid` in mirror image, and the demoted groups were added *on top of* a full mid
budget rather than paid for out of it.

Note the design doc's own table hides this by listing three small scaled groups under a row headed
*other 50+ groups* — a scaled group of a handful is a 2–49 group by the profiler's arithmetic. The
real large band is all four ≥50 groups, not the dominant handover group alone.

**Resolved by the user on 2026-08-18: preserve ticket shares, not band membership.** Three
arithmetics were put up with their numbers. The chosen one gives the large band its measured ticket
share in a single group (the proportional dominant group plus the tickets of the three demoted
groups), with the three small groups living in the mid band's own ticket budget. Bands now come out
equal to the real ones to within ±0.0001 on every seed.

The rejected options, so they are not re-proposed: keeping all four groups ≥50 (the dominant group
plus three groups of exactly 50) puts the bands several points out and would require rewriting the
±1.0 point acceptance criterion; a smaller dominant group plus three groups of 50 keeps four groups
*and* exact shares but flattens the dominant cluster to a fraction of its real share.

**The accepted costs, so they are not rediscovered as bugs:** the fixture has **one** cluster ≥50
where the corpus has four, and its largest cluster is somewhat larger than the real largest, because
it absorbs the other three.

### 3. The correlated handover block is not modelled — CLOSED (`1695332`…`aead5f2`)

**Closed 2026-08-18.** Four commits: the planner groups fields sharing a `present_count`
into a block (`1695332`), the renderer assigns a block as a unit and seats it on the
largest group (`401f506`), the CLI passes the group assignment (`660610f`), and `verify`
refuses a form that is half-filled or off-cluster (`aead5f2`). 262 tests pass, lint clean.

Measured after the fix, identical on seeds 7, 1 and 42 — the design's numbers reproduced
exactly, with no seed dependence: the descriptor-count quantiles match the real corpus except p75
and max (see the residuals below). The fixture also carries the form on its planned share of rows
(the real handover-form share, scaled), every member of the largest group carrying the form, and
every field's presence share still exact.

**The two residuals are the predicted ones and are not reachable**: the fixture's p75 sits one
descriptor below the real one and its max is well below the real max. Both are the 26 fields the
profile suppresses (52 distinct, 26 emitted after the presence floor and entity sweep). Those unnamed
fields are what carry real rows past the form's descriptor count; reproducing them would mean
inventing field names no measurement supports. `max` is a design-doc target the fixture misses, and
that is the honest number to report rather than to manufacture.

**Two things the plan got wrong, both caught by tests rather than by review:**

1. **`CustomField.block` defaulting to `0` merged unrelated fields into a phantom form.**
   `0` was both the default and the first id `plan()` hands out, so any two hand-built
   fields that omitted `block=` were grouped as one form and the second silently inherited
   the first's row set. The pinned share test caught it: `baugruppe` came out at
   `fehlercode`'s row count instead of its own planned count, breaching the ±2.0 point tolerance. The
   default is now `None`, meaning "no form"; explicit ids still group normally, `0`
   included, so a hand-written `block=0` on two fields still means what it looks like.
   Renderer and verifier both group through `fixtures.plan.block_key`, deliberately, so
   they cannot disagree about what a form is — a verifier with its own definition would
   bless exactly the fixtures the renderer got wrong.
2. **The plan's Task 3 integration test cannot see what Task 3 does.** It was written
   expecting to fail before the CLI passed `groups` and pass after; it passes both ways.
   Block cohesion alone puts all 21 fields on the same rows whether or not those rows are
   the cluster's, and the test only checks the form-row count, all-or-nothing membership
   and the quantiles — never *which* rows. Measured: the same number of form rows with the seating and
   without it. **`verify`'s cluster check is the only thing in the suite that can see
   this**, confirmed red/green — scattering the form makes it report "block 4 is absent
   from many rows of the largest group", while the seated fixture reports nothing.

The original finding, kept for the reasoning:

21 real fields share exactly the same `present_count` — they are one form, all-or-nothing. Its
signature is a real quantile jump in the descriptor count per ticket between p75 and p90, with the
max far above. The fixture assigned each field an independent row-subset, giving a much flatter
distribution and **zero** rows carrying that many descriptors. So no fixture row is a handover form.

`PROJECT_BRIEF.md` §8 requires "**Joint** null-mask patterns with frequencies — not
per-column rates. Missingness is correlated." This is that requirement, unmet, and it is
the structural cause of the corpus's largest cluster.

**The plan that closed it:** `docs/superpowers/plans/2026-08-18-m2-finding-3-joint-masks.md`.
Three things were measured on 2026-08-18 that the finding above did not record, and they
turned the design from a judgement call into arithmetic:

1. **Exactly 21 emitted fields share one `present_count`, and every other emitted field has a
   distinct count** (`ansprechpartner-tel`, `ansprechpartner`, `baugruppe`, `fehlercode`,
   `operations`). So the block is *derived* by grouping fields on their presence count, not
   hard-coded as a list of names.
2. **`records_per_row_quantiles` is flat from p90 to p999 at the form's descriptor count.** Four
   identical values are only possible if form rows carry the form and essentially nothing else — if
   they also carried `ansprechpartner` (most rows) then p95 and p99 would exceed it. The arithmetic
   agrees independently: the form rows' descriptors plus the other five fields' descriptors over
   the remaining rows (a mean of a couple of descriptors) account for the totals, and all five fit
   inside those non-form rows.
3. **The form must be seated on the cluster.** Essentially all members of the largest group are among
   the form carriers, with a minority of carriers outside. In the fixture: all cluster members plus
   a few dozen others carry it.

Simulated and then run with the plan's own code: p50, p90, p95 and p99 match the real quantiles.
Two residuals will remain and are **not** reachable — p75 one descriptor low, and the max far below
the real max — both caused by the 26 fields the profile suppresses (52 distinct, 26 emitted after
the presence floor and entity sweep). Those unnamed fields are what carry real rows past the form's
descriptor count, and reproducing them would mean inventing field names no measurement supports.

**Why it had to be group-aware, and why it was worth doing before generation.** The
finding-2 decision reaches the band shares by arithmetic alone, so the large band no longer
depends on the handover form producing the cluster. But the fixture's one large cluster is a bit
smaller than the form's scaled reach, so the fix had to coordinate the two: nearly all of the
form-carrying rows are the cluster's members, which is what the `groups` argument threaded from the
CLI achieves. Under the rejected options with a larger dominant cluster it would have lined up at
the real ratio with no coordination at all. Doing it before the fixture was generated was much
cheaper than after, because re-gating a committed fixture costs another sealed window.

### 4. `generate` degraded silently on real model output — CLOSED (`d26be27`)

`_parse` only flushed a record on a `---` line. Two well-formed records without a separator
parsed to **one** ticket — the earlier one overwritten in place. A `**TITEL:**` or
`1. TITEL:` prefix yielded a ticket with an **empty title** rather than none, which is
worse: it flowed into the fixture instead of registering as a shortfall.

`_parse` now flushes on the separator **or** on the next `TITEL`, strips leading
markdown/list decoration before matching a field, and drops any record without a title.
Verified against deliberately messy output — markdown bold, `1.`/`3)` numbering, `>`
quoting, `###` headings, a missing separator, prose preamble — all parse; a titleless
fragment yields no ticket.

Padding still exists, because stalling a run is worse, but it is no longer silent:
`generate.tickets` takes a `stats` dict and the CLI prints a WARNING with the number of
padded tickets and short groups. Padded tickets remain byte-identical within their group
and carry no solution — that is a real degradation, now visible at the moment it happens.

### 5. `verify.py` implemented 2 of the design doc's 7 checks — CLOSED (`e41b4ac`, `0c78df4`, `3ffeeac`)

All seven now run: row count, `customData` field presence shares, `solutions` fill,
`customData` round-trip, `fehlercode` shape mix, group-size distribution, fill-by-year.

The round-trip one was subtle — `check()` called `parse_records` only to harvest key names,
and `or []` made a malformed value (which returns `None`) indistinguishable from a
legitimately empty envelope (which returns `[]`, and some real rows are exactly that). It
now counts and reports unparsable values while an empty envelope still verifies clean.

Two things worth knowing about the new checks:

- **The shape-mix check needed the renderer fixed first** (`7fcf0aa`). `values.pick_shape`
  drew per row, which reproduces a mix only in expectation — at a few hundred `fehlercode` rows the standard error on a mid-sized shape is a couple of points against a ±3.0 point tolerance, across ten
  shapes. Shapes are now allocated by largest remainder; measured worst deviation across
  all 26 fields and 5 seeds is **0.0019**. The check skips fields under 34 rows, where the
  ±3.0 tolerance is arithmetically unreachable (the error can be 1/n, and 1/34 < 0.03).
- **The group-size check verifies plumbing, not German.** `verify.check` takes the group
  assignment (`[t.group for t in tickets]`) as a required third argument and compares the
  realised sizes to `plan.group_sizes`. On a 1,500-row run it reconstructs them exactly. Whether the *text* clusters that way is a
  separate question that only a model-generated fixture can answer — `--fake` prose
  collapses into one cluster of 1,500.

### 6. Fill-by-year was not reproduced at all — CLOSED (`ecf502f`)

`fixtures/__main__.py` assigned `months = sorted(fixture_plan.fill_by_year)`, whose keys are
four-character **years**. The calendar month was drawn uniformly at random, the per-year
**rate values were never read anywhere**, years were cycled round-robin and unweighted, and
`solutions_fill` was applied as one flat corpus-wide probability.

It was closed because finding 5 forced it, twice: the design doc's check list includes
fill-by-year, and applying per-year rates over uniformly-cycled years gives a corpus-wide solutions fill far below the plan, which `verify.check` already
refuses at ±0.02. The two halves only work together.

`FixturePlan` now carries `month_weights` from `temporal.created_per_month`; months are
allocated by largest remainder and **shuffled** (group members are contiguous in the ticket
list, so an ordered assignment would drop the whole dominant cluster into one month); and
each year's solutions and description fill is applied to exactly `round(rate * n)` of its
rows. Measured: per-year row counts follow the real per-year volume, each year's solutions and
description fill lands within a fraction of a point of the plan, and the corpus fill matches the plan
and is seed-independent.

The fill-by-year check allows `max(0.05, 0.5/n)` — the first year holds only a handful of
rows, where a high rate rounds to a row or two short, which is several points out before anything has
gone wrong.

### 7. One prompt cannot fill the dominant group — FIXED IN CODE (`cfba316`), regeneration pending

Found on 2026-08-19 by the first real H100 run. **The fixture was NOT written: `verify`
refused it.** This is the finding `--fake` was structurally incapable of surfacing, because
`Fake.BLOCKS = 200` hands back 200 records for any prompt and a real model does not.

Served `Qwen/Qwen2.5-32B-Instruct-AWQ` under vLLM 0.27.1 on `hpc`, GPU 0 pinned,
`--gpu-memory-utilization 0.75` (the 60 GB cap), `--max-model-len 32768`. 99 prompts, 28
minutes, all answered by the model — cache identity `vllm:Qwen/Qwen2.5-32B-Instruct-AWQ@t0.8`
under `local/fixtures/cache/vllm-Qwen-Qwen2.5-32B-Instruct-AWQ-t0.8/`, no `fake-seed-*`
involvement.

**It is one group, not a general failure.** Per-group supply, measured:

| group | asked | 1st | +retry1 | +retry2 | total | padded |
|---:|---:|---:|---:|---:|---:|---:|
| 0 (dominant) | **~200** | 3 | 6 | 5 | **14** | **~200** |
| 1 | 15 | 15 | — | — | 15 | 0 |
| 2 | 6 | 6 | — | — | 6 | 0 |
| 3, 7, 28 | 5 | 5 | — | — | 5 | 0 |

Singleton batches asking 25 returned **22–31** each across 46 batches (shortfall 12). So the
model reliably delivers 15–31 records per prompt, and collapses to 3–6 when asked for ~200 —
**asking for an absurd count degrades the response** rather than truncating it. A probe
confirmed it independently: asked for ~200 in one message it emitted 5 records, 576
completion tokens, `finish_reason: stop`. Not a timeout, not a context limit.

Total padded **214 of 1,500** across 9 short groups. Padded tickets carry no solution, which
is what `verify` caught:

```
solutions fill is 0.739, planned <real-derived figure omitted>
solutions fill in <each later year> is 0.68-0.86, planned <figure omitted>   (each short by 0.12 to 0.15)
```

This is exactly the mechanism finding 6 recorded at `Fake.BLOCKS=40` (70 padded → fill below plan). With a real model it is 214 padded → 0.739.

**Everything not downstream of padding reproduced the real corpus.** Measured on the
unverified build: `customData` field shares 26/26 within 0.0003; `fehlercode` shape mix
10/10 within 0.0019; descriptor quantiles p90/p95/p99/p999 all matching; description fill-by-year
6/6 pass. Only `solutions` fill-by-year fails, and only for every year after the first, all by −0.12 to −0.15
— the padding, nothing else.

**The cluster bands remain UNANSWERED.** They came out off the real shares, but that
measurement is worthless: the largest cluster is ~200 rows of which nearly all are byte-identical
padding, so it clusters by construction. The 14 genuine tickets for group 0 did not form it. The mid
band is inflated by a 12-row `stoerung` cluster, which is the singleton padding fallback. **The question of
whether model prose clusters at the real band shares is still open and still needs a run
without padding.**

**The cause is one bound**, `fixtures/generate.py`: `while len(produced) < size and attempt
< 2`. The top-up mechanism is right; a bound of 2 cannot fill the dominant group (~200) at ~5 per response, which needs ~10 rounds of 20 or ~40 of 5. The obvious fix mirrors the already-approved
`SINGLETON_BATCH = 25`: cap the per-prompt ask and loop, which the singleton path shows works.

**Resolved 2026-08-19 (`cfba316`). The user's ruling: the bound IS the intent.** So the bound
did not move. `TOPUP_ATTEMPTS = 2` now names it, and it applies *per ask*: padding exists so a
short model cannot stall the run, and a loop that retried until satisfied would spin forever on
a model that cannot deliver. `test_padding_is_reported_rather_than_silent` passes **untouched**,
because a group of 5 is still a single ask — one record, two top-ups, then pad.

What changed is the **size of the ask**: `GROUP_BATCH = 20` caps any single prompt and a large
group is filled by several, mirroring `SINGLETON_BATCH`. 20 is inside the measured-working range
rather than an extrapolation past it. `groups_short` is still per group, not per batch.

`_series(group, batch, attempt)` keeps batch 0's first ask on the bare group index and its
top-ups on `group * 1000 + attempt` — what those prompts were before batching — so a group of
GROUP_BATCH or fewer sends byte-identical prompts to the cached ones.

Measured against the 99 cached responses: a regeneration needs **11 new model calls**, all of
them group 0's batches, and padding falls **214 → 12**. The residual 12 is the real singleton
shortfall already in the cache (8 short batches of 46), which is 0.8% of rows and puts
solutions fill close to the plan — inside the ±0.02 that refused the last run.

**Still unproven against the model.** 265 tests pass and the cost is measured, but nothing here
substitutes for a regeneration, and the cluster bands remain the open question.

### 8. The prompt asks for variety; the cluster metric measures sameness — CLOSED (`1e44136`)

Found on 2026-08-19 by the first *padding-free* model run. The fixture generated and
**`verify` passed** (padding 12 of 1,500, exit 0, 1,500 rows). Everything the design doc
measures reproduced the corpus **except the cluster bands**, which failed completely:

Band results (real figures omitted): the singleton band came out about four points high, the mid
band about ten points high, and the large band was **empty (0.0000)** against a real band of about a
seventh of all tickets, all against a tolerance of 0.01.

**The dominant group did not cluster at all.** The largest fixture cluster is 13 rows. The
mass did not vanish, it moved: group 0 fragmented into many 2–49 clusters, which is exactly
why `mid` is high while `large` is empty.

Everything else passed: `customData` field shares 26/26 (worst 0.0003), `fehlercode` shape mix
10/10 (worst 0.0019), fill-by-year 12/12, descriptor quantiles p90–p999 all matching.

**Why.** Clustering is `minhash-lsh(num_perm=128) over cleaned title+description` at
**threshold 0.7** — near-duplicate territory. Measured over group 0's titles: token Jaccard
median **0.111**, p90 0.400, only 8.4% of pairs at or above 0.5. Almost nothing reaches 0.7.
Compounding it, **About a third of group-0 rows carry no description** (the fill-by-year blanking,
which is faithful), so those rows cluster on title alone — and the titles are individually
phrased: *Defekter Ventilator verursacht Druckverlust*, *Blockierter Rücklauferhitzer*,
*Defekte Drucksensor*.

**This is a design contradiction, not a bug.** `generate.py`'s prompt demands *"Jedes Ticket
muss einen unterschiedlichen Loesungsweg beschreiben … Nicht dieselbe Loesung anders
formuliert"*, and the model obeyed. Genuinely different approaches are **not** near-duplicates
at threshold 0.7. Both properties cannot hold at once.

**And the real corpus never had the property we are generating.** The real largest cluster's
top tokens are the two title words of the handover slip, across a large share of the tickets — repeated boilerplate
handover paperwork. Finding 3 already said it in words: *"that cluster is a form, not a
fault."* Nobody connected that to the generator. A form is reproduced by **repeating short
boilerplate**, not by writing ~200 individually-phrased fault narratives.

**The two earlier bugs were cancelling.** The 2026-08-19 padded run scored `large` as a
PASS — but that was ~200 byte-identical padded rows. Padding was masking a total failure to
cluster. Fixing the padding revealed it.

**Recommended direction, for a human to decide.** Generate the dominant cluster as the
handover **form**: a short, repeated, boilerplate title in the shape of the real handover-slip title, rather than ~200 distinct fault stories. This also makes the design
self-consistent — finding 3 already seats the 21-field handover block on exactly those rows,
so the text and the `customData` would finally describe the same thing. Note the product
priority *"comprehensive answers over deduplication / variants must be different approaches"*
applies to the **mid band's variant groups**, not to a form; nothing is lost by making the
form boilerplate.

**Fixed 2026-08-19 (`1e44136`), and it worked.** Spec:
`docs/superpowers/specs/2026-08-19-cluster-structure-shared-problem-design.md`. One prompt now
yields one `TITEL`/`BEFUND` plus N numbered `LOESUNG` lines; a group shares the problem text and
each member carries its own resolution, which must state its own diagnosis so nothing the
application needs is lost. Regenerated: padding 12, `verify` clean, 61 new model calls.

**Measured after the fix — all 51 intended groups cluster, 0 fragmented** (against 50 of 51
fragmented before), and the large band went from empty to **within tolerance of the real band — PASS**. Everything else still passes: field shares 26/26, shape mix 10/10, fill-by-year 12/12,
descriptors p90–p999 all matching.

**Two residuals keep the fixture from acceptance:**

Round 2 band results (real figures omitted): the singleton band was about ten points low, the mid
band about ten points high, and the large band **within tolerance (+0.002, PASS)**.

**Residual A — singletons collide across batches.** 182 of the intended singletons
landed in a cluster of ≥2, across 73 spurious clusters. `_prompt_distinct` asks each batch for
25 *verschiedene* faults but the model has no memory across the 46 batches, so it reaches for the
same names repeatedly: *Defekter Ansaugfilter* ×8, *Defektes Bodenbearbeitungsgerät* ×7,
*Defektes Antriebsgetriebe* ×4. Those 182 rows are exactly what deflates the singleton band and
inflates mid. Two sub-causes, one of them trivial: **12 of them are the singleton padding
fallback** `f"Stoerung {group}"`, whose tokens reduce to `{stoerung}` once digits are dropped, so
all 12 collapse into one cluster.

Likely fix: give each singleton batch a distinct subsystem/component hint (a list longer than the
46 batches), so batches stop competing for the same vocabulary, and make the padding fallback text
distinct.

**Residual B — description blanking splits a shared-problem group in two.** Group 0 came out as
a larger cluster of rows with a description plus a smaller one of blanked rows. A blanked row's token
set is the **title only**, which cannot reach 0.7 Jaccard against title+description. Both halves
exceed 50 here so the large band passes, but that holds only because the blank rate (about a third of
the group) sits comfortably above the point where the smaller half would fall under 50; the same
group at a 10% blank rate would put about 20 rows into the mid band instead.

Worth noting the real corpus does **not** split this way — its largest cluster is a single group despite a middling-to-high real description fill by year. That implies real handover paperwork has an
empty or boilerplate description, not a 3-sentence narrative. Making the form's description short
boilerplate would make blanking a no-op for it. **That is a fidelity question about the client's
data that no measurement here answers**, so it is recorded rather than guessed.

**Artifacts.** The band-rejected fixture is kept at
`local/fixtures/export.bands-rejected-2026-08-19.csv` (pre-fix, no cluster structure) and round
2 at `local/fixtures/export.round2-singleton-collisions-2026-08-19.csv` (groups cluster, large
band passes, singleton/mid do not). Both are real model output, worth keeping for comparison. It was moved **off** `local/fixtures/export.csv` deliberately: while it
sat there, `make test` was red on
`test_the_generated_fixture_profiles_like_the_real_corpus` (correctly), and a later run would
have mistaken a band-rejected file for the accepted artifact. `make test` is green at 265
**because** that file was set aside, not because the fixture was accepted. 115 model responses
are cached, so the non-group-0 prompts stay free.

### 9. Singletons collided — **CLOSED 2026-08-26**, and the stated cause was wrong

**Round 7 passes every band.** Measured with Appendix A over the fixture now at
`local/fixtures/export.csv`, `uv run python <scratchpad>/profile_compare.py` exiting **0** with
*"every compared dimension is within the design doc's tolerance"*:

All three bands (singletons, mid, large) are within ±0.0001 of the real bands (tolerance 0.01), so
all three **PASS** (real figures omitted).

Appendix B, `uv run python <scratchpad>/diagnose_clusters.py`: **0 of the intended singletons collide**
(down from 173), **0 spurious clusters** (from 76), 51 of 51 groups clustering, 0 fragmented.
`verify` clean, exit 0, 1,500 rows, padding **1** of 1,500. `make test` **294 passed** with
`test_the_generated_fixture_profiles_like_the_real_corpus` green for the first time. 413 model
responses cached, provenance `vllm-Qwen-Qwen2.5-32B-Instruct-AWQ-t0.8`, no `fake-seed-*`.

Progression, so the contribution of each change is attributable:

| round | change | bands vs real | collisions | padding |
|---|---|---|---:|---:|
| 3 | baseline | singletons low, mid high, large passes | 173 | 0 |
| 4 | voices + designations (`f7bab79`, `6088740`) | singletons low, mid high, large exact | 121 | 0 |
| 5 | group-consistent blanking (`05e2cb8`) | singletons low, mid high, large exact | 121 | 0 |
| 6 | dedup, exact Jaccard 0.7 (`d93bcd4`) | singletons slightly low, mid slightly high | 19 | 0 |
| 7 | dedup via the profiler's LSH (`7ba12f9`) | **all three within ±0.0001** | **0** | 1 |

**The finding's stated cause was wrong, and this is the correction.** It said the collisions were
formulaic German phrasing crossing MinHash 0.7 over a token set, and recommended voices as *the*
fix. Voices are real — they cut collisions 173 → 121 and are visibly doing their job, the terse
`Monteurnotiz` producing *"Druckmessung bei Betrieb: 120 bar statt 140 bar"* against round 3's
flowing prose — but they were not the fix. The actual causes were two mechanical defects:

1. **The model repeats itself inside ONE response.** 175 of 1,112 parsed singleton tickets were
   literal repeats; 48 reached the fixture. 100% of round 4's collisions sat inside a single
   batch at median pairwise Jaccard **1.000**. Not near-duplicates — exact duplicates.
2. **Per-row description blanking split groups.** A pair clusters iff both members agree on
   blanking: 14 of 14 size-2 groups with exactly one member blanked SPLIT, all 17 with 0 or 2
   held. 41 loose rows, 24 alone in a size-1 cluster.

The two pulled the band in opposite directions and partially cancelled, so fixing only the
obvious one overshot the target. Both were needed.

**Three hypotheses of mine were tested and were WRONG. Recorded with their numbers.**

- *Terse voices drive the residual, because a small token set crosses 0.7 on few shared tokens.*
  Refuted: per voice, Monteurnotiz 10.0%, Kundenmail 13.9%, Formularauszug 8.0%, and colliding
  documents carried LARGER token sets than clean ones (median 8 vs 6). The rambling voice is the
  weak one.
- *A `ReadTimeout` is a stalled request from a previously killed run* (the plan's own
  explanation). Refuted: the container was two minutes old and 61 group asks had just succeeded
  through it. See finding 10.
- *An exact-Jaccard cutoff at 0.7 suffices for dedup.* Refuted, and this is the one worth
  carrying: `clusters.profile` builds clusters from `lsh.query()` buckets and never re-verifies
  Jaccard, so **MinHashLSH(0.7, num_perm=128) clusters pairs measured as low as 0.600.** Of the
  15 pairs surviving the exact rule, 7 were below 0.7 (0.647, 0.667 ×4, 0.600 ×2). The generator
  now queries the same index instead of modelling it, which costs 26.5% of supply against 30.8%
  for a guessed exact-0.6 margin.

**"Near-duplicate at 0.7" therefore means "at roughly 0.6 or above" throughout this project.**
The real corpus's own bands were measured with the same approximation, so the comparison is
like-for-like and there is no fidelity problem — but do not reason from the 0.7 as if it were
exact.

**What actually closed it**, all six commits verified by re-running `make test` and `make lint`
by hand: voices (`f7bab79`), invented designations (`6088740`), a `max_tokens` bound
(`199805c`, finding 10), group-consistent blanking (`05e2cb8`), batch dedup plus a top-up that
names the faults already taken and a lexically-distinct `llm.Fake` (`d93bcd4`), and dedup by
LSH query (`7ba12f9`).

**Dedup alone was not enough and this is why the top-up changed.** Filtering converts repetition
into shortfall: 32 of 46 batches came up short by 319 rows in total, and a blind top-up cannot
refill because the model still cannot see what it already produced. A top-up now lists the
accepted titles under `Vermeide`. An empty avoid tuple leaves the first ask byte-identical, so
the 46 cached first-ask responses still hit; a test pins that byte-identity.

**The fixture is the acceptance candidate and is deliberately NOT committed.** It sits at
`local/fixtures/export.csv` and stays uncommitted until the Window B leakage gate is green —
a separate plan and a sealed window. Re-gating a committed fixture costs another window.

The original finding, kept for the reasoning:

### 9 (original). Singletons collide on formulaic German, not on shared vocabulary

The last thing between the fixture and acceptance. Round 3 (2026-08-19): padding **0**,
`verify` clean, 1,500 rows, all 51 groups clustering, large band within tolerance of the real one. Two bands still out:

Round 3 bands (real figures omitted): singletons about ten points low, mid about ten points high,
large passes.

**173 of the intended singletons (about 15%) land in clusters of ≥2**, across 76 spurious clusters. Those
rows are precisely the singleton deficit and the mid surplus.

**A hypothesis was tested and was wrong — recorded so it is not retried.** Finding 8's
residual A assumed the cause was *cross-batch vocabulary competition*: 46 batches asked for 25
different faults with no memory of each other. Steering each batch to its own subsystem
(`SUBSYSTEMS`, `1e44136`…) moved collisions from **182 to 173**. A 5% improvement, not a fix.

The measurement showed why. The collisions are now **within** a batch, not across batches:
*Zapfwelle blockiert / Zapfwelle nicht gerade / Zapfwelle nicht dicht*,
*Kraftstofftankventilabdeckung / Kraftstofftankventilkopf*. Forcing 25 distinct faults into a
single subsystem makes the model emit minor variations on one component. The steering traded
cross-batch collisions for within-batch ones at roughly par. It was kept because it does no
harm and the subsystem vocabulary is more realistic, but **it is not the fix.**

**The real cause is formulaic phrasing.** At MinHash 0.7 over a token *set*, two short
generic German descriptions collide easily — *"Defektes X. Die Maschine zeigt …"* recurs
regardless of which component X is. The generator asks for content, never for *voice*.

**Two `PROJECT_BRIEF.md` §8 requirements are unimplemented, and they are the fix.**

1. **Voices.** §8: "Expand each into 1–40 variants … *in different voices (terse mechanic,
   rambling customer email, template dump)*." Nothing in `generate.py` asks for a voice. A
   terse mechanic's note and a rambling customer email about the same fault share few tokens,
   so voice is the lever with real leverage on Jaccard. **This is the recommended fix.**
2. **A fictional product line.** §8: "Invent a fictional product line with obviously fake
   designations (`TX-2200`, `LR-45`) so any leak is visually obvious." Also unimplemented.
   Worth doing on its own merits — it is a leakage-detection aid — and it helps here, but only
   marginally: `_TOKEN` is `[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,}`, so a token may contain
   digits provided it *starts* with a letter. `TX-2200` survives as one unique token (unlike
   `Stoerung 98`, whose `98` is dropped entirely — that is finding 8's padding bug). But the
   arithmetic is unforgiving: two docs of ~30 tokens at Jaccard 0.75 share ~25.7 tokens, and
   adding one unique token each only drops them to 0.708. Two unique tokens reach 0.671.
   Designations alone will not clear a 0.9 collision.

So: implement voices for the singleton path, add the fictional designations alongside, and
re-measure. Do **not** re-attempt subsystem steering as the cure — it has been measured.

**Do not fix this by adjusting the planner's mid budget.** Letting the planner allocate fewer
intentional mid groups to absorb ~170 accidental ones would make the bands match while leaving
relevance density roughly double the real corpus, which inflates recall@10 on synthetic exactly
where `PROJECT_BRIEF.md` §9's divergence rule says to fix the generator instead.

#### Round 4 (2026-08-26): voices and designations shipped, measured, and NOT sufficient

Tasks 1 and 2 of `docs/superpowers/plans/2026-08-19-cluster-bands-voices-and-designations.md`
are implemented (`f7bab79`, `6088740`), 281 tests pass, lint clean. Task 3 was **not** run: it
is gated on window question 1, still unanswered. Regenerated on the H100 against
`Qwen/Qwen2.5-32B-Instruct-AWQ`, 353 cached model responses, padding **0**, `groups_short` 0,
`verify` clean, exit 0, 1,500 rows.

Round 4 (real figures omitted): singletons about six points low (**FAIL**), mid about six points
high (**FAIL**), large **PASS, exactly**.

Singleton collisions **173 → 121** of the intended singletons (about 15% → 10%), spurious clusters **76 → 51**,
all 51 intended groups still cluster, 0 fragmented. Everything else still passes: `customData`
field shares 26/26, fill-by-year 12/12, descriptor quantiles p90–p999 all matching, parse success 1.0.

**So voices are a real effect and an insufficient one.** A 30% cut in collisions moved the singleton band only about a third of the distance it needed. To reach the ±0.01 band the collisions must fall
from 121 to about **38** — roughly two thirds of what remains. **Task 3 cannot supply that:**
it changes only the dominant group's text, and the large band already passes exactly. Nothing
in the current plan addresses the residual 121.

Two incidental wins worth keeping: the large band is now **exact** (round 3 was a few rows over) and the invented designations are visibly present in
`clusters.largest` top_tokens (`tx-2200`, `lr-2200`, `vg-2210`, `tx-2250`), which is precisely
the leak-detection aid `PROJECT_BRIEF.md` §8 asked for.

**A hypothesis about the residual was tested and was WRONG — recorded so it is not retried.**
The surviving collision titles are terse (*Schlauch C3 Risse*, *Kabelbaum: Kabelenden lose*),
which suggested that terse voices produce small token sets and small sets cross Jaccard 0.7 on
few shared tokens. Measured per voice over the intended singletons:

| voice | rows | collide | rate | median cleaned tokens |
|---|---:|---:|---:|---:|
| Monteurnotiz (terse) | 390 | 39 | **10.0%** | 6 |
| Kundenmail (rambling) | 375 | 52 | **13.9%** | 10 |
| Formularauszug (form) | 375 | 30 | **8.0%** | 9 |

The **rambling** voice collides most and the terse ones least, and colliding documents have
*larger* token sets than clean ones (median 8 vs 6, p75 17 vs 11). So the terse-small-set
theory is refuted. The weak voice is `Kundenmail`; if this is picked up again, look there
first rather than at the terse voices.

#### The anatomy of the residual, measured 2026-08-26 — finding 9's PREMISE IS WRONG

Finding 9 says the residual is "formulaic phrasing" colliding at MinHash 0.7 over a token set.
**It is not.** Measured on the round-4 fixture:

- **100% of the 121 collisions are inside a single batch.** 51 clusters, every one confined to
  one batch, **zero** spanning batches.
- **Median pairwise Jaccard is 1.000 — on title+description AND on title alone.** These are not
  near-duplicates at 0.7. They are *exact* duplicates. 60.4% of colliding pairs reach 0.7 on the
  title alone.

The mechanism is that **the model repeats itself inside one response.** Asked for 25 distinct
faults in one subsystem it emits literal repeats — series 25 produced *"Druckluftanlage hat
Schwierigkeiten mit dem Anpressen"* twice, identically, and `_parse` accepts every copy.

| | |
|---|---:|
| tickets parsed from first asks | 1,112 |
| **exact repeats within one response** | **175 (15.7%)** |
| tickets parsed from top-up asks | 230 |
| top-up rows repeating a first-ask row | **7** |
| batches whose used 25 contain a duplicate | **16 of 46** |
| duplicate rows surviving into the fixture | **48** |

Worst batches: series 25 (Druckluftanlage) 11, series 35 (Ventilsteuerung) 10, series 19
(Kabelbaum) 7. So the residual is ~48 exact duplicates plus ~22 genuine near-duplicates.

**There is a SECOND defect, and it pulls the band the other way.** 27 of 51 intended groups
have a member that clusters with none of its own group — 41 loose rows, 24 of them alone in a
size-1 cluster, almost all in groups of size 2. Cause, confirmed with zero exceptions:

| groups of size 2 | outcome | count |
|---|---|---:|
| 0 of 2 blanked | cluster together | 11 |
| **1 of 2 blanked** | **SPLIT** | **14** |
| 2 of 2 blanked | cluster together | 6 |

A pair splits **iff exactly one member's description was blanked**, because a blanked row's
cleaned token set is the title alone. This is finding 8's residual B and the same mechanism as
the dominant group's 141+75 split — and Task 3 addresses it only for groups ≥ `FORM_GROUP_MIN`
(planned 50), so every group of 2 stays broken.

**The band arithmetic, which is why the obvious fix is not enough:**

| scenario | singleton band | verdict |
|---|---|---|
| measured (round 4) | well below target | FAIL |
| fix A only (singletons all distinct) | **overshoots** the target | **FAIL** |
| fix B only (groups all cluster) | further below target | FAIL |
| **fix A and B** | **on target (within ±0.0001)** | **PASS** |

The two defects partially cancel, so fixing only the duplicates moves the band *past* the
target. Both are required, and together they land on the design's predicted band exactly.
Any future session that "fixes the duplicates" alone and sees the band overshoot should look
here rather than concluding the dedup was wrong.

#### Task 3 as written would make `verify` REFUSE the fixture — measured 2026-08-26

Independent of window question 1, Task 3 cannot be run as the plan writes it.
`fixtures/__main__.py:114` renders `description = ticket.description if keep_description[index]
else ""`, so the per-year fill plan is only met when the ticket actually carries description
text. Task 3 gives the dominant group no `BEFUND` and sets its fallback to `""`, so all of its rows carry empty text and the rows the plan flagged `keep` render empty anyway.

Measured on the round-4 fixture, description fill-by-year after Task 3:

the first year (a handful of rows) stays within tolerance, but every later year falls 5 to 13 points
below its target (tolerance 0.05), so **5 of 6 years fail**.

Corpus description fill drops by about nine points, **5 of 6 years outside tolerance**,
so `verify` returns exit 3 and no fixture is written. Task 3 needs a compensating change
before it can run: either the planner hands the form group's description budget to other rows,
or the form carries a short *shared boilerplate* description instead of none — which also
still fixes the 141+75 split, because a boilerplate description is identical across members
and so blanking it is the only thing that can split them.

**Artifacts.** Four rounds of real model output are kept for comparison, none accepted, none at
the shipped path: `export.bands-rejected-2026-08-19.csv` (pre-fix, no cluster structure at all),
`export.round2-singleton-collisions-2026-08-19.csv` (groups cluster, large band passes),
`export.round3-no-padding-2026-08-19.csv` (padding 0), and
`export.round4-voices-designations-2026-08-26.csv` (padding 0, collisions 121, large band exact
— the current best). 353 model responses are cached.

### 10. Generation is unbounded, so one unlucky draw kills a whole run — CLOSED (`199805c`)

**Fixed 2026-08-26, but this entry was never updated, so it read OPEN for six weeks.** Noticed 2026-10-11 when the operator chose this finding as the next task and the fix was already in the code: `fixtures/llm.py` sends `"max_tokens": MAX_TOKENS` (4096), outside the cache key, and `test_a_model_request_bounds_its_own_length` pins it (passes). The analysis below is kept as the reasoning behind the number.

Found 2026-08-26 while regenerating for round 4. Two consecutive runs died on
`httpx.ReadTimeout` — after 588s at singleton series 0, then after 903s at series 25.

**The plan's stock explanation for a ReadTimeout is wrong and should not be repeated.** It says
such a timeout is "usually a request left stalling by a previously killed run". It cannot have
been: the vLLM container was two minutes old and all 61 group asks had just gone through it.

**The cause is that `fixtures/llm.py` sends `temperature: 0.8` with no `max_tokens`,** so a
draw is bounded only by `--max-model-len 32768` while the client gives up at 120s. The length
distribution has a long tail. Measured over one prompt, n=6 each, and over the 28 calls of a
prefill run:

- 12 controlled draws: 1,012–2,601 completion tokens, 17–43s, every one `finish_reason: stop`.
- prefill, 28 calls: fastest 14.4s / 867 tokens, **slowest 112.6s / 6,665 tokens** — seven
  seconds inside the timeout — plus a 92.6s / 5,505-token draw.
- the two draws that killed the runs were still generating past 120s at ~59 tok/s, i.e. roughly
  7,000 tokens, with GPU KV cache usage climbing monotonically at `Running: 1`.

So ~2 of ~36 draws exceed the timeout, about 5%. Round 3 surviving 46/46 was luck, not
headroom: its largest cached response is 8,617 chars.

**Also measured, and it clears Task 1 of blame:** the new voiced prompt is *faster* than round
3's, median 25.2s against 34.1s and median 1,521 completion tokens against 2,052. The two
failures landed on different voices (series 0 is Monteurnotiz, series 25 is Kundenmail) and 8
Kundenmail batches succeeded, so this is not voice-specific.

**The fix, for the operator to rule on:** add `"max_tokens": 4096` to the request in
`fixtures/llm.py`. It caps a runaway at ~70s while leaving every measured draw untouched, and
it does **not** invalidate the cache, because the key is `sha256(identity + "\0" + prompt)`
(`fixtures/llm.py:56`) and excludes request parameters. It was deliberately **not** applied,
because it changes generation semantics for every future run and is outside the approved plan.

**The workaround used instead, which needs no production change:** replay `generate.tickets`
with the CLI's own plan through `llm.Cached` under the CLI's own identity and cache directory,
with a 900s read timeout. Same model, same temperature, same prompts, same identity, so the
cached answers are genuine model output and resumption is exactly what the cache is for. The
CLI then runs fully warm.

### 12. The leakage gate's neighbour baseline was saturated by the fixture's own clusters — CLOSED 2026-09-07

Found 2026-08-27 by running Plan A's finished gate over the accepted fixture against itself.
This is exactly what Plan A's "runnable with no model, no GPU, no window" property is for: the
defect is in the **approved design**, and a sealed window is the most expensive place to find
one.

`docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md` says the
synthetic-vs-real p99 is compared against a synthetic-vs-synthetic p99 "calibrated in the same
window … reported alongside the baseline so the number is interpretable". The baseline is meant
to say **how close unrelated invented tickets sit** under the embedder.

Measured on the accepted 1,500-row fixture:

| | |
|---|---:|
| baseline p99, whole fixture | **1.000000** |
| baseline p99, intended singletons only | **0.926838** |
| rows in deliberate duplicate groups | about a quarter of 1,500 |
| rows whose nearest neighbour is at cosine ~1.0 | 41 (2.7%) |

The 99th percentile needs only the top 1%, so 41 saturating rows put the baseline at 1.0. The
bar `cross_p99 <= baseline_p99` becomes `cross_p99 <= 1.0`, **which nothing can exceed — check
2 cannot fail.** The cause is structural rather than arithmetic: the fixture is *built* to
contain near-duplicate clusters, so a whole-corpus baseline measures those instead of unrelated
text.

This is the same failure class as the diagonal bug that `self_baseline` guards against — a
check that appears to do arithmetic while its verdict is predetermined — arrived at by a
different route. The diagonal one was caught by deliberately writing the wrong version; this
one only appeared once the whole gate ran against real fixture structure.

**Made visible, not silently fixed.** `report.build` now emits `baseline_saturated` beside the
verdict (`0f5b937`), so "neighbours: pass" cannot be read as evidence when the bar was 1.0.
Choosing the actual fix is a decision the operator's three 2026-08-27 rulings do not cover:

- **pass the singleton boundary in** (e.g. `--baseline-rows-from N`) and compute the baseline
  over intended singletons only, which is closest to the design's stated intent and gives
  0.926838. Costs the gate a piece of planner knowledge it currently does not need.
- **lower the percentile.** Measured on the whole fixture: p95 0.965943, p90 0.942546, p75
  0.852062, p50 0.751427. Cheap, but picks a number without a principle.
- **exclude near-duplicate pairs from the baseline.** Circular unless the exclusion rule is
  something other than cosine, and group members are *not* byte-identical documents — they
  share title and description but differ in `solutions` — so an identical-text rule would not
  catch them.

#### Resolved: `BASELINE_PERCENTILE = 95` (`a7540b7`)

The operator chose to lower the percentile rather than pass the singleton boundary in. Which
percentile was then a sub-decision, and picking it by eye risks the opposite failure — a bar so
tight the gate fires on a clean fixture and gets relaxed the first time it does.

So it was chosen against a measured **clean** comparison, which needed a corpus genuinely
independent of the current fixture. **Most of the parked rounds are not** — worth knowing before
anyone else uses them as a comparison baseline:

| parked round | byte-identical documents shared with round 7 |
|---|---:|
| round 3 | **2 of 1,450 (0.1%)** — genuinely independent |
| round 4 | 1,033 of 1,451 (71.2%) |
| round 5 | 1,071 of 1,450 (73.9%) |
| round 6 | 1,280 of 1,467 (87.3%) |

Rounds 4–6 overlap because round 7 reused 413 cached model responses written during them, so
their `cross_p99` of 1.000000 against round 7 is an artifact of shared text rather than
similarity. Round 3 predates the voice, designation and dedup prompt changes, so every one of
its prompts differed. Round 7 against round 3 scores **cross_p99 0.898644**, and against that:

| percentile | baseline | verdict |
|---|---:|---|
| p99 | 1.000000 | saturated — the check cannot fail |
| **p95** | **0.965943** | **usable, and the highest not saturated** |
| p90 | 0.942546 | usable but tighter for no gain |
| p75 | 0.852062 | below 0.898644 — would fail a clean fixture |
| p50 | 0.751427 | below 0.898644 — would fail a clean fixture |

Round 3 shares this generator's themes and subsystem vocabulary, so it is *more* similar to
round 7 than real data should be to either: 0.898644 is a conservative bound.

**Verified end to end, not by arithmetic.** The fixture against itself now goes red
(cross 1.0 > baseline 0.96689, exit 3); against round 3 it goes green (0.898644 < 0.96689).
Both previously passed vacuously against a 1.0 bar.

`CROSS_PERCENTILE` stays 99 — a leak surfaces as a handful of rows in the tail — so the two
quantiles differ deliberately and the report field is named `baseline_p95` to make that visible.
`baseline_saturated` remains as the guard for a future fixture with more cluster mass: p95 needs
5% of rows twinned to saturate, against the 2.7% measured today.

### 13. The leakage gate's roster check CANNOT FAIL — OPEN, needs an operator ruling

Found 2026-09-07 while establishing ground truth for Plan B's Task 6, and confirmed against the
real corpus's own profile rather than against the fixture alone.

`profiler/gate/__main__.py:32` sets `ROSTER_COLUMN = "ansprechpartner"`. That is **not one of the
38 columns** in `profiler/columns.py`, and `local/artifacts/profile.json` shows the real export
has exactly 38 top-level columns with no `ansprechpartner` among them. It is a key one level down
inside the double-encoded `customData` EAV envelope — the parked-decision section below places it
there, in most rows.

So `[row.get(ROSTER_COLUMN) for row in synthetic_rows]` is a list of `None`, `roster_violations`
skips blanks by design, and check 4 returns 0 **whatever the roster holds** — in a real window
too, because the real export has no such column either.

Measured on a 1,500-row `--fake` fixture (seed 7):

| | |
|---|---:|
| `ROSTER_COLUMN` present as a top-level column | **False** |
| non-blank values in 1,500 rows | **0** |
| `roster_violations(values, frozenset({"Nobody"}))` | **0** |
| rows whose `customData` names `ansprechpartner` | 1,256 of 1,500 |

Two aggravating factors:

- With **no** `--roster` at all, `__main__.py` passes `roster_violations=0` under a comment saying
  *"reporting 0 violations would claim a check that did not run"*. It then reports 0 anyway, and
  `report.build` turns that into `"roster": {"passed": true, "violations": 0}`, which feeds a
  `True` into the `all(...)` behind `verdict`.
- `report.py` already carries `embedder_is_a_model` and `baseline_saturated` for exactly this
  hazard. Check 4 has no counterpart, so **in the artifact a skipped roster check is
  byte-identical to one that ran and found nothing.** The DPO-facing report cannot distinguish
  them.

**Not fixed, deliberately.** The obvious repair — read the name out of `customData` — is forbidden
by the 2026-08-17 parked decision that nothing downstream may read `ansprechpartner`. Options for
the operator: point `ROSTER_COLUMN` at a column that exists and carries names (`merchantName`,
`endCustomerName` and `lastModifiedUser` are all among the 38), or add a `roster_values_traced`
count to the report so vacuity is visible the way saturation is.

### 14. The window's gate report will carry `code_commit: "unknown"` — OPEN, one-line fix

`report.py`'s docstring says the manifest exists so "the run is reproducible".
`__main__._commit()` shells out to git and falls back to `"unknown"`. Measured: `command -v git`
inside `recall/profiler:pinned` returns nothing, and window b's `WINDOW_CMD` passes no
`--code-commit`. So the field reads `"unknown"` in exactly the run the manifest exists for. The
CLI's own comment anticipates this (*"The operator passes --code-commit there"*) but the command
block written in Plan B's Task 5 does not.

Fix: add `--code-commit "$(git rev-parse --short HEAD)"` to window b's `WINDOW_CMD`. `cmd_ship`
already refuses a dirty tree, so the sha would be meaningful.

### 15. The CLI's "end-to-end green" test is green on three checks, not four — OPEN

The eighth wrong-reason assertion on this project. `tests/unit/test_gate_report.py:191`
(`test_the_cli_writes_a_green_report_without_a_model`) asserts `verdict == "green"` on a `main()`
call that passes no `--roster`, so check 4 never runs and is counted as a pass by finding 13's
mechanism. Measured: `grep -rn '\-\-roster' tests/` returns **0**, against **3** `main()` call
sites in that file. Nothing in the assertion block mentions the roster, so the skip is invisible
at the test level while the test's name presents it as the CLI's end-to-end green.

### Two wrong-reason tests found and CLOSED in Plan B's own test file (`52091b6`)

Both were in text Plan B specified verbatim, which is worth noting: the plan was reviewed and
still shipped them.

1. **`_model()`'s `except Exception` turned every failure into a skip** labelled "weights not
   available locally". Measured: before `E5Embedder` existed the file reported `5 skipped` with
   reason `module 'profiler.gate.embedder' has no attribute 'E5Embedder'` — so the file had **no
   failing state at all**, only `passed` or `skipped`. Now the class is resolved *outside* the
   `try` and only `OSError` skips. The exception type was determined empirically, not guessed:
   transformers raises a plain `OSError`, chained from
   `huggingface_hub.errors.LocalEntryNotFoundError` — catching that subclass would **not** have
   worked.
2. **`test_pooling_is_masked_mean_not_cls` could not detect CLS pooling.** Measured: a CLS variant's
   alone-vs-padded difference is **6.519e-08** against the test's own `atol=1e-4`, ~1500x inside
   it, because padded positions are excluded from attention so row 0's CLS state is
   padding-invariant too. Meanwhile **cosine(masked-mean, CLS) = 0.957832**, so the mistake would
   shift every cosine in the report and the percentile calibration while the test stayed green.
   Renamed to `test_padding_does_not_shift_the_result` (what it actually pins) and a new
   `test_pooling_matches_an_independently_computed_masked_mean` recomputes the masked mean by hand
   and asserts the CLS vector differs. Verified by injection: with CLS pooling patched in, the new
   test fails and the renamed one still passes.

### Measured e5 CPU throughput — do NOT budget a window from a rehearsal figure

| corpus | mean document | rate |
|---|---:|---:|
| `--fake` stub, i.e. what a rehearsal measures | 106 chars | **13.51 docs/s** |
| built to the real corpus's measured token-length mix | ~600 chars | **1.21 docs/s** |

An **11x gap**, both on the workstation (i5-9400F, 6 cores), `batch_size=16`, 512 documents each
after a 32-document warm-up, called through `neighbours._encode`'s prefix.

And the work is **~20,000 encode passes, not one per document**: `neighbours.cross_p99` encodes
synthetic + real, and `neighbours.self_baseline` encodes the synthetic corpus **again**. At the
real-length rate that is **~4.4 h** on the workstation.

**The window runs on `hpc`, not the workstation** — AMD EPYC 9534, 256 threads, 1 TB RAM — so
per-document throughput there should be materially better. But measured 2026-09-07 23:42 its load
average was **193.97 with 22 users logged in**, and **nothing caps thread count**: not the gate,
not `E5Embedder`, and not `window.sh`'s podman invocation (no `--cpus`). torch will take every
core it can see. Whoever books the window should choose a thread cap deliberately rather than
discover one, both for fair use and to make the runtime predictable.

### Hypotheses of mine that were WRONG, recorded so the next session does not re-suspect them

- **"The stub's documents are too short to form an 8-token shingle, so check 1 is vacuous."**
  Wrong. Measured on 1,500 rows: 1,698 shingles for seed 7, with **849 of 1,500 documents
  (56.6%)** carrying at least one, and copying one document verbatim to the real side makes
  `shingles.collisions` return 1. Check 1's zero is evidence, not an empty intersection.
- **"Two `--fake` seeds will overlap lexically, since this file records that stub text
  near-duplicates itself."** Wrong for cross-seed comparison. Seeds 7 and 23 at 1,500 rows share
  **0** byte-identical documents and produce **0** shingle collisions. The self-similarity that
  collapses a single `--fake` run into one cluster does not translate into cross-seed overlap, so
  Plan B's premise for the rehearsal corpora holds.
- **"The sealed image will be 4–5 GB."** It is **3.51 GB**, up from 405 MB.

### 11. The dedup is per-batch, so two clustering paths are uncovered — OPEN, not currently biting

Found 2026-08-27 by reviewing the claim in `_keep_distinct`'s own docstring. It says a
per-batch `MinHashLSH` index faithfully predicts the whole-corpus one. For **pairwise
bucketing** that is true and the reasoning holds: datasketch bands each signature
independently, so whether two items share a bucket depends only on their own band slices, not
on what else is indexed.

**But `clusters.profile` does not match pairwise — it does a greedy sweep:**

```python
members = {int(k) for k in lsh.query(hashes[i])} | {i}
```

so a row joins a cluster because it buckets with *any* member, including one it was never
compared against. `_keep_distinct` compares a candidate only against the ~25 already accepted
**in the same batch**. Two paths are therefore uncovered:

1. a singleton buckets with a member of the dominant group or a mid group
2. a singleton buckets with a singleton from a **different** batch — dedup and the `Vermeide`
   avoid list are both per batch

**Measured on round 7, at the raw LSH level before the greedy sweep collapses it:**

| relation | singletons affected |
|---|---:|
| buckets with a group row | **0** |
| buckets with another batch's singleton | **0** |
| buckets within its own batch (what dedup covers) | **0** |

So round 7's 0 collisions are genuine and are not hiding an uncovered path that merely
happened not to fire. The within-batch zero also confirms the dedup does what it claims.

**Why it is still worth recording.** Nothing in the generator *prevents* either path — the two
zeros come from voices, per-batch subsystems and invented designations making cross-batch
overlap unlikely, and from group text being structurally unlike singleton text. That is
well-founded but it is not a guarantee. Two consequences:

- **The bands may be seed-sensitive.** Round 7 is seed 7 only. A different seed changes the
  plan and therefore the prompts, and nothing rules out a cross-batch bucket on another seed.
  Confirming would cost one H100 regeneration per seed.
- **`PROJECT_BRIEF.md` §8's programmatic noise injection is still unimplemented** — signatures,
  quoted reply chains, corrupted casing, HTML, applied mechanically after generation. Noise
  moves token sets, so it could make either path fire. Whoever implements it should re-measure
  these three numbers, not just the bands.

Closing it properly would mean deduping against a corpus-wide index rather than a per-batch
one, which needs the group text available at singleton-generation time. Not done, because
nothing currently justifies the coupling.

### Task 3 (the dominant cluster as a form) — DROPPED 2026-08-27 by operator ruling

It bought no acceptance criterion. The large band passes **exactly** against the real band (a with-description cluster plus a blanked one), every other group coheres after `05e2cb8`, and Task 3's
only remaining effect would have been merging that with-description/blanked split into one cluster — the
same band either way. Its value was robustness: if the description blank rate ever fell far
enough to put one half under 50, that half would drop into the mid band.

It also **could not be run as the plan wrote it**. `fixtures/__main__.py:114` renders
`description = ticket.description if keep_description[index] else ""`, so emptying the form
group's description text drops corpus description fill by about nine points and puts **5 of 6 years**
outside `verify`'s tolerance — exit 3, no fixture. The operator selected the shared-boilerplate
variant if it were ever revived: one short description identical across all members, which
cannot be split by blanking (identical text either way) while preserving the fill budget.

**Consequence: window question 1 below is retired as a blocker.** It gated only this task.
Questions 1–4 are kept as fidelity questions about the client's data, because the answers would
still tell us whether the real dominant cluster is near-empty tickets — but nothing in M2 now
waits on them, and no sealed window needs to be spent on them.

### Open questions — no longer blocking; kept as fidelity questions (2026-08-19)

**Why the real corpus's biggest cluster does not split under description blanking, when the
fixture's does.** Finding 8's residual B: the fixture's dominant group comes out as a larger cluster
of rows with a description plus a smaller blanked one, because a blanked row's cleaned token set is
the **title alone** and cannot reach 0.7 Jaccard against title+description. The real largest cluster
is a single group despite a middling-to-high real description fill by year, so something differs.

What the gated profile already shows, without a window: real titles are short (a handful of cleaned
tokens at the median) and descriptions are shorter still. At least a quarter of all real rows have a
**completely empty** cleaned description, and the median is under ten tokens. The fixture's synthetic
descriptions run 30-40 tokens.

And `clusters.largest` top_tokens are tiny: one or two tokens per cluster (the two handover-slip title
words, and single words about fault codes and warranty claims). Narrative tickets would carry far more
vocabulary.

**Hypothesis: the real near-duplicate clusters are near-empty tickets** - a two-word title and
no description - which would explain both why they cluster at all and why blanking cannot split
them. **Not confirmed**, because `top_tokens` is frequency-floored and entity-swept, so 1-2
tokens may only mean the rest fell below the floor.

Four aggregate-only questions, for the operator to answer on the box. Question 1 is decisive:

1. Of the **rows in the largest near-duplicate cluster**, what fraction have a non-empty
   `description`?
2. For those cluster rows that *do* have one - median cleaned token count of the description,
   and of the title?
3. How many **distinct** cleaned description strings exist across those rows? A handful
   means a form; hundreds means narrative.
4. Does the cluster mix rows with and without a description, or is it homogeneous? If it mixes
   them, MinHash is bridging them somehow and that mechanism matters.

If (1) comes back near zero, the fixture's dominant cluster should be a short title with an
**empty** description and the split disappears by construction - that is Task 3 of
`docs/superpowers/plans/2026-08-19-cluster-bands-voices-and-designations.md`. If it comes back
above ~50%, the hypothesis is wrong and that task must not be run as written.

### Lesser, recorded so they are not rediscovered

- **The plan's Appendix A `profile_compare.py` dirties `local/quarantine`, and rounds 1–3 did
  it too.** `profiler/safety.py` sets `DETAIL_LOG = RECALL_PROFILER_DETAIL_LOG or
  QUARANTINE_DIR / "profiler_detail.log"` at import, and `build_profile` writes its verbatim
  detail sink there. Inside pytest an autouse fixture in `tests/conftest.py` monkeypatches it
  away; run as a plain script there is no fixture, so `local/quarantine/profiler_detail.log`
  appears and `test_the_test_suite_does_not_dirty_the_quarantine` correctly goes red. Fix in
  any copy of that script: `os.environ.setdefault("RECALL_PROFILER_DETAIL_LOG", <scratchpad
  path>)` **above** the profiler import. The stray file must be shredded by the operator —
  `make check-clean` says "inspect it yourself, shred it, and do not read it with an AI tool",
  and the session hook denies any assistant command naming that path.
- **Two plan bugs in Task 1, both caught by existing tests rather than review** (2026-08-26).
  First, the voice instruction cannot be placed before the `"Schreibe {count} Tickets"`
  sentence: three tests read the count back with `prompt.split("Schreibe ")[1]`
  (`test_fixture_generate.py:190`, `:266`, `:350`) and every instruction opens `"Schreibe als
  …"`, giving `ValueError: invalid literal for int() with base 10: 'als'`. The instruction now
  sits after the count sentence. Second, the singleton top-up offset had to move from
  `len(SUBSYSTEMS) * 1000` to `* 2000`: the new
  `test_consecutive_singleton_batches_do_not_share_a_voice` collects *every* prompt containing
  `VERSCHIEDENEN`, including the two top-ups per batch, and 50·1000 ≡ 2 (mod 3) makes a batch's
  third ask land on the voice the next batch opens with (voices 0,2,1 | 1,0,2 → five adjacent
  clashes). 50·2000 ≡ 1 (mod 3) gives 0,1,2 | 1,2,0 → none. Both multipliers are exact
  multiples of `len(SUBSYSTEMS)`, so `test_a_singleton_topup_stays_in_its_subsystem` holds
  either way. The plan's claim that 50 and 3 being coprime was sufficient did not account for
  its own new test counting top-ups.
- **A wrapper that appends `echo "PYTEST EXIT=$?"` reports exit 0 for a failed run.** The
  background notification said "exit code 0" for a run that failed in 588s. Same class of trap
  the plan already records for piping through `tail`. Use
  `cmd > log 2>&1; rc=$?; echo ... >> log; exit $rc`.
- **25 of 38 columns render as empty strings**, so the design doc's "per-column fill rates
  ±2.0 points" cannot be met by anything in the current generator. This is at least the safe
  direction: the empties include every PII column (`merchantName`, `endCustomerName`,
  `contactEmail`, `contactPhone*`).
- **`notes` (about 40% real fill) and `operations` (about 70%) render empty**, because prose fields carry
  no shape mix. A fixture cannot exercise the open question of indexing them alongside
  `solutions`.
- **Shape-faithful values are semantically impossible** — `deliveryDate` yields `89.88.3403`,
  `baugruppe` yields `,)0,)`. Correct for shape synthesis and it re-profiles identically, but
  anything that ever *parses* those `customData` dates will break.
- **`timestampCreated` is a bare `YYYY-MM-DD`** with the day drawn from 1–28. It parses
  (`temporal.py` anchors on `^\s*(\d{4})-(\d{2})-(\d{2})`), but the column name promises a
  time component the real export probably has.
- **The integration tests are still not fully hermetic**: the two older ones do not pass
  `--cache`, so a run leaves gitignored stub files in the repo's `local/fixtures/cache/`.
  The danger is gone — entries now live in a per-client subdirectory, so stub output cannot
  land where a model run would read it — but the litter remains. The newest test does pass
  `--cache`.
- **`values.pick_shape` has no production caller** since shapes are allocated exactly
  (`7fcf0aa`). Only its own unit test exercises it. Left in place deliberately; deleting it
  is a separate decision.
- **Blanking descriptions per year interacts with clustering, and cannot be measured yet.**
  Near-duplicate clusters are computed over cleaned *title + description*, and roughly a
  third of rows corpus-wide — about half of the rows of the two weakest years — now carry no
  description, so those rows cluster on their title alone. This is faithful, because the
  real corpus's cluster distribution was measured with exactly those blanks present. But
  `--fake` prose collapses into one cluster regardless, so the first real evidence comes
  from the H100 run. **If the measured bands come out low against the plan, look here
  first** — and the fix is a planner or prompt change, not a tolerance change.
- **PII behaved as the deferred decision requires**: `ansprechpartner` renders as obviously
  fake (`Tr. Ouxmu`), is present in the fixture, and is read by nothing.

## SOLVED — customData, and what it changed

`customData` is **double-encoded JSON**: a JSON string whose content is a JSON array of
field *descriptors*, each `{group, key, label, value, text, type}`. So the JSON keys are
the envelope's own attributes and the client's field names are **values of `key`**. It
now parses at **100%**, and `custom_data.envelope` carries the real inventory: 52 distinct
fields, 26 emitted after the floor and entity sweep, a median of a few descriptors per ticket.

**The identifier arm is founded after all, and two earlier conclusions were wrong.**

| field | share of tickets | fill | dominant shape |
|---|---:|---:|---|
| `ansprechpartner-tel` | about 80% | 100% | `#DDDDDDDDDDDD` |
| `ansprechpartner` | about 80% | 100% | `Aa._Laaaaa` |
| `baugruppe` | about a quarter | 100% | `##D##` |
| **`fehlercode`** | **under a fifth** | **nearly 100%** | **`DDDD-D`** |
| `deliveryDate` / `warrantyStart` / `warrantyEnd` | a small minority (the handover slips) | 100% | `DD.DD.DDDD` |
| the handover block (`warrantyPdf`, `checklist`, `equipmentScope`, `driverInstructions`, …) | the same minority | 100% | `Aaaa` |
| `memoryError` / `hydraulicError` / `vehicleError` | the same minority | 100% | `Aaaa`/`Aaaaa` |
| `notes` | the same minority | about 40% | prose |
| `operations` | about a tenth | about 70% | prose |

1. **Round 1's "identifier arm unfounded at a tiny share of tickets" was wrong twice over.** The codes live
   in `customData.fehlercode` (under a fifth of tickets), and their shapes are `DDDD-D`,
   `DDDD-DD`, `DDDDD`, `ALL_DD`, `ALDD_DDDDD` — while `PATTERNS["error_code"]` is
   `\b[A-Z]{1,3}\d{3,5}\b`, which cannot match a leading digit. Wrong field, wrong
   pattern. Some values hold two codes at once (`DDDD-DD#_DDDD-DD`). **Rewrite the
   identifier patterns from these shapes before building the identifier arm.**
2. **`customData` carries PII in most tickets.** `ansprechpartner` (shape `Aa._Laaaaa`
   — an abbreviated salutation plus a surname) and `ansprechpartner-tel` are contact name
   and phone. They must never be indexed, embedded, or surfaced in an answer. This is the
   single most important constraint M2 inherits from this window.
3. **The large handover-slip cluster is explained**: a small minority of tickets carry the
   handover block, whose `Aaaa` values are almost certainly German yes/no flags. That
   cluster is a form, not a fault.
4. **`baugruppe` (about a quarter of tickets) is a component dimension** — a usable retrieval facet the design
   did not know existed.
5. `operations` (about 70% filled) and `notes` (about 40%) are additional free text that may be worth
   indexing alongside `solutions`.

## Previously the open blocker — kept for the reasoning

Kept because the reasoning generalises, not because it is still open.

Rounds 2 and 3 had `customData` present in nearly all rows at a few hundred chars and
parsing at 0.0% — neither JSON nor `key=value`, so the key inventory was empty and the
milestone question went unanswered for two windows.

We cannot see the format because shape discovery matches `[A-Za-z0-9._/:-]` and therefore
cannot represent `=`, `;`, `{`, `<` or whitespace — we excluded exactly the characters
that identify a syntax.

The syntax probe answered it (`preflight-export.sh <export> --syntax customData`), which
is the tool to reach for whenever a free-form column will not parse: it identifies a
format from punctuation alone, on the workstation, without spending a sealed window.

It prints a punctuation skeleton (every letter and digit removed) and a 40-char prefix
shape, both frequency-floored at 50. `{":,}` means JSON, `=;` key-value, `<>/` XML.

The lesson worth carrying: shape discovery deliberately excludes `=`, `;`, `{`, `<` and
whitespace, so it can never explain why a column fails to parse. When something will not
parse, look at the punctuation, not the tokens.

**A session hook blocks any Bash command containing `.csv`,** so the assistant cannot run
`window.sh push` or the probe against the real export. The user must run those two
commands. Do not try to evade the hook.

## What the real corpus says (tens of thousands of tickets, recent years)

- **`solutions` fill is high** (most tickets), usable (non-junk) nearly the same; it is a single
  free-text field. Junk is almost entirely empty strings.
- **About three quarters of tickets are singletons.** A few hundred near-duplicate groups cover the
  remaining quarter.
- **Largest group: roughly one ticket in eight** — handover-slip paperwork. The next largest groups
  are an order of magnitude smaller.
- **Hundreds of groups of size 2–49** cover about a tenth of tickets. These are the variant
  approaches; see the product decision below.
- **The corpus is not uniform** — a real workflow change: in the earliest year solutions were rarely
  filled (about a quarter) although descriptions were; in the two middle years descriptions dipped to
  about half while solutions were nearly always present; in the last two years both fields are well
  filled (about 80%). Recent data is materially better on both fields, so corpus selection is a real
  lever.
- **In free text the identifier arm is thin** — only a few hundred regex matches across the whole
  corpus, and free-text shapes are dominated by bare digit runs and `DD.DD.DDDD` German dates. This
  was read as "the arm is unfounded" for two rounds. It was not: the codes are in
  `customData.fehlercode` (under a fifth of tickets), see the SOLVED section above. The distinctive
  `aDD…` family occurs **only** in `customData`, which was the clue.
- **Over a hundred shapes** clear the frequency floor, covering nearly all digit-bearing token
  occurrences. (Round 2 kept only 50 and reported 68 dropped; the cap is now 200.)
- **`vehicleModelId` is an opaque numeric FK.** The prefix-based model-family proxy is
  dead. `dimension_hints.vehicleModelId` gives per-model vocabulary instead.

## Decisions already made — do not relitigate

- **Near-identical tickets are an ASSET, and every differing solution must reach the
  technician** (user, 2026-08-19). Two tickets describing the same problem with slightly
  different resolutions are exactly what lets the system propose the best approach rather than
  the first one. This is a **retrieval requirement for M3+**, not a fixture concern, and it is
  the reason the fixture's groups are now "one problem, many resolutions" (finding 8). Do not
  design a dedup step that collapses them.
- **Comprehensive answers over deduplication.** Every variant approach must reach the
  technician. Near-duplicate groups are grouped and shown, never collapsed to one
  representative; the large handover-slip group stays in the index. This is the
  user's highest product priority.
- **Cluster characterisation floor stays at `min_frequency`.** A three-ticket cluster's
  top tokens summarise three tickets. The report bands group sizes with counts only, so
  small groups are visible without being characterised.
- **German compound splitting** is solved by deriving a dictionary at build time —
  igerman98 grants `COMPOUNDBEGIN` via affix flag continuation, which PostgreSQL's
  `spell.c` does not implement. Gate is 7/7.
- **`source.filename`** is withheld as `<non-conforming>` unless the file is named
  `export.csv`, plus a warning.
- Sandbox `enabled: false` in settings, keeping deny rules.

## Deferred decisions — parked deliberately, pick up later

### PII in customData (parked 2026-08-17)

`ansprechpartner` (contact name, shape `Aa._Laaaaa` — abbreviated salutation plus
surname) and `ansprechpartner-tel` (phone, `#DDDDDDDDDDDD`) appear in most tickets,
100% filled. **Decision: excluded from the pipeline for now, final treatment deferred.**

Nothing downstream may read, index, embed or surface these two fields until this is
decided. Excluding them is the current behaviour, not a stopgap to be optimised away.

The options when it is picked up, and why it was parked: dropping them at ingest is
simplest and a technician asking "how do I fix fault X" never needs the reporter's phone
number; masking before embedding keeps a future "who reported similar faults" feature
alive at the cost of a scrubbing step that must be correct every time; indexing but not
surfacing is the most capable and the most ways to get it wrong, since the embedding
itself becomes a reconstruction risk. Worth revisiting when the client is reachable and
can say whether contact lookup has any product value at all.

## Open decisions for the user

1. **Rewrite the identifier patterns** from the real `fehlercode` shapes, and decide
   whether the identifier arm is a retrieval arm or just a filter facet at under 20% coverage.
2. **Corpus window for v1** — whether to restrict to the last two years, given the first year's solutions
   collapse and the middle years' description dip.
3. **Two questions only the client can answer:** the `vehicleModelId` values (dozens) mapped to
   a model hierarchy, and whether a fresher export exists.
4. ~~**Generate the fixture now, or close finding 3 first?**~~ Resolved 2026-08-18: finding
   3 was closed first (`1695332`…`aead5f2`), then generation attempted. Generation is
   pending only on the shared H100 being free.

## Operating the airlock

`infra/profiler/window.sh` drives a window end to end. Commands: `ship`, `push`, `run`,
`verify`, `fetch`, `clean`, `status`, `all`. Options include `--window a|b|c`, `--clean`,
`--yes`, `--dry-run`.

Two properties worth preserving if you edit it:

- **`fetch` is allowlisted per window**, so it cannot copy the export or the detail log
  back by accident. That is a property of the code, not of operator memory.
- **`all` deliberately stops before `fetch`**, because the runbook requires
  `profile_report.md` to be read on the box first. That review is the control the whole
  design rests on.

Host `hpc`, quarantine `<data-dir>/recall-quarantine` (`<data-dir>` is `/data/<box-user>`;
`/data` itself is root-owned). Nothing is mounted over `/work`. `ulimit -c 0` is a data
safety control, not tidiness.

`make window-a-rehearsal` is 28/28 and must stay green before any window.

## Carried non-blocking items

- **`uv` is not installed on the workstation as of 2026-10-11** — not on PATH, not in `~/.local/bin`, not a pacman package; it was there through 2026-09-14. `make test` and `make lint` both call `uv run` and fail. Until it is reinstalled the existing `.venv` works directly: `PG_DSN=postgresql://recall:recall_dev_only@localhost:5433/recall .venv/bin/python -m pytest` gives the usual `1 failed, 348 passed`, and `.venv/bin/ruff check . && .venv/bin/ruff format --check .` is clean. Regenerating `uv.lock` or rebuilding the image's lock needs `uv` back.

- `make test` needs the DB up; `needs_pg` has no skip wired.
- `CREATE INDEX CONCURRENTLY` cannot work through the migration runner — this bites M3
  when HNSW indexes are built.
- `-s`-linked German compounds are still missed (xfail).
- The two `cp`s in the Postgres Dockerfile write through Debian symlinks.
- **`<export-dir>/` still holds the real export.**

## Client-data guard (branch `feat/recall-guard`, registered 2026-10-17)

A repo-local `PreToolUse` hook (`tools/guard/`, registered in the tracked `.claude/settings.json`)
keeps real data out of every AI context in this repo. Design:
`docs/superpowers/specs/2026-10-16-recall-guard-design.md`; plan:
`docs/superpowers/plans/2026-10-16-recall-guard.md`. Agent rules are in `CLAUDE.md`.

- **Read policy is an allowlist**: git-tracked files, `local/released/`, `local/artifacts/`,
  `local/fixtures/`, the scratchpad, and files the agent created with `Write` (exact paths).
  Every other file, so every new log or output, is unreadable by default. Sealed outputs go
  through `recall.sealed`; only `tools/guard/export_aggregate.py` (numbers only) releases them.
- **It is a tripwire, not a boundary.** Parsing Bash text cannot be made sound (two independent
  adversarial reviews each found real bypasses; the demonstrated ones are fixed). The hard
  guarantees are the airlock protocol (no real data on the workstation) and the OS sandbox
  (`sandbox.enabled` is still `false`, see below).
- **Maintaining it**: agents cannot edit `tools/guard/`, the registration or the airlock marker;
  a human starts `claude` with `RECALL_GUARD_DEV=1`. `python3 tools/guard/guard.py --explain
  <path>` shows why a path is allowed or denied; `--selfcheck` lists installation problems.
- **Stricter than before**: agents may only `git add` explicit readable files; commit messages
  must be plain `-m "..."` (no `$(cat <<EOF)`); `$VAR`/`$(...)` path arguments are denied.

Human to-do before this is complete:

- [ ] Create `docs/export.header.txt` (one line: the first line of the real export) and
      `git add` it.
- [ ] `make guard-install` (sets `core.hooksPath` for the pre-commit lint).
- [ ] Create `.claude/guard.local.json` with
      `{"extra_protected": ["<export-dir>"]}`: the guard does not yet protect the
      directory that still holds the real export (only the Read deny rule does).
- [ ] Enable the sandbox in `.claude/settings.json` (`"enabled": true`), then check `make test lint`
      and `window.sh status` still work; add `sandbox.excludedCommands` for ssh/uv/docker/podman
      if they break. Confirm the `denyWrite` key is accepted.
- [ ] Run the fresh-session checklist in Task 14 Step 5 of the plan.
