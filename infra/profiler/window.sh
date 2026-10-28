#!/usr/bin/env bash
# Drive an airlock window end to end: ship the sealed image, push the export, run the
# profiler on the box, verify, retrieve the artifacts, and shred what must not survive.
#
# The design rule this script exists to enforce: what may leave the box is an explicit
# per-window allowlist, so `fetch` CANNOT copy the CSV or the detail log back by
# accident. That is a property of the code, not of the operator's memory. Everything
# else here is convenience; this part is the point.
#
# It deliberately does NOT automate past the human review gate. `all` stops after
# verification, because docs/airlock-runbook.md requires profile_report.md to be read in
# full, on the box, before anything crosses. A script that copied first and asked later
# would remove the one control the whole airlock design rests on.
#
# Usage:  infra/profiler/window.sh [options] <command>
# Help:   infra/profiler/window.sh --help
set -euo pipefail

HOST="${RECALL_WINDOW_HOST:-hpc}"
# The per-user directory on the box is deliberately not in the repo: export
# RECALL_WINDOW_QUARANTINE=/data/<box-user>/recall-quarantine, or pass --quarantine. The
# placeholder keeps --dry-run working and makes a real run refuse (see below).
QUARANTINE="${RECALL_WINDOW_QUARANTINE:-<data-dir>/recall-quarantine}"
IMAGE="${RECALL_WINDOW_IMAGE:-recall/profiler:pinned}"
# Thread cap for the sealed run. Measured 2026-09-07 on the box (finding 17): on real-length
# documents 32 threads gave 2.08 docs/s but 128 gave 1.10 - roughly HALF - because the box sits
# at load ~200 of 256 with other users and oversubscription turns into context switching.
# Uncapped means all 256, which is deeper into the regime that measured worse. 32 is the best
# of the three sampled; overridable because a quiet box can afford more.
THREADS="${RECALL_WINDOW_THREADS:-32}"

# --- Window E only: the LLM server -----------------------------------------------------------
# Same placeholder idea as the quarantine path: neither value is in the repo (the image is pinned
# by digest on the box, the weights live in a per-user directory), the `<` keeps --dry-run working
# and makes a real run of window e refuse until both are set (see the check before dispatch).
# RECALL_WINDOW_LLM_IMAGE: the vLLM image, pinned by digest (docker.io/vllm/vllm-openai@sha256:...),
#   because a floating tag would let the model server change between the rehearsal and the window.
# RECALL_WINDOW_HF_CACHE: host directory holding the model weights. It is mounted READ-ONLY and
#   the server runs with HF_HUB_OFFLINE=1, so nothing is fetched and nothing is written to it.
LLM_IMAGE="${RECALL_WINDOW_LLM_IMAGE:-<vllm-image@sha256:digest>}"
HF_CACHE="${RECALL_WINDOW_HF_CACHE:-<hf-cache-dir>}"
# AWQ 4-bit: the bf16 default is ~65 GB and breaches the shared 60 GB fair-use cap.
LLM_MODEL="Qwen/Qwen2.5-32B-Instruct-AWQ"
# 0.70 of the 80 GB card is 56 GB: under the shared 60 GB cap, with room for e5 on the same card.
LLM_GPU_UTIL="0.70"
LLM_MAX_LEN=32768
# Starting points, not tuned: the real cluster-size distribution is unknown and a poor K only costs
# a repeat window (design, open item 5).
# RECALL_WINDOW_CLUSTERS is the tuning knob for the first real window (window e); the default is
# unchanged. The catalog build caps the count it actually uses at eligible tickets // k.
CLUSTERS="${RECALL_WINDOW_CLUSTERS:-300}"
WORKERS=8
# Model load takes minutes. Poll every 10 s for up to 30 min, then fail the whole run and tear
# down rather than wait for ever on a window nobody is watching.
READY_POLL_S=10
READY_BUDGET_S=1800
ARTIFACTS="local/artifacts"
WINDOW=a
CSV=""
DO_CLEAN=0
ASSUME_YES=0
DRY_RUN=0

# --- provenance ----------------------------------------------------------------------
# The gate's hash manifest exists so a run is reproducible. It pins the two input SHA-256s
# and the embedder identity by itself, but there is no git INSIDE the sealed image and the
# CLI cannot see the image it is running in - so without these two the report comes out with
# code_commit "unknown" and image_digest "unknown". Measured on a real sealed run 2026-09-07
# (finding 14): two of the manifest's four provenance anchors were absent in exactly the run
# the manifest exists for.
#
# cmd_ship already refuses a dirty tree, so the short sha genuinely identifies the code.
code_commit()  { git rev-parse --short HEAD 2>/dev/null || echo unknown; }
image_digest() { docker image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || echo unknown; }

