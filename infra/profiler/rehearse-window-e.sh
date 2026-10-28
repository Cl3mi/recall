#!/usr/bin/env bash
# Window E dress rehearsal - SYNTHETIC DATA ONLY.
#
# Drives the REAL infra/profiler/window.sh --window e (run, verify, leakcheck, release, fetch,
# clean) end to end, so the actual script's control flow is what gets exercised: the teardown trap,
# the readiness poll, the order of the steps, the explicit teardown, the fetch allowlist and the
# shred list. Nothing in window.sh is re-implemented here. What makes that possible on a
# workstation is a set of PATH shims in a scratch directory:
#
#   podman  forwards to docker, and rewrites ONLY what a workstation cannot do (listed below)
#   ssh     runs the "remote" command locally, with the same shims on PATH
#   scp     copies locally ("host:/path" means "/path")
#   gpu-fairuse2.sh  a stub in the scratch copy of the tree that "claims" a made-up GPU
#
# The shim also RECORDS evidence for the assertions: for every container it starts, the
# `docker inspect` JSON and the arguments window.sh passed; for every network, its inspect JSON.
#
#   ./infra/profiler/rehearse-window-e.sh          # full rehearsal, rebuilds the image
#   ./infra/profiler/rehearse-window-e.sh --quick  # skip the rebuild (the stale-image guard
#                                                  # below still refuses a stale image)
#
# Set RECALL_REHEARSAL_PYTHON to a Python that has this project's dependencies installed (the
# repo's .venv). `docker` rather than `podman`: podman is the box's runtime, docker is the
# workstation's (see rehearse-window-b.sh).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

WORK="${TMPDIR:-/tmp}/recall-window-e-rehearsal"
IMAGE=recall/profiler:pinned
STANDIN_IMAGE=recall/profiler:llm-standin
MODEL="Qwen/Qwen2.5-32B-Instruct-AWQ"
QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

PY="${RECALL_REHEARSAL_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY="$REPO/.venv/bin/python"; else PY=python3; fi
fi
RUFF="$(dirname "$PY")/ruff"
[[ -x "$RUFF" ]] || RUFF=ruff

# ---------------------------------------------------------------- substitutions
# The ONLY differences between this rehearsal and the real window. Everything else (flags,
# --network shapes, --ulimit, --log-driver, the trap, the allowlist) is window.sh's own.
SUBSTITUTIONS=(
  "build runs --embedder hashing instead of e5 (no weights, no GPU needed)"
  "window.sh is run with RECALL_WINDOW_CLUSTERS=3 instead of its default 300 (the stand-in corpus has 3 problems); the command itself is not rewritten"
  "build runs --workers 2 instead of 8"
  "the LLM container runs catalog.stubserver (the fake drafter) instead of vLLM; the image is this one, tagged as the stand-in"
  "no GPU: --device and --ipc=host are dropped, the read-only weights mount is dropped"
  "foreground containers run without --rm and are removed by the shim after docker inspect"
  "every container runs as this user's uid, so the scratch quarantine stays removable"
  "ssh and scp run locally; gpu-fairuse2.sh is a stub that claims a made-up GPU id"
  "the stand-in corpus: 3 problems x 60 tickets, 8 vehicles, 8 dealers (the real floors 50 / 5 / 5 apply)"
)

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1" | tee -a "$WORK/transcript" ; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1" | tee -a "$WORK/transcript" ; fail=$((fail+1)); }
note() { printf '        %s\n' "$1" | tee -a "$WORK/transcript" ; }
head2(){ printf '\n\033[1m%s\033[0m\n' "$1" | tee -a "$WORK/transcript" ; }

# Refuse to operate anywhere but our own scratch directory: this script removes files.
case "$WORK" in
  "${TMPDIR:-/tmp}"/recall-window-e-rehearsal) : ;;
  *) printf 'ABORT scratch dir %s is outside %s - refusing\n' "$WORK" "${TMPDIR:-/tmp}" >&2
     exit 1 ;;
esac

