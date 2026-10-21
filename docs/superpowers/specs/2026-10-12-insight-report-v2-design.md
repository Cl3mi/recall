# Insight report v2 — everything that helps decide the RAG strategy

**Status:** design approved 2026-10-12. Supersedes the section list of
`2026-10-11-insight-window-report-design.md` for stage 1; its safety model is unchanged.

## Why

The first real run (2026-10-12) worked except for one section and answered less than
it could. **Baugruppe came back empty** (coverage near zero against about a quarter of tickets expected) because
the real value is a **list of numeric id strings**, e.g. `['<id>', '<id>']`, sometimes empty, and the
extractor only accepted a plain string. The profile's value shapes (`##D##`, `##DD##`,
`##D##_#DD##`, `##`) said so, and the synthetic stand-in encoded the wrong assumption, so the
tests agreed with the bug. Every airlock cycle is expensive, so this run is made as informative as
possible: the operator asked for "everything that could help us see trends we could use for the
RAG system (context, ingestion)", including the formats of serial numbers and model ids.

## What the first run already established (do not re-derive)

Handover forms are a sizeable minority of tickets; about three quarters of tickets are singletons;
the cleaning step destroys every part number (the few tickets carrying one drop to zero); real `fehlercode` values look
like `1234-5`, not the `[A-Z]{1,3}\d{3,5}` the identifier regex knows; a sizeable share of tickets have no
model id and most have no `vehicleYear`; a first name slipped through the name sweep.

## Rules that do not change

Aggregates only; every released value floored at `k = 50` and swept per field; the guard is a closed
allowlist; the CLI writes nothing unless the guard accepts; serial prefixes stay off; **no id of a
person or organisation is ever released**. New in this version: a `shape` released field (closed
alphabet only), a first-name list in the free-text sweep, and a `partner` field for Baugruppe pairs.

## Decisions taken with the operator (2026-10-12)

| Decision | Choice |
|---|---|
| Scope | Fix Baugruppe **plus** the ten sections below |
| Dealers (`merchantId`) | **Concentration numbers only.** No dealer id is released. |
| End customers, creators, assignees, persons, last-modified user | Concentration only, never ids (employees and customers are personal data) |
| Serial / model / id formats | Shapes only (closed alphabet), floored |
| Delivery | Baked into the image (digest pins the code) |

## The sections

Every list is a list of entry dicts, never a dict keyed by a value. Dicts keyed by a **column name
from the published 38-column contract** are allowed; those names are structure, not content.

1. **Baugruppe, fixed.** A ticket's value is a list of ids. Per id: tickets carrying it. Plus:
   coverage (tickets with at least one id), share of tickets whose list is empty, ids-per-ticket
   quantiles, share with two or more ids, distinct count, id pairs above the floor (`value` +
   `partner`), by year, concentration, and the Baugruppe × model × year table **exploded per id**.
2. **Formats.** For `vehicleSerialNo`, `vehicleModelId`, `vehicleId`, `ticketNumber`,
   `vehicleSerialIndex`, `id`, and the customData fields `fehlercode`, `deliveryDate`,
   `warrantyStart`, `warrantyEnd`: coverage, distinct count, length quantiles, and the top shapes
   above the floor (`profiler`'s `shape_of`, at most 16 characters, closed alphabet). Plus the
   serial ↔ `vehicleId` relationship: serials with more than one vehicle id and the reverse.
3. **Volume and fill over time.** Tickets per year and per month; per year, the fill rate of
   description, solution, serial, model id, Baugruppe, `fehlercode`, `vehicleHours` and delivery date.
4. **Dimensions.** Value counts above the floor for `categoryId`, `statusId`, `priorityId`,
   `subStatusString`, `vehicleStatus`, `showInProteam`, `contractTransaction`, by year; and per
   category: ticket count, solution fill, description fill, problem-text length median and p95.
5. **Where tickets come from.** For `merchantId`, `endCustomerId`, `userCreatedId`,
   `userAssignedId`, `personId`, `lastModifiedUser`: coverage, distinct, tickets-per-entity
   quantiles, top-1/5/10 share, Gini. **No id.**
6. **Vehicle lifecycle.** `vehicleHours` quantiles and fixed buckets; days from `deliveryDate` to
   the ticket (fixed buckets); warranty status at ticket time (in, out, unknown). Bucket labels are
   fixed literals; each count is floored.
7. **Recurrence.** Per vehicle, days between consecutive tickets (quantiles) and the share of
   tickets that repeat within 30, 90 and 365 days of the vehicle's previous one.
8. **`fehlercode` field.** Coverage, per-year coverage, and the top single code values above the floor
   (`value` field, code sweep, so a long identifier-like value is withheld and counted).
9. **Vocabulary.** Titles: tokens, bigrams, trigrams. Solutions: tokens, bigrams, trigrams (what
   kinds of solution are given). Per category: top title and solution tokens (floored per cell).
   Everything passes the token sweep, which now includes a first-name list.
10. **RAG readiness.** Counts only: tickets with title, description and solution all present; tickets
    in near-duplicate clusters of at least `k` (templated, e.g. handover forms); tickets that are
    non-templated with a non-blank solution; exact-duplicate solution texts shared by at least `k`
    tickets; and the usable-ticket count after excluding templated and empty-solution tickets.

Existing sections that stay: vehicles/serials (behaviour only), models, vehicle years, title tokens
and bigrams, text lengths, identifier density raw and after cleaning, repetition, suppression ledger.

## New safety mechanics

- **`shape` released field.** `release.flagged("shape", v)` is true unless `v` fullmatches the closed
  alphabet and is at most 16 characters. Shapes are structurally incapable of carrying a value, so
  the entity sweep does not apply, but the floor does. Shapes are only ever taken from identifier-like
  columns, never from prose.
- **First-name list.** `insight/names.py` holds common German first names that are unlikely to be
  technical words. `_token_flagged` withholds a token that is one. Regression test: of the real
  title tokens already released on 2026-10-12, exactly one (a first name) is flagged.
- **`partner` released field** for the second id of a Baugruppe pair, with the code sweep.
- **Column-name keys.** The guard allows dict keys that are column names the report actually uses,
  drawn from one constant per section module, with a liveness test.
- **Fixed bucket labels** are literals matched in full by path.

## Stand-in

The synthetic stand-in must mirror the REAL shapes, taken from the profile: Baugruppe as lists of
numeric id strings (single, double and empty), `fehlercode` as `1234-5`-style codes, dates as
`DD.MM.YYYY`, several serial formats, numeric model ids with many missing, a cleaning-sensitive part
number. A first version of this design failed on exactly this, so building the stand-in from the
profile's value shapes is the first task, not an afterthought.

## Out of scope

Stage 2 (embeddings, clusters, labels), the HTML view, and any change to `profiler.entities`,
`profiler.safety`, or `profiler.blessing` (safety controls; the operator's call).

## What this cannot answer

Meaning: ids are opaque, so which Baugruppe or model an id is needs the client's lookup tables.
Whether a cluster of tickets is "the same problem" needs stage 2.