# --- per-window contract -----------------------------------------------------------
# OUT   : the ONLY files that may cross out. fetch refuses anything else.
# SHRED : what must not survive the window.
# CMD   : the container command, or empty when the window's controls are not settled.
# REVIEW: the file the operator must read in full, ON THE BOX, before `fetch`.
# GPU   : GPU index to CLAIM through gpu-fairuse2.sh, or empty for a CPU-only window.
#         Per-window on purpose: Window A profiles text and has no use for one, and a window
#         holding a card it does not need is unfair on a box with other users.
window_contract() {
  case "$1" in
    a)
      WINDOW_NAME="Window A - profiling"
      WINDOW_IN="export.csv"
      WINDOW_OUT=(profile.json profile_report.md)
      WINDOW_REVIEW="profile_report.md"
      WINDOW_SHRED=(export.csv profiler_detail.log)
      WINDOW_GPU=""
      WINDOW_CMD='python -m profiler --csv /q/export.csv --out /q/profile.json'
      ;;
    b)
      WINDOW_NAME="Window B - leakage gate"
      WINDOW_IN="export.csv"
      WINDOW_OUT=(gate_report.json)
      WINDOW_REVIEW="gate_report.json"
      # synthetic.csv and roster.txt added 2026-09-11 (finding 16, caught by the Window B
      # rehearsal on the box). Phase 0 stages three files but WINDOW_IN names only the
      # export, so before this the other two survived `fetch --clean` and the next window
      # started against stale inputs. Phase 0 re-stages them every time, so nothing is lost.
      WINDOW_SHRED=(export.csv synthetic.csv roster.txt
                    profiler_detail.log shingles.bin neighbours.bin)
      # Written at the start of M2. Real-corpus embeddings are not retained between
      # windows, and the shingle/neighbour checks run on the box against the synthetic
      # corpus - only counts and verdicts cross out.
      #
      # Plan B, 2026-09-07. The synthetic corpus is shipped in beside the real export; both
      # are read from /q, and only gate_report.json comes back out - counts, thresholds and
      # verdicts, no shingle set and no vectors, per docs/airlock-runbook.md.
      #
      # --embedder e5 is explicit rather than defaulted: the CLI defaults to the hashing
      # stand-in so the test suite runs without weights, and a window that silently used the
      # stand-in would produce a report whose embedder_is_a_model is false - indistinguishable
      # from one produced deliberately.
      #
      # GPU 0, by decision (operator, 2026-09-11), REVERSING the 2026-09-07 CPU-only ruling
      # once the CPU cost was measured at ~2.2 h per window (finding 17). Claimed through
      # gpu-fairuse2.sh so the card is pinned by UUID rather than index and the 60 GB cap is
      # respected - e5-large needs ~2.2 GB, far inside it. The thread cap still matters:
      # tokenization and the neighbour matmul stay on CPU.
      WINDOW_GPU=0
      #
      # --code-commit and --image-digest added 2026-09-11 (finding 14). Without them the
      # manifest's provenance fields read "unknown" in exactly the run it exists for.
      # rehearse-window-b.sh reads this command back out of `--dry-run` rather than
      # hardcoding it, so these substitutions cannot silently drift from what is rehearsed.
      WINDOW_CMD="python -m profiler.gate --synthetic /q/synthetic.csv --real /q/export.csv --out /q/gate_report.json --embedder e5 --roster /q/roster.txt --code-commit $(code_commit) --image-digest $(image_digest)"
      ;;
    c)
      WINDOW_NAME="Window C - real-data eval"
      WINDOW_IN="export.csv"
      WINDOW_OUT=(eval_real.json)
      WINDOW_REVIEW="eval_real.json"
      WINDOW_SHRED=(export.csv profiler_detail.log eval_queries.json
                    enrichment_state.jsonl vllm.log)
      # Window C runs vLLM and will want a GPU, but its command block is unwritten and its
      # controls are not settled, so it claims nothing yet.
      WINDOW_GPU=""
      # Written at the start of M4. Overnight unattended run of the whole offline
      # pipeline; every stage must already be proven on synthetic data first.
      WINDOW_CMD=''
      ;;
    d)
      WINDOW_NAME="Window D - insight report (stage 1)"
      WINDOW_IN="export.csv"
      # report.json is the only thing that may cross, and it is the file the operator reads
      # in full on the box first: it is the AI-readable artifact, so the human review is the
      # control, exactly as profile_report.md is for Window A.
      WINDOW_OUT=(report.json)
      WINDOW_REVIEW="report.json"
      # report.json.tmp: the CLI writes under a temporary name and moves it into place, so a
      # killed run can leave a clearly partial .tmp file. It must not survive the window.
      WINDOW_SHRED=(export.csv profiler_detail.log report.json.tmp)
      # Stage 1 is deterministic: no model and no GPU, so it claims nothing - holding a card
      # it has no use for would be unfair on a shared box (see Window A).
      WINDOW_GPU=""
      # --min-frequency 50 is spelled out although it is the default, so the rehearsal can
      # assert it and a changed default cannot silently weaken a real window. --serial-prefixes
      # is ABSENT on purpose (operator ruling, 2026-10-12): vehicleSerialNo stays on the
      # never-emit list. --allow-weak-floor must never appear here; it is for rehearsals.
      # --code-commit and --image-digest follow Window B (finding 14), and the CLI refuses a
      # value its guard would refuse, before any real row is read. --cube-budget 1800 caps the
      # cube's derivability measurement (two LP passes, ~15 min each on data of the real shape);
      # it never fails the run, and the report says how many cells it settled.
      WINDOW_CMD="python -m insight --csv /q/export.csv --out /q/report.json --min-frequency 50 --cube-budget 1800 --code-commit $(code_commit) --image-digest $(image_digest)"
      ;;
    e)
      WINDOW_NAME="Window E - catalog extraction"
      WINDOW_IN="export.csv"
      # Only the released catalog and the report that vouches for it may cross. The DRAFT never
      # does: it is what the operator reads and edits on the box, and only `release` (which needs
      # a passing report for those exact bytes) turns it into catalog.json.
      WINDOW_OUT=(catalog.json catalog.leak_report.json)
      # Two files, because the report only says the draft passed the checks; reading it without
      # the draft would approve a catalog nobody looked at.
      WINDOW_REVIEW="catalog.draft.json and catalog.leak_report.json"
      # The *.tmp names: the CLI writes under a temporary name and moves it into place, so a
      # killed run can leave a partial file behind, and a partial draft holds real text.
      WINDOW_SHRED=(export.csv catalog.draft.json catalog.draft.json.tmp catalog.json.tmp
                    catalog.leak_report.json.tmp profiler_detail.log)
      # Claimed through gpu-fairuse2.sh as for window b (UUID-pinned): shared by the LLM server
      # and the e5 embeddings in the catalog container.
      WINDOW_GPU=0
      # Empty on purpose: window e is not one container but two on a private network, so it has
      # its own run path (cmd_run_e) instead of the single `podman run` of windows a-d.
      WINDOW_CMD=''
      ;;
    *) die "unknown window '$1' (expected a, b, c, d or e)" ;;
  esac
}

