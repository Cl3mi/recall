#!/usr/bin/env bash
# One disposable runtime, shared by the operator window and synthetic rehearsal.
# Arguments: runtime quarantine pipeline-image postgres-image threads gpu-uuid command...
# Client rows are never printed. The only writable persistent mount is the sealed /q.
set -euo pipefail
RUNTIME=$1 Q=$2 PIPELINE=$3 POSTGRES=$4 THREADS=$5 GPU_UUID=$6
shift 6
[[ "$RUNTIME" == docker || "$RUNTIME" == podman ]] || exit 4
[[ "$Q" =~ ^(/[A-Za-z0-9._-]+)+$ ]] || exit 4
[[ "$THREADS" =~ ^[1-9][0-9]*$ ]] || exit 4
[[ -z "$GPU_UUID" || "$GPU_UUID" =~ ^GPU-[A-Za-z0-9-]+$ ]] || exit 4
for image in "$PIPELINE" "$POSTGRES"; do
  [[ "$image" =~ ^[A-Za-z0-9][A-Za-z0-9/:@._-]*$ ]] || exit 4
done
[[ "$RUNTIME" != podman || -n "$GPU_UUID" ]] || exit 4
ulimit -c 0
# A run must never leave the previous report presentable when it fails early.
if (( $# )); then rm -f -- "$Q/eval_real.json" "$Q/eval_real.json.tmp"; fi
PG=recall-c-pg-$$
WORKER=recall-c-worker-$$
POD=recall-c-pod-$$
teardown() {
  local status=$? failed=0 name
  # Ignore further signals: a second Ctrl-C must not stop teardown halfway.
  trap '' HUP INT TERM
  trap - EXIT
  for name in "$WORKER" "$PG"; do
    if "$RUNTIME" container inspect "$name" >/dev/null 2>&1; then
      "$RUNTIME" rm -fv "$name" >/dev/null 2>&1 || failed=1
      if "$RUNTIME" container inspect "$name" >/dev/null 2>&1; then failed=1; fi
    fi
  done
  if [[ "$RUNTIME" == podman ]] && podman pod exists "$POD"; then
    podman pod rm -f "$POD" >/dev/null 2>&1 || failed=1
    if podman pod exists "$POD"; then failed=1; fi
  fi
  # A failed inspect is not evidence of absence when the daemon itself is down.
  "$RUNTIME" info >/dev/null 2>&1 || failed=1
  if (( failed )); then printf 'E_TEARDOWN\n' >&2; exit 8; fi
  if (( status == 0 )); then printf 'C_RUNTIME_OK\n'; fi
  exit "$status"
}
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
PIPE_ID=$("$RUNTIME" image inspect --format '{{.Id}}' "$PIPELINE")
PG_ID=$("$RUNTIME" image inspect --format '{{.Id}}' "$POSTGRES")
# Docker prints `sha256:<hex>`, Podman the bare 64-hex ID; both name one exact image.
for id in "$PIPE_ID" "$PG_ID"; do
  [[ "$id" =~ ^(sha256:)?[0-9a-f]{64}$ ]] || { printf 'E_IMAGE_ID\n' >&2; exit 4; }
done
T=$THREADS
C=$(nproc)
if (( T > C )); then T=$C; fi
worker_run() {
  if [[ "$RUNTIME" == podman ]]; then
    "$HOME/bin/podman-gpu" "$GPU_UUID" "$@"
  else
    local gpu=()
    [[ -n "$GPU_UUID" ]] && gpu=(--gpus "device=$GPU_UUID")
    docker run "${gpu[@]}" "$@"
  fi
}
# No input mount is present in this preflight. On the box it must prove actual CUDA
# access through the same UUID wrapper that will join the pod below.
probe='from profiler.gate.embedder import E5Embedder; import torch; e=E5Embedder(); assert e.encode(["passage: Erfundene Pumpe"]).shape == (1,1024)'
[[ -n "$GPU_UUID" ]] && probe+='; assert torch.cuda.is_available() and e.device == "cuda"'
if ! worker_run --rm --pull=never --network=none --read-only --tmpfs /tmp:rw,nosuid,nodev \
    --ulimit core=0 --log-driver=none -e HOME=/tmp -e HF_HOME=/opt/hf \
    "$PIPE_ID" python -c "$probe" >/dev/null 2>&1; then
  printf 'E_GPU_PREFLIGHT\n' >&2; exit 6
fi
if (( $# == 0 )); then printf 'C_PREFLIGHT_OK\n'; exit 0; fi
namespace=(--network=none)
if [[ "$RUNTIME" == podman ]]; then
  # Reuse the already-pinned Postgres image for the infra sleeper too: no third
  # pause-image lookup/pull occurs. Native box rehearsal must prove this works.
  podman pod create --name "$POD" --label recall.window=c --network=none \
    --infra-image "$PG_ID" --infra-command '/usr/bin/sleep infinity' >/dev/null
  namespace=(--pod "$POD")
fi
"$RUNTIME" run -d --name "$PG" --label recall.window=c --pull=never \
  "${namespace[@]}" --read-only --log-driver=none --ulimit core=0 --cpus "$T" \
  --tmpfs /var/lib/postgresql:rw,nosuid,nodev,size=16g \
  --tmpfs /var/run/postgresql:rw,nosuid,nodev,mode=3777 --tmpfs /tmp:rw,nosuid,nodev \
  -e PGDATA=/var/lib/postgresql/18/docker \
  -e POSTGRES_DB=recall -e POSTGRES_USER=recall -e POSTGRES_PASSWORD=recall_dev_only \
  "$PG_ID" postgres -c logging_collector=off -c log_statement=none \
  -c log_min_error_statement=panic -c max_parallel_workers=0 >/dev/null 2>&1
ready=0
for (( attempt=0; attempt<60; attempt++ )); do
  if "$RUNTIME" exec "$PG" pg_isready -h 127.0.0.1 -U recall -d recall >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
(( ready )) || { printf 'E_DATABASE_READY\n' >&2; exit 7; }
# Docker lists --tmpfs mounts only under HostConfig.Tmpfs, never in .Mounts, so the
# tmpfs proof comes from the kernel's mount table inside the container instead.
mounts=$("$RUNTIME" container inspect --format '{{range .Mounts}}{{println .Type .Destination}}{{end}}' "$PG")
if grep -q '^volume ' <<<"$mounts"; then printf 'E_STORAGE\n' >&2; exit 7; fi
if ! "$RUNTIME" exec "$PG" sh -ec '
grep -q "^[^ ]* /var/lib/postgresql tmpfs " /proc/mounts
data=$(psql -U recall -d recall -Atqc "show data_directory")
case "$data" in /var/lib/postgresql/*) ;; *) exit 1;; esac
case "$(readlink -f "$data/pg_wal")" in /var/lib/postgresql/*) ;; *) exit 1;; esac
' >/dev/null 2>&1; then
  printf 'E_STORAGE\n' >&2; exit 7
fi
if [[ "$RUNTIME" == docker ]]; then namespace=(--network "container:$PG"); fi
# In the background and waited for: bash defers traps while a foreground child runs,
# so a signal would otherwise wait for the whole worker run before teardown.
worker_run --name "$WORKER" --label recall.window=c --pull=never \
  "${namespace[@]}" --read-only --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --ulimit core=0 --log-driver=none --cpus "$T" -e OMP_NUM_THREADS="$T" \
  -e MKL_NUM_THREADS="$T" -e HOME=/tmp -e HF_HOME=/opt/hf \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e RECALL_WINDOW_C=1 -e RECALL_SEALED_ROOT=/q -v "$Q:/q" \
  "$PIPE_ID" "$@" >/dev/null 2>&1 &
if ! wait "$!"; then
  printf 'E_WORKER\n' >&2; exit 9
fi
