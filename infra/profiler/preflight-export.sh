#!/usr/bin/env bash
# Structural preflight for a real export. Reads shape, never content.
#
#   ./infra/profiler/preflight-export.sh /path/to/export.csv
#   ./infra/profiler/preflight-export.sh /path/to/export.csv --syntax customData
#
# Runs on the WORKSTATION, not the GPU box, and before/outside any airlock window. The
# export is already here; the window exists to keep real data off machines that hold an
# AI context, and this reads no content, so it needs neither the box nor a sealed run.
#
# Default mode prints column-contract conformance, row count, encoding, delimiter and row
# integrity. --syntax COLUMN additionally probes one free-form column's syntax: the
# punctuation skeleton with every letter and digit removed, and a frequency-floored
# prefix shape.
#
# It cannot print a field value. The only strings it emits are column names drawn from
# the published 38-column contract, fixed literals, and character-class shapes.
#
# The output is safe to paste into an AI tool. The file itself is not.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ $# -lt 1 || "${1:-}" == -* ]]; then
  cat >&2 <<'EOF'
usage: preflight-export.sh <export.csv> [--syntax COLUMN] [--min-frequency N]

  (no flags)            check the export against the 38-column contract
  --syntax COLUMN       probe that column's syntax - shapes and punctuation only
  --min-frequency N     floor for the syntax probe (default 50)

Run this on the workstation. It needs no airlock window and no GPU box.
EOF
  exit 2
fi

cd "$REPO" || exit 1
# No `uv`: it is not installed here any more, and `uv run` would reach for the network anyway.
# profiler.preflight needs only the standard library and profiler.columns, so any Python 3 on
# the workstation works. RECALL_PYTHON overrides it; the repo's .venv is preferred when present.
PYTHON="${RECALL_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
fi
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" -m profiler.preflight "$@"