cleanup() {
  # Belt and braces: window.sh's own trap should have removed these already; if it did not,
  # the assertions below have said so, and this keeps the workstation tidy.
  docker ps -aq --filter name=recall-e- 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1
  docker ps -aq --filter name=rh- 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1
  docker network ls -q --filter name=recall-e- 2>/dev/null | xargs -r docker network rm >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT
rm -rf "$WORK"
mkdir -p "$WORK/q" "$WORK/hf" "$WORK/bin" "$WORK/log" "$WORK/tree/infra/profiler" \
  "$WORK/tree/infra/fairuse"
: > "$WORK/transcript"

printf '\n\033[1mWindow E rehearsal - what differs from the real window\033[0m\n' | tee -a "$WORK/transcript"
for s in "${SUBSTITUTIONS[@]}"; do note "- $s"; done

# ---------------------------------------------------------------- Phase 0
head2 "Phase 0 - preparation (network allowed, no real data present)"

TEST_OUT="$("$PY" -m pytest tests/unit/test_window_e_contract.py tests/unit/test_window_d_contract.py \
  -p no:cacheprovider 2>&1)"
if grep -qE '^[0-9]+ passed' <<<"$TEST_OUT" && ! grep -qE ' failed| error' <<<"$TEST_OUT"; then
  ok "window-e and window-d contract tests ($(grep -oE '^[0-9]+ passed' <<<"$TEST_OUT"))"
else
  bad "window contract tests - fix before any window"
  note "$(tail -3 <<<"$TEST_OUT" | tr '\n' ' ')"
fi
if bash -n infra/profiler/window.sh && bash -n "${BASH_SOURCE[0]}"; then
  ok "window.sh and this script parse"; else bad "a shell script does not parse"; fi
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S warning infra/profiler/rehearse-window-e.sh >/dev/null 2>&1 \
    && ok "shellcheck" || bad "shellcheck"
else
  note "shellcheck not installed; skipped"
fi

if (( QUICK )); then
  note "skipping image build (--quick)"
else
  if docker build -q -f infra/profiler/Dockerfile -t "$IMAGE" . >/dev/null 2>&1; then
    ok "sealed image builds"
  else
    bad "sealed image build FAILED - stop here"; printf '\n%d passed, %d failed\n' "$pass" "$fail"; exit 1
  fi
fi

sealed() { docker run --rm --network=none "$IMAGE" "$@"; }
if sealed python -c "import catalog.__main__, catalog.stubserver, fixtures.llm" >/dev/null 2>&1; then
  ok "image imports the catalog CLI, the stub server and the LLM client with --network=none"
else
  bad "the image lacks catalog/ or fixtures/ - rebuild from this branch (no --quick)"
fi

# Does the image carry the working tree's code? LC_ALL=C on BOTH sides is load-bearing (see
# rehearse-window-d.sh): under a UTF-8 locale identical content hashes differently.
HOST_SRC="$(find catalog fixtures insight profiler -name '*.py' -type f | LC_ALL=C sort \
  | xargs sha256sum | sha256sum | cut -c1-16)"
IMG_SRC="$(sealed sh -c \
  "find catalog fixtures insight profiler -name '*.py' -type f | LC_ALL=C sort | xargs sha256sum | sha256sum" \
  2>/dev/null | cut -c1-16)"
if [[ "$HOST_SRC" == "$IMG_SRC" && -n "$IMG_SRC" ]]; then
  ok "image carries the working tree's catalog/, fixtures/, insight/ and profiler/ ($IMG_SRC)"
else
  bad "STALE IMAGE: the image ($IMG_SRC) != working tree ($HOST_SRC)"
  note "rebuild without --quick, or every assertion below is about the wrong code"
  printf '\n%d passed, %d failed\n' "$pass" "$fail"; exit 1
fi
docker tag "$IMAGE" "$STANDIN_IMAGE" && ok "image tagged as the stand-in LLM image" \
  || bad "could not tag the stand-in LLM image"

# ---------------------------------------------------------------- stand-in
head2 "Stand-in export (invented tickets from tests/catalog_corpus.py)"
if "$PY" - "$WORK/q/export.csv" >/dev/null 2>&1 <<'PY'
import csv
import pathlib
import sys

sys.path.insert(0, ".")
from profiler.columns import EXPECTED_COLUMNS
from tests import catalog_corpus

rows = catalog_corpus.rows(per_problem=60, problems=3, vehicles=8, dealers=8)
with pathlib.Path(sys.argv[1]).open("w", newline="", encoding="utf-8") as handle:  # guard: ok(invented corpus)
    writer = csv.DictWriter(handle, fieldnames=list(EXPECTED_COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
PY
then ok "stand-in built (180 tickets, 3 problems, 8 vehicles, 8 dealers)"
else bad "stand-in build failed"; fi

# Words from the stand-in corpus that must never appear in anything this rehearsal prints.
"$PY" - >"$WORK/corpus_words" 2>/dev/null <<'PY'
import sys

sys.path.insert(0, ".")
from tests import catalog_corpus

words = set()
for problem in catalog_corpus.PROBLEMS[:3]:
    words.update(w for text in problem for w in text.split() if len(w) >= 6)
words.update(catalog_corpus.FILLERS)
words.add("Z90000000")
print("\n".join(sorted(words)))
PY
[[ -s "$WORK/corpus_words" ]] && note "$(wc -l < "$WORK/corpus_words") corpus words kept aside for the output check" \
  || bad "could not list the corpus words"

# ---------------------------------------------------------------- the scratch tree and shims
head2 "Scratch tree: the real window.sh, byte for byte, plus shims on PATH"
cp infra/profiler/window.sh "$WORK/tree/infra/profiler/window.sh"
cmp -s infra/profiler/window.sh "$WORK/tree/infra/profiler/window.sh" \
  && ok "window.sh copied unchanged into the scratch tree (it resolves local/artifacts and infra/fairuse there)" \
  || bad "window.sh copy differs"

cat > "$WORK/tree/infra/fairuse/gpu-fairuse2.sh" <<'STUB'
#!/usr/bin/env bash
# Rehearsal stub: the real script asks the shared box over ssh. Same output contract.
case "${1:-check}" in
  claim) printf 'export GPU=%q\n' "nvidia.com/gpu=GPU-REHEARSAL-0" ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$WORK/tree/infra/fairuse/gpu-fairuse2.sh"

cat > "$WORK/bin/ssh" <<'SHIM'
#!/usr/bin/env bash
# window.sh calls: ssh "$HOST" "<command>". Run the command here, with these shims on PATH.
shift
exec bash -c "$1"
SHIM

cat > "$WORK/bin/scp" <<'SHIM'
#!/usr/bin/env bash
# window.sh calls: scp -q host:/path dest  or  scp -q file host:/path
args=()
for a in "$@"; do
  [[ "$a" == -q ]] && continue
  [[ "$a" =~ ^[^/:]+:/ ]] && a="${a#*:}"
  args+=("$a")
done
exec cp -- "${args[@]}"
SHIM

cat > "$WORK/bin/podman" <<'SHIM'
#!/usr/bin/env bash
# Forwards podman to docker. Rewrites only what a workstation cannot do (see the rehearsal's
# header) and records evidence: the original arguments, `docker inspect` of every container and of
# every network, and - once per network, right after the readiness poll succeeds - a probe from a
# throwaway container on the same internal network.
set -u
LOG="${RH_LOG:?}"
case "${1:-}" in
  network)
    if [[ "${2:-}" == create ]]; then
      docker "$@"; rc=$?
      if (( rc == 0 )); then
        name="${!#}"
        printf '%s\n' "$*" > "$LOG/network-$name.args"
        docker network inspect "$name" > "$LOG/network-$name.json" 2>/dev/null
      fi
      exit "$rc"
    fi
    exec docker "$@" ;;
  image)
    if [[ "${2:-}" == exists ]]; then docker image inspect "${3:?}" >/dev/null 2>&1; exit $?; fi
    exec docker "$@" ;;
  run) shift ;;
  *) exec docker "$@" ;;