# --- output ------------------------------------------------------------------------
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
info() { printf '  \033[34m--\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
die()  { printf '  \033[31mABORT\033[0m %s\n' "$1" >&2; exit 1; }

# Every remote call goes through here so --dry-run is total rather than best-effort.
remote() {
  if (( DRY_RUN )); then
    printf '  \033[90mdry-run\033[0m ssh %s "%s"\n' "$HOST" "$1"
    return 0
  fi
  ssh "$HOST" "$1"
}

confirm() {
  (( ASSUME_YES )) && return 0
  (( DRY_RUN )) && return 0
  printf '  %s [y/N] ' "$1"
  read -r reply </dev/tty
  [[ "$reply" == [yY] ]]
}

usage() {
  cat <<'EOF'
Drive an airlock window end to end.

  infra/profiler/window.sh [options] <command>

Commands
  ship          docker save the sealed image, podman load it on the box, verify it
                runs offline there
  push          preflight the export (shape only, never its content) and copy it to
                quarantine as export.csv
  run           run this window's command on the box, sealed with --network=none
                (window e: an LLM container and a catalog container on a private
                internal network, torn down on any exit, then a leak check with no network)
  verify        on-box sanity checks that silently cost a cycle when wrong
  leakcheck     window e only: re-run the leak check on the draft after you edited it
  release       window e only: write catalog.json, only if the report passed for the
                exact draft (runs with --network=none)
  fetch        copy back ONLY this window's allowlisted artifacts
  clean         shred this window's sensitive files on the box
  status        list what is currently sitting in quarantine
  all           ship + push + run + verify, then STOP at the human review gate

Options
  --window a|b|c|d|e  which window (default: a)
  --csv PATH        the real export, for push
  --host HOST       (default: hpc, or $RECALL_WINDOW_HOST)
  --quarantine DIR  (default: $RECALL_WINDOW_QUARANTINE; required for a real run)
  --image REF       (default: recall/profiler:pinned)
  --threads N       CPU cap for the sealed run (default: 32, or $RECALL_WINDOW_THREADS).
                    32 measured ~2x faster than 128 on the shared box; uncapped takes all
                    256 and is slower still. Raise it only on a quiet box.
  --clean           after a successful fetch, shred the remote files
  --yes             never prompt - for unattended use
  --dry-run         print what would run and change nothing
  --help

Window E environment (a real run refuses the placeholders)
  RECALL_WINDOW_LLM_IMAGE  the vLLM image, pinned by digest
  RECALL_WINDOW_HF_CACHE   host directory holding the model weights (mounted read-only)
  RECALL_WINDOW_CLUSTERS   k-means clusters requested by the catalog build (default: 300).
                           A tuning knob for the first real window: the real cluster-size
                           distribution is unknown. The build never uses more than
                           eligible tickets // k clusters.

The review gate
  `all` deliberately stops before fetch. Read profile_report.md on the box, then run
  `fetch --clean` yourself. Nothing is copied back until you have looked at it.
  Window e: read catalog.draft.json AND catalog.leak_report.json in full on the box, run
  `leakcheck` again if you edited the draft, then `release`, then `fetch --clean`.

Examples
  infra/profiler/window.sh --csv ~/work/<export-dir>/<export-file> all
  infra/profiler/window.sh fetch --clean
  infra/profiler/window.sh --window a clean --yes
EOF
}

# --- commands ----------------------------------------------------------------------

cmd_ship() {
  bold "Ship the sealed image"
  [[ -n "$(git status --porcelain)" ]] &&
    die "working tree is dirty - the image would not correspond to any commit"
  ok "tree clean at $(git rev-parse --short HEAD)"

  if (( DRY_RUN )); then
    info "dry-run: docker save $IMAGE | ssh $HOST 'podman load'"
  else
    docker image inspect "$IMAGE" >/dev/null 2>&1 ||
      die "$IMAGE not built locally - run: docker build -f infra/profiler/Dockerfile -t $IMAGE ."
    info "transferring image (this is the slow step)"
    docker save "$IMAGE" | ssh "$HOST" 'podman load' >/dev/null
  fi
  ok "image loaded on $HOST"

  # Window e adds the catalog CLI to the image, so its import is proved here too - a missing
  # module found inside the window would cost the whole window.
  local import_line="import profiler.__main__, profiler.blessing, insight.__main__"
  [[ "$WINDOW" == e ]] && import_line+=", catalog.__main__"
  remote "podman run --rm --network=none $IMAGE python -c '$import_line'" \
    && ok "offline import works on the box" || die "the image cannot import offline on the box"
  remote "podman run --rm --network=none $IMAGE hunspell -d de_DE -l </dev/null" \
    && ok "German dictionary present in the image" || die "hunspell/de_DE missing on the box"

  if [[ "$WINDOW" == e ]]; then
    # The private network is the whole isolation story for the two-container window, so prove on
    # the box that this podman can make an INTERNAL one (design, open item 2) - a plain network
    # would silently give the LLM and catalog containers a route out. Create and remove a probe.
    remote "podman network create --internal recall-e-probe-\$\$ >/dev/null && podman network rm recall-e-probe-\$\$ >/dev/null" \
      && ok "podman can create an internal network on the box" \
      || die "podman network create --internal does not work on the box - window e cannot be isolated"
    # The LLM image is pinned and is NOT shipped by this script, so a typo or a missing load is
    # found here, before the window, rather than as a pull attempt (which has no network) inside it.
    remote "podman image exists $LLM_IMAGE" \
      && ok "LLM image present on the box" \
      || die "LLM image $LLM_IMAGE is not on the box - load it there first"
  fi

  remote "mkdir -p $QUARANTINE && chmod 700 $QUARANTINE"
  ok "quarantine ready at $QUARANTINE (mode 700)"
}

cmd_push() {
  bold "Push the export"
  [[ -n "$CSV" ]] || die "no --csv given"
  [[ -f "$CSV" ]] || die "no such file: $CSV"

  # Shape-only. This reports column names and counts and never the rows themselves,
  # which is what makes it safe to run with AI assistance present.
  if [[ -x infra/profiler/preflight-export.sh ]]; then
    info "preflight (shape only, never content)"
    ./infra/profiler/preflight-export.sh "$CSV" || die "preflight failed - do not open a window"
    ok "export matches the 38-column contract"
  else
    warn "preflight script missing; skipping (it is the cheapest check you have)"
  fi

  # source.filename is emitted verbatim into the artifact. The profiler now withholds a
  # non-conforming name and warns, but shipping it correctly named keeps the artifact
  # informative instead of merely safe.
  if [[ "$(basename "$CSV")" != "export.csv" ]]; then
    info "renaming to export.csv in transit ($(basename "$CSV") would be withheld)"
  fi

  if (( DRY_RUN )); then
    info "dry-run: scp $CSV $HOST:$QUARANTINE/export.csv"
  else
    scp -q "$CSV" "$HOST:$QUARANTINE/export.csv"
  fi
  ok "export in quarantine as export.csv"
}

cmd_run() {
  bold "$WINDOW_NAME  (AI OFF from here)"
  [[ -n "$WINDOW_CMD" || "$WINDOW" == e ]] ||
    die "window '$WINDOW' has no command block yet - it is written at the start of its milestone"

  # The box must not be crowded. Exit 1 means wait; exit 3 means unreachable, which is a
  # connectivity problem to investigate rather than something to push past.
  #
  # A window that wants a GPU CLAIMS it rather than merely checking: claim pins one index,
  # returns its UUID, and is itself a GO gate. The UUID matters - an index can move between
  # runs, and `nvidia.com/gpu=<uuid>` cannot silently land on somebody else's card.
  local device_arg=""
  if [[ -x infra/fairuse/gpu-fairuse2.sh ]] && (( ! DRY_RUN )); then
    if [[ -n "${WINDOW_GPU:-}" ]]; then
      local claim
      claim="$(./infra/fairuse/gpu-fairuse2.sh claim "$WINDOW_GPU" 2>/dev/null)" ||
        die "fairuse refused GPU $WINDOW_GPU - wait rather than crowding the box"
      eval "$claim"
      device_arg="--device ${GPU:?fairuse claim returned no GPU}"
      ok "fairuse claimed GPU $WINDOW_GPU ($GPU)"
    elif ./infra/fairuse/gpu-fairuse2.sh check >/dev/null 2>&1; then
      ok "fairuse check: GO"
    else
      case $? in
        3) die "the box is unreachable - investigate connectivity, do not proceed" ;;
        *) die "the box is busy - wait rather than crowding it" ;;
      esac
    fi
  elif [[ -n "${WINDOW_GPU:-}" ]]; then
    device_arg="--device nvidia.com/gpu=<claimed at run time>"
    info "dry-run: would claim GPU $WINDOW_GPU through gpu-fairuse2.sh"
  fi

  # Window e has two containers and a network to tear down, so it does not use the single
  # `podman run` below. The GPU claim above is shared: one card, one UUID, for both containers.
  if [[ "$WINDOW" == e ]]; then
    cmd_run_e "$device_arg"
    return 0
  fi

  # ulimit -c 0 is a data-safety control, not tidiness: a core dump written on the box
  # would contain ticket text straight out of memory, and it would outlive the window.
  # --network=none is the actual guarantee that nothing phones home.
  # RECALL_PROFILER_DETAIL_LOG must point INSIDE the mounted volume: the default is a
  # relative path, which --rm destroys along with the container.
  # Nothing is mounted over /work - that shadowed the image venv and cost a cycle.
  # --cpus and the two thread env vars are a FAIR-USE control as much as a speed one: the
  # box is shared and torch takes every core it can see otherwise. They also make the
  # runtime reproducible. See THREADS above and finding 17.
  # The clamp runs ON THE BOX, not here: a --threads larger than the box has cores makes the
  # container runtime refuse to start at all ("range of CPUs is from 0.01 to N"), and that
  # would be a sealed-window failure with no AI available to read the message. Caught by the
  # rehearsal on a 6-core workstation, where --cpus 32 exited 125.
  local run_cmd="ulimit -c 0; T=$THREADS; C=\$(nproc); if [ \"\$T\" -gt \"\$C\" ]; then T=\$C; fi; \
    podman run --rm --network=none \
    $device_arg \
    --cpus \$T \
    -e OMP_NUM_THREADS=\$T \
    -e MKL_NUM_THREADS=\$T \
    -v $QUARANTINE:/q \
    -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
    $IMAGE \
    $WINDOW_CMD"

  remote "$run_cmd" || die "the sealed run failed - read $QUARANTINE/profiler_detail.log ON THE BOX"
  ok "sealed run completed"
}

