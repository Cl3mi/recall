# 0012. The lexical arm queries with an OR of the query's words

Status: Accepted
Date: 2026-10-11

## Context

`plainto_tsquery` ANDs every term. A technician may paste a whole ticket with dozens of words, so
an AND query matches almost nothing and the lexical arm goes silently empty while the system
appears to work. The query text is also user input headed for a `tsquery`, where operators are
syntax.

## Decision

Clean the query like indexed text first, then build the lexical query as `a | b | c` over the
distinct lowercase words of the cleaned query,
capped at 64 terms, and run it through `to_tsquery('de_tech', ...)`. Only letters, digits,
umlauts, `ß` and underscore survive the tokeniser, so nothing in the text can act as a tsquery
operator. Candidates are ranked by `ts_rank_cd`.

## Consequences

- Long pasted queries still return candidates; a unit test pins this.
- OR matching admits many weak candidates, so ranking quality rests on `ts_rank_cd` and on fusion
  with the dense arm; there is no IDF weighting (ADR 0007).
- Truncating at 64 distinct words drops the tail of very long queries.
- Query text cannot inject tsquery syntax.
- It does not use the `de_tech` cleaning of identifiers (hyphenated codes such as `1234-5` split at
  the tokeniser); exact-code handling is the deferred identifier arm.

## References

- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 2
- `src/recall/retrieve.py` (`or_query`, `MAX_TERMS`)
