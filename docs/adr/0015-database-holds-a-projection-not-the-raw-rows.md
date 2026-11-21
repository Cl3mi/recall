# 0015. The database holds a retrieval projection, not the raw rows or identity columns

Status: Accepted
Date: 2026-11-05

## Context

The brief says the raw export is immutable and every derived artifact reproducible from it. The M3
spec therefore planned a `ticket_raw` table holding all 38 columns as JSON beside the projection.
The export also carries dealer, customer and contact identity columns that retrieval never reads.
In Window C the database is disposable and lives on tmpfs (ADR 0022), and on the workstation it is
fed synthetic data only.

## Decision

Migration `0003_index.sql` creates only the projection (`ticket`) and the labels (`eval_label`).
The projection carries the cleaned problem and solution text, vectors, a generated `tsvector`, a
few filter fields (`created`, `category_id`, `vehicle_model_id`, casefolded `vehicle_serial`) and
`source_sha256` of the input rows. `ticket_raw` was not created; identity columns and raw rows
never enter the database (the migration says the raw row is "deliberately NOT copied" because
nothing in M3 reads it; commit 9cbc6d6, 2026-11-05, "projection without identity columns").
The immutable raw source remains the export file itself.

## Consequences

- A leak out of the database cannot expose identity columns that were never loaded, and the
  database can be rebuilt from the export at any time.
- Reproducibility is by the input hash and the code commit, not by an in-database copy.
- This deviates from the approved M3 spec (2026-10-11), which planned `ticket_raw`; the spec was
  not amended, and the M3 plan's Task 1 line still lists `ticket_raw`, so that line is stale. This
  ADR is the record of the difference. `vehicle_serial` is a second deviation: it is in 9cbc6d6 but
  not in the spec's projection.
- Features that need an unprojected column (dealer-level analysis, display of contact fields)
  require a migration and an explicit privacy decision.
- Vehicle serial is a quasi-identifier and is stored; it is needed for the same-serial history
  signal, which is why that signal is a deliberate, not accidental, use.

## References

- `src/recall/db/migrations/0003_index.sql` (header comment); `src/recall/index.py`
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 1 (original plan)
- `PROJECT_BRIEF.md` invariant 4
