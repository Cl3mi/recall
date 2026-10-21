# Insight report v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (each task:
> implement test-first, controller verifies, risky tasks get an adversarial review).

**Goal:** `python -m insight` produces a report that fixes the empty Baugruppe section and adds ten
sections that show the trends the RAG strategy needs (formats, time, dimensions, concentration,
lifecycle, recurrence, `fehlercode`, vocabulary, readiness), all aggregate, floored and guarded.

**Spec:** `docs/superpowers/specs/2026-10-12-insight-report-v2-design.md`. Read it first. Existing
code: `insight/` (read `release.py`, `guard.py`, `extract.py`, `report.py` before changing anything).

## Rules for every task

- Work only in `~/mci/recall/.worktrees/feat-insight-stage1` (branch `feat/insight-v2`).
- **Test first, and show the red run** before writing the implementation.
- **Never read anything under `local/quarantine/` or `<export-dir>`.** The artifact
  `local/artifacts/report.json` (first real run) IS readable, and so is `local/artifacts/profile.json`
  after `unblessed == 0`. **Never commit any value from them**: git holds no data, not even
  vocabulary. A test that needs a real value must read the artifact at run time and skip if absent.
- A harness hook rejects any Bash command containing the text `.csv`. Keep export paths inside Python
  files (the stand-in builder does), never on a command line, and do not try to work around it.
- The scratchpad is shared: give helper scripts a UNIQUE name, and run `git status --short` after any
  script that writes files. Never run a script you did not write.
- Never `git stash`. Every commit ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Python: `~/mci/recall/.venv/bin/python -m pytest <path> -p no:cacheprovider` (no extra
  `-q`). Lint: `~/mci/recall/.venv/bin/ruff check` and `ruff format --check` clean.
- Do not touch `profiler/entities.py`, `profiler/safety.py`, `profiler/blessing.py`, `profiler/selfcheck.py`.
- Each task ends green: `pytest tests/unit/test_insight_*.py tests/integration/test_insight_*.py
  tests/unit/test_window_d_contract.py` passes and lint is clean.

## Conventions every section module follows

- `build(tickets: list[Ticket], k: int = release.K) -> dict`, pure, no I/O.
- Every released string goes through `release.release(counts, fields, k)`; everything else is a number.
  Entry lists only (`[{"value": ..., "count": n}]`), never a dict keyed by a value. Dicts keyed by a
  column name are allowed; each such module exposes `COLUMNS: tuple[str, ...]` (the guard imports it).
- Withheld tallies use the existing `{"below_floor": {...}, "entity_like": {...}}` blocks so the
  suppression ledger picks them up automatically.
- Fixed bucket labels (hours, days) are literals defined once in the module (`BUCKETS`), released
  through `release.release` with a structural `None` field, so each bucket count is floored too.
- A section that cannot be computed (no parseable dates, say) returns zeros and says so with a
  coverage block. It never raises on an absent column.

## Task 1: Real shapes — Ticket v2, list-valued Baugruppe, new stand-in

**Files:** `insight/release.py`, `insight/names.py` (new), `insight/extract.py`, `insight/origin.py`,
`insight/crosstab.py`, `tests/insight_standin.py`, and their tests (update every test the change
breaks; do not delete coverage).

1. `release.py`: add released fields **`shape`** (flagged unless it fullmatches the closed alphabet
   built from `recall.german.identifiers.SHAPE_ALPHABET`, 1..`SHAPE_MAX` characters) and **`partner`**
   (the code sweep, like `value`). Add them to the sweep table so `RELEASED_FIELDS` includes them.
2. `names.py`: `FIRST_NAMES`, a frozenset of common German first names (lowercase, a few hundred,
   male and female) **chosen so that none is a plausible technical or everyday word** (so not `max`,
   `mark`, `nick`, `wolf`, `rosa`, `bernd` is fine). `release._token_flagged` flags a token that is
   one, and a bigram or trigram if any part is. Tests: ordinary technical words (`motor`, `getriebe`,
   `hydraulik`, `ecm`, `ls`, `fkt`) are NOT flagged; `stefan` and `maria` ARE.
   Plus a real-data regression test that reads `origin.titles.tokens` from `local/artifacts/report.json`
   **at run time** and asserts that the tokens it flags by `names` are exactly the ones the operator reviewed (the expected set lives in the review, not in the repo); it must skip if
   the file is absent and must not embed any token.
