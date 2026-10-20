#!/usr/bin/env bash
# Fail-closed wrapper around guard.py: a crash, a timeout or a missing file denies the call
# (exit 2) instead of silently allowing it.
#
# The hook process must not be steerable from files an agent can write: python runs isolated
# (-I: no PYTHON* variables, no user site, no script-directory imports), prefers the system
# interpreter over whatever PATH offers, and runs with the system directories first on PATH
# (the guard shells out to git).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="$here/guard.py"

fail() {
    echo "recall guard: $1 - denying (fail closed). A human can run: python3 tools/guard/guard.py --selfcheck" >&2
    exit 2
}

[ -f "$guard" ] || fail "guard.py missing"
if [ -x /usr/bin/python3 ]; then
    py=/usr/bin/python3
else
    py="$(command -v python3 2>/dev/null)" || py=""
fi
[ -n "$py" ] || fail "python3 missing"

runner=()
timeout_bin="$(command -v timeout 2>/dev/null)" && runner=("$timeout_bin" 8)

out="$(PATH="/usr/bin:/bin:$PATH" ${runner[@]+"${runner[@]}"} "$py" -I "$guard" "$@")"
rc=$?
[ "$rc" -eq 0 ] || fail "guard exited with status $rc"
[ -z "$out" ] || printf '%s\n' "$out"
exit 0
