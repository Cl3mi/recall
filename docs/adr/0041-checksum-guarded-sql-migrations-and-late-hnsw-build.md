# 0041. Schema changes are plain SQL migrations with checksums; the HNSW index is built by the loader

Status: Accepted
Date: 2026-08-04 (the runner); the late HNSW build dates from the M3 design (2026-10-11), with migration 0003 committed on 2026-11-05

## Context

The sources record the choice of a small checksum-guarded runner but not a comparison with migration
frameworks. The schema is small and the database is disposable in every environment that holds data
(dev container, rehearsal pod, Window C tmpfs). The vector index has a particular constraint: building HNSW after a
bulk load is faster than maintaining it during inserts, and `CREATE INDEX CONCURRENTLY` cannot run
inside the migration runner's transaction.

## Decision

`recall.db.migrate` applies `migrations/NNNN_*.sql` in filename order and records each version with
the SHA-256 of its file in `schema_migrations`. A migration edited after it was applied raises, so
names and contents are immutable once applied. Migration `0003` creates the tables and the GIN
index on the generated `tsvector`, but not the HNSW index: `index.build` drops it, truncates
`ticket` with cascade, bulk-loads, then creates `ticket_problem_vec_idx` on `problem_vec` with
cosine ops. `make db-up` starts the dev Postgres (`:5433`) and `make migrate` applies migrations;
the migrate target exports one DSN variable so a different instance cannot be migrated by mistake.

## Consequences

- No framework dependency, and migrations are readable SQL with comments explaining the German
  dictionary and the label split.
- The M3 spec and the original plan describe `ticket_raw`, `ticket_problem` and `ticket_identifier`
  tables and a `halfvec` column; migration 0003 has only `ticket` and `eval_label` and uses
  `vector(1024)` (ADR 0015).
- Fixing a mistake means a new migration: an applied file cannot be amended, not even a comment,
  because the checksum covers the whole file.
- `index.build` is a full rebuild, not incremental; there is no in-place update or delete path for
  tickets yet, which a serving system would need.
- The index is absent while a build runs, so queries during a rebuild fall back to a sequential
  scan; acceptable for a disposable evaluation database, not for a live service.

## References

- `src/recall/db/migrate.py`, `src/recall/db/migrations/`; commit 970220a
- `src/recall/index.py`; `Makefile` (`migrate`)
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 1
