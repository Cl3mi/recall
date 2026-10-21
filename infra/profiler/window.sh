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
    *) die "unknown window '$1' (expected a, b, c or d)" ;;
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
  verify        on-box sanity checks that silently cost a cycle when wrong
  fetch         copy back ONLY this window's allowlisted artifacts
  clean         shred this window's sensitive files on the box
  status        list what is currently sitting in quarantine
  all           ship + push + run + verify, then STOP at the human review gate

Options
  --window a|b|c|d  which window (default: a)
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

The review gate
  `all` deliberately stops before fetch. Read profile_report.md on the box, then run
  `fetch --clean` yourself. Nothing is copied back until you have looked at it.

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

  remote "podman run --rm --network=none $IMAGE python -c 'import profiler.__main__, profiler.blessing, insight.__main__'" \
    && ok "offline import works on the box" || die "the image cannot import offline on the box"
  remote "podman run --rm --network=none $IMAGE hunspell -d de_DE -l </dev/null" \
    && ok "German dictionary present in the image" || die "hunspell/de_DE missing on the box"

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
  [[ -n "$WINDOW_CMD" ]] ||
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

cmd_verify() {
  bold "On-box verification"
  # Counts and verdicts only - this prints nothing derived from a row's content.
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
  confirm "Have you read the report on the box?" || die "stopping - read it first"

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
(( DRY_RUN )) && bold "DRY RUN - nothing will be changed on $HOST"

case "$COMMAND" in
  ship)   cmd_ship ;;
  push)   cmd_push ;;
  run)    cmd_run ;;
  verify) cmd_verify ;;
  fetch)  cmd_fetch ;;
  clean)  cmd_clean ;;
  status) cmd_status ;;
  all)    cmd_all ;;
  *)      die "unknown command '$COMMAND' (try --help)" ;;
esac
