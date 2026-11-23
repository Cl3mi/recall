#!/usr/bin/env bash
# Operator driver for the remaining M3 Window C runs. Run it yourself in a normal terminal,
# from any directory; it never prints rows and never skips a human gate.
#
#   bash infra/profiler/finish-window-c.sh prepare            # no real data involved
#   bash infra/profiler/finish-window-c.sh window --csv PATH  # the real window, AI off
#   add --dry-run to either to see the steps without changing anything
#
# prepare: clean tree, full integration suite, publish, box pull, image-source and image checks.
# window : airlock open -> preflight -> push -> run -> verify -> whole-report review on the box
#          -> fetch -> release -> clean -> both-location checks -> airlock close.
# Any failure after the airlock opens shreds C's files on both sides; the airlock is closed
# only when that cleanup is verified. Otherwise it stays open and the script says so.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Pins from the green native box rehearsal (docs/airlock-runbook.md, Window C).
REHEARSED=514d8de
PIPE_ID=7a8e5017edd6464302b0759441504df81d515301f51ccbc4674e5a3eecb41c72
PG_ID=1156b73510303a2d33f15650f2eeefb42f8bc7fd649f502d5cd8c895f40ac3bf
HOST=${RECALL_WINDOW_HOST:-hpc}

PHASE="" CSV="" DRY=0
while (( $# )); do
  case "$1" in
    prepare|window) PHASE=$1; shift ;;
    --csv) CSV=${2:?--csv needs a path}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) printf 'usage: finish-window-c.sh prepare|window [--csv PATH] [--dry-run]\n' >&2; exit 4 ;;
  esac
done
[[ -n "$PHASE" ]] || { printf 'usage: finish-window-c.sh prepare|window [--csv PATH] [--dry-run]\n' >&2; exit 4; }

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  ok   %s\n' "$*"; }
die() { printf '  STOP %s\n' "$*" >&2; exit 1; }
# Commands with side effects outside window.sh: echoed in a dry run, executed otherwise.
act() { if (( DRY )); then printf '  dry-run: %s\n' "$*"; else "$@"; fi; }
win() { bash infra/profiler/window.sh --window c "${WFLAGS[@]}" "$@"; }
WFLAGS=()
(( DRY )) && WFLAGS+=(--dry-run)

ask() {
  local reply
  printf '  %s [type yes] ' "$1"
  read -r reply || return 1
  [[ "$reply" == yes ]]
}

clean_tree() {
  if (( DRY )) && [[ -n "$(git status --porcelain)" ]]; then
    printf '  dry-run: tree not clean; a real run stops here\n'; return 0
  fi
  [[ -z "$(git status --porcelain)" ]] ||
    die "working tree not clean (window.sh ship refuses it); commit, exclude or move: $(git status --porcelain | cut -c4- | tr '\n' ' ')"
  ok "tree clean at $(git rev-parse --short HEAD)"
}

prepare() {
  step "1/6 workstation tree"
  clean_tree
  step "2/6 full integration suite (disposable dev database)"
  act make db-up
  act env PG_DSN=postgresql://recall:recall_dev_only@localhost:5433/recall \
    uv run pytest tests/integration -p no:cacheprovider -q
  ok "integration suite green (plan baseline: 182 passed, 2 xfailed)"
  step "3/6 publish"
  act make publish
  step "4/6 box pulls the published snapshot"
  act ssh "$HOST" 'cd ~/recall && git pull --ff-only'
  step "5/6 image source unchanged since the rehearsed snapshot"
  # The box images were built from $REHEARSED; any change to their source needs a rebuild
  # and a new box rehearsal, never this script.
  act ssh "$HOST" "cd ~/recall && git diff --quiet $REHEARSED HEAD -- src/recall profiler insight" ||
    die "image source changed since $REHEARSED: rebuild the images and rehearse again"
  ok "src/recall, profiler and insight match $REHEARSED"
  step "6/6 both pinned images present on the box"
  export RECALL_WINDOW_IMAGE=$PIPE_ID RECALL_WINDOW_C_PG_IMAGE=$PG_ID
  win ship
  step "prepare done: next, after the sign-offs, run: bash infra/profiler/finish-window-c.sh window --csv <export>"
}

