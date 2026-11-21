# 0014. Relevance labels live in their own table, invisible to retrieval

Status: Accepted
Date: 2026-10-11

## Context

An evaluation is circular if the retriever can see whatever defines relevance. On real data the
label is a normalised `fehlercode`; on synthetic data it is the dev3 recipe id. Both could be
tempting retrieval features (an exact-code arm), and a stray join would inflate every metric
without any test failing.

## Decision

Labels are stored in `eval_label(ticket_id, problem_key, fehlercode)`, separate from `ticket`.
Retrieval SQL never names it, and `tests/integration/test_index_build.py` pins that
`retrieve.py` does not. `problem_key` is the supplied label or the normalised `fehlercode`
(upper-cased, whitespace removed, `None` when blank); a null key is neither a query nor relevant to
anything. Using the code as a retrieval arm is a separate, deferred decision (ADR 0007).

## Consequences

- The metric cannot be circular through retrieval code, by structure and by test.
- A future `fehlercode` arm or filter would make the label visible to retrieval, so the
  evaluation would need a different notion of relevance or the circularity returns (an inference
  from the design, not a recorded decision); the two have to be decided together.
- Two tables to load and keep in step; `eval_label` rows are deleted by cascade on truncate.
- On real data the label is a proxy for "same problem" (ADR 0021).

## References

- `src/recall/db/migrations/0003_index.sql`; `src/recall/index.py`
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 1
