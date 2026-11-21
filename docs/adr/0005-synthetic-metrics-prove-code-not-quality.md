# 0005. Synthetic metrics prove the code is correct, not that retrieval is good

Status: Accepted
Date: 2026-08-04

## Context

Retrieval is built before the first real-data measurement, on invented corpora (the M2 fixture and
the dev3 stand-in). Invented text is far more regular than real tickets: in the earlier
fake-writer run, tickets of one recipe shared words literally, which made the lexical arm look
better than it can be on real wording. The project has repeatedly been bitten by checks that pass
for the wrong reason: a stub-filled cache that answered for the model, gate calibrations done on the
hashing stub (finding 18), tests that passed vacuously, and a rehearsal run against a stale image.

## Decision

No retrieval-quality decision is made on synthetic metrics. Synthetic evaluation exists to prove
the code and the metric are right and to choose between code paths whose differences are structural.
The principle is invariant 5 of the project brief (present from the initial commit); the M3 spec
(2026-10-11) and plan amendment 2 (2026-11-05) apply it to the stand-in. A related rule (the
brief's divergence rule) forbids tuning the generator or shrinking a band budget to make synthetic
numbers look right: it would inflate synthetic recall.
Only the real-data evaluation (Window C) can establish quality. Reports make the distinction
visible: the synthetic report carries a fixed `CAVEAT`, embedder and reranker identities start
with `hashing:` or `overlap:` when a stand-in was used, and `eval_real.json` carries
`embedder_is_a_model` and `coded_faults_only`.

## Consequences

- M3's and M4's numbers are recorded but not treated as evidence of quality. In particular, M4's
  null result for the reranker does not say a reranker cannot help on real tickets.
- Defaults chosen on stand-in numbers (the `query:` prefix, the reranker staying opt-in) are
  explicitly revertible when real data disagrees.
- Judging boosts and a `fehlercode` arm waits for Window C; enrichment itself is buildable on the
  stand-in, but its value is not provable there.
- Stakeholders get fewer headline numbers early, which is the price of not overclaiming.

## References

- `PROJECT_BRIEF.md` invariant 5; `src/recall/eval.py` (`CAVEAT`)
- `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` (amendment 2, Results)
- `docs/STATE.md` findings 12 and 18 (calibrations that were stub-specific)