esac

orig=("$@")
opts=(); detached=0; name=""; image=""; rest=(); net=""
while (( $# )); do
  case "$1" in
    -d) detached=1; opts+=("$1"); shift ;;
    --rm) shift ;;                      # re-added for detached runs below
    --ipc=host) shift ;;                # no GPU here
    --device) shift 2 ;;
    --device=*) shift ;;
    -v)
      case "$2" in
        *:/root/.cache/huggingface:*) ;;   # the read-only weights: nothing to mount here
        *) opts+=(-v "$2") ;;
      esac
      shift 2 ;;
    --name) name="$2"; opts+=(--name "$2"); shift 2 ;;
    --network) net="$2"; opts+=(--network "$2"); shift 2 ;;
    --network-alias|--cpus|-e|--ulimit|--log-driver|--user) opts+=("$1" "$2"); shift 2 ;;
    -*) opts+=("$1"); shift ;;
    *) image="$1"; shift; rest=("$@"); break ;;
  esac
done
[[ -n "$name" ]] || { name="rh-$$-$RANDOM"; opts+=(--name "$name"); }
printf '%s\n' "${orig[@]}" > "$LOG/args-$name.txt"

if [[ "$image" == "$RH_STANDIN" ]]; then
  rest=(python -m catalog.stubserver --host 0.0.0.0 --port 8000 --model "$RH_MODEL")