AIRLOCK_OPEN=0
recover() {
  local status=$?
  trap - EXIT INT TERM
  (( AIRLOCK_OPEN )) || exit "$status"
  (( status == 0 )) && exit 0
  set +e
  printf '\n\033[1m== FAILED (exit %s): cleaning both locations, AI stays off\033[0m\n' "$status" >&2
  if win clean --yes && leftovers && act make check-clean; then
    act tools/guard/airlock close
    printf '  cleanup verified, airlock closed. Report only the failing step and its E_ code.\n' >&2
  else
    printf '  CLEANUP NOT VERIFIED: the airlock stays OPEN. Clean by hand (runbook, Window C), then\n' >&2
    printf '  run make check-clean and tools/guard/airlock close yourself.\n' >&2
  fi
  exit "$status"
}

leftovers() {
  local q=$RECALL_WINDOW_QUARANTINE
  # Names only: the listing is for your eyes; the test below is what decides.
  act ssh "$HOST" "ls -la $q" || return 1
  # Every check exits explicitly, and a podman that cannot list counts as a failure, not as
  # "nothing left".
  act ssh "$HOST" "for f in export.csv eval_real.json eval_real.json.tmp window_c.log; do \
    [ ! -e $q/\$f ] || exit 1; done; \
    if ls $q/.eval_real.json.*.tmp >/dev/null 2>&1; then exit 1; fi; \
    pods=\$(podman pod ps -q --filter label=recall.window=c) || exit 1; \
    [ -z \"\$pods\" ] || exit 1; \
    containers=\$(podman ps -aq --filter label=recall.window=c) || exit 1; \
    [ -z \"\$containers\" ] || exit 1" || return 1
  ok "box: no C inputs, outputs, temp files, pods or containers left"
}

window() {
  [[ -n "$CSV" ]] || die "window needs --csv <path to the export>"
  [[ -n "${RECALL_WINDOW_QUARANTINE:-}" ]] ||
    die "export RECALL_WINDOW_QUARANTINE=<data-dir>/recall-quarantine first"
  step "0/14 before booking: your sign-offs (nothing is staged yet)"
  ask "Catalog/relevance prerequisite signed off (normalized fehlercode labels)?" || die "not signed off"
  ask "Isolation, fetch and shred controls reviewed?" || die "controls not reviewed"
  ask "Box swap/tmpfs arrangement checked (no client data on disk)?" || die "swap/tmpfs not checked"
  ask "This is a booked AI-free window (no AI session in any terminal)?" || die "not an AI-free window"
  clean_tree
  export RECALL_WINDOW_IMAGE=$PIPE_ID RECALL_WINDOW_C_PG_IMAGE=$PG_ID

  step "1/14 airlock open"
  trap recover EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  act tools/guard/airlock open
  AIRLOCK_OPEN=1
  step "2/14 pins: pipeline ${PIPE_ID:0:12}, postgres ${PG_ID:0:12}, quarantine set"
  step "3/14 ship: both pinned images on the box"
  win ship
  step "4/14 preflight: GPU claim and offline embedder, before any data"
  win preflight
  step "5/14 push the export (shape-only preflight)"
  win --csv "$CSV" push
  step "6/14 run (pod torn down on every exit)"
  win run
  step "7/14 verify the frozen numeric schema"
  win verify
  step "8/14 READ THE WHOLE REPORT ON THE BOX"
  printf '  Fixed keys and numbers only. Any text that is not a key name: quit less, answer no below.\n'
  act ssh -t "$HOST" "less $RECALL_WINDOW_QUARANTINE/eval_real.json"
  step "9/14 fetch (asks whether you read the whole report; --yes cannot answer it)"
  win fetch
  step "10/14 release through the unchanged exporter"
  win release
  step "11/14 clean both locations"
  win clean --yes
  step "12/14 box leftovers"
  leftovers || die "something is left on the box"
  step "13/14 workstation quarantine empty"
  act make check-clean
  step "14/14 airlock close"
  act tools/guard/airlock close
  AIRLOCK_OPEN=0
  trap - EXIT INT TERM
  step "Window C done. Tell Claude 'window C released' to interpret local/released/ and close M3."
}

"$PHASE"
