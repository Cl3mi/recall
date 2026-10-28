# Dev3 fixture: three synthetic vehicles from a released problem catalog

**Status:** approved by the operator 2026-10-21. Identity columns stay empty (ruling below).

## Why

The current fixture (`local/fixtures/export.csv`, 1,500 rows) matches the real corpus's *statistics*
(cluster bands, fill rates, shapes) but its title, description and solution text is generic LLM
output and its `vehicleSerialNo` values do not form a per-vehicle problem history. The RAG work
(M3: retrieval, tuning, eval) needs the opposite emphasis: believable problems and fixes, and
vehicles whose ticket histories exercise same-serial retrieval, near-duplicates and chronology.

## Constraint that shapes everything

Real text is under NDA and may only be handled in a manual, AI-free airlock window on the box
(`docs/airlock-runbook.md`). Anything an LLM writes after reading real tickets is real-derived.
So no real-derived free text may reach the generator that produces the dataset, and no per-ticket
real text leaves the box.

## Decisions (operator, 2026-10-21)

| Decision | Choice |
|---|---|
| Release level out of the window | **Problem catalog only** (approach B): abstract, hand-reviewed recipes. No per-ticket paraphrases, no verbatim examples. |
| Vehicle design | **Different problem profiles** per vehicle (below). |
| Vehicles | **3 invented serials** of the real shape (letter + 12 digits). No real serial is used. Real vehicles with 150-200 tickets are unlikely to exist, so each vehicle is a composite. |
| Size | About 150-200 tickets per vehicle, about 450-600 in total. |

Defaults taken unless the operator objects: floor k = 50 tickets, at least 5 distinct vehicles and
5 distinct dealers per recipe; titles are abstracted templates; output in `local/fixtures/dev3/`.

## Stage 1 - catalog extraction (new Window E, on the box, sealed)

- **Container.** The sealed image (`--network=none`) plus a local LLM server (vLLM, Qwen2.5-32B as
  for the fixture generator). The image grows; `ship` takes longer than the current hour.
  Claims a GPU through the fair-use guard like Window B.
- **Pipeline, reusing existing code.** `cleaning` and boilerplate stripping (`insight/quality.py`
  phrase list) -> drop the handover-slip category (a delivery date is the proxy) and noise -> e5
  embeddings -> **semantic clustering (k-means, fixed K)**, not `groups()`: `groups()` is MinHash
  near-duplicate grouping, and `quality.grades` already treats a near-duplicate problem cluster of
  k or more as templated noise (amended 2026-10-21 while planning) -> per cluster, the LLM sees a
  sample of member tickets and drafts one recipe, and refuses a cluster that is not one problem.
- **Release floors.** A cluster becomes a recipe only if it has at least k tickets spread over at
  least 5 vehicles and 5 dealers. Counted per ticket, not per occurrence (the lesson of v2).
- **Scrub.** Names, serials, part numbers, phone numbers, dates, plate-like strings and anything
  `profiler.entities` or the `insight` name lists catch are removed from recipe fields.
- **Review and guard.** Output goes to the sealed root through `recall.sealed.sealed_path`
  (`catalog.draft.json`). The operator reads and edits it on the box, deleting anything too
  specific. A closed-allowlist guard (new `catalog/guard.py`, same shape as `insight.guard`)
  re-checks field names, lengths, types and a sweep; only a passing file is released to
  `local/released/catalog.json` (numbers-and-templates only, see below).
- **Window mechanics.** `window.sh --window e`, one-file allowlist `catalog.json`, shred list for
  inputs and drafts, a rehearsal (`make window-e-rehearsal`) on a stand-in corpus, and a runbook
  section written for reading with no AI. Follows Window D.

## The catalog recipe (the only real-derived artifact)

