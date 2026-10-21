#!/usr/bin/env bash
# Window B dress rehearsal - SYNTHETIC DATA ONLY.
#
# Runs every step of docs/airlock-runbook.md Phase 0 + Window B against two generated
# stand-in corpora, using the exact same image, flags and mounts the real window uses,
# and reports PASS/FAIL per step. Nothing here touches real data, and it refuses to run
# if you point it at anything outside its own scratch directory.
#
# The point: a sealed window has no AI available and every failure costs a full airlock
# cycle. This is where the failures are supposed to happen instead. The Window A
# rehearsal has already caught six defects that would each have cost a cycle.
#
#   ./infra/profiler/rehearse-window-b.sh          # full rehearsal
#   ./infra/profiler/rehearse-window-b.sh --quick  # skip the image rebuild
#
# `docker` rather than `podman`: podman is the box's runtime, docker is the workstation's.
# rehearse-window-a.sh makes the same choice, and window.sh bridges them with
# `docker save | ssh HOST 'podman load'`.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

WORK="${TMPDIR:-/tmp}/recall-window-b-rehearsal"
IMAGE=recall/profiler:pinned
ROWS=1500
QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

# The gate command is READ BACK OUT of window.sh's own --dry-run rather than hardcoded here.
# It used to be a copy plus a fixed-string grep, which detects drift but still lets the two
# disagree for one commit. Extracting it means the rehearsal cannot rehearse a command the
# window does not run - and it survives the command carrying substitutions, which it now does
# (--code-commit and --image-digest are computed at run time, finding 14).
GATE_CMD="$(./infra/profiler/window.sh --window b run --dry-run 2>/dev/null \
  | sed -r 's/\x1b\[[0-9;]*m//g' \
  | sed -n 's/.*\(python -m profiler\.gate .*\)"$/\1/p' | head -1)"

# Same thread cap the window uses, for the same fair-use reason. See window.sh's THREADS.
#
# Clamped to this machine's core count, because the container runtime REFUSES TO START when
# asked for more CPUs than exist - "range of CPUs is from 0.01 to 6.00" - and exits 125. The
# box has 256 cores so it would never show up there; a rehearsal runs on a workstation, which
# is exactly where it does. window.sh clamps the same way, on the box.
# The window attaches GPU 0 via CDI (`--device nvidia.com/gpu=<uuid>`, claimed through
# gpu-fairuse2.sh). Docker on a workstation spells the same thing `--gpus`, so the rehearsal
# uses that. Empty when this machine has no usable GPU, in which case the run below exercises
# the CPU fallback instead - which is a legitimate rehearsal, just a slower one.
GPU_ARG=""
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  GPU_ARG="--gpus all"
fi

THREADS="${RECALL_WINDOW_THREADS:-32}"
HOST_CPUS="$(nproc)"
THREADS_CLAMPED=0
if (( THREADS > HOST_CPUS )); then
  THREADS_CLAMPED=1
  THREADS="$HOST_CPUS"
fi

# What window.sh's window-b WINDOW_SHRED names. Mirrored here rather than sourced because
# window.sh executes on load; the extraction above covers the command, and this list is
# asserted against the directory below.
SHRED=(export.csv synthetic.csv roster.txt profiler_detail.log shingles.bin neighbours.bin)

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
note() { printf '        %s\n' "$1"; }
head2(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

# Refuse to operate anywhere but our own scratch directory. This script removes files, and
# a WORK pointing at a real quarantine would remove the wrong ones.
case "$WORK" in
  "${TMPDIR:-/tmp}"/recall-window-b-rehearsal) : ;;
  *) printf 'ABORT scratch dir %s is outside %s - refusing\n' "$WORK" "${TMPDIR:-/tmp}" >&2
     exit 1 ;;
esac

trap 'rm -rf "$WORK"' EXIT
rm -rf "$WORK"; mkdir -p "$WORK/q"

# ---------------------------------------------------------------- Phase 0
head2 "Phase 0 - preparation (network allowed, no real data present)"

# The suite includes integration tests that need the dev database, and the container does
# not survive a reboot. Bring it up rather than reporting a confusing test failure.
if ! docker compose -f infra/postgres/compose.yml exec -T db pg_isready -U recall -d recall >/dev/null 2>&1; then
  note "dev database not running - starting it"
  make db-up  >/dev/null 2>&1
  make migrate >/dev/null 2>&1
