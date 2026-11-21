# 0042. M3 is built and scored on the dev3 stand-in, with the recipe id as ground truth

Status: Accepted
Date: 2026-11-05

## Context

The retrieval work (M3) needed a corpus and a definition of relevance before any real-data window
could run. The 1,500-row M2 fixture matches the real corpus's statistics but its text is generic and
its serials do not form per-vehicle histories (ADR 0029). The real catalog run yielded too few
recipes for dev3's planner (ADR 0031), so on 2026-11-05 the options were to ship the latest catalog
image again, split mixed clusters, draft recipes from domain knowledge, or build M3 on an invented
stand-in meanwhile. The original M3 spec had derived synthetic groups from the planner.

## Decision

Build M3 on the dev3 stand-in, not on the M2 fixture. Synthetic ground truth is the dev3 label file,
which maps every ticket to a `recipe_id`, vehicle and persona: `eval_label.problem_key` is the
recipe id, and a ticket's relevant set is the other tickets of the same recipe, on the same or
another vehicle. An optional confusable stand-in catalog adds four near-twin recipes to exercise
separation. Tests build their corpora in memory (`tests/catalog_corpus.py`) and the eval CLI takes
`--corpus` and `--labels` as arguments, so no test names or reads a data file.

## Consequences

- M3 and M4 could proceed while the real catalog yield was unresolved, and the twin failure that
  motivated the reranker became visible (ADR 0019).
- The numbers prove the code and the metric, not retrieval quality on real tickets (ADR 0005); the
  support floor that limits the catalog also makes stand-in scores overstate real recall.
- The labels come from the same generator that wrote the text, so a retriever can do well by
  recovering the generator's shared wording; the earlier fake-writer run showed that effect on the
  lexical arm.
- The M3 plan's Task 8 (real data, Window C) stayed deferred and needed its own plan (ADR 0021).

## References

- `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` (amendments 1, 2 and 4; status table)
- `docs/handoff-window-e-2026-10-28.md` (update 2026-11-05)
- `src/recall/eval.py` (`load_labels`), `dev3/`, `tests/catalog_corpus.py`