| Field | Content |
|---|---|
| `recipe_id`, `support` | opaque id; ticket count (>= k) |
| `component`, `symptom`, `cause` | short generic phrases (length-capped) |
| `fix_steps` | 2-6 paraphrased generic steps, no part numbers or names |
| `title_templates` | 3-5 abstract templates with slots such as `<component>`, `<symptom>` |
| `description_style` | fill probability, length quantiles (whole numbers), tone tags |
| `solution_style` | length quantiles; workflow boilerplate classes it tends to use |
| `fehlercode_shape` | a shape such as `DDDD-D`, never a value |
| `recurrence_gap_days` | whole-number quantiles, no `p1`/`max` |
| `co_occurs_with` | other `recipe_id`s with a lift above a floor |

No verbatim sentence from a ticket may appear. The operator's hand review is the control for that;
the guard enforces length caps and the sweep but is not a proof.

## Stage 2 - generating the three vehicles (no real data in reach)

New package `dev3/` beside `fixtures/`, reusing `fixtures/render.py` (38-column renderer with the
double-encoded `customData`), `fixtures/llm.py` (cached client, GPU-free fake) and `verify`.

- **Vehicle profiles.**
  - V1, chronic: a few recipes recurring many times with short gaps (same-serial history,
    near-duplicates).
  - V2, broad: many recipes, mostly one-off (precision, confusable problems).
  - V3, evolving: one problem that changes over time with follow-up tickets (chronology).
- **Planner.** Lays tickets on a timeline from the released gap quantiles and co-occurrence;
  seeded, pure and deterministic. Each ticket gets a `recipe_id`, a writer persona (terse dealer,
  verbose dealer, title-only, template-heavy) and a fill pattern from the catalog's style fields.
- **Writer.** The LLM receives one recipe and one persona and writes title, description and
  solution. It never sees real text. Other columns come from the existing renderer; the three
  serials are invented.
- **Ground truth.** `labels.jsonl` maps each ticket to `recipe_id`, vehicle and persona, so
  retrieval can be scored automatically: relevant = same recipe (same or other vehicle).
- **Output.** `local/fixtures/dev3/tickets.csv` and `labels.jsonl`. The CSV is gitignored like
  other fixtures; the code and a tiny stand-in catalog are tracked.

## Column plan (the 38 columns of `docs/export.header.txt`)

Note the column is `solutions` (plural), not `solution`.

| Source | Columns |
|---|---|
| **LLM writer, from a recipe + persona** (the focus) | `title`, `description`, `solutions` |
| **Planner, invented, per vehicle** | `vehicleSerialNo` (3 invented serials), `vehicleId` (one per invented vehicle; the real data has ids spanning several serials, so V2 or V3 may deliberately share one to test it), `vehicleModelId`, `vehicleYear`, `vehicleHours`, `vehicleStatus`, `timestampCreated`, `deadline`, `categoryId` (never the handover category), `statusId`, `priorityId`, `subStatusString`, `subStatusChanged`, `ticketNumber` |
| **Planner, inside `customData`** | `fehlercode` in the shape the recipe declares, in the double-encoded EAV form. No Baugruppe: its ids are opaque and the catalog does not release them (amended 2026-10-21) |
| **Derived by the existing renderer** | `id`, `vehicleSerialIndex`, `showInProteam`, `contractTransaction`, `contractItems`, `userCreatedId`, `userAssignedId`, `lastModifiedUser` (opaque ids only) |
| **Identity columns, never filled from real data** | `personId`, `merchantName`, `merchantId`, `merchantNumber`, `merchantPhoneNumber`, `endCustomerName`, `endCustomerId`, `endCustomerNumber`, `endCustomerPhoneNumber`, `contactEmail`, `contactPhone`, `contactPhoneTrimmed`: **left empty** (operator ruling 2026-10-21), as in the current fixture. No value is ever taken from a real row. |

Free text written by the LLM must not contain emails, phone numbers or names either; the output
sweep covers `title`, `description`, `solutions` and `customData`.

## Verification