fi
fixed=()
i=0
while (( i < ${#rest[@]} )); do
  case "${rest[i]}:${rest[i+1]:-}" in
    --embedder:e5) fixed+=(--embedder hashing); i=$((i+2)) ;;
    --workers:8) fixed+=(--workers 2); i=$((i+2)) ;;
    *) fixed+=("${rest[i]}"); i=$((i+1)) ;;
  esac
done

if (( detached )); then
  docker run --rm --user "$RH_UID" "${opts[@]}" "$image" "${fixed[@]}"; rc=$?
  (( rc == 0 )) && docker inspect "$name" > "$LOG/container-$name.json" 2>/dev/null
  exit "$rc"
fi

docker run --user "$RH_UID" "${opts[@]}" "$image" "${fixed[@]}"; rc=$?
docker inspect "$name" > "$LOG/container-$name.json" 2>/dev/null
docker rm -f "$name" >/dev/null 2>&1

# The readiness poll answered: probe from a second throwaway container on the same network while it
# exists, once per network. Plus a control on the default bridge, to tell "blocked by the internal
# network" from "this workstation is offline".
if (( rc == 0 )) && [[ "${fixed[*]}" == *"/v1/models"* && -n "$net" && ! -e "$LOG/probe-$net.txt" ]]; then
  read -r -d '' PROBE <<'PY'
import socket
import sys
import urllib.request


