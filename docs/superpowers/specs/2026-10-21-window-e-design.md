# Window E - catalog extraction on the real export (two sealed containers)

**Status:** design for operator approval, 2026-10-21. Nothing in `infra/` changes before approval.
Implements the "window" half of `2026-10-21-dev3-vehicle-fixture-design.md` (Stage 1 + leak gate).

## Why

`python -m catalog` (build, leakcheck, release) is built and tested on synthetic stand-ins. Running it
on the real export needs a local LLM, and real rows may only be handled in a manual, AI-free
window on the box (`docs/airlock-runbook.md`). The window must keep Window A-D's guarantees:
no network, an explicit output allowlist, a human review before anything crosses, and shredding.

## Decisions (operator, 2026-10-21)

| Decision | Choice |
|---|---|
| LLM placement | **Two sealed containers** on a private internal network with no route out: an LLM server and the catalog container. |
| Word floor | Dealers + tickets (already built into `catalog.build` and `catalog.leakcheck`). |
| Release | Only through `catalog.release_gate` (a passing leak report for the exact draft). |

## Topology and run sequence (`window.sh --window e run`)

1. **Claim a GPU** through `gpu-fairuse2.sh claim 0` (UUID, as Window B). Refused = wait.
2. `podman network create --internal recall-e-<pid>`: containers on it reach each other by name and
   nothing else. No `-p` is ever published.
3. **LLM container** (detached, `--rm`): the image already used on the box
   (`docker.io/vllm/vllm-openai`, pinned by digest), `--network recall-e-<pid> --network-alias llm`,
   `--device nvidia.com/gpu=<UUID>`, `--ipc=host`, the weights from the host's Hugging Face cache
   mounted read-only (`HF_HUB_OFFLINE=1`), `--ulimit core=0`, **`--log-driver=none`**, vLLM flags
   `--model Qwen/Qwen2.5-32B-Instruct-AWQ --no-enable-log-requests --gpu-memory-utilization 0.70
   --max-model-len 32768`. **It mounts nothing from quarantine**: real text reaches it only over the
   internal network, lives only in memory, and its stdout is discarded.
4. **Wait for readiness** by polling `http://llm:8000/v1/models` from a throwaway catalog container
   on the same network (model load takes minutes); give up after a fixed budget and tear down.
5. **`catalog build`** in the catalog container (`--network recall-e-<pid>`, quarantine mounted at
   `/q`, `RECALL_SEALED_ROOT=/q`, `ulimit -c 0`, thread cap as other windows, the same claimed GPU for
   the e5 embeddings): `--embedder e5 --llm vllm --base-url http://llm:8000 --model
   Qwen/Qwen2.5-32B-Instruct-AWQ --workers 8 --clusters 300` writing `catalog.draft.json`.
6. **Teardown always** (shell `trap` on EXIT, success or failure): stop and remove the LLM container,
   remove the network. GPU memory is freed with the container.
7. **`catalog leakcheck`** in a container with `--network=none` (no LLM needed): writes
   `catalog.leak_report.json` bound to the draft's SHA-256.

## Human gate (AI OFF)

The operator reads `catalog.draft.json` and `catalog.leak_report.json` in full ON THE BOX, edits the
draft by hand if needed (any edit invalidates the report, so `leakcheck` is re-run), then runs
`window.sh --window e release`: `catalog release` in a `--network=none` container, which refuses
unless the gate passes. Then `fetch` copies back **only** `catalog.json` and `catalog.leak_report.json`
(the sibling-report naming is what `tests/leak/test_released_artifacts.py` checks).
`--clean` shreds: `export.csv`, `catalog.draft.json`, every `*.tmp`, `profiler_detail.log`.

## Controls (each is asserted by the rehearsal or the contract test)

| Control | Why |
|---|---|
| internal network, no published port | nothing phones home; the LLM server is unreachable from outside the box |
| LLM container has no quarantine mount and `--log-driver=none` | the model server cannot write real text to disk or logs |
| `--no-enable-log-requests` | vLLM does not log prompts (real ticket text) even to the discarded stdout |
| `ulimit -c 0` on both containers | no core dump with ticket text in memory |
| fair-use claim, UUID-pinned, `--gpu-memory-utilization 0.70` (56 GB of 80) | stays under the shared 60 GB cap |
| allowlist `catalog.json`, `catalog.leak_report.json` | `fetch` cannot copy the export, draft or logs back |
| release needs a passing report for the exact draft | no unvetted catalog crosses |
| teardown trap | a failed run never leaves a model server or network behind |

## Code changes (after approval)

- `catalog/__main__.py`: default `--model` becomes `Qwen/Qwen2.5-32B-Instruct-AWQ` (the bf16 default is
  ~65 GB and breaches the cap); `--workers N` for concurrent LLM calls with results collected in
  deterministic order (300 clusters sequentially would take hours); `--base-url` already exists.
- `catalog/stubserver.py`: a minimal OpenAI-compatible server returning the fake drafter's answers,
  for the rehearsal (no GPU, no weights).
- `infra/profiler/Dockerfile`: `COPY catalog ./catalog` after the weights, plus an import check.
- `infra/profiler/window.sh`: window `e` contract, the two-container `run`, a `release` command,
  `verify` probe (counts only), usage/ship text.
- `infra/profiler/rehearse-window-e.sh` + `make window-e-rehearsal`: runs the whole sequence locally with
  docker on an internal network, the stub LLM and a stand-in corpus; asserts egress from both containers
  fails, the LLM container has no quarantine mount, the sequence passes, only the allowlist is
  fetchable and the shred list empties quarantine.
- `tests/unit/test_window_e_contract.py`: pins the sealed commands from `window.sh --dry-run`
  (no published port, `--network=none` for leakcheck/release, `--log-driver=none`, the allowlist,
  the shred list), as the Window D contract test does.
- `tests/leak/test_released_artifacts.py`: also check the artifacts directory the catalog lands in.
- `docs/airlock-runbook.md`: a Window E section written for reading with no AI.

## Open items for the operator

1. **Paths and pins on the box:** the Hugging Face cache directory (read-only mount; if vLLM needs write
   access for lock files, mount it read-write - weights are not data - and say so), and the vLLM image
   digest to pin.
2. **`podman network create --internal`** must work on the box's podman; `ship` will check it.
3. **Destination of the fetched catalog:** `local/artifacts/` (readable per the project rules) rather
   than `local/released/`, whose numbers-only gate a text catalog cannot pass.
4. **GPU for e5:** the catalog container shares the claimed GPU for embeddings (about 2 GB on top of the
   LLM's 56 GB); otherwise CPU embeddings take about an hour or more.
5. **K and workers:** 300 clusters and 8 workers are starting points; the real cluster-size
   distribution is unknown, and a poor K only costs a repeat window.
6. **Run-time estimate:** 300 recipes at 8 workers should take tens of minutes to a couple of hours
   on the H100; unmeasured.