# A catalog container with NO network: used for leakcheck and release, which need real rows or
# the draft but never the LLM. --network=none is the actual guarantee that nothing phones home;
# --ulimit core=0 is the container-side twin of the shell's ulimit -c 0 (a core dump would hold
# ticket text). The sealed root is the quarantine mount, so every output name is relative to it
# and goes through recall.sealed. $1 is the catalog subcommand and its arguments.
catalog_sealed() {
  printf '%s' "podman run --rm --network=none --ulimit core=0 -v $QUARANTINE:/q -e RECALL_SEALED_ROOT=/q -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log $IMAGE python -m catalog $1"
}
# No floor flag is ever passed: the CLI defaults ARE the release floors, and --allow-weak-floor
# is for rehearsals only.
leakcheck_args() { printf '%s' "leakcheck --csv /q/$WINDOW_IN --draft catalog.draft.json --out catalog.leak_report.json"; }
release_args()   { printf '%s' "release --draft catalog.draft.json --report catalog.leak_report.json --out catalog.json"; }

# Window e: LLM server + catalog build on a private internal network, then a leak check with no
# network. ONE remote script, so the teardown trap lives in the same shell as everything it must
# clean up - separate ssh calls would leave a failed run's model server and network behind.
cmd_run_e() {
  local device_arg="$1"
  local tries=$(( READY_BUDGET_S / READY_POLL_S ))
  local script
  script="$(cat <<EOF
set -e
NET=recall-e-\$\$
LLM=recall-e-llm-\$\$
teardown() {
  podman stop -t 10 \$LLM >/dev/null 2>&1 || true
  podman rm -f \$LLM >/dev/null 2>&1 || true
  podman network rm -f \$NET >/dev/null 2>&1 || true
}
trap teardown EXIT
trap 'exit 1' HUP INT TERM
ulimit -c 0
rm -f $QUARANTINE/catalog.draft.json $QUARANTINE/catalog.leak_report.json $QUARANTINE/catalog.json
podman network create --internal \$NET >/dev/null
podman run -d --rm --name \$LLM --network \$NET --network-alias llm $device_arg --ipc=host \
  -v $HF_CACHE:/root/.cache/huggingface:ro -e HF_HUB_OFFLINE=1 --ulimit core=0 --log-driver=none \
  $LLM_IMAGE --model $LLM_MODEL --no-enable-log-requests --gpu-memory-utilization $LLM_GPU_UTIL \
  --max-model-len $LLM_MAX_LEN --host 0.0.0.0 --port 8000 >/dev/null
READY=0
N=0
while [ \$N -lt $tries ]; do
  if podman run --rm --network \$NET --ulimit core=0 $IMAGE python -c "import httpx; httpx.get('http://llm:8000/v1/models', timeout=5).raise_for_status()" >/dev/null 2>&1; then READY=1; break; fi
  sleep $READY_POLL_S
  N=\$((N + 1))
done
[ \$READY = 1 ] || { echo 'the LLM server never answered within the readiness budget' >&2; exit 1; }
T=$THREADS
C=\$(nproc)
if [ "\$T" -gt "\$C" ]; then T=\$C; fi
podman run --rm --network \$NET $device_arg --cpus \$T -e OMP_NUM_THREADS=\$T -e MKL_NUM_THREADS=\$T --ulimit core=0 \
  -v $QUARANTINE:/q -e RECALL_SEALED_ROOT=/q -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
  $IMAGE python -m catalog build --csv /q/$WINDOW_IN --draft catalog.draft.json --embedder e5 \
  --llm vllm --base-url http://llm:8000 --model $LLM_MODEL --workers $WORKERS --clusters $CLUSTERS
teardown
$(catalog_sealed "$(leakcheck_args)")
EOF
)"

  # What each control is for:
  # - trap before anything is created: a failed run must never leave a model server holding GPU
  #   memory, or a network, behind - and nobody is watching an unattended window to clean up.
  # - --internal: containers on it reach each other by name and nothing else. No -p anywhere, so
  #   the LLM server is unreachable from outside the box.
  # - the LLM container mounts nothing from quarantine and has --log-driver=none, so real text
  #   reaches it only over the network, lives only in memory, and its stdout is discarded;
  #   --no-enable-log-requests stops vLLM printing prompts (ticket text) even to that stdout.
  # - --ulimit core=0 on every container, on top of the shell's ulimit -c 0 above: no core dump.
  # - the explicit teardown BEFORE leakcheck: the check needs no model, so the GPU is freed and
  #   the one container still touching real rows has no network at all. The trap's later run of
  #   teardown is harmless (every step tolerates a missing container).
  # - the rm -f of the old draft, report and catalog before anything starts: a run that fails before
  #   its leak check (the build, the model server) would otherwise leave the PREVIOUS run's report and
  #   catalog.json next to a missing or different draft, and `fetch` would hand them out.
  # - the thread clamp is the same ON-THE-BOX clamp as windows a-d (see cmd_run).
  remote "$script" || die "the sealed run failed - read the output above (the catalog CLI prints codes and counts only); nothing real is printed"
  ok "sealed run completed: draft and leak report written"
}

