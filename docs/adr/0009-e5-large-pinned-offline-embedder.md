# 0009. One embedder, multilingual-e5-large, pinned by revision and loaded offline

Status: Accepted
Date: 2026-08-27

## Context

The 2026-08-04 planning session picked a quality-first stack: Qwen3-Embedding-8B for retrieval and
BGE-M3 as the gate's detector, deliberately a different model from the one under test. It also
noted that pgvector indexes `vector` only up to 2000 dimensions, so the 8B model's native 4096
cannot be HNSW-indexed without truncation. On 2026-08-27, when the Window B gate plan was written,
the operator chose `intfloat/multilingual-e5-large` instead and asked that the gate and M3's index
share it, so the gate's cosine bound applies to the vectors the index actually stores. The sources
record the choice and its sharing rationale, not a bake-off.

## Decision

Use `intfloat/multilingual-e5-large` (1024 dimensions) as the single embedder for the leakage gate,
the pgvector index and queries. Pin it by revision (`3d7cfbda...`), load with
`local_files_only=True`, pool with a masked mean (CLS pooling degrades this family), truncate at
512 tokens identically on every corpus, and use `passage:` for documents. The device (CPU or CUDA)
is not part of the identity; a test pins that vectors agree across devices.

## Consequences

- The gate measures the vectors M3 stores. Its p95 calibration was first done on the hashing stub
  and was re-measured with e5 (finding 18); it survived, but with a thinner margin (+0.032 against
  +0.068) and a higher twin fraction (3.5% against 2.7%).
- 1024 dimensions fit an HNSW `vector(1024)` column without truncation.
- The model is public, which is why ADR 0003 forbids retaining real embeddings.
- The detector is no longer independent of the model under test, a property the original design
  wanted; the gate's neighbour check measures the model it ships.
- e5 truncates at 512 tokens, so very long tickets lose their tail on both sides equally.
- A stronger embedder (the Qwen3 family, BGE-M3) stays an open upgrade; changing it re-embeds the
  corpus and re-opens the gate calibration.

## References

- `docs/superpowers/plans/2026-08-27-window-b-leakage-gate.md` ("Decisions already made")
- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 2 (original stack)
- `profiler/gate/embedder.py`; commits 830f9b6, 79f9f94, 7ecdc38
