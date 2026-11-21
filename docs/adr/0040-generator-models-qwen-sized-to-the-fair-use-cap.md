# 0040. Local generation uses 32B Qwen models sized to the fair-use cap

Status: Accepted
Date: 2026-08-04 (the Qwen2.5 AWQ build was in use for fixtures by 2026-08-26; made the Window E default on 2026-10-21)

## Context

The planning session closed the generator question as Qwen3-32B in FP8 on one card: about 33 GB of
weights plus working memory leaves about 24 GB of KV cache under the 60 GB cap. A 70B model at INT4
was rejected on two legs: about 38 GB of weights would leave under 60k tokens of KV (at about
320 KiB per token) and 4-bit kernels are weakest at shallow batch depth, and the planned corpus
size made iteration speed look binding. The second leg lapsed once the real export proved to be
about four times smaller than the planned 65,000 rows (a 70B pass would then take only hours); the
rejection stands on KV headroom alone.

In practice the roles split. The fixture generator and dev3 default to `Qwen/Qwen2.5-32B-Instruct`
(bf16, about 65 GB, which breaches the cap, so a real run must pass the AWQ model explicitly), and
Window E's design made `Qwen/Qwen2.5-32B-Instruct-AWQ` its default. Qwen3-32B was planned as the
product's enrichment and synthesis model, and enrichment has not been built; the generators in this
repository only draft catalogs and fixtures. The sources record the move to Qwen2.5 but not why.

## Decision

Local generation in this repository (fixtures, dev3, catalog drafting) uses a 32B Qwen instruct
model served by vLLM on one card. For Window E, use the AWQ build with
`--gpu-memory-utilization 0.70` (about 56 GB of 80), a maximum model length of 32768 and a worker
pool for concurrent calls, with results collected in a deterministic order so the catalog does not
depend on the worker count. The model server is pinned by image digest and reads its weights from a
read-only mounted cache (ADR 0039); the fixture response cache is keyed by client identity and
prompt hash. The product's future enrichment and synthesis model is not decided by this ADR.

## Consequences

- Generation fits the shared cap, with little headroom: e5 adds about 2 GB on top of 56 GB, so
  about 58 of the 60 GB.
- 4-bit quantisation can lower draft quality; catalog drafts are reviewed by hand and checked
  (ADR 0033), which contains the risk but not its cost.
- The plan's model (Qwen3-32B FP8) and the code's model (Qwen2.5-32B) differ, and the Qwen3
  choices for the embedder and reranker in the same planning table were also replaced (ADR 0009,
  0019). Any move to Qwen3 should supersede this ADR with a measured comparison.
- The 70B option stays rejected for this hardware allocation, on KV headroom.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 2 (section 12.6 and its
  later amendment on the real row count)
- `docs/superpowers/specs/2026-10-21-window-e-design.md` ("Code changes"); commits 42103a9, a3481c9
- `fixtures/llm.py`, `catalog/defaults.py`, `dev3/__main__.py`; `docs/client-questions.md`
