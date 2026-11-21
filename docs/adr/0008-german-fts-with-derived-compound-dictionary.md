# 0008. German full text uses `de_tech` with a compound dictionary derived at image build

Status: Accepted
Date: 2026-08-04

## Context

Stock `to_tsvector('german')` stems but does not split compounds, so `Hydraulikpumpe` does not
match `Pumpe defekt`; in a German technical corpus compounds are most of the vocabulary. The brief
proposed a hunspell dictionary on top of `german_stem`. When this was tried, the stock `de_de`
dictionary shipped by `hunspell-de-de` produced no compound splits at all: igerman98 grants the
compound flags through hunspell affix-flag continuation, which PostgreSQL's `spell.c` does not
implement, so it saw zero `COMPOUNDBEGIN` entries among 21,214 compound-capable ones and every
compound fell through to the stemmer.

## Decision

Build a Postgres-consumable dictionary at image build: `infra/postgres/derive-compound-dict.pl`
resolves the flag continuation statically into `de_compound.dict` and `de_compound.affix`. The
`de_tech` configuration maps word tokens through `de_synonyms`, then `german_hunspell`
(on `de_compound`), then `german_stem`. A second configuration, `de_tech_ua`, runs `unaccent`
first for comparison. The stock `de_de` files stay in the image for comparison only.

## Consequences

- Compounds are actually split, which is the point of the lexical arm. Do not "simplify" back to
  `de_de`; the migration says so.
- The Postgres image is custom and its dictionary generation is a build step that must be kept
  working across `hunspell-de-de` updates.
- `de_synonyms` exists but its synonym file is empty. The brief planned to mine dealer shorthand
  (`Getr.` to `Getriebe`) from unrecognised tokens; that is not done. The migration comment
  attributes it to M4, which became the reranker (ADR 0019), so the plan is now unscheduled.
- On the plan's seven-case acceptance test the stock `de_de` failed four cases, `de_tech_ua` two
  (the umlaut compounds) and `de_tech` passed all seven. A fugen-s gap remains, pinned by a strict
  `xfail` in `tests/integration/test_german_fts.py`: a query `Wartung` misses `Wartungsintervall`.
  The image build now fails instead of silently deriving a weaker dictionary (commit 789319f).
- Mined synonyms would be real-corpus vocabulary, so a populated synonym file can never be
  committed; it would live in quarantine.
- Compound splitting quality on real tickets has not been verified with `ts_debug` on real text.

## References

- `src/recall/db/migrations/0002_german_config.sql`, `infra/postgres/`
- Commits 1af97ae (derive dictionary), 4966286 (`de_tech` with compound splitting)
- `PROJECT_BRIEF.md` section 7; `tests/integration/test_german_fts.py`