def tcp(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close()
        return True
    except OSError:
        return False


if sys.argv[1] == "internal":
    try:
        socket.gethostbyname("llm")
        print("resolve_llm=ok")
    except OSError:
        print("resolve_llm=FAIL")
    try:
        urllib.request.urlopen("http://llm:8000/v1/models", timeout=3).read()
        print("stub_http=ok")
    except Exception:
        print("stub_http=FAIL")
    try:
        socket.gethostbyname("example.com")
        print("egress_dns=OPEN")
    except OSError:
        print("egress_dns=blocked")
print("egress_ip=" + ("OPEN" if tcp("1.1.1.1", 443) or tcp("8.8.8.8", 53) else "blocked"))
PY
  docker run --rm --user "$RH_UID" --network "$net" "$image" python -c "$PROBE" internal \
    > "$LOG/probe-$net.txt" 2>&1
  docker run --rm --user "$RH_UID" "$image" python -c "$PROBE" control \
    > "$LOG/control-$net.txt" 2>&1
fi
exit "$rc"
SHIM
chmod +x "$WORK/bin/ssh" "$WORK/bin/scp" "$WORK/bin/podman"
ok "shims written: podman (-> docker), ssh and scp (-> local)"

export PATH="$WORK/bin:$PATH"
export RH_LOG="$WORK/log" RH_STANDIN="$STANDIN_IMAGE" RH_MODEL="$MODEL" RH_UID="$(id -u):$(id -g)"
export RECALL_WINDOW_HOST=rehearsal-box
export RECALL_WINDOW_QUARANTINE="$WORK/q"
export RECALL_WINDOW_IMAGE="$IMAGE"
export RECALL_WINDOW_LLM_IMAGE="$STANDIN_IMAGE"
export RECALL_WINDOW_HF_CACHE="$WORK/hf"
export RECALL_WINDOW_CLUSTERS=3

GIT_BEFORE="$(git status --porcelain)"

# wl <args>: run the real window.sh (window e) from the scratch tree. Sets OUT and RC, prints the
# output indented - it is the same text the operator sees, and it never carries a row value.
OUT=""; RC=0
wl() {
  ( cd "$WORK/tree" && bash infra/profiler/window.sh --window e "$@" ) > "$WORK/out.raw" 2>&1
  RC=$?
  OUT="$(sed -r 's/\x1b\[[0-9;]*m//g' "$WORK/out.raw")"
  printf '%s\n' "$OUT" | sed 's/^/        | /' | tee -a "$WORK/transcript"
}

QDIR="$WORK/q"
# .sealed is the marker recall.sealed puts in a sealed root (it holds one fixed line of text and is
# meant to stay): not a leftover.
ls_q() { ls -A "$QDIR" | grep -vx '.sealed' | LC_ALL=C sort | tr '\n' ' '; }
leftovers() {  # containers and networks the window should have removed
  { docker ps -a --filter name=recall-e- --format 'container:{{.Names}}'
    docker network ls --filter name=recall-e- --format 'network:{{.Name}}'; } 2>/dev/null
}

# ---------------------------------------------------------------- the run
head2 "window.sh --window e run  (real script: claim, internal network, LLM, readiness, build, teardown, leakcheck)"
wl run
(( RC == 0 )) && ok "run exits 0" || bad "run exited $RC (expected 0)"
[[ -s "$QDIR/catalog.draft.json" ]] && ok "catalog.draft.json exists after the run" \
  || bad "no draft after the run"
[[ -s "$QDIR/catalog.leak_report.json" ]] && ok "catalog.leak_report.json exists after the run" \
  || bad "no leak report after the run"
grep -qE 'wrote draft: tickets=180 recipes=[1-9]' <<<"$OUT" \
  && ok "build produced recipes from the 180 tickets" || bad "build produced 0 recipes (or did not run)"
grep -q 'leakcheck tickets=180 .* passed=True' <<<"$OUT" && ok "leakcheck passed at the real floors" \
  || bad "leakcheck did not pass"

# (f, first half) after a successful run nothing may be left behind
L="$(leftovers)"
[[ -z "$L" ]] && ok "teardown: no LLM container and no network left after the run" \
  || bad "teardown left behind: $(tr '\n' ' ' <<<"$L")"

head2 "Evidence recorded by the shim"
EVID="$("$PY" - "$WORK/log" "$WORK/q" "$MODEL" <<'PY'
import glob
import json
import os
import sys

log, quarantine, model = sys.argv[1:4]


def load(path):
    with open(path, encoding="utf-8") as handle:  # guard: ok(rehearsal evidence, no rows)
        return json.load(handle)


def report(key, passed, detail):
    print(f"{key} {'PASS' if passed else 'FAIL'} {detail}")


nets = sorted(glob.glob(f"{log}/network-recall-e-*.json"))
internal = [load(p)[0].get("Internal") for p in nets]
report("a", bool(nets) and all(internal), f"{len(nets)} network(s) created, Internal={internal}")

boxes = {p: load(p)[0] for p in sorted(glob.glob(f"{log}/container-*.json"))}
published = []
for path, box in boxes.items():
    bound = {k: v for k, v in (box["HostConfig"].get("PortBindings") or {}).items() if v}
    shown = {k: v for k, v in (box["NetworkSettings"].get("Ports") or {}).items() if v}
    if bound or shown or box["HostConfig"].get("PublishAllPorts"):
        published.append(os.path.basename(path))
report("b", len(boxes) >= 4 and not published,
       f"{len(boxes)} container(s) inspected, published ports on: {published or 'none'}")

llm_path = next((p for p in boxes if "container-recall-e-llm-" in p), None)
if llm_path is None:
    report("c", False, "no LLM container was recorded")
else:
    llm = boxes[llm_path]
    sources = [m.get("Source", "") for m in llm.get("Mounts", [])]
    dests = [m.get("Destination", "") for m in llm.get("Mounts", [])]
    original = open(llm_path.replace("container-", "args-").replace(".json", ".txt"),  # guard: ok(rehearsal evidence, no rows)
                    encoding="utf-8").read()
    weights_ro = any(
        line.endswith(":/root/.cache/huggingface:ro") for line in original.splitlines()
    )
    no_q = not any(s.startswith(quarantine) for s in sources) and "/q" not in dests
    no_q_orig = ":/q" not in original and "quarantine" not in original.lower()
    logdrv = llm["HostConfig"]["LogConfig"]["Type"]
    alias = any("llm" in (n.get("Aliases") or []) for n in llm["NetworkSettings"]["Networks"].values())
    report("c", no_q and no_q_orig and logdrv == "none",
           f"mounts={len(sources)} none-of-quarantine={no_q} args-have-no-/q={no_q_orig} log driver={logdrv}")
    report("c2", weights_ro and "--log-driver=none" in original and "--no-enable-log-requests" in original,
           "window.sh's own arguments: weights mount is :ro, log-driver none, request logging off")
    report("c3", alias, "the LLM container is reachable as 'llm' on the internal network")

builds = [b for b in boxes.values() if "catalog" in (b["Config"]["Cmd"] or [])
          and "build" in (b["Config"]["Cmd"] or [])]
orig_build = [open(p.replace("container-", "args-").replace(".json", ".txt"), encoding="utf-8").read()  # guard: ok(rehearsal evidence, no rows)
              for p in boxes if "build" in (boxes[p]["Config"]["Cmd"] or [])]
real_flags = bool(orig_build) and all(
    f in orig_build[0] for f in ("--embedder\ne5", "--workers\n8", "--clusters\n3", "--llm\nvllm",
                                 "--network\nrecall-e-", "--ulimit\ncore=0"))
report("k", bool(builds) and real_flags and any(m.get("Destination") == "/q" for b in builds for m in b["Mounts"]),
       "the build container mounts the quarantine, and window.sh passed e5 / 8 workers / RECALL_WINDOW_CLUSTERS (3) clusters")

leak = [b for b in boxes.values() if "leakcheck" in (b["Config"]["Cmd"] or [])]
report("l", bool(leak) and all(b["HostConfig"]["NetworkMode"] == "none" for b in leak),
       "the leakcheck container has NetworkMode none")

probes = sorted(glob.glob(f"{log}/probe-recall-e-*.txt"))
if not probes:
    report("d", False, "the probe never ran (readiness did not succeed?)")
else:
    values = dict(line.split("=", 1) for line in open(probes[0], encoding="utf-8").read().split()  # guard: ok(rehearsal evidence, no rows)
                  if "=" in line)
    good = (values.get("resolve_llm") == "ok" and values.get("stub_http") == "ok"
            and values.get("egress_ip") == "blocked")
    report("d", good, f"from the internal network: {values}")
    control = glob.glob(f"{log}/control-recall-e-*.txt")
    if control:
        text = open(control[0], encoding="utf-8").read().strip()  # guard: ok(rehearsal evidence, no rows)
        print(f"n control (default bridge): {text}")
PY
)"
while IFS= read -r line; do
  key="${line%% *}"; rest="${line#* }"
  case "$rest" in
    PASS\ *) case "$key" in
        a) ok "(a) the created network is Internal: ${rest#PASS }" ;;
        b) ok "(b) no container has a published port: ${rest#PASS }" ;;
        c) ok "(c) the LLM container has no quarantine mount and log driver none: ${rest#PASS }" ;;
        d) ok "(d) from the internal network: llm resolves, the stub answers, a public IP is unreachable: ${rest#PASS }" ;;
        *) ok "($key) ${rest#PASS }" ;;
      esac ;;
    FAIL\ *) bad "($key) ${rest#FAIL }" ;;
    *) note "$line" ;;
  esac