fi
if docker compose -f infra/postgres/compose.yml exec -T db pg_isready -U recall -d recall >/dev/null 2>&1; then
  ok "dev database reachable"
else
  bad "dev database unreachable - 'make db-up' first"
fi

# Captured once - make test takes a minute and this branch used to run it three times.
TEST_OUT="$(make test 2>&1)"
if grep -qE '^[0-9]+ passed' <<<"$TEST_OUT"; then
  ok "make test ($(grep -oE '^[0-9]+ passed.*' <<<"$TEST_OUT" | head -1))"
elif grep -qE '^1 failed, [0-9]+ passed' <<<"$TEST_OUT" &&
     grep -q 'test_the_test_suite_does_not_dirty_the_quarantine' <<<"$TEST_OUT"; then
  # One failure is expected and is the operator's: a stray profiler_detail.log in
  # local/quarantine that only they may shred. Anything else is ours.
  ok "make test - only the operator's quarantine failure ($(grep -oE '^1 failed, [0-9]+ passed.*' <<<"$TEST_OUT" | head -1))"
  note "local/quarantine/profiler_detail.log is theirs to shred; see make check-clean"
else
  bad "make test - fix before any window"
  note "$(grep -E '^[0-9]+ (failed|passed)|^FAILED' <<<"$TEST_OUT" | head -5 | tr '\n' ' ')"
fi
if make lint >/dev/null 2>&1; then ok "make lint"; else bad "make lint"; fi

if (( QUICK )); then
  note "skipping image build (--quick)"
else
  if docker build -q -f infra/profiler/Dockerfile -t "$IMAGE" . >/dev/null 2>&1; then
    ok "sealed image builds"
  else
    bad "sealed image build FAILED - stop here"; printf '\n%d passed, %d failed\n' "$pass" "$fail"; exit 1
  fi
fi

if docker run --rm --network=none "$IMAGE" \
     python -c "import profiler.__main__" >/dev/null 2>&1; then
  ok "image imports with --network=none (nothing resolves at run time)"
else
  bad "offline import failed - a dependency is resolving lazily"
fi

# Does the image actually contain the code under test?
#
# --quick skips the build, which is what makes iteration bearable - and which means a
# rehearsal can otherwise report green while exercising an image that PREDATES the change
# being rehearsed. That happened on 2026-09-14: report.py gained `values_traced`, the
# rehearsal ran --quick against the older image, and the field came back empty while the
# summary still said 0 failed. A stale image makes every assertion below meaningless.
# LC_ALL=C on BOTH sides, and it is load-bearing. Without it the host sorts under a UTF-8
# locale and the container under C, so `profiler/__init__.py` lands on opposite sides of
# `profiler/gate/...` and the two hashes differ for identical content - a guard that fails on
# every build, which is the kind that gets ignored rather than fixed.
HOST_GATE="$(find profiler -name '*.py' -type f | LC_ALL=C sort \
  | xargs sha256sum | sha256sum | cut -c1-16)"
IMG_GATE="$(docker run --rm --network=none "$IMAGE" \
  sh -c "find profiler -name '*.py' -type f | LC_ALL=C sort | xargs sha256sum | sha256sum" \
  2>/dev/null | cut -c1-16)"
if [[ "$HOST_GATE" == "$IMG_GATE" && -n "$IMG_GATE" ]]; then
  ok "image carries the working tree's profiler/ ($IMG_GATE)"
else
  bad "STALE IMAGE: profiler/ in the image ($IMG_GATE) != working tree ($HOST_GATE)"
  note "rebuild without --quick, or every assertion below is about the wrong code"
fi

if docker run --rm --network=none "$IMAGE" hunspell -d de_DE -l </dev/null >/dev/null 2>&1; then
  ok "German dictionary present INSIDE the image"
else
  bad "German dictionary missing - hunspell_unrecognized_top will come back empty"
fi

# ---------------------------------------------------------------- the model, offline
head2 "The sealed embedder (the thing Plan A could not prove)"

MODEL_ID="$(docker run --rm --network=none "$IMAGE" python -c "
from profiler.gate.embedder import E5Embedder
print(E5Embedder().identity)" 2>/dev/null | tail -1)"
if [[ "$MODEL_ID" == e5:intfloat/multilingual-e5-large@* ]]; then
  ok "model loads offline: $MODEL_ID"
