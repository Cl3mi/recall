# M4 (first step) — a reranker over the fused candidates

**Status:** design approved section by section with the operator, 2026-11-13.
**Builds on:** `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` (retrieval) and
the M3 plan's Task 13 decision (2026-11-12): the small side of each twin pair scores
0.60 / 0.33 / 0.45 recall@10 (full / title / head) under `fused_query`, against 0.95+ for groups
without a twin, while MRR on full queries stays high. That is the shape a reranker addresses, if
the right tickets are in the candidate list.
**Scope:** measure the candidate ceiling, then a two-model reranker bake-off on the same
`dev3-confusable` fixture, then one decision. Same-serial boost, the `fehlercode` arm and Task 8
(real data, Window C) are out (M3 plan, Task 13).

## Decisions taken during design

| Decision | Choice | Why |
|---|---|---|
| Plan shape | One plan; its first task is a **gate** that measures recall at the candidate depth | A reranker only reorders what retrieval returns; the gate is a cheap CPU run |
| Gate threshold | Small-twin recall at depth N **≥ 0.80** in every mode | Enough headroom to tell a real lift from noise on groups of 22 queries |
| Candidates | **Fused top N**, N set by the gate (50 or 100) | Master design §12.8; bounded latency |
| Hardware | **GPU only** for now; adapters refuse to run without CUDA | Operator, 2026-11-13. No CPU fallback in M4 |
| Models | `BAAI/bge-reranker-v2-m3` and `Qwen/Qwen3-Reranker-4B` | A strong cross-encoder baseline and the master design's pick (§12.5); both Apache-2.0 |
| Integration | **In-process** (transformers), like `E5Embedder` | One container, same offline story as e5; no vLLM in the sealed image |
| Candidate text | Two variants: `problem` and `problem_solution` | Twins share component and symptom and differ by cause and fix; the fix lives in `solution_text` |
| Final order | **Pure reranker score**, ties by fused rank | No new weight to tune on stand-in text |
| Qwen instruction | One fixed, task-specific instruction | Pinned by a test, not tuned |
| Win bar | Small-twin lift **≥ 15 points** in every mode, no collateral damage (§3) | Well clear of the 1-2 point spread between M3's fusion variants |
| Among winners | **Best quality wins**: the largest small-twin lift; only the winner stays in the code | Operator, 2026-11-13 |
| Latency | Recorded, never a veto | ~0.1-0.5 s expected on an H100; a 510-ticket stand-in says little about production load |
| No winner | The best cell stays **opt-in**, the other adapter is deleted | Real data (Task 8) can still test it |
| A winner | Becomes the **default config**; real data can revert it | Same stance as the `query:` prefix |
| Eval on the box | A **CUDA container** from a tracked `infra/eval/Dockerfile`, weights mounted | Reproducible and reviewable; mirrors how the sealed image is built |

Rejected: reranking the union of both pools (up to 4x the pairs, and it makes RRF pointless in the
reranked path); blending reranker and RRF scores (a weight tuned on invented text); serving the
model over HTTP via vLLM (a third container, and the sealed image would have to ship vLLM);
`gte-multilingual-reranker-base` (needs `trust_remote_code`) and `Qwen3-Reranker-0.6B` (not
chosen for the first bake-off); jina rerankers (CC-BY-NC, master design §12.5).

## 1. Flow

**Phase A, the gate (no reranker code yet).** `recall.eval` learns `--depths 10,50,100,all`: the
same ranked lists are scored at several depths. MRR and nDCG stay at 10. `all` scores the fused list
without a limit, which is exactly the union of both 100-deep pools, the ceiling of any rerank over
them. Recall at depth d divides by `min(d, |relevant|)`, so a small twin (21 relevant) is scored on
how many of its 21 are in the list. The run needs no GPU: the M3 command on the existing CPU venv,
plus the recreated Postgres container.

Gate rule, on the small twins (R004, R009-R012), `fused_query`, every query mode:

Read top to bottom; the first row that applies decides. 0.80 is the floor; the 10-point clause only
chooses between 50 and 100.