done <<<"$EVID"
if [[ "$EVID" == *"egress_dns=OPEN"* ]]; then
  note "egress_dns=OPEN: names resolve through docker's embedded DNS on this engine; no connection leaves, but note it"
fi
if grep -q 'control (default bridge): egress_ip=blocked' <<<"$EVID"; then
  note "the control on the default bridge ALSO could not reach a public IP: this workstation may be offline, so (d)'s egress result rests on the Internal flag in (a)"
fi

# ---------------------------------------------------------------- verify / human gate / release
head2 "window.sh verify  (counts and verdicts only)"
wl verify
(( RC == 0 )) && ok "verify exits 0" || bad "verify exited $RC"
grep -q 'report passed        : True' <<<"$OUT" && ok "verify: report passed : True" || bad "verify: report did not pass"
grep -q 'report matches draft : True' <<<"$OUT" && ok "verify: report matches draft : True" \
  || bad "verify: report does not match the draft"

head2 "An edit after leakcheck invalidates the report - release must refuse"
cp "$QDIR/catalog.draft.json" "$WORK/draft.orig"
"$PY" - "$QDIR/catalog.draft.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
draft = json.loads(path.read_text(encoding="utf-8"))
draft["recipes"].reverse()  # a hand edit that adds no new words, so leakcheck still passes
path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")  # guard: ok(invented draft)
PY
wl release
(( RC != 0 )) && ok "(g) release exits non-zero for an edited draft" || bad "(g) release EXITED 0 for an edited draft"
[[ ! -e "$QDIR/catalog.json" ]] && ok "(g) no catalog.json was written" || bad "(g) catalog.json WAS written for an edited draft"
grep -q 'REFUSED' <<<"$OUT" && ok "(g) release printed REFUSED with a reason code" || bad "(g) no REFUSED line"
wl verify
grep -q 'report matches draft : False' <<<"$OUT" && ok "verify shows 'report matches draft : False' after the edit" \
  || bad "verify did not flag the edited draft"