3. `extract.py`: `Ticket` keeps its first eight fields in order but `baugruppe` becomes
   `tuple[str, ...]`; add keyword fields with defaults: `baugruppe_empty: bool`, `vehicle_id`,
   `serial_index`, `ticket_number`, `row_id`, `vehicle_status`, `category`, `status`, `priority`,
   `sub_status`, `show_in_proteam`, `contract_transaction`, `fehlercode`, `hours: float | None`,
   `created: date | None`, `created_month: str | None`, `delivery`, `warranty_start`,
   `warranty_end`, `status_changed`, `deadline` (dates), and the identity columns `merchant`,
   `end_customer`, `creator`, `assignee`, `person`, `last_modified`. **Every identity column,
   `serial`, `vehicle_id`, `serial_index`, `ticket_number`, `row_id` and the free text use
   `field(repr=False)`.** Add `custom_values(value, name) -> tuple[str, ...]`: the non-blank string
   values of a customData descriptor whether `value` is a list, a JSON list string, a Python-repr list
   string (`"['5', '12']"`) or a plain string; empty list gives `()` and the caller can tell "present
   but empty" from "absent" (return `None` for absent). Add `parse_date` (`YYYY-MM-DD[ HH:MM:SS]`
   and `DD.MM.YYYY`, else `None`) and `parse_hours`.
4. `origin.baugruppe`: counts **tickets carrying each id** (one ticket counts once per distinct id),
   plus `coverage` (tickets with at least one id), `empty` (tickets whose list is present but empty),
   `ids_per_ticket_quantiles`, `multi_share` (tickets with two or more ids over tickets with at least
   one), `distinct`, `distinct_casefolded`, `top`, `pairs` (entries with `value`, `partner`, `count`,
   unordered pairs, the smaller id first, floored as cells), `concentration`, `by_year`. Keep the
   existing withheld blocks. `crosstab.baugruppe_model_year` explodes per id.
5. `tests/insight_standin.py`: rebuild so it **mirrors the real shapes** (the spec's Stand-in
   section) and exports a `PLAN` mapping of every planted constant so later tests assert against
   constants, not magic numbers. Required: Baugruppe as list values (planted single-id, two-id and
   empty-list rows; keep coverage 0.25 and the existing planted `Huber GmbH` entity-like id and the
   rare id), numeric id strings for some ids; `fehlercode` as `1234-5`-style codes (some rows with two
   codes, a few over 16 characters); `deliveryDate`, `warrantyStart`, `warrantyEnd` as `DD.MM.YYYY`;
   four or five serial formats; `vehicleId` mostly 1:1 with the serial with a few exceptions; numeric
   model ids with about a third missing; `vehicleYear` mostly empty; categories, statuses,
   priorities, sub-statuses; identity columns with a skewed distribution; `vehicleHours`;
   `timestampCreated` over several recent years and `subStatusChanged`/`deadline`; a templated title repeated at
   least `K_TEST` times; an exact-duplicate solution shared by at least `K_TEST` tickets; a part
   number that the cleaning step redacts; the first name `Stefan` in at least `K_TEST` solution
   texts. Existing planted leaks stay and stay effective.
6. Update `report`, `guard` (only what is needed to keep the existing report green: new Baugruppe
   keys) and every existing test; the whole suite is green at the end.

**Done when:** the existing report on the new stand-in passes the guard, `baugruppe` coverage is no
longer empty, and a test proves list values of all four encodings parse.

## Task 2: Formats — `insight/formats.py`

`COLUMNS = ("vehicleSerialNo", "vehicleModelId", "vehicleId", "ticketNumber", "vehicleSerialIndex",
"id", "fehlercode", "deliveryDate", "warrantyStart", "warrantyEnd")`. `build` returns, per column:
`coverage`, `distinct`, `length_quantiles`, `shapes` (entries `{"shape", "count"}` via
`release.release(..., "shape", k)`, the top 20 above the floor) and its `withheld` block. Shapes use
`recall.german.identifiers.shape_of`. Plus `serial_vehicle_id`: serials with more than one
`vehicleId`, vehicle ids with more than one serial, and tickets where both are present (numbers
only). Tests: a stand-in-independent unit test per behaviour; a test that no raw value appears;
a test that shape entries pass `release.flagged("shape", ...)` negatively (never flagged).

## Task 3: Time and lifecycle — `insight/timeline.py`, `insight/lifecycle.py`