else
  bad "model did NOT load offline inside the image (got '${MODEL_ID:-<nothing>}')"
  note "the weights must be baked in at build time; the window has --network=none"
fi

if [[ "$MODEL_ID" == *@main ]]; then
  bad "revision is 'main' - the manifest would be a claim about whatever the hub served"
else
  ok "revision is pinned, not 'main'"
fi

# The Dockerfile's own self-check asserts `v.shape[0] == 1` - the ROW count, which cannot
# fail, because encoding one document always yields one row. A model that loaded at the
# wrong width would print `dim 768` and the build would still pass green. This closes that.
DIM="$(docker run --rm --network=none "$IMAGE" python -c "
from profiler.gate.embedder import E5Embedder
print(E5Embedder().encode(['passage: Pumpe undicht']).shape[1])" 2>/dev/null | tail -1)"
if [[ "$DIM" == "1024" ]]; then
  ok "embedding width is 1024"
else
  bad "embedding width is '${DIM:-<nothing>}', expected 1024 - wrong or swapped model"
fi

# GPU 0 is an operator decision (2026-09-11) reversing the earlier CPU-only one, so this
# assertion is inverted from what it was: the image must now carry a CUDA build. A CPU wheel
# would run the window on CPU while window.sh cheerfully attached a card - exactly the kind
# of "looks accelerated, is not" result this project keeps paying for.
CUDA="$(docker run --rm --network=none "$IMAGE" python -c "
import torch; print(torch.version.cuda)" 2>/dev/null | tail -1)"
if [[ "$CUDA" != "None" && -n "$CUDA" ]]; then
  ok "image carries a CUDA torch (cuda build: $CUDA)"
else
  bad "image carries a CPU-only torch (cuda build: ${CUDA:-<nothing>})"
  note "window.sh attaches GPU 0, but this wheel cannot address it - the run would be CPU"
fi

# And the fallback, which is not a nicety: the image's own build-time self-check runs with no
# GPU attached, so the embedder must degrade to CPU rather than raise. Proven by running it
# with no GPU at all.
FALLBACK="$(docker run --rm --network=none "$IMAGE" python -c "
from profiler.gate.embedder import E5Embedder
print(E5Embedder().device)" 2>/dev/null | tail -1)"
if [[ "$FALLBACK" == "cpu" ]]; then
  ok "with no GPU attached the embedder falls back to CPU"
else
  bad "with no GPU attached the embedder reported device '$FALLBACK' - expected cpu"
fi

# And the case the window actually runs: a card attached, and the embedder must USE it. The
# window would otherwise hold a GPU it never touches, which is both slow and unfair.
if [[ -n "$GPU_ARG" ]]; then
  ONGPU="$(docker run --rm --network=none $GPU_ARG "$IMAGE" python -c "
from profiler.gate.embedder import E5Embedder
print(E5Embedder().device)" 2>/dev/null | tail -1)"
  if [[ "$ONGPU" == "cuda" ]]; then
    ok "with a GPU attached the embedder uses it (device: cuda)"
  else
    bad "a GPU was attached but the embedder reported device '$ONGPU'"
    note "the window would claim a card through fairuse and then not use it"
  fi
else
  note "no usable GPU on this machine - the run below exercises the CPU fallback"
fi

# ---------------------------------------------------------------- stand-in corpora
head2 "Stand-in corpora (two --fake seeds, ${ROWS} rows each)"

# Two seeds rather than one corpus against itself. Measured on seeds 7 and 23 at 1500 rows:
# 0 shingle collisions and 0 byte-identical documents between them, so check 1 can pass
# honestly - and check 1 is not vacuous here either, since 849 of 1500 documents (56.6%)
# form at least one 8-token content shingle.
#
# 1500 rather than something quicker: the generator refuses smaller counts. --rows 40 dies
# on the large-group guard and --rows 250 exits 3 on year-bucket fill drift.
if uv run python -m fixtures --profile local/artifacts/profile.json \
     --out "$WORK/q/synthetic.csv" --rows "$ROWS" --seed 7 --fake >/dev/null 2>&1; then
  ok "synthetic corpus built (seed 7, $(( $(wc -l < "$WORK/q/synthetic.csv") - 1 )) rows)"
else
  bad "synthetic corpus build failed"
fi