# Re-run the leak check after the operator edited the draft: any edit changes the draft's
# SHA-256 and so invalidates the report, and release refuses a report for other bytes.
cmd_leakcheck() {
  [[ "$WINDOW" == e ]] || die "'leakcheck' is only for window e"
  bold "Leak check (no network)"
  remote "ulimit -c 0; $(catalog_sealed "$(leakcheck_args)")" ||
    die "the leak check failed or did not pass - read the report ON THE BOX"
  ok "leak report written"
}

# The only way a catalog is made: catalog.release_gate refuses unless the report passed for the
# exact bytes of the draft. --network=none because releasing needs no model and no network.
cmd_release() {
  [[ "$WINDOW" == e ]] || die "'release' is only for window e"
  bold "Release the catalog (no network)"
  remote "ulimit -c 0; $(catalog_sealed "$(release_args)")" ||
    die "release refused - the report must have passed for the exact draft; run leakcheck again"
  ok "catalog.json written"
}

cmd_verify() {
  bold "On-box verification"
  # Counts and verdicts only - this prints nothing derived from a row's content.
  if [[ "$WINDOW" == e ]]; then
    # Never prints a value: the recipe count, each check's name with ok/FAILED and its failure
    # count, the report's verdict, and whether the report is for the CURRENT draft - the digest is
    # computed by the same function the release gate uses, on the box, with no network.
    local catalog_probe="podman run --rm --network=none -v $QUARANTINE:/q $IMAGE python -c \"
import json
from catalog.leakcheck import draft_digest
d = json.load(open('/q/catalog.draft.json'))
r = json.load(open('/q/catalog.leak_report.json'))
print('recipes in draft     :', len(d['recipes']))
for c in r['checks']:
    print('check', c['name'], 'ok' if c['passed'] else 'FAILED', 'failures=%d' % c['failures'])
print('report passed        :', r['passed'])
print('report matches draft :', r['draft_sha256'] == draft_digest(d))
\""
    remote "$catalog_probe" || die "could not read the draft and report on the box"
    cat <<EOF

  Every check must read ok, 'report passed' must be True and 'report matches draft' True.
  'report matches draft' False means the draft changed after the check: run leakcheck again.
  0 recipes means the build produced nothing - the window is spent and the fix is in code.
  This is counts and verdicts only: read the draft and the report themselves ON THE BOX.
EOF
    return 0
  fi
  if [[ "$WINDOW" == d ]]; then
    local report_probe="podman run --rm --network=none -v $QUARANTINE:/q $IMAGE python -c \"
import json
r = json.load(open('/q/report.json'))
print('schema_version      :', r['schema_version'])
print('rows                :', r['source']['row_count'])
print('guard passed        :', r['selfcheck']['passed'])
print('min_frequency       :', r['provenance']['min_frequency'])
print('serial prefixes     :', r['provenance']['serial_prefixes_enabled'])
print('baugruppe coverage  :', r['origin']['baugruppe']['coverage']['share'])
print('baugruppe empty     :', r['origin']['baugruppe']['empty']['share'])
print('baugruppe distinct  :', r['origin']['baugruppe']['distinct'])
print('fehlercode coverage :', r['formats']['fehlercode']['coverage']['share'])
print('templated share     :', r['readiness']['templated']['share'])
print('usable share        :', r['readiness']['usable']['share'])
print('serial shapes       :', len(r['formats']['vehicleSerialNo']['shapes']))
print('shapes listed       :', sum(len(c['shapes']) for c in r['formats'].values() if 'shapes' in c))
print('ledger rows         :', len(r['suppression']))
\""
    remote "$report_probe" || die "could not read the report on the box"
    cat <<EOF

  'guard passed' must be True, 'min_frequency' 50 and 'serial prefixes' False.
  'baugruppe coverage' near 0.25 is what the profile predicts (about a quarter of the
  rows carry the field). 0.0 means customData did not yield a baugruppe at all: the window is spent,
  and the fix is in code, with no AI near the data. 'fehlercode coverage' 0.0 means the same
  for fehlercode. 'usable share' 0.0 or 'shapes listed' 0 means a section came back empty.
EOF
    return 0
  fi
  local probe="podman run --rm --network=none -v $QUARANTINE:/q $IMAGE python -c \"
import json
p = json.load(open('/q/profile.json'))
print('schema_version      :', p['schema_version'])
print('rows                :', p['source']['row_count'])
print('selfcheck passed    :', p['selfcheck']['passed'])
print('warnings            :', len(p['selfcheck'].get('warnings', [])))
print('hunspell unrecognised:', len(p['vocabulary']['hunspell_unrecognized_top']))
print('age years max       :', p['temporal']['age_years_quantiles']['max'])
print('customData format   :', p['custom_data']['format'])
print('customData keys     :', len(p['custom_data']['keys']))
print('discovered shapes   :', len(p['discovered_identifier_shapes']))
print('largest clusters    :', len(p['clusters'].get('largest', [])))
\""
  remote "$probe" || die "could not read the profile on the box"
  cat <<EOF

  A zero for 'hunspell unrecognised' means the dictionary was not live.
  A zero for 'age years max' means timestampCreated is not YYYY-MM-DD.
  Either one silently costs a cycle.
EOF
}

