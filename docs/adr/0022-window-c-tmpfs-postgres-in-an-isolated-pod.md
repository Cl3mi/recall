# 0022. Window C runs a disposable tmpfs Postgres next to a read-only worker in a network-less pod

Status: Proposed (implemented but unrehearsed; the Window C plan calls its controls proposals and
operator review is pending)
Date: 2026-11-16

## Context

Window C is the first window that needs a database, so real text and real embeddings would exist
inside Postgres, which normally writes data, WAL, logs and temporary files to disk and can retain
them after a crash. ADR 0003 forbids retaining anything derived from real data. Podman is the box's
runtime while the workstation has Docker, and the reproducible rehearsal must run on both.

## Decision

`infra/profiler/window-c-runtime.sh` runs one disposable runtime shared by the operator window and
the synthetic rehearsal. The worker and Postgres share a Podman pod created with `--network=none`
(under Docker, the worker joins the database container's network namespace); there are no
published ports. All Postgres data and WAL live under a tmpfs at `/var/lib/postgresql`, anonymous
volumes are rejected, and logging is disabled. The worker root is read-only, scratch is tmpfs, and
sealed `/q` is its only persistent writable mount. Both containers drop core dumps and runtime
logs. Image IDs are pinned locally with pulls disabled; the GPU is checked through the UUID wrapper
with no data mount; readiness and storage are verified; one trap removes the exact containers and
pod and fails loudly if it cannot. The pod's infra container reuses the Postgres image.

## Consequences

- Real rows exist only in memory and in the sealed report; a hard kill leaves nothing on disk
  except possibly swap, which tmpfs alone does not rule out and the operator must inspect.
- The tmpfs size (16 GB) bounds corpus size; the Postgres parallel workers are disabled.
- Podman infra-command and GPU-wrapper compatibility are unproven in the agent sandbox and must be
  proved on the box before any real-data window.
- The same script serves the rehearsal, so the isolation that is rehearsed is the isolation that
  runs (ADR 0028).
- The spec put the pod inside `window.sh` (`WINDOW_POD=1`); it was built as a shared
  `window-c-runtime.sh` called from `cmd_run_c`. Under Docker the database container is also
  `--network=none`. The CLI accepts only the fixed DSN and requires `RECALL_WINDOW_C=1`, because
  `index.build` truncates, and Window C has its own image (`Dockerfile.window-c`, e5 baked in).

## References

- `infra/profiler/window-c-runtime.sh`, `infra/profiler/rehearse-window-c.sh`
- `docs/superpowers/plans/2026-11-16-m3-window-c.md`, `.state.md`, `docs/handoff-codex-window-c-2026-11-16.md`
- ADR 0003, 0027, 0028
