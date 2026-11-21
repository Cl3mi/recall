# 0013. One cleaning pipeline normalises indexed text, queries and profiler input

Status: Accepted
Date: 2026-08-04

## Context

The brief expected tickets with heavy HTML, quoted reply chains, signatures and diagnostic dumps.
Window A measured those as near absent (about 1% or less for HTML, quoted chains, dumps and
all-caps), and the pipeline as largely idle on this corpus, so its real jobs are symmetry between
index and query and PII redaction. The brief calls symmetry between index-time and query-time
normalisation "the core trick": a messy new ticket can only match a messy old one if both are
projected into the same space. The profiler also needs to measure cleaned text to size the
problem.

## Decision

`recall.clean.pipeline.clean()` is the only normaliser. In order: strip HTML, strip quoted reply
chains, strip signatures, redact PII, collapse whitespace. It returns the text and a `CleanReport`
of booleans and lengths. `index.build`, `retrieve.search` (via `clean_query`), the reranker input
and the profiler all call it.

## Consequences

- Index and query text are symmetric by construction; changing the pipeline requires a re-index.
- The pipeline is shared with the sealed windows, so any change is also a change to what Windows A
  and D measure.
- Known cost: the phone pattern redacts part numbers such as `1234.56789` to `[TEL]`, which
  destroyed identifier counts on the first real runs. It is measured rather than fixed: the insight
  report publishes identifier density raw and after cleaning, so the loss shows up as a number
  (`tickets` against `tickets_after_cleaning`). The profiler's safety modules are the operator's to
  change.
- Boilerplate in solutions (callback requests, ticket-closing notices, warranty notes) is not
  stripped by `clean`; the insight quality grade strips workflow notes only to score tickets
  (ADR 0035), not for embedding. The finding that boilerplate should be stripped before embedding
  is open.

## References

- `PROJECT_BRIEF.md` section 5; `src/recall/clean/`
- `docs/STATE.md` (Report v2 findings: part numbers lost, solution boilerplate)
