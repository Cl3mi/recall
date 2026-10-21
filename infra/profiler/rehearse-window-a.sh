#!/usr/bin/env bash
# Window A dress rehearsal - SYNTHETIC DATA ONLY.
#
# Runs every step of docs/airlock-runbook.md Phase 0 + Window A against a generated
# stand-in export, using the exact same image, flags and mounts the real window uses,
# and reports PASS/FAIL per step. Nothing here touches real data, and it refuses to run
# if you point it at anything outside its own scratch directory.
#
# The point: a sealed window has no AI available and every failure costs a full airlock
# cycle. This is where the failures are supposed to happen instead. It has already
# caught six defects that would each have cost a cycle.
#
#   ./infra/profiler/rehearse-window-a.sh          # full rehearsal
#   ./infra/profiler/rehearse-window-a.sh --quick  # skip the image rebuild
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

WORK="${TMPDIR:-/tmp}/recall-window-a-rehearsal"
IMAGE=recall/profiler:pinned
QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
note() { printf '        %s\n' "$1"; }
head2(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

trap 'rm -rf "$WORK"' EXIT
rm -rf "$WORK"; mkdir -p "$WORK"

# ---------------------------------------------------------------- Phase 0
head2 "Phase 0 - preparation (network allowed, no real data present)"

# The suite includes integration tests that need the dev database, and the container
# does not survive a reboot. Bring it up rather than reporting a confusing test failure.
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

if make test >/dev/null 2>&1; then ok "make test"; else bad "make test - fix before any window"; fi
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

if docker run --rm --network=none "$IMAGE" hunspell -d de_DE -l </dev/null >/dev/null 2>&1; then
  ok "German dictionary present INSIDE the image"
else
  bad "German dictionary missing - hunspell_unrecognized_top will come back empty"
  note "that loses the synonym-mining input and costs a whole extra cycle"
fi

# ---------------------------------------------------------------- stand-in
head2 "Stand-in export (fictional TX-22xx / LR-45 product line)"
if uv run python - "$WORK" >/dev/null 2>&1 <<'PY'
import pathlib, sys
sys.path.insert(0, "tests")
from conftest import build_standin
build_standin(pathlib.Path(sys.argv[1]) / "q" / "export.csv")
PY
then ok "stand-in built ($(wc -l < "$WORK/q/export.csv") lines)"
else bad "stand-in build failed"; fi

# ---------------------------------------------------------------- Window A
head2 "Window A - the exact command the runbook specifies"
OUT="$(docker run --rm --network=none \
        -v "$WORK/q":/q \
        -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
        "$IMAGE" \
        python -m profiler --csv /q/export.csv --out /q/profile.json 2>&1)"
RC=$?
printf '        %s\n' "$OUT"
if (( RC == 0 )); then ok "exit 0"; else bad "exit $RC (expected 0)"; fi
grep -q 'selfcheck_passed=True' <<<"$OUT" && ok "selfcheck_passed=True" \
                                          || bad "selfcheck did NOT pass"
grep -qE 'rows=[1-9]' <<<"$OUT" && ok "row count is non-zero" \
                                || bad "rows=0 - truncated transfer, not a result"