`timeline.build`: `per_year` and `per_month` (entries with `year`/`month`, `count`), `fill_by_year`
(per year: tickets and the fill share of description, solutions, serial, model id, Baugruppe,
`fehlercode`, hours, delivery date), `recurrence` (per vehicle with a serial and a parseable date:
`gap_days_quantiles` between consecutive tickets, and `repeat_within_30/90/365_share` over tickets
that have a previous ticket on the same vehicle), `resolution` (`days_to_status_change_quantiles`
where both dates parse, with coverage). `lifecycle.build`: `hours` (coverage, quantiles, bucket
counts), `days_since_delivery` (coverage, quantiles, bucket counts, including a `negative` bucket for
a ticket dated before delivery), `warranty` (counts of in/out/unknown at ticket time, using
`warranty_start`/`warranty_end`). Dates that do not parse count as absent and are reported in
coverage. Tests cover empty input, a single ticket, unparseable dates, and ordering independence
(shuffled rows give an identical result).

## Task 4: Dimensions and concentration — `insight/dimensions.py`, `insight/concentration.py`

`dimensions.COLUMNS = ("categoryId", "statusId", "priorityId", "subStatusString", "vehicleStatus",
"showInProteam", "contractTransaction")`. Per column: coverage, distinct, `values` (entries
`{"value", "count"}`), `by_year` (entries `value`, `year`, `count`), withheld blocks. Plus
`by_category` (entries per `categoryId` value above the floor): ticket count, solution fill,
description fill, problem-text length median and p95. `concentration.COLUMNS = ("merchantId",
"endCustomerId", "userCreatedId", "userAssignedId", "personId", "lastModifiedUser")`: per column
only numbers (`coverage`, `distinct`, `per_entity_quantiles`, `top1_share`, `top5_share`,
`top10_share`, `gini`). **The module must have no code path that releases an id**, and a test must
assert that no planted id from the stand-in appears anywhere in its output.

## Task 5: Vocabulary and readiness — `insight/vocabulary.py`, `insight/readiness.py`, `insight/texts.py`

`vocabulary.build`: titles trigrams; solutions tokens, bigrams, trigrams; and `by_category` (per
`categoryId` value above the floor: the top title tokens and top solution tokens, floored per
(category, token) cell, 30 each). Reuse `origin.titles`' cleaning and sweep; solutions get the same
`token` sweep including the first-name list. The planted `Stefan` must be withheld and counted.
`texts.py`: expose per-ticket near-duplicate cluster sizes (`cluster_sizes(tickets)`), deterministic
and independent of row order (sort documents with a stable tiebreak, as `_repetition` does).
`readiness.build`: `complete_triple` (title, description and solution all non-blank),
`templated` (in a near-duplicate cluster of at least `k`), `solution_present`,
`duplicate_solution_share` (exact solution texts shared by at least `k` tickets, counts only),
`usable` (not templated and with a non-blank solution), each with its share. Tests include a chain of
near-duplicates shuffled many ways.

## Task 6: Assembly — guard, report, CLI, window probe, rehearsal

`report.build` adds `formats`, `timeline`, `lifecycle`, `dimensions`, `concentration`, `vocabulary`,
`readiness` under their own top-level keys. `guard.py`: add the new static keys (run the assembled
report through `guard.unaccounted` and declare exactly what it lists as undeclared, nothing more),
a `COLUMN_KEYS` set built from each module's `COLUMNS` with a liveness test, and a LITERALS path
for every fixed bucket-label field. `test_every_declared_key_is_used` and `test_every_literal_path_is_used`
and `test_every_declared_section_is_emitted` keep passing: `SECTIONS` gains every new withheld block.
`__main__.py`: nothing about its safety behaviour changes; `REQUIRED_COLUMNS` stays. Update the
Window D verify probe in `infra/profiler/window.sh` to also print the new coverage numbers
(Baugruppe coverage and empty share, `fehlercode` coverage, templated share), and the rehearsal's
assertions (Baugruppe coverage is the planted value, not 0.25 hard-coded if the stand-in changed it;
planted ids, first names and part numbers handled as designed; the new sections present). Keep the
contract test green.

## Task 7: Adversarial review, verification, image, rehearsal, state

Controller: attack the guard and the new released fields; run the full suite in a pristine
worktree; rebuild the image; run `make window-d-rehearsal`; update the runbook (new report contents,
what to look for) and `docs/STATE.md`; commit.

## Done when

All tests and lint green; the rehearsal prints `0 failed` against a fresh build; the report on the
stand-in shows every new section with the planted values; the guard accepts it; and no committed file
contains a value from the real corpus.