if uv run python -m fixtures --profile local/artifacts/profile.json \
     --out "$WORK/q/export.csv" --rows "$ROWS" --seed 23 --fake >/dev/null 2>&1; then
  ok "stand-in export built (seed 23, $(( $(wc -l < "$WORK/q/export.csv") - 1 )) rows)"
else
  bad "stand-in export build failed"
fi

# The roster the window stages. Its contents cannot change the outcome today - see the
# NOTE on check 4 below - but the real window stages one, so the rehearsal does too.
printf 'Erika Beispiel\nMax Muster\nAnna Vorlage\n' > "$WORK/q/roster.txt"

# Phase 0 staging is the omission this rehearsal exists to catch: WINDOW_IN is the export
# ONLY, so nothing in window.sh puts the synthetic corpus or the roster on the box.
staged=1
for f in synthetic.csv export.csv roster.txt; do
  [[ -s "$WORK/q/$f" ]] || { bad "Phase 0 did not stage $f into quarantine"; staged=0; }
done
(( staged )) && ok "Phase 0 staged all three inputs (synthetic corpus, export, roster)"

# ---------------------------------------------------------------- drift check
head2 "The rehearsed command is the real one"

# Extraction, not comparison: if this came back empty the rehearsal has nothing to run and
# must fail loudly rather than silently exercising a stale copy.
if [[ -z "$GATE_CMD" ]]; then
  bad "could not read window b's command out of window.sh --dry-run"
  note "without it this rehearsal would be proving something about a command nobody runs"
else
  ok "gate command read back out of window.sh --dry-run"
fi

# The flags that carry meaning. Extraction guarantees we run what the window runs; these
# assert the window still runs what it is SUPPOSED to run.
for flag in "--synthetic /q/synthetic.csv" "--real /q/export.csv" \
            "--out /q/gate_report.json" "--embedder e5" "--roster /q/roster.txt" \
            "--code-commit" "--image-digest"; do
  grep -qF -- "$flag" <<<"$GATE_CMD" && ok "command carries $flag" \
                                     || bad "command is MISSING $flag"
done
note "$GATE_CMD"

# ---------------------------------------------------------------- Window B
head2 "Window B - the exact command, flags and mounts the runbook specifies"

if (( THREADS_CLAMPED )); then
  note "thread cap clamped from ${RECALL_WINDOW_THREADS:-32} to $THREADS - this machine has"
  note "only $HOST_CPUS cores. The timing below is therefore NOT comparable to the box."
else
  note "thread cap: $THREADS (same as the window)"
fi

# Same as window.sh cmd_run: --network=none, no --device, the detail log inside the mount,
# and nothing mounted over /work.
STARTED=$(date +%s)
OUT="$(ulimit -c 0; docker run --rm --network=none \
        $GPU_ARG \
        --cpus "$THREADS" \
        -e OMP_NUM_THREADS="$THREADS" \
        -e MKL_NUM_THREADS="$THREADS" \
        -v "$WORK/q":/q \
        -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
        "$IMAGE" \
        $GATE_CMD 2>&1)"
RC=$?
ELAPSED=$(( $(date +%s) - STARTED ))
printf '        %s\n' "$OUT"

# NOT asserted green, deliberately - do not "fix" this by adding that assertion.
# The two --fake corpora are templated and heavily self-similar, so self_baseline can come
# out near 1.0 and the neighbours check may go red, or pass against a saturated bar, for
# reasons that say nothing about the real window. Exit 0 (green) and exit 3 (red) are both
# legitimate here; anything else is a crash and is a real failure.
if (( RC == 0 || RC == 3 )); then
  ok "gate ran to completion (exit $RC: $( ((RC==0)) && echo green || echo red ))"
else
  bad "gate exited $RC - neither green (0) nor red (3), so it crashed"
fi

[[ -s "$WORK/q/gate_report.json" ]] && ok "gate_report.json written" \
                                    || bad "gate_report.json missing - nothing to fetch"