# ------------------------------------------------- the runbook's sanity checks
head2 "Runbook sanity checks (each of these silently costs a cycle if wrong)"
jqq() { docker run --rm --network=none -v "$WORK/q":/q "$IMAGE" python -c "
import json,sys
p=json.load(open('/q/profile.json'))
for k in sys.argv[1].split('.'): p=p[k]
print(len(p) if isinstance(p,list) else p)" "$1" 2>/dev/null; }

H="$(jqq vocabulary.hunspell_unrecognized_top)"
[[ "${H:-0}" =~ ^[0-9]+$ && "${H:-0}" -gt 0 ]] \
  && ok "hunspell_unrecognized_top non-empty ($H) - dictionary was live" \
  || bad "hunspell_unrecognized_top EMPTY - dictionary missing during the run"

A="$(jqq temporal.age_years_quantiles.max)"
awk -v a="${A:-0}" 'BEGIN{exit !(a>0)}' \
  && ok "temporal.age_years_quantiles.max > 0 ($A) - timestamps parsed" \
  || bad "ages all zero - timestampCreated is not YYYY-MM-DD; widen temporal.py"

for f in profile.json profile_report.md; do
  [[ -s "$WORK/q/$f" ]] && ok "$f written" || bad "$f missing"
done

# ------------------------------------------------- safety properties
head2 "Window A v2 sections"
v2() { docker run --rm --network=none -v "$WORK/q":/q "$IMAGE" python -c "
import json,sys
p=json.load(open('/q/profile.json'))
for k in sys.argv[1].split('.'): p=p[k]
print(len(p) if isinstance(p,(list,dict)) else p)" "$1" 2>/dev/null; }

[[ "$(v2 schema_version)" == "2" ]] && ok "schema_version is 2" || bad "schema_version is not 2"

fmt=$(v2 custom_data.format)
if [[ -n "$fmt" && "$fmt" != "unknown" ]]; then
  ok "customData parsed as $fmt"
else
  bad "customData did not parse ($fmt) - the key inventory will be empty"
fi

# Assign to a variable first. Nesting a command substitution inside a parameter
# expansion is a bad substitution: it passes `bash -n` and fails only when the
# rehearsal actually runs, which is the worst possible place to find out.
for probe in "custom_data.keys|customData keys" \
             "discovered_identifier_shapes|identifier shapes" \
             "clusters.largest|characterised clusters"; do
  path=${probe%%|*}; label=${probe#*|}
  n=$(v2 "$path")
  if [[ "${n:-0}" =~ ^[0-9]+$ ]] && (( n > 0 )); then
    ok "$label present ($n)"
  else
    bad "$label missing or empty"
  fi
done

head2 "Safety properties (what makes the artifact readable by an AI at all)"
LEAK=0
for v in Musterhaendler Beispielkunde test@example.invalid TN-100001 "+43"; do
  grep -qF "$v" "$WORK/q/profile.json" && { bad "corpus value '$v' LEAKED into profile.json"; LEAK=1; }
done
(( LEAK == 0 )) && ok "no stand-in corpus value appears in profile.json"

grep -qF "Musterhaendler" <<<"$OUT" && bad "corpus value reached stdout" \
                                    || ok "no corpus value on stdout"

# ------------------------------------------------- failure paths
head2 "Failure paths - what happens when a sealed run goes wrong"
FOUT="$(docker run --rm --network=none -v "$WORK/q":/q \
         -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
         "$IMAGE" python -m profiler --csv /q --out /q/bad.json 2>&1)"
FRC=$?
(( FRC == 3 )) && ok "a broken input exits 3" || bad "exit $FRC (expected 3)"
grep -q 'Traceback' <<<"$FOUT" && bad "a TRACEBACK leaked - may carry corpus bytes" \
                               || ok "no traceback on stdout, only the exception type"
[[ -s "$WORK/q/profiler_detail.log" ]] \
  && ok "detail log reached the mounted volume (retrievable after --rm)" \
  || bad "detail log did NOT reach /q - a failed window would have no diagnostic"

EOUT="$(printf 'id,title\n' > "$WORK/q/empty.csv"; docker run --rm --network=none -v "$WORK/q":/q \
         "$IMAGE" python -m profiler --csv /q/empty.csv --out /q/e.json 2>&1)"
grep -q 'EMPTY_INPUT' <<<"$EOUT" && ok "a zero-row export is refused, not reported as success" \
                                 || bad "zero rows was not refused"

# ------------------------------------------------- workstation hygiene
head2 "Workstation hygiene"
if make check-clean >/dev/null 2>&1; then ok "local/quarantine is empty"; else
  bad "local/quarantine is NOT empty - inspect it yourself, do not read it with an AI"; fi
[[ -z "$(git status --porcelain)" ]] && ok "working tree clean" || bad "working tree dirty"
[[ -z "$(git remote)" ]] && ok "no git remote" || bad "a git remote is configured"

# ---------------------------------------------------------------- verdict
head2 "Verdict"
printf '  %d passed, %d failed\n\n' "$pass" "$fail"
if (( fail == 0 )); then
  cat <<'EOF'
  Window A is ready to run for real. The remaining steps are yours and are
  deliberately AI-free - see docs/airlock-runbook.md:

    1. Resolve ~/work/<export-dir>/ first. A real client export must not be on this
       workstation at all. Move it to the box or shred it.
    2. Rename the export to export.csv before it reaches the box - source.filename
       is emitted verbatim into profile.json.
    3. docker save recall/profiler:pinned | ssh hpc 'podman load'
    4. Run the Window A block from the runbook, with --network=none and
       -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log, and do NOT mount
       anything over /work.
    5. Read profile_report.md on the box before copying anything off it.
EOF
  exit 0
else
  echo "  Do NOT open a window until these are fixed - each failure here is a"
  echo "  failure you would otherwise hit with no AI available to diagnose it."
  exit 1
fi
