# M3 implementation plan: hybrid retrieval and eval, built on the dev3 stand-in

**Spec:** `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` (approved, unchanged
except the amendments below). **Why now:** the real catalog has 3 recipes (run 3, 2026-11-03), below
the 4 that `dev3` needs, so no real-derived fixture exists. Nothing in M3's plumbing needs one.

## Amendments to the spec

1. **Synthetic ground truth is the dev3 label, not a re-derived planner group.** The spec was
   written before dev3. `dev3` writes a label file mapping every ticket to `recipe_id`, vehicle and
   persona. `eval_label.problem_key` = `recipe_id`; relevant = same recipe, same or other vehicle.
   That removes the spec's "verify ticket ids follow plan order" step for this corpus.
2. **Build against `local/fixtures/dev3/` (8 invented recipes) now.** It is invented text, so it
   proves the code and the metrics, not retrieval quality on real tickets (the spec's own caveat for
   synthetic numbers). The old 1,500-row fixture stays available as a second, statistics-matched corpus.
3. **Same-serial history is a retrieval signal** (STATE.md: over a third of real tickets have an
   earlier ticket on the same serial). dev3's V1 vehicle exists to exercise it. M3 only *reports*
   how often a same-serial earlier ticket is relevant; using it as an arm is M4.
4. **Tests must not name or read data files** (guard). Tests build corpora in memory with
   `tests/catalog_corpus.py` or `dev3` helpers; the CLI takes `--csv` and `--labels` paths as arguments.

## Tasks (each: failing test first, then code, then commit)

1. **Migration `0003_index.sql`**: `ticket_raw`, `ticket` (vectors, generated `problem_tsv` with
   `de_tech`), `eval_label`. Test: migrate on a fresh db, columns and index exist, `eval_label` is
   not referenced by any retrieval SQL (grep-style test over the module's SQL strings).
2. **`recall.retrieve.rrf`** (pure): ties, one-arm-only, empty arm, per-arm ranks carried.
3. **`recall.retrieve.build_query`**: OR of lexemes; a 60-word query still produces candidates.
4. **`recall.index.build`**: load, clean (`recall.clean.pipeline`), embed (`E5Embedder`, injectable
   so unit tests use `HashingEmbedder`), insert, then HNSW after the bulk load. Labels loaded into
   `eval_label` only.
5. **`recall.retrieve.search`**: dense and lexical arms, symmetric cleaning, self-exclusion,
   cutoff filter. `needs_pg` integration tests on a small corpus; both arms return candidates.
6. **`recall.eval.score`**: recall@10 with `min(10, |relevant|)`, MRR, nDCG@10, macro-average per
   problem group, label coverage. Hand-computed expected values.
7. **`recall.eval` synthetic wrapper**: dense / lexical / fused and both e5 prefixes, report with
   corpus identity and the "code correctness, not quality" caveat. Key-set pin test.
8. **Real wrapper and Window C** stay as in the spec and wait: they need a window, and they should
   not be spent before the synthetic numbers show the harness is sound.

## What this plan deliberately does not do

- No change to `catalog/` or `dev3/`, no lowering of `MIN_RECIPES` (operator decision).
- No metadata boosts, reranker or `fehlercode` arm (M4).
- No quality claims from stand-in numbers.

## Environment

`make db-up` starts Postgres on port 5433 (docker compose); `PG_DSN` is exported by the Makefile.
Run Postgres tests with that, other tests under the clean env from the handoff doc.