| Reading | Decision |
|---|---|
| recall@100 < 0.80 in any mode | **stop**: the loss is recall, not order. The `all` row shows whether deeper pools would help. The operator re-plans |
| recall@50 ≥ 0.80 in every mode, and recall@100 − recall@50 < 0.10 in every mode | go, **N = 50** |
| otherwise | go, **N = 100** (deeper either is needed to reach 0.80, or adds 10+ points) |

**Phase B, the reranker.** Code built test-first against a torch-free stand-in (§2), the eval's
reranked matrix, the eval image, and the weights downloaded at a pinned revision.

**Phase C, one GPU run and the decision** (§3).

## 2. Components

### `src/recall/rerank.py` (new)

- `Reranker` protocol: `identity: str`, `device: str`,
  `score(query: str, candidates: list[tuple[str, str | None]]) -> list[float]` (each candidate is
  its problem text and its solution text or None, so the budget can split them at token level),
  higher is more relevant. Mirrors `profiler.gate.embedder.Embedder`.
- `OverlapReranker`: deterministic, torch-free stand-in for tests (token overlap). Its identity
  starts with `overlap:` so a report made with it cannot pass for a model's.
- `BgeReranker`: `BAAI/bge-reranker-v2-m3`, `AutoModelForSequenceClassification`, fp16, the raw
  logit as score.
- `Qwen3Reranker`: `Qwen/Qwen3-Reranker-4B`, `AutoModelForCausalLM`, bf16, score = the "yes"
  versus "no" logit in the model card's prompt format, with one fixed instruction:
  *"Given a vehicle service ticket, judge whether the candidate ticket describes the same fault
  with the same cause, so its fix applies."*
- Both adapters: weights pinned by revision (constants next to the model names, like
  `E5_REVISION`), `local_files_only=True`, torch imported lazily, and a `RuntimeError` at
  construction when CUDA is not available ("the reranker is GPU only").
- **Token budget per pair: 512 content tokens** (each model's special tokens and prompt frame
  come on top), the same for both models, applied by a pure helper over token-id
  lists. The query gets at most 128 tokens (title and head never reach it; a full ticket is cut);
  the candidate gets the rest. In `problem_solution` the problem and the solution get half of the
  candidate's share each, so a long description cannot push the fix text out of the window.

### `recall.retrieve.search` (extended, unchanged by default)

New keywords: `reranker=None`, `depth: int | None = None`, `doc_text="problem"`
(or `"problem_solution"`). With a reranker: fuse as today, keep the fused top `depth`, fetch their
texts in one query by id from `ticket` only, score the **cleaned** query (the text the arms see)
against them, sort by reranker score with ties broken by fused rank, return the top `k`. `Hit`
gains `rerank: float | None`. With `reranker=None` the output is exactly today's.

### `recall.eval` (extended)

- `--depths` (Phase A), as above.
- `--rerankers bge,qwen3-4b --depth N` builds cells `rr_<model>_<text>` next to the unchanged
  `VARIANTS`. Each query's fused top N is retrieved **once per mode** and reused by every reranked
  cell.
- `--e5-device cpu`: the index is built on CPU even when a GPU is visible, so the run's index is
  the one M3 measured.
- The report adds rerank time per query (p50, p95), with N and the device. Aggregates only; the
  report's key-set pin is updated on purpose.

### `recall.config.Settings`

`rerank_url` (an early HTTP sketch) is replaced by `rerank_model`, `rerank_depth` and
`rerank_text`, all `None` until §3 decides. `search()` keeps `reranker=None`: the config is the
application's default, not the pure function's.

### `infra/eval/Dockerfile` (new)

Same pattern as `infra/profiler/Dockerfile`: `python:3.12-slim-bookworm`, `uv sync --frozen
--no-dev` (the lock already pins cu126 torch), the code copied in (`src`, `profiler`, `insight`).
**No weights baked**: the shared Hugging Face cache is mounted read-only with `HF_HUB_OFFLINE=1`.
No fixture in the image: it is mounted read-only by exact path at run time.

## 3. How the run is judged (fixed before the run)

