# 0004. All inference is local and the corpus stays German end to end

Status: Accepted
Date: 2026-08-04

## Context

The brief sets two non-negotiable invariants: no API calls to hosted model providers from the
application at runtime, and no translation of the German corpus at any stage. The data is under
NDA (ADR 0002), so ticket text must not reach a third-party service, and technical German
(compounds, dealer shorthand, error-code formats) is exactly what a translation step would damage.
The brief also assumed a single 80 GB GPU; the real box is shared (ADR 0038).

## Decision

Embedding, reranking, drafting and any later generation run on locally hosted open-weight models,
loaded offline from pinned revisions. Text is embedded, indexed, searched and prompted in German
without translation. Model licences must permit commercial use; `jina-embeddings-v3` and
`jina-reranker-v2` are excluded as CC-BY-NC. The brief's rule that a generator must never invent
identifiers (every code or part number verified as a substring of its source) belongs to a
generation layer that does not exist yet.

## Consequences

- No hosted-API dependency, and the sealed windows can run with no network.
- Model choice is bounded by what runs on a shared card under a memory cap, and by the licence
  filter (ADR 0009, 0019, 0040).
- Quality depends on multilingual models rather than German-specialised ones, and on the German
  full-text work in ADR 0008.
- Claude Code is a development tool only and sees synthetic or guarded data, never real rows.

## References

- `PROJECT_BRIEF.md` section 3 (invariants 3 and 7)
- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 2 (licence table)
