#!/usr/bin/env bash
# Synthetic only: creates all six tickets itself; accepts no corpus or work-directory path.
# Images must already be built from a clean published snapshot, outside the airlock.
set -euo pipefail
RUNTIME=docker
GPU_UUID=""
while (( $# )); do
  case "$1" in
    --runtime) RUNTIME=${2:?}; shift 2 ;;
    --gpu) GPU_UUID=${2:?}; shift 2 ;;
    *) printf 'E_REHEARSAL_ARGUMENT\n' >&2; exit 4 ;;
  esac
done
[[ "$RUNTIME" == docker || "$RUNTIME" == podman ]] || exit 4
[[ -z "$GPU_UUID" || "$GPU_UUID" =~ ^GPU-[A-Za-z0-9-]+$ ]] || exit 4
[[ "$RUNTIME" != podman || -n "$GPU_UUID" ]] || exit 4
IMAGE=${RECALL_WINDOW_IMAGE:-recall/window-c:pinned}
PG_IMAGE=${RECALL_WINDOW_C_PG_IMAGE:-recall/postgres:18}
PIPE_ID=$("$RUNTIME" image inspect --format '{{.Id}}' "$IMAGE")
PG_ID=$("$RUNTIME" image inspect --format '{{.Id}}' "$PG_IMAGE")
printf 'pipeline_image=%s\npostgres_image=%s\n' "$PIPE_ID" "$PG_ID"
WORK=$(mktemp -d /tmp/recall-c-rehearsal.XXXXXX)
CHILD=""
cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [[ -n "$CHILD" ]] && kill -0 "$CHILD" 2>/dev/null; then
    kill -TERM "$CHILD" 2>/dev/null || true
    wait "$CHILD" || true
  fi
  rm -rf -- "$WORK"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
mkdir -m 700 "$WORK/q"
common=(--rm --pull=never --network=none --read-only --tmpfs /tmp:rw,nosuid,nodev
        --log-driver=none --ulimit core=0)
# Same ordering and locale on both sides; no stale-image pass against yesterday's CLI.
HOST_HASH=$(find src/recall profiler insight -name '*.py' -type f | LC_ALL=C sort \
  | xargs sha256sum | sha256sum | cut -d ' ' -f1)
IMAGE_HASH=$("$RUNTIME" run "${common[@]}" "$PIPE_ID" sh -ec \
  "find src/recall profiler insight -name '*.py' -type f | LC_ALL=C sort | xargs sha256sum | sha256sum" \
  | cut -d ' ' -f1)
[[ "$HOST_HASH" == "$IMAGE_HASH" ]] || { printf 'E_STALE_IMAGE\n' >&2; exit 5; }
"$RUNTIME" run -i "${common[@]}" -v "$WORK/q:/q" "$PIPE_ID" python - <<'PY'
import csv
import json
from profiler.columns import EXPECTED_COLUMNS

dates = ("2024-02-28", "2024-02-29", "2024-08-31", "2024-08-30", "2024-02-01", "")
codes = ("C_SYNTH_CODE_A", "C_SYNTH_CODE_A", "C_SYNTH_CODE_A", "C_SYNTH_CODE_B", "", "C_SYNTH_CODE_C")
with open("/q/export.csv", "w", newline="", encoding="utf-8") as handle:  # synthetic only
    writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
    writer.writeheader()
    for number, (created, code) in enumerate(zip(dates, codes, strict=True), 1):
        row = dict.fromkeys(EXPECTED_COLUMNS, "")
        row.update(id=f"C-INVENTED-TICKET-{number}", title="Erfundene Hydraulikpumpe undicht",
                   description="Pumpe verliert Druck C_SYNTHETIC_PRIVATE",
                   vehicleSerialNo="C-INVENTED-SERIAL", timestampCreated=created,
                   customData=json.dumps([{"key": "fehlercode", "value": code}]) if code else "")
        writer.writerow(row)
PY
# Read back the real operator command, never maintain a second CLI spelling here.
DRY=$(bash infra/profiler/window.sh --window c --dry-run run)
COMMAND=$(printf '%s\n' "$DRY" | sed -n 's/.*\(python -m recall.window_c --csv \/q\/export.csv --out eval_real.json\).*/\1/p' | head -n 1)
[[ -n "$COMMAND" ]] || { printf 'E_COMMAND\n' >&2; exit 5; }
read -r -a command_args <<<"$COMMAND"
bash infra/profiler/window-c-runtime.sh "$RUNTIME" "$WORK/q" "$PIPE_ID" "$PG_ID" \
  "${RECALL_WINDOW_THREADS:-32}" "$GPU_UUID" "${command_args[@]}" &
CHILD=$!
wait "$CHILD"
CHILD=""
"$RUNTIME" run -i "${common[@]}" -v "$WORK/q:/q:ro" "$PIPE_ID" python - <<'PY'
import json
from pathlib import Path
from recall.eval_real import validate_report

report = json.loads(Path("/q/eval_real.json").read_text())
assert validate_report(report)
assert report["embedder_is_a_model"] is True
assert tuple(report[k] for k in ("n_tickets", "n_dated_tickets", "n_labeled_tickets",
                                 "n_query_tickets", "n_candidate_tickets")) == (6, 5, 5, 3, 2)
for variants in report["modes"].values():
    for cell in variants.values():
        assert (cell["n_queries"], cell["n_unscored"], cell["n_groups"]) == (2, 1, 1)
for name in ("eval_real.json", "window_c.log"):
    text = Path("/q", name).read_text()
    assert "C-INVENTED" not in text and "C_SYNTH" not in text
assert not list(Path("/q").glob("*.tmp"))
print("C_REHEARSAL_OK")
PY
# The runtime verifies removal of its exact names before returning success. This
# rehearsal establishes code correctness and isolation, never a quality threshold.
