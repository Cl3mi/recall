# 0003. Nothing derived from the real corpus is retained between windows

Status: Accepted
Date: 2026-08-04

## Context

An early plan kept real-corpus embeddings and 8-token shingle hashes on the box so that the
leakage gate (Window B) could skip a cycle on later runs. Two risks were identified. Embedding
inversion attacks can reconstruct substantial parts of short texts from their vectors, and they
work better when the embedding model is public, which e5 is. A set of shingle hashes is a
membership oracle for the text it came from. Retained vectors or hashes are therefore the text in
thin disguise, and they would sit on a shared box between windows.

## Decision

The earlier draft was reversed. No row-level or reconstructable derivative (embeddings, hash sets,
indexes) survives a window; only guarded aggregates and the reviewed catalog leave. Window B re-imports the real export each time and computes the shingle
intersection and nearest-neighbour check on the box, emitting only counts and verdicts. Window C
builds a disposable database per run and discards it (ADR 0022). Each window's shred list is part
of its contract (ADR 0027).

## Consequences

- One extra manual cycle per gate run, accepted as the cheaper trade.
- Real embeddings are recomputed in every window that needs them; the GPU decision (ADR 0037) was
  partly driven by that recurring cost (roughly 1.1 to 2.6 h per window on CPU, depending on box load).
- Any future "persistent index of the real corpus" is a new decision that must supersede this one,
  not a convenience feature.
- Operators must treat hand-written real-data evaluation queries as real data too: they live and
  die inside the window.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` ("Reversed decision")
- `docs/STATE.md` findings 16 and 17 (shred list, thread cost)
- ADR 0002, 0022
