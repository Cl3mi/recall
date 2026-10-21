#!/usr/bin/env bash
# Window D dress rehearsal - SYNTHETIC DATA ONLY.
#
# Runs the insight report exactly as window.sh's window d runs it - same image, same flags, same
# mounts, --network=none - against a generated stand-in export, and reports PASS/FAIL per step.
# Nothing here touches real data, and it never leaves its own scratch directory.
#
# Why it exists: a sealed window has no AI available and every failure costs a full airlock
# cycle. The Window A and B rehearsals have caught defects that would each have cost one. This is
# where Window D's failures are supposed to happen instead.
#
#   ./infra/profiler/rehearse-window-d.sh          # full rehearsal, rebuilds the image
#   ./infra/profiler/rehearse-window-d.sh --quick  # skip the rebuild (the stale-image guard
#                                                  # below still refuses a stale image)
#
# Set RECALL_REHEARSAL_PYTHON to a Python that has this project's dependencies installed (the
# repo's .venv). `uv` is deliberately not used: it is not installed here any more.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

WORK="${TMPDIR:-/tmp}/recall-window-d-rehearsal"
IMAGE="${RECALL_WINDOW_IMAGE:-recall/profiler:pinned}"
QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

PY="${RECALL_REHEARSAL_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
fi
RUFF="$(dirname "$PY")/ruff"
[[ -x "$RUFF" ]] || RUFF=ruff

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
note() { printf '        %s\n' "$1"; }
head2(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

trap 'rm -rf "$WORK"' EXIT
rm -rf "$WORK"; mkdir -p "$WORK/q" "$WORK/fp"

# Same thread cap the window uses, clamped to this machine: the container runtime refuses to
# start when asked for more CPUs than exist (exit 125), which only a workstation can show.
THREADS="${RECALL_WINDOW_THREADS:-32}"
HOST_CPUS="$(nproc)"
(( THREADS > HOST_CPUS )) && THREADS="$HOST_CPUS"

sealed() {  # sealed <extra docker args...> -- <command words...>
  local extra=()
  while [[ "$1" != "--" ]]; do extra+=("$1"); shift; done
  shift
  docker run --rm --network=none --cpus "$THREADS" \
    -e OMP_NUM_THREADS="$THREADS" -e MKL_NUM_THREADS="$THREADS" \
    "${extra[@]}" "$IMAGE" "$@"
}

# ---------------------------------------------------------------- Phase 0
head2 "Phase 0 - preparation (network allowed, no real data present)"

TEST_OUT="$($PY -m pytest tests/unit/test_insight_*.py tests/integration/test_insight_*.py \
  tests/unit/test_window_d_contract.py -p no:cacheprovider 2>&1)"
if grep -qE '^[0-9]+ passed' <<<"$TEST_OUT" && ! grep -qE ' failed| error' <<<"$TEST_OUT"; then
  ok "insight and window-d contract tests ($(grep -oE '^[0-9]+ passed' <<<"$TEST_OUT"))"
else
  bad "insight or window-d contract tests - fix before any window"
  note "$(tail -3 <<<"$TEST_OUT" | tr '\n' ' ')"
fi
if "$RUFF" check insight infra tests/unit/test_window_d_contract.py >/dev/null 2>&1; then
  ok "ruff"; else bad "ruff"; fi
if bash -n infra/profiler/window.sh && bash -n "${BASH_SOURCE[0]}"; then
  ok "window.sh and this script parse"; else bad "a shell script does not parse"; fi

if (( QUICK )); then
  note "skipping image build (--quick)"
else
  if docker build -q -f infra/profiler/Dockerfile -t "$IMAGE" . >/dev/null 2>&1; then
    ok "sealed image builds"
  else
    bad "sealed image build FAILED - stop here"; printf '\n%d passed, %d failed\n' "$pass" "$fail"; exit 1
  fi
fi

if sealed -- python -c "import profiler.__main__, insight.__main__" >/dev/null 2>&1; then
  ok "image imports profiler and insight with --network=none"
else
  bad "offline import failed - a dependency resolves lazily, or insight is not in the image"
fi

# Does the image actually contain the code under test? --quick skips the build, so without this
# a rehearsal can report green about an image that PREDATES the change (finding 20). LC_ALL=C on
# BOTH sides is load-bearing: under a UTF-8 locale the host sorts differently from the container
# and identical content hashes differently - a guard that always fails gets ignored.
HOST_SRC="$(find insight profiler -name '*.py' -type f | LC_ALL=C sort \
  | xargs sha256sum | sha256sum | cut -c1-16)"
IMG_SRC="$(sealed -- sh -c \
  "find insight profiler -name '*.py' -type f | LC_ALL=C sort | xargs sha256sum | sha256sum" \
  2>/dev/null | cut -c1-16)"
if [[ "$HOST_SRC" == "$IMG_SRC" && -n "$IMG_SRC" ]]; then
  ok "image carries the working tree's insight/ and profiler/ ($IMG_SRC)"
else
  bad "STALE IMAGE: insight/+profiler/ in the image ($IMG_SRC) != working tree ($HOST_SRC)"
  note "rebuild without --quick, or every assertion below is about the wrong code"
fi

if sealed -- hunspell -d de_DE -l </dev/null >/dev/null 2>&1; then
  ok "German dictionary present INSIDE the image"
else
  bad "German dictionary missing - cleaning would behave differently from the real window"
fi

# ---------------------------------------------------------------- stand-in
head2 "Stand-in export (fictional TX-22xx / LR-45 product line, planted leaks)"
if "$PY" - "$WORK/q/export.csv" >/dev/null 2>&1 <<'PY'
import pathlib, sys
sys.path.insert(0, ".")
from tests import insight_standin
insight_standin.build(pathlib.Path(sys.argv[1]))
PY
then ok "stand-in built ($(wc -l < "$WORK/q/export.csv") lines)"
else bad "stand-in build failed"; fi
SHA_BEFORE="$(sha256sum "$WORK/q/export.csv" | cut -d' ' -f1)"

# ---------------------------------------------------------------- drift check
head2 "The rehearsed command is the real one"

# Read back AFTER the image build: the command embeds the image digest, and window.sh computes it
# from the image as it stands, so reading it earlier would rehearse a stale digest.
# The sealed command is READ BACK OUT of window.sh's own --dry-run rather than copied here, so
# this rehearsal cannot rehearse a command the window does not run.
DRY="$(./infra/profiler/window.sh --window d run --dry-run 2>/dev/null | sed -r 's/\x1b\[[0-9;]*m//g')"
CMD="$(sed -n 's/.*\(python -m insight .*\)"$/\1/p' <<<"$DRY" | head -1)"
if [[ -z "$CMD" ]]; then
  bad "could not read window d's command out of window.sh --dry-run"
  note "without it this rehearsal would be proving something about a command nobody runs"
else
  ok "command read back out of window.sh --dry-run"
fi
for flag in "--csv /q/export.csv" "--out /q/report.json" "--min-frequency 50" \
            "--cube-budget 1800" "--code-commit" "--image-digest"; do
  grep -qF -- "$flag" <<<"$CMD" && ok "command carries $flag" || bad "command is MISSING $flag"
done
for flag in "--serial-prefixes" "--allow-weak-floor"; do
  grep -qF -- "$flag" <<<"$CMD" && bad "command carries $flag - never in a real window" \
                                || ok "command does not carry $flag"
done
note "$CMD"
if (( THREADS < ${RECALL_WINDOW_THREADS:-32} )); then
  note "thread cap clamped to $THREADS - this machine has $HOST_CPUS cores, so timings are not the box's"
fi

# ---------------------------------------------------------------- Window D
head2 "Window D - the exact command, flags and mounts the runbook specifies"
# shellcheck disable=SC2086  # CMD is a list of flag words with no spaces inside a value
OUT="$(sealed -v "$WORK/q":/q -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log -- $CMD 2>&1)"
RC=$?
printf '        %s\n' "$OUT"
(( RC == 0 )) && ok "exit 0" || bad "exit $RC (expected 0)"
grep -q 'selfcheck_passed=True' <<<"$OUT" && ok "selfcheck_passed=True" || bad "the guard did NOT pass"
grep -qE 'rows=[1-9]' <<<"$OUT" && ok "row count is non-zero" || bad "rows=0 - not a result"
grep -q 'columns_expected_missing=0' <<<"$OUT" && ok "no expected column missing" \
  || bad "columns_expected_missing is not 0 - the stand-in lost a column"
grep -q 'cube_checked=' <<<"$OUT" && ok "the cube measurement reported how far it got" \
  || bad "no cube_checked line - the measurement did not report"

R="$WORK/q/report.json"
[[ -s "$R" ]] && ok "report.json written" || bad "report.json missing"
[[ ! -e "$R.tmp" ]] && ok "no report.json.tmp left behind" || bad "a partial .tmp file survived"

field() { "$PY" -c "
import json, sys
p = json.load(open(sys.argv[1]))
for key in sys.argv[2].split('.'):
    p = p[key]
print(p)" "$R" "$1" 2>/dev/null; }

[[ "$(field provenance.min_frequency)" == "50" ]] && ok "floor recorded as 50" \
  || bad "floor in the report is not 50"
[[ "$(field provenance.serial_prefixes_enabled)" == "False" ]] && ok "serial prefixes recorded as off" \
  || bad "serial prefixes are not off"
[[ "$(field selfcheck.passed)" == "True" ]] && ok "selfcheck.passed True in the file" \
  || bad "selfcheck.passed is not True in the file"
[[ "$(field provenance.code_commit)" == "$(git rev-parse --short HEAD)" ]] \
  && ok "code_commit is this tree's commit" || bad "code_commit does not match the tree"
[[ "$(field provenance.image_digest)" == sha256:* ]] && ok "image_digest is a sha256" \
  || bad "image_digest is not pinned"
"$PY" -c "import json,sys; json.load(open(sys.argv[1]))" "$R" 2>/dev/null \
  && ok "report.json is valid JSON" || bad "report.json is not valid JSON"

# The v2 sections, and the planted values the stand-in's PLAN says they must show. Only values
# that do not depend on the floor are compared: the run uses the real floor of 50, the plan's
# released lists assume the test floor. Prints the names of failed checks, never a value.
PLANNED="$("$PY" - "$R" 2>&1 <<'PY'
import json, sys
sys.path.insert(0, ".")
from tests.insight_standin import PLAN
from insight import cube
r = json.load(open(sys.argv[1]))
sections = ("formats", "timeline", "lifecycle", "dimensions", "concentration", "vocabulary",
            "readiness", "quality")
missing = [s for s in sections if s not in r]
if missing:
    print("missing sections:", " ".join(missing))
    sys.exit(1)
rows = PLAN["rows"]
checks = {
    "baugruppe coverage": r["origin"]["baugruppe"]["coverage"]["share"]
    == round(PLAN["baugruppe_present"] / rows, 4),
    "baugruppe empty": r["origin"]["baugruppe"]["empty"]["present"] == PLAN["baugruppe_empty"],
    "fehlercode coverage": r["formats"]["fehlercode"]["coverage"]["present"]
    == PLAN["fehlercode_present"],
    "serial distinct": r["formats"]["vehicleSerialNo"]["distinct"] == PLAN["serials_distinct"],
    "delivery coverage": r["lifecycle"]["days_since_delivery"]["coverage"]["present"]
    == PLAN["delivery_present"],
    "concentration distinct": all(
        r["concentration"][c]["distinct"] == len(n) for c, n in PLAN["identity"].items()
    ),
    "readiness total": r["readiness"]["total"] == rows,
    "usable tickets > 0": r["readiness"]["usable"]["tickets"] > 0,
    "quality total": r["quality"]["overall"]["count"] == rows,
    "quality noise reasons add up": sum(r["quality"]["overall"]["noise_reasons"].values())
    == r["quality"]["overall"]["noise"],
    "quality catches the handover form": r["quality"]["overall"]["noise_reasons"]["templated"]
    >= PLAN["templated_rows"],
    "quality ladder falls": [x["tickets"] for x in r["quality"]["overall"]["retrievable"]]
    == sorted((x["tickets"] for x in r["quality"]["overall"]["retrievable"]), reverse=True),
    "retrievable tickets > 0": r["quality"]["overall"]["retrievable"][0]["tickets"] > 0,
    "cube has every cut": [c["axes"] for c in r["quality"]["cube"]["cuts"]]
    == list(cube.CUT_NAMES),
    "cube cells floored": all(
        cell["count"] >= 50 for c in r["quality"]["cube"]["cuts"] for cell in c["cells"]
    ),
    "cube measured": r["quality"]["cube"]["measurement"]["checked"]
    == r["quality"]["cube"]["measurement"]["withheld_cells"],
}
failed = [name for name, passed in checks.items() if not passed]
print("failed:", ", ".join(failed) if failed else "none")
sys.exit(1 if failed else 0)
PY
)"; PRC=$?
if (( PRC == 0 )); then
  ok "all seven v2 sections and the quality section present; baugruppe coverage, empty lists,"
  note "fehlercode, serials, delivery dates, concentration, readiness, quality and the cube match"
else
  bad "v2 sections or planted values wrong: $PLANNED"
fi

# ------------------------------------------------- safety properties
head2 "Safety properties (what makes the artifact readable by an AI at all)"
# Every planted string the stand-in knows (leaks, contact data, every serial and every id of a
# vehicle, a ticket, a person or an organisation), plus RAW PHRASES longer than a trigram: words,
# word pairs and triples that clear the floor ARE released on purpose, so 'Hydraulikpumpe' is not
# a leak, but a longer phrase is a sentence the report has no way to carry. Case-folded, and only
# the NUMBER of matches is printed: a failure message is output too.
# An all-digit id matches only between non-digits, and the digests and the commit are blanked
# first: the guard pins them to hex, and a hex digest or a byte count can spell a five-digit
# ticket number by chance, which would make this check fail on one image build in twenty.
leaks() {  # leaks <file> -> prints the number of planted strings found in it
  "$PY" - "$1" 2>&1 <<'PY'
import json, re, sys
sys.path.insert(0, ".")
from tests.insight_standin import all_planted_strings
phrases = {"baut keinen druck auf", "druck geprueft pumpe getauscht", "rueckruf"}
text = open(sys.argv[1], encoding="utf-8").read()
try:
    r = json.loads(text)
    r["source"]["sha256"] = ""
    r["provenance"]["code_commit"] = r["provenance"]["image_digest"] = ""
    text = json.dumps(r, ensure_ascii=False)
except (ValueError, KeyError, TypeError):
    pass  # not the report: stdout
text = text.casefold()
def found(s):
    if s.isdigit():
        return re.search(f"(?<![0-9]){s}(?![0-9])", text) is not None
    return s.casefold() in text
print(sum(1 for s in all_planted_strings() | phrases if found(s)))
PY
}
N="$(leaks "$R")"
[[ "$N" == "0" ]] && ok "no planted string or raw ticket phrase appears in report.json" \
  || bad "report.json carries planted strings: $N match(es)"
printf '%s' "$OUT" > "$WORK/stdout.txt"
N="$(leaks "$WORK/stdout.txt")"; rm -f "$WORK/stdout.txt"
[[ "$N" == "0" ]] && ok "no planted string on stdout" \
  || bad "stdout carries planted strings: $N match(es)"

# ------------------------------------------------- failure paths
head2 "Failure paths - what happens when a sealed run goes wrong"
cp "$WORK/q/export.csv" "$WORK/fp/export.csv"
FP="-v $WORK/fp:/fp -e RECALL_PROFILER_DETAIL_LOG=/fp/detail.log"
# shellcheck disable=SC2086
fp() { sealed $FP -- python -m insight "$@" 2>&1; }

FSHA="$(sha256sum "$WORK/fp/export.csv" | cut -d' ' -f1)"
FOUT="$(fp --csv /fp/export.csv --out /fp/export.csv)"; FRC=$?
(( FRC == 4 )) && ok "--out equal to the input exits 4" || bad "--out == input exited $FRC (expected 4)"
[[ "$(sha256sum "$WORK/fp/export.csv" | cut -d' ' -f1)" == "$FSHA" ]] \
  && ok "the input is byte-for-byte unchanged" || bad "THE INPUT WAS OVERWRITTEN"

printf '{"selfcheck": {"passed": true}}' > "$WORK/fp/report.json"
FOUT="$(fp --csv /fp/export.csv --out /fp/report.json --code-commit not-a-commit)"; FRC=$?
(( FRC == 4 )) && ok "a bad --code-commit exits 4" || bad "bad commit exited $FRC (expected 4)"
[[ ! -e "$WORK/fp/report.json" ]] && ok "a failed run leaves no stale report claiming it passed" \
  || bad "a STALE report survived a failed run"

sed 's/,/;/g' "$WORK/fp/export.csv" > "$WORK/fp/semi.csv"
FOUT="$(fp --csv /fp/semi.csv --out /fp/r2.json)"; FRC=$?
(( FRC == 4 )) && grep -q 'WRONG_INPUT' <<<"$FOUT" \
  && ok "a wrong-delimiter file is refused (WRONG_INPUT), not reported as an empty success" \
  || bad "a wrong-schema file was not refused (exit $FRC)"

printf 'id,title\n' > "$WORK/fp/header.csv"
FOUT="$(fp --csv /fp/header.csv --out /fp/r3.json)"
grep -q 'EMPTY_INPUT' <<<"$FOUT" && ok "a zero-row export is refused" || bad "zero rows was not refused"

FOUT="$(fp --csv /fp/nonexistent-client-name --out /fp/r4.json)"; FRC=$?
(( FRC == 4 )) && grep -q 'MISSING_INPUT' <<<"$FOUT" && ! grep -q 'nonexistent-client-name' <<<"$FOUT" \
  && ok "a missing input is refused without echoing its path" || bad "missing input handled wrongly"

# The cell limit was raised to 16 MiB so one pasted mail thread cannot abort a window. A 300 KB cell
# is therefore READ (and then refused for missing columns, exit 4), not a crash.
"$PY" -c "
import sys
sys.stdout.write('title,description\nx,' + 'y' * 300000 + '\n')" > "$WORK/fp/long.csv"
FOUT="$(fp --csv /fp/long.csv --out /fp/r5a.json)"; FRC=$?
(( FRC == 4 )) && ok "a 300 KB cell is read, not a crash" || bad "a 300 KB cell exited $FRC (expected 4)"

# A cell ABOVE the limit is a genuine unexpected failure: exit 3, only the exception type printed.
"$PY" -c "
import sys
sys.stdout.write('title,description\nx,' + 'y' * 17_000_000 + '\n')" > "$WORK/fp/huge.csv"
FOUT="$(fp --csv /fp/huge.csv --out /fp/r5.json)"; FRC=$?
(( FRC == 3 )) && ok "an unreadable file exits 3" || bad "unreadable file exited $FRC (expected 3)"
grep -q 'Traceback' <<<"$FOUT" && bad "a TRACEBACK leaked - may carry corpus bytes" \
                               || ok "no traceback on stdout, only the exception type"
[[ -s "$WORK/fp/detail.log" ]] \
  && ok "detail log reached the mounted volume (retrievable after --rm)" \
  || bad "detail log did NOT reach the volume - a failed window would have no diagnostic"

# ------------------------------------------------- teardown
head2 "Teardown - after the shred list runs, only the artifact may remain"
SHRED="$(./infra/profiler/window.sh --window d clean --dry-run 2>/dev/null \
  | sed -r 's/\x1b\[[0-9;]*m//g' | sed -n 's|^    .*/\([^/]*\)$|\1|p')"
if [[ -z "$SHRED" ]]; then
  bad "could not read window d's shred list out of window.sh --dry-run"
else
  ok "shred list read back out of window.sh: $(tr '\n' ' ' <<<"$SHRED")"
  for f in $SHRED; do rm -f "$WORK/q/$f"; done
  REMAIN="$(ls -A "$WORK/q" | tr '\n' ' ')"
  [[ "$REMAIN" == "report.json " ]] && ok "only report.json remains after the shred list" \
    || bad "after shredding, quarantine still holds: $REMAIN"
fi

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
  Window D is ready to run for real. The remaining steps are yours and are deliberately
  AI-free - see "Window D" in docs/airlock-runbook.md:

    1. Resolve ~/work/<export-dir>/ first. A real client export must not stay on this
       workstation. Move it to the box or shred it.
    2. infra/profiler/window.sh ship     (about an hour: the image is 9.3 GB and CHANGED)
    3. infra/profiler/window.sh --window d --csv <the export> push
       infra/profiler/window.sh --window d run
       infra/profiler/window.sh --window d verify
       (not `all`: it ships the image a second time)
    4. Read report.json ON THE BOX, in full, before anything crosses.
    5. infra/profiler/window.sh --window d fetch --clean
    6. make check-clean on the workstation, unsandboxed.
EOF
  exit 0
else
  echo "  Do NOT open a window until these are fixed - each failure here is a"
  echo "  failure you would otherwise hit with no AI available to diagnose it."
  exit 1
fi