head2 "leakcheck again on the edited draft, then the whole sequence: release -> fetch --clean"
wl leakcheck
(( RC == 0 )) && ok "leakcheck exits 0 on the edited draft" || bad "leakcheck exited $RC on the edited draft"
wl verify
grep -q 'report matches draft : True' <<<"$OUT" && ok "after leakcheck the report matches the edited draft again" \
  || bad "report still does not match after leakcheck"
wl release
R_RELEASE=$RC
[[ -s "$QDIR/catalog.json" ]] || R_RELEASE=99
wl fetch --clean --yes
R_FETCH=$RC
(( R_RELEASE == 0 && R_FETCH == 0 )) \
  && ok "(e) run -> verify -> release -> fetch --clean: every step exits 0 and catalog.json was written" \
  || bad "(e) release exit $R_RELEASE, fetch exit $R_FETCH"

# (h) fetch copies exactly the allowlist
GOT="$(ls -A "$WORK/tree/local/artifacts" 2>/dev/null | LC_ALL=C sort | tr '\n' ' ')"
[[ "$GOT" == "catalog.json catalog.leak_report.json " ]] \
  && ok "(h) fetch copied exactly catalog.json and catalog.leak_report.json" \
  || bad "(h) artifacts directory holds: $GOT"
# (i) clean leaves only those two files
REMAIN="$(ls_q)"
[[ "$REMAIN" == "catalog.json catalog.leak_report.json " ]] \
  && ok "(i) after fetch --clean quarantine holds only catalog.json and catalog.leak_report.json" \
  || bad "(i) quarantine still holds: $REMAIN"
