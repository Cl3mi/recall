#!/usr/bin/env bash
# Publish a snapshot of HEAD to the private GitHub repo, as ONE new commit on the remote main.
#
# Why a snapshot and not `git push`: local history holds NDA-sensitive material (client name,
# real-corpus figures, host details), so history never leaves the machine. Only the paths in
# tools/publish/allowlist.txt do, and only after a scan against the local denylist.
#
# The denylist lives in local/publish-denylist.txt (gitignored, one fixed string per line,
# case-insensitive) because it contains the very strings that must not be published. The script
# refuses to run without it.
set -euo pipefail

REPO_DIR=$(git rev-parse --show-toplevel)
cd "$REPO_DIR"

REMOTE=${PUBLISH_REMOTE:-git@github.com:Cl3mi/recall.git}
ALLOW=tools/publish/allowlist.txt
DENY=local/publish-denylist.txt

[ -f "$DENY" ] || { echo "ABORT: $DENY is missing (one forbidden string per line)" >&2; exit 1; }
[ -s "$DENY" ] || { echo "ABORT: $DENY is empty" >&2; exit 1; }

mapfile -t PATHS < <(grep -vE '^[[:space:]]*(#|$)' "$ALLOW")
git diff --quiet HEAD -- "${PATHS[@]}" || { echo "ABORT: uncommitted changes in published paths" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SNAP="$WORK/snap"; mkdir "$SNAP"
git archive HEAD "${PATHS[@]}" | tar -x -C "$SNAP"

# 1. No data files of any kind, whatever their content.
if find "$SNAP" -type f \( -iname '*.csv' -o -iname '*.tsv' -o -iname '*.parquet' -o -iname '*.jsonl' \
     -o -iname '*.xls*' -o -iname '*.npy' -o -iname '*.npz' -o -iname '*.pkl' -o -iname '*.zip' \
     -o -iname '*.gz' -o -iname '*.syn' \) | grep -q .; then
  echo "ABORT: snapshot contains a data-file extension" >&2; exit 1
fi

# 2. No denylisted string anywhere in the snapshot (file names included).
# uv.lock is machine-generated hashes; a short figure can match one by chance.
if grep -rIiF --exclude=uv.lock -f "$DENY" "$SNAP"; then
  echo "ABORT: snapshot contains a denylisted string" >&2; exit 1
fi
if (cd "$SNAP" && find . -type f) | grep -iF -f "$DENY"; then
  echo "ABORT: a denylisted string is in a file name" >&2; exit 1
fi

# 3. Clone the remote, replace its tree with the snapshot, commit on top, push (fast-forward).
git clone -q "$REMOTE" "$WORK/remote"
cd "$WORK/remote"
git rm -rq --ignore-unmatch . >/dev/null
cp -a "$SNAP"/. .
git add -A
if git diff --cached --quiet; then
  echo "Nothing to publish: remote already matches HEAD."
  exit 0
fi
SRC=$(git -C "$REPO_DIR" rev-parse --short HEAD)
git -c commit.gpgsign=false commit -q -m "Sync snapshot of main@$SRC

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git diff --stat HEAD~1 | tail -1
git push origin HEAD:main
echo "Published main@$SRC."