cmd_fetch() {
  bold "Retrieve artifacts"
  cat <<EOF
  The runbook requires $WINDOW_REVIEW to be read in full, ON THE BOX, before
  anything crosses. That review is the control this whole design rests on.
EOF
  if [[ "$WINDOW" == e ]]; then
    # The report alone only says the draft passed; the draft is what would be released.
    confirm "Have you read BOTH the draft and the report, in full, on the box?" ||
      die "stopping - read both first"
  else
    confirm "Have you read the report on the box?" || die "stopping - read it first"
  fi

  mkdir -p "$ARTIFACTS"
  # Allowlist, not a wildcard. This is what stops the CSV or the detail log coming
  # back on a tired evening, and it is enforced by the loop rather than by care.
  local f
  for f in "${WINDOW_OUT[@]}"; do
    if (( DRY_RUN )); then
      info "dry-run: scp $HOST:$QUARANTINE/$f $ARTIFACTS/"
    else
      scp -q "$HOST:$QUARANTINE/$f" "$ARTIFACTS/" || die "could not retrieve $f"
    fi
    ok "$f -> $ARTIFACTS/"
  done
  info "${#WINDOW_OUT[@]} allowlisted artifact(s); nothing else can be fetched by this script"

  (( DO_CLEAN )) && cmd_clean
  return 0
}