rep() { docker run --rm --network=none -v "$WORK/q":/q "$IMAGE" python -c "
import json,sys
p=json.load(open('/q/gate_report.json'))
for k in sys.argv[1].split('.'): p=p[k]
print(len(p) if isinstance(p,list) else p)" "$1" 2>/dev/null; }

if docker run --rm --network=none -v "$WORK/q":/q "$IMAGE" \
     python -c "import json; json.load(open('/q/gate_report.json'))" >/dev/null 2>&1; then
  ok "gate_report.json is valid JSON"
else
  bad "gate_report.json is not valid JSON - the artifact a DPO reads is corrupt"
fi

# THE assertion this whole plan exists for.
IS_MODEL="$(rep embedder_is_a_model)"
if [[ "$IS_MODEL" == "True" ]]; then
  ok "embedder_is_a_model is true - a real leakage verdict, not a stand-in"
else
  bad "embedder_is_a_model is '$IS_MODEL' - the report is NOT a leakage verdict"
  note "a stub-produced report looks exactly like a deliberate one; this is the difference"
fi

# ------------------------------------------------- for the record, not pass/fail
head2 "The verdict and its numbers (recorded, not asserted - see the comment above)"
note "verdict            : $(rep verdict)"
for c in shingles neighbours pii roster; do
  note "$(printf '%-18s : %s' "$c" "$(rep "checks.$c.passed")")"
done
note "cross_p99          : $(rep checks.neighbours.cross_p99)"
note "baseline_p95       : $(rep checks.neighbours.baseline_p95)"
note "baseline_saturated : $(rep checks.neighbours.baseline_saturated)"
note "embedder           : $(rep manifest.embedder)"

# ------------------------------------------------- two things a reader must not misread
head2 "Provenance, and one check whose green means less than it looks"

# Established against the real corpus's own profile, not inferred.
note "roster values_traced : $(rep checks.roster.values_traced)  <- 0 means it examined nothing"
printf '\n'
note "check 4 (roster) CANNOT FAIL as currently wired. ROSTER_COLUMN is"
note "'ansprechpartner', which is not one of the 38 columns in profiler/columns.py, and"
note "local/artifacts/profile.json shows the real export has 38 top-level columns with no"
note "'ansprechpartner' among them. roster_violations therefore receives a list of Nones"
note "and returns 0 whatever the roster holds - measured 0 non-blank values in 1500 rows."
note "Unlike check 2 there is no baseline_saturated-style flag, so nothing in the report"
note "reveals it traced nothing. Do not read 'roster: True' above as evidence."
printf '\n'
# Finding 14, fixed 2026-09-11: the window now passes both. These are assertions rather than
# notes because the report is what a DPO reads, and a manifest that cannot say which code or
# which image produced the verdict is not the reproducibility guarantee report.py claims.
COMMIT="$(rep manifest.code_commit)"
DIGEST="$(rep manifest.image_digest)"
if [[ "$COMMIT" != "unknown" && -n "$COMMIT" ]]; then
  ok "manifest.code_commit is pinned: $COMMIT"
else
  bad "manifest.code_commit is 'unknown' - the report cannot say which code ran"
fi
if [[ "$DIGEST" != "unknown" && -n "$DIGEST" ]]; then
  ok "manifest.image_digest is pinned: ${DIGEST:0:26}..."
else
  bad "manifest.image_digest is 'unknown' - the report cannot say which image ran"
fi

# ------------------------------------------------- safety properties
head2 "Safety properties (only counts, thresholds and verdicts may cross out)"

# Derived from the corpora at run time rather than hardcoded: a hardcoded token that the
# generator stopped producing would make this check pass while testing nothing.
uv run python - "$WORK" > "$WORK/tokens.txt" <<'PY'
import csv, pathlib, re, sys

work = pathlib.Path(sys.argv[1])
seen = []
for name in ("synthetic.csv", "export.csv"):
    words = set()
    with (work / "q" / name).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for col in ("title", "description", "solutions"):
                for tok in re.findall(r"[A-Za-zaeoeueAEOEUE]{9,}", row.get(col) or ""):
                    words.add(tok)
    # The longest few are the most distinctive and the least likely to be coincidence.
    seen.extend(sorted(words, key=len, reverse=True)[:5])
print("\n".join(seen))
PY

LEAK=0
while read -r tok; do
  [[ -z "$tok" ]] && continue
  if grep -qF -- "$tok" "$WORK/q/gate_report.json"; then
    bad "corpus token '$tok' LEAKED into gate_report.json"
    LEAK=1
  fi
done < "$WORK/tokens.txt"
if (( LEAK == 0 )); then
  ok "no corpus token from either corpus appears in gate_report.json ($(grep -c . "$WORK/tokens.txt") probed)"
fi

grep -qF "shingle" <<<"$OUT" && note "('shingle' appears on stdout - that is the check name, not corpus text)"
if grep -qE 'Traceback' <<<"$OUT"; then
  bad "a TRACEBACK reached stdout - it may carry corpus bytes out of the window"
else
  ok "no traceback on stdout"
fi

# ------------------------------------------------- throughput
head2 "Throughput (for whoever books the window - NOT a pass/fail gate)"

# cross_p99 encodes synthetic+real; self_baseline encodes synthetic AGAIN. So the work is
# 3 x ROWS encode passes, not 2, and the wall clock also carries container start, a ~15s
# model load, the shingle pass and the PII sweep.
ENCODES=$(( ROWS * 3 ))
note "wall clock                 : ${ELAPSED}s for ${ENCODES} encode passes (${ROWS}x3)"
if (( ELAPSED > 0 )); then
  note "effective rate             : $(awk -v e="$ENCODES" -v t="$ELAPSED" 'BEGIN{printf "%.2f", e/t}') encodes/s end to end"
fi
printf '\n'
note "DO NOT BUDGET THE REAL WINDOW FROM THIS NUMBER. The --fake corpora are far shorter"
note "than real tickets: mean 106 chars here against several hundred for real"
note "title+description+solutions. Measured on a 6-core i5-9400F: 13.51 docs/s on"
note "stub-length text but only 1.21 docs/s on real-length text - an 11x gap."
note "A real window is 1500 synthetic + the whole real corpus, and the synthetic corpus is"
note "encoded twice, so the encode passes exceed the document count. At the real-length"
note "rate that is several hours on that workstation. The operator has accepted an overnight run."

# ------------------------------------------------- the shred list
head2 "Teardown - the shred list actually clears quarantine"

for f in "${SHRED[@]}"; do
  if [[ -e "$WORK/q/$f" ]]; then
    if rm -f "$WORK/q/$f" 2>/dev/null && [[ ! -e "$WORK/q/$f" ]]; then
      ok "shredded $f"
    else
      bad "could NOT remove $f - it would survive the window"
    fi
  else
    note "$f not present (window b's shred list names files this gate never writes)"
  fi
done

REMAIN="$(cd "$WORK/q" && ls -A)"
if [[ "$REMAIN" == "gate_report.json" ]]; then
  ok "gate_report.json is the only thing left in quarantine"
else
  bad "quarantine still holds more than the artifact: $(echo "$REMAIN" | tr '\n' ' ')"
  note "window b's WINDOW_SHRED should name every file Phase 0 stages. It was missing the"
  note "synthetic corpus and the roster until 2026-09-11 (finding 16); if this fires again"
  note "something else is being left behind. They are synthetic, so this is hygiene rather"
  note "than a leak - but the next window would start against stale inputs. Changing the"
  note "shred list is a safety-control change and therefore the operator's call."
fi

# ------------------------------------------------- workstation hygiene
head2 "Workstation hygiene"
if make check-clean >/dev/null 2>&1; then
  ok "local/quarantine is empty"
else
  note "local/quarantine is NOT empty - expected while the operator's profiler_detail.log"
  note "is still there. Inspect it yourself; do not read it with an AI tool."
fi
[[ -z "$(git status --porcelain)" ]] && ok "working tree clean" || bad "working tree dirty"
[[ -z "$(git remote)" ]] && ok "no git remote" || bad "a git remote is configured"

# ---------------------------------------------------------------- verdict
head2 "Verdict"
printf '  %d passed, %d failed\n\n' "$pass" "$fail"
if (( fail == 0 )); then
  cat <<'EOF'
  Window B is ready to book. The remaining steps are yours and are deliberately
  AI-free - see docs/airlock-runbook.md:

    1. Phase 0 stages THREE files into quarantine, not one. WINDOW_IN names only the
       export, so put the synthetic corpus and the roster there yourself.
    2. docker save recall/profiler:pinned | ssh hpc 'podman load'
    3. Run the Window B block with --network=none. It claims GPU 0 through
       gpu-fairuse2.sh, so check the box is free first.
    4. Read gate_report.json on the box before copying anything off it.
    5. Remember check 4 still traces a column that does not exist (finding 13), so its
       green is not evidence. The manifest's provenance fields ARE pinned now.
EOF
  exit 0
else
  echo "  Do NOT open a window until these are fixed - each failure here is a"
  echo "  failure you would otherwise hit with no AI available to diagnose it."
  exit 1
fi
