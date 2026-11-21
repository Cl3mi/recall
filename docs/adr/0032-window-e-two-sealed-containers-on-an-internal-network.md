# 0032. Window E runs the LLM and the catalog build as two containers on an internal network

Status: Accepted
Date: 2026-10-21

## Context

Drafting recipes needs a local LLM that reads real ticket text, but real rows may only be handled
in a manual, AI-free window with no network. The dev3 spec and plan first planned a single
container with the model baked in (and a ship of over an hour); the Window E design superseded
that with a separate model server. The Window E design states no rationale for the split. The
controls it adds follow from the risk that a model server which logs requests or writes to disk
would persist real text. The operator decided on 2026-10-21; the design was written "for operator
approval".

## Decision

Window E uses two sealed containers on a private Podman network created with `--internal`, with no
route out and no published port. The LLM container runs a pinned vLLM image with weights mounted
read-only from the host's Hugging Face cache and `HF_HUB_OFFLINE=1`. It mounts nothing from
quarantine, uses `--log-driver=none` and `--no-enable-log-requests`, and receives real text only
over the network. The catalog container mounts quarantine, shares the claimed GPU, and calls the
server by name. Readiness is polled with a fixed budget, one remote script holds a teardown trap so
a failed run never leaves a model server or network behind, a GPU preflight with no mounts fails in
seconds (exit 6) if the CDI spec is stale, and the leak check then runs in a container with
`--network=none` after the model is torn down. Core dumps are disabled everywhere.

## Consequences

- The model server never touches the filesystem with real text and is unreachable from outside the
  box; the container still processes real text in memory, so its image and flags are part of the
  trusted base and are pinned by digest.
- The sealed image stays smaller; weights are mounted, not baked (ADR 0039).
- A local LLM reading real tickets inside the network-less window is treated as AI-free, an
  operator ruling recorded in the dev3 spec's open items (with Plan 2's stage 2 as precedent).
- The catalog goes to `local/artifacts/`, not `local/released/`, because a text catalog cannot pass
  the numbers-only gate (ADR 0024). Only `catalog.json` and `catalog.leak_report.json` can be
  fetched, and `release` runs with `--network=none`.
- `window.sh` needs a dedicated run path for E, and the rehearsal needs a stub OpenAI-compatible
  server to run without a GPU.
- A stale CDI spec on the box made every GPU container fail after a reboot and needs an admin; the
  preflight turns that from a wasted readiness budget into an immediate abort.
- The default model is an AWQ build so the footprint stays under the shared memory cap (ADR 0040).

## References

- `docs/superpowers/specs/2026-10-21-window-e-design.md`
- `infra/profiler/window.sh` (`cmd_run_e`); commits 2be4c8c, 7a63939, becad0c
- `catalog/stubserver.py`