cmd_clean() {
  bold "Shred what must not survive the window"
  local f targets=()
  for f in "${WINDOW_SHRED[@]}"; do targets+=("$QUARANTINE/$f"); done

  printf '  the following will be shredded on %s:\n' "$HOST"
  for f in "${targets[@]}"; do printf '    %s\n' "$f"; done
  confirm "Proceed?" || die "cancelled - nothing was removed"

  # shred -u, not rm: the point is that the bytes do not linger. Missing files are fine
  # (a window may not have produced all of them), so this must not abort the run.
  remote "shred -u ${targets[*]} 2>/dev/null || true"
  ok "shredded"

  bold "What remains in quarantine"
  remote "ls -la $QUARANTINE" || true
  cat <<EOF

  Only the window's own artifacts should remain. If the export or the detail log is
  still listed, remove it before doing anything else.
EOF
}

cmd_status() {
  bold "Quarantine contents on $HOST"
  remote "ls -la $QUARANTINE 2>/dev/null || echo '  (quarantine does not exist yet)'"
}

cmd_all() {
  cmd_ship
  echo
  cmd_push
  echo
  cmd_run
  echo
  cmd_verify
  echo
  bold "Stopping here, deliberately"
  if [[ "$WINDOW" == e ]]; then
    cat <<EOF
  Read BOTH files in full on the box before anything crosses:

    ssh $HOST 'less $QUARANTINE/catalog.draft.json $QUARANTINE/catalog.leak_report.json'

  Edit the draft by hand if needed (any edit invalidates the report), then:

    infra/profiler/window.sh --window e leakcheck     # only after an edit
    infra/profiler/window.sh --window e release
    infra/profiler/window.sh --window e fetch --clean
EOF
    return 0
  fi
  cat <<EOF
  Read the report on the box before anything crosses:

    ssh $HOST 'less $QUARANTINE/$WINDOW_REVIEW'

  Then bring back only the allowlisted artifacts and shred the rest:

    infra/profiler/window.sh --window $WINDOW fetch --clean
EOF
}