- Existing `fixtures.verify` structural checks on the output.
- New: an entity sweep over the output text, identity-column and structure checks, and per-vehicle
  profile assertions (V1's recurrence, V2's recipe count, V3's chain). The copy check against real
  tickets (a recipe string sharing a 5-word run with a member ticket) runs in Stage 1, where the
  tickets are; copying from the released catalog is not a leak (amended 2026-10-21).
- The leakage gate may be run once in a window against the real corpus if extra assurance is
  wanted; it is not a dependency, since no real text reaches the generator.

## Testing

All code is built and tested against a synthetic stand-in catalog and stand-in corpus; only
Stage 1's real run needs a window. Tests first for the guard and the scrub (as for Plan 2).
Mutation-style tests: a recipe below k, a recipe with a name, a too-long field, an unknown field
must each be refused.

## Leak gate (added 2026-10-21, operator requirement: no NDA leak before a remote AI may read it)

A catalog is releasable only through an automated gate; the real rows are read only inside the
window, and the AI-readable artifacts are the catalog plus a leak report (check names, counts,
opaque recipe ids; never a value).

- **`build`** drops a recipe whose words fall below the **rare-word floor** (every word must occur in
  at least k tickets, at least `min_dealers` distinct dealers and at least `min_vehicles` distinct
  vehicles across the WHOLE corpus - operator ruling), contain an **identity token** (dealer,
  customer, creator, contact, serial, ticket and number columns; strict, so a generic word shared
  with a dealer name also drops the recipe), copy a 5-word run from the cluster's tickets, or fail
  the draft checks (angle tokens, characters outside a closed class, client errors swallowed).
  The LLM sample is hash-ordered and capped at 2 tickets per dealer, so the wording cannot come
  from one dealer.
- **`leakcheck`** re-verifies the finished draft independently against the whole corpus
  (vocabulary floor, identity denylist, 5-word runs against every ticket, the guard) and writes
  `leak_report.json` containing the SHA-256 of the draft's canonical JSON.
- **`release`** requires `--report` and refuses unless `catalog.release_gate.release_problems` is
  empty: a passing report, every check present and passed, the digest matching the exact draft
  (an edit after the check is `STALE_REPORT`), floors at or above the hard minimums (k >= 50,
  5 vehicles, 5 dealers; `--allow-weak-floor` can never release), and the guard clean.
- **Automatic tests** (`tests/leak/`, `make leak-test`): planted leaks of every class on a synthetic
  corpus, mutation tests that switch each check off and must then fail, hostile LLM clients,
  the release gate's refusals, and a pre-read test that fails, naming only the file, when a catalog
  sits in the released directory without a valid sibling report named `<stem>.leak_report.json`.
- **Limits.** The tests prove the checks catch the planted classes, not that no unknown leak
  exists; the operator's hand review of the draft remains the last control. A deny-list of names
  cannot be complete; the rare-word floor is the generic protection.

## Findings while planning (2026-10-21)

- The existing fixture never fills `vehicleSerialNo` (`fixtures/render.py::row`), so it cannot test
  same-serial history; `dev3/rows.py` fills the vehicle columns.
- The write lint's `SCOPE_PREFIXES` (`tools/guard/recall_guard/lint.py`) does not cover `catalog/`,
  which sees real rows in the window. Operator to add it; until then `catalog/` routes every output
  through `recall.sealed.sealed_path` by hand.

## Out of scope

Per-ticket paraphrase of real tickets; any release of real serials, names, part numbers or
verbatim text; changing the existing 1,500-row fixture or the leakage gate; the RAG retrieval
code itself (M3).

## Residual risks, accepted and written down

- A recipe phrase may still be recognisable to the client even if it is not verbatim; the
  mitigation is the k floor, the abstraction level and the operator's hand review.
- Catalog quality depends on the LLM's clustering summaries; weak recipes show up as poor
  retrieval scores, not as a leak.
- The sealed image gets larger; a rehearsal and ship cost an extra hour.

## Open items for the operator

1. Confirm k = 50 and the 5-vehicle / 5-dealer floors, or name other values.
2. Ruling that a *local* LLM reading real tickets inside the sealed, `--network=none` window
   counts as AI-free for the NDA protocol (precedent: Plan 2's stage 2 already assumes it).
3. Whether to spend a leakage-gate window on the finished fixture.