"$PY" -c "
import json, sys
d = json.load(open(sys.argv[1])); r = json.load(open(sys.argv[2]))
sys.exit(0 if d.get('recipes') and r.get('passed') is True else 1)" \
  "$WORK/tree/local/artifacts/catalog.json" "$WORK/tree/local/artifacts/catalog.leak_report.json" 2>/dev/null \
  && ok "the fetched catalog has recipes and the fetched report says passed" \
  || bad "the fetched files are not a catalog with a passing report"

# ---------------------------------------------------------------- failure path
head2 "A failing run: the export is missing, so build fails after the LLM is up"
printf '{"stale": true}' > "$QDIR/catalog.draft.json"
printf '{"stale": true}' > "$QDIR/catalog.leak_report.json"
rm -f "$QDIR/catalog.json" "$QDIR/export.csv"
wl run
(( RC != 0 )) && ok "(f) the failing run exits non-zero" || bad "(f) the failing run exited 0"
grep -q 'MISSING_INPUT' <<<"$OUT" && ok "(f) the failure is the build's MISSING_INPUT code (the LLM was up and was used to fail)" \
  || bad "(f) the failure is not the expected build failure"
L="$(leftovers)"
[[ -z "$L" ]] && ok "(f) teardown ran on the failure path: no LLM container and no network left" \
  || bad "(f) a FAILED run left behind: $(tr '\n' ' ' <<<"$L")"
[[ ! -e "$QDIR/catalog.draft.json" ]] && ok "(f) no stale draft survives a failed run" \
  || bad "(f) a stale catalog.draft.json survived the failed run"
[[ ! -e "$QDIR/catalog.leak_report.json" ]] && ok "(f) no stale leak report survives a failed run" \
  || bad "(f) a stale catalog.leak_report.json survived the failed run"

# ---------------------------------------------------------------- output hygiene
head2 "The rehearsal's own output"
HITS="$(grep -ciFf "$WORK/corpus_words" "$WORK/transcript")"
[[ "$HITS" == "0" ]] && ok "(j) no stand-in corpus word appears anywhere in this rehearsal's output" \
  || bad "(j) $HITS line(s) of this rehearsal's output carry stand-in corpus words"
[[ "$GIT_BEFORE" == "$(git status --porcelain)" ]] && ok "the repository's git status is unchanged by the rehearsal" \
  || bad "the repository's git status changed during the rehearsal"
# Informational: this rehearsal never touches the repo's quarantine, so a non-empty one is the
# operator's own leftover (see rehearse-window-b.sh), not a failure of Window E.
if make check-clean >/dev/null 2>&1; then ok "local/quarantine is empty"; else
  note "make check-clean reports local/quarantine is not empty - yours to inspect and shred; not read here"; fi

# ---------------------------------------------------------------- verdict
head2 "Verdict"
printf '  %d passed, %d failed\n' "$pass" "$fail"
printf '  Substitutions versus the real window (and only these):\n'
for s in "${SUBSTITUTIONS[@]}"; do printf '    - %s\n' "$s"; done
echo
if (( fail == 0 )); then
  cat <<'EOF'
  The window's control flow, controls and allowlist behave as designed against a stub LLM.
  NOT covered here (check on the box, see "Window E" in docs/airlock-runbook.md):
    - vLLM's image entrypoint and the `--model` argument form
    - the weights mount: read-only, SELinux label, or read-write for lock files
    - the real GPU claim, e5 on the GPU, and the real model's output
    - podman's own `network create --internal` (ship checks it on the box)
EOF
  exit 0
else
  echo "  Do NOT open a window until these are fixed - each failure here is a"
  echo "  failure you would otherwise hit with no AI available to diagnose it."
  exit 1
fi
