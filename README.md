# recall — Lösungsfinder

German ticket-similarity search: given a new support ticket, retrieve resolved
historical tickets and synthesise a grounded, cited suggestion. Trained and validated
without any real ticket data ever reaching an AI tool.

- **Spec:** `PROJECT_BRIEF.md`
- **Decisions and corrections:** `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md`
- **Implementation plan:** `docs/superpowers/plans/2026-08-04-loesungsfinder.md`
- **Sealed-window procedure:** `docs/airlock-runbook.md` — read before touching real data

Current state: **Milestone 0 and the autonomous part of Milestone 1 are complete.**
Window A (profiling the real export) has not been run; nothing downstream of it can
start, because Milestone 2's generator is conditioned on `profile.json`.

## The one rule

**Git holds no data. None.** Not the real export, not the profile, not synthetic
fixtures, not embeddings, not eval queries. Only code, schemas, docs, generators, seeds
and checksums. There is **no git remote** and none should be added — `make test`
asserts both.

Real data exists only on the HPC box, inside a manual AI-free window. On this
workstation `local/quarantine/` stays empty and `make check-clean` proves it.

```
local/artifacts/   AI may read  - profile.json, gate report, eval_*.json
local/fixtures/    AI may read  - regenerated synthetic corpus
local/quarantine/  NEVER        - real CSV, detail logs, embeddings, eval queries
```

## Setup

```bash
uv sync                 # fetches Python 3.12 even though the host has 3.14
make db-up              # Postgres 18 + pgvector + the derived German dictionary
make migrate            # checksum-guarded SQL migrations
make test lint          # 106 passed, 1 skipped, 2 xfailed
make check-clean        # asserts local/quarantine is empty
```

`make check-clean` must be run in a **normal terminal**. Under the Claude Code sandbox
it cannot list the denied directory and reports a false `clean`.

Postgres listens on **5433**, not 5432 — port 5432 is usually taken by a host install.

## Make targets

| Target | What it does |
|---|---|
| `db-up` / `db-down` | start / stop the dev Postgres |
| `db-reset` | drop the volume and rebuild the schema from zero |
| `migrate` | apply pending migrations; silent means nothing pending |
| `test` / `lint` | pytest / ruff |
| `check-clean` | fail if `local/quarantine/` holds anything |
| `local-dirs` | create the three local tiers |
| `window-a-rehearsal` | full Window A dress rehearsal on synthetic data |

Override the target database with `make migrate PG_DSN=…` — this drives both `PG_DSN`
(read by the tests) and `RECALL_PG_DSN` (read by `recall.config`).

## Before a window: preflight the export

```bash
./infra/profiler/preflight-export.sh /path/to/export.csv
```

Reads shape, never content — column-contract conformance, row count, encoding,
delimiter, row integrity. Output is safe to share; the file is not. Catches the
mismatches that otherwise cost a whole airlock cycle to discover.

## Running the profiler

The profiler is a **separate top-level package** from `recall`, deliberately: it runs
unattended on a box holding real data, so it may import only `recall.clean` and
`recall.german.identifiers`. A test enforces that it never pulls in psycopg, httpx or
the API layer.

Against a synthetic stand-in, on this workstation:

```bash
python - <<'EOF'
import pathlib, sys; sys.path.insert(0, 'tests')
from conftest import build_standin
build_standin(pathlib.Path('/tmp/rehearsal/export.csv'))
EOF
uv run python -m profiler --csv /tmp/rehearsal/export.csv --out /tmp/rehearsal/profile.json
```

Against real data, use the sealed image and follow `docs/airlock-runbook.md` exactly.
Two things in that command are load-bearing and easy to get wrong:

- **Do not mount anything over `/work`.** The image holds the code and its virtualenv
  there; mounting over it hides the venv and the run dies on `ModuleNotFoundError`.
- **Set `RECALL_PROFILER_DETAIL_LOG` to a path on the mounted volume.** The default is
  relative, so otherwise the verbatim detail log is written inside the container and
  destroyed by `--rm`, leaving a failed sealed run with no diagnostic.

Exit codes: `0` ok · `2` safety violation (code and schema path on stdout are safe to
read) · `3` unexpected failure (exception *type* only; traceback goes to the detail
log) · `4` bad argument or empty input.

## Layout

```
profiler/        SEALED: runs in Window A. No network, no DB, no GPU.
src/recall/
  clean/         German reply chains, signatures, HTML, diagnostic dumps, PII
  german/        identifier extraction, safe shape inference, model-family proxy
  db/            checksum-guarded migration runner + numbered SQL
infra/postgres/  pg18 image; derive-compound-dict.pl builds the German dictionary
infra/profiler/  the pinned, offline-capable profiler image
infra/fairuse/   two-GPU fair-use guard for the shared HPC box
```

## Two things worth knowing before you change anything

**German compound splitting needs a derived dictionary.** igerman98 grants
`COMPOUNDBEGIN` through hunspell affix *flag continuation*, which PostgreSQL's
`spell.c` does not implement — so with the stock dictionary every compound lexizes to
`NULL` and `Pumpe` does not match `Hydraulikpumpe`.
`infra/postgres/derive-compound-dict.pl` resolves that at image-build time. Do not
"simplify" `0002_german_config.sql` back to `dictfile = de_de`.

**`COMPOUNDMIN` is inert.** PostgreSQL parses it and does not enforce it. What actually
prevents over-splitting is that PostgreSQL prefers a whole-word dictionary hit. Do not
cite `COMPOUNDMIN` as a safeguard.