Baseline: `fused_query` recall@10 from the same run. It must reproduce the 2026-11-12 numbers
exactly, or the run is not comparable and nothing is decided.

A reranked cell (model x text, at the gate's N) **passes** only if all four hold:

| # | Rule | Measured on |
|---|---|---|
| 1 | Small twins rise by **≥ 15 points** in every mode | mean recall@10 over R004, R009-R012 |
| 2 | Groups without a twin drop by **≤ 2 points** in every mode | mean over R005-R008 |
| 3 | Macro recall@10 is **not lower** in any mode | macro |
| 4 | Macro MRR on full queries drops by **≤ 2 points** | macro, `full` |

Among passing cells, the **largest small-twin lift, averaged over the three modes**, wins (model,
text variant and N together). Latency is reported and decides nothing.

- **A winner:** its values go into `Settings`; the other model's adapter and tests are deleted,
  and the losing text variant leaves the eval and `doc_text`.
- **No winner:** the best cell by the same measure stays in the code as opt-in (`Settings` stays
  `None`); the other adapter is deleted; the results and a short reading go into the plan, and the
  operator picks the next step.
- **Either way:** per-group numbers for the large originals (R001-R003) are recorded, so a twin lift
  bought by pushing its original down is visible. The stand-in caveat stays in the report.

## 4. Box runs

Exact paths, the GPU wrapper and the fair-use claim are in
`docs/handoff-hpc-continuation-2026-11-10.md` (local, not published); the plan writes the commands
out as numbered steps for the operator, because the guard blocks agent commands that name data
files.

- **Postgres** is recreated once from `infra/postgres/Dockerfile` with the values of
  `infra/postgres/compose.yml` (database, user and password `recall` / `recall_dev_only`, port
  5433, a named volume at `/var/lib/postgresql`). First check that podman's image store is on the
  large data disk, not the full root disk.
- Rootless containers die with the last ssh session: Postgres is started in the same ssh command
  as each eval.
- **Phase A:** the M3 eval command (CPU venv, GPUs hidden) plus `--per-group --depths 10,50,100,all`.
- **Phase C:** claim a GPU from the workstation, then the eval image through the box's GPU podman
  wrapper with `--network=host` (Postgres on `localhost:5433`), the HF cache and the fixture
  mounted read-only, and `--embedder e5 --e5-device cpu --per-group --depths 10,50,100,all
  --rerankers bge,qwen3-4b --depth N`. If transformers insists on writing into a read-only cache,
  mount it read-write instead.

## Testing

- **Unit, no torch:** `OverlapReranker` is deterministic; the budget helper (query cap, total cap,
  the 50/50 split, short texts untouched); scoring one ranking at several depths, `all` = unlimited;
  cell names; retrieval runs once per query and mode however many reranked cells (counted through a
  fake); the report's new keys; an adapter raises without CUDA (monkeypatched
  `torch.cuda.is_available`).
- **Integration (`needs_pg`):** `search` with the stand-in reorders only the fused top `depth`,
  breaks ties by fused rank, and reads the right text per `doc_text`; with `reranker=None` the
  result equals today's; `retrieve.py` still never names `eval_label`.
- **Box only, as a smoke command** (`python -m recall.rerank smoke --model <name>`, run in the eval
  image; the box's published snapshot carries no `tests/unit` or `tests/integration`): each adapter
  loads offline on the GPU and scores a German same-fault pair above an unrelated one. The Qwen
  instruction is pinned by a unit test.

## Errors

No CUDA: `RuntimeError` at adapter construction. `depth < k`, an unknown `doc_text`, or a reranker
without a `depth`: `ValueError`. Missing weights fail loudly through `local_files_only`. Query and
candidate texts are never logged; the report stays aggregates only, and per-group output stays
synthetic only (on real data a group key is a `fehlercode`).

## Out of scope

Same-serial boost, the `fehlercode` arm, Task 8 / Window C, CPU latency or a CPU fallback, baking
reranker weights into the sealed image, and any change to `MIN_RECIPES`, `catalog/` options or
`tools/publish/allowlist.txt`.