# --- argument parsing ---------------------------------------------------------------
COMMAND=""
while (( $# )); do
  case "$1" in
    --window)     WINDOW="${2:?--window needs a value}"; shift 2 ;;
    --csv)        CSV="${2:?--csv needs a value}"; shift 2 ;;
    --host)       HOST="${2:?--host needs a value}"; shift 2 ;;
    --quarantine) QUARANTINE="${2:?--quarantine needs a value}"; shift 2 ;;
    --image)      IMAGE="${2:?--image needs a value}"; shift 2 ;;
    --threads)    THREADS="${2:?--threads needs a value}"; shift 2 ;;
    --clean)      DO_CLEAN=1; shift ;;
    --yes|-y)     ASSUME_YES=1; shift ;;
    --dry-run|-n) DRY_RUN=1; shift ;;
    --help|-h)    usage; exit 0 ;;
    -*)           die "unknown option '$1' (try --help)" ;;
    *)            [[ -n "$COMMAND" ]] && die "more than one command given"; COMMAND="$1"; shift ;;
  esac
done

# --clean on its own is a clean, so the flag reads the way it is spelled.
[[ -z "$COMMAND" && $DO_CLEAN -eq 1 ]] && COMMAND=clean
[[ -n "$COMMAND" ]] || { usage; exit 1; }

window_contract "$WINDOW"
if (( ! DRY_RUN )) && [[ "$QUARANTINE" == *"<"* ]]; then
  die "quarantine path is still the placeholder: export RECALL_WINDOW_QUARANTINE=/data/<box-user>/recall-quarantine (your writable per-user directory on the box) or pass --quarantine"
fi

# Window e's two pins are as placeholder-guarded as the quarantine path: a real run must not start
# an LLM container from "<vllm-image@sha256:digest>" or mount "<hf-cache-dir>". Only the commands
# that start or check the LLM need them; leakcheck, release and verify never touch the LLM.
if (( ! DRY_RUN )) && [[ "$WINDOW" == e ]]; then
  case "$COMMAND" in
    ship|run|all)
      [[ "$LLM_IMAGE" == *"<"* ]] &&
        die "LLM image is still the placeholder: export RECALL_WINDOW_LLM_IMAGE=docker.io/vllm/vllm-openai@sha256:<digest> (the image pinned on the box)"
      [[ "$HF_CACHE" == *"<"* && "$COMMAND" != ship ]] &&
        die "Hugging Face cache is still the placeholder: export RECALL_WINDOW_HF_CACHE=/data/<box-user>/<hf-cache> (the host directory holding the model weights)"
      ;;
  esac
fi
(( DRY_RUN )) && bold "DRY RUN - nothing will be changed on $HOST"

case "$COMMAND" in
  ship)   cmd_ship ;;
  push)   cmd_push ;;
  run)    cmd_run ;;
  verify) cmd_verify ;;
  leakcheck) cmd_leakcheck ;;
  release) cmd_release ;;
  fetch) cmd_fetch ;;
  clean)  cmd_clean ;;
  status) cmd_status ;;
  all)    cmd_all ;;
  *)      die "unknown command '$COMMAND' (try --help)" ;;
esac
