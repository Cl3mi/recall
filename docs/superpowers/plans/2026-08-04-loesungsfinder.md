# Lösungsfinder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a German-language ticket similarity search that, given a new support ticket's text, retrieves resolved historical tickets and synthesises a grounded, cited suggestion — trained and validated without any real ticket data ever reaching an AI.

**Architecture:** Hybrid retrieval (dense + German FTS + exact identifiers) fused by RRF, cross-encoder reranked, then LLM-synthesised with citations, over a Postgres/pgvector store. Enrichment — not chunking — is the data-cleaning and length-normalisation layer. All inference is local on two H100 PCIe cards, one model per card. Real data is touched only inside three manual, AI-free "airlock" windows that emit aggregate artifacts.

**Tech Stack:** Python 3.12 (uv), Postgres 18 + pgvector + hunspell German, vLLM (Qwen3-32B FP8 generator, Qwen3-Embedding-8B, Qwen3-Reranker-4B), FastAPI, SvelteKit, Docker locally / podman on the HPC box.

**Read first:** `PROJECT_BRIEF.md` (spec) and `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` (decisions, corrections to the brief, airlock protocol).

---

## Scope of this plan

**Milestones 0 and 1 are specified to task level with complete code.** Milestones
2–6 are specified to **acceptance-criteria level only**, deliberately: M2's
generator is conditioned on `profile.json`, and M3–M5's tuning targets come from
it. Expanding them into TDD steps now would be inventing details that Window A
will supply. **Each of M2–M6 gets its own task-level plan written at the start of
that milestone**, from this document's acceptance criteria plus the profile.

This is a scope boundary, not a placeholder. Do not begin M2 without writing its
task plan first.

---

## Pre-flight — verify before Task 1

Cheap checks that each cost minutes now and hours later. Everything here was true
on 2026-08-04; re-verify rather than assume.

- [ ] `git config --get user.name && git config --get user.email` — every task ends
      in a commit, so a missing identity fails thirteen times.
- [ ] `docker --version && docker compose version` — the workstation has Docker;
      **the HPC box has podman**, so container commands differ by machine. Compose
      files are workstation-only; the box uses plain `podman run`.
- [ ] `uv --version` (0.11+), `python3 --version`. The project pins
      `>=3.12,<3.13`; uv will fetch 3.12 even though the host has 3.14.
- [ ] `command -v bwrap socat` — both present, so `sandbox.filesystem.denyRead` in
      Task 6 is enforceable. Without them that control silently does nothing.
- [ ] `./infra/fairuse/gpu-fairuse2.sh check` after Task 5 — GPUs 0 and 1 are
      2× H100 PCIe, 81,559 MiB each, MIG disabled. **PCIe, so never tensor-parallel
      across the pair**; one model per card.
- [ ] `ls <export-dir>/` — **resolve this before anything else.** A
      `Ticket-*.csv` sits there. If it is real client data it must not be on the
      workstation at all under the data handling rules, and it must not be readable
      by any AI tool. Task 6 already denies the path in both `permissions.deny` and
      `sandbox.filesystem.denyRead`; confirm the classification and either move it
      to the HPC box quarantine or delete it.

**What this plan cannot finish without you.** Tasks 1–13 are fully autonomous. The
M1 acceptance criteria that say *Window A executed* are not: they need the real
export and a manual, AI-free session. An implementing agent should complete Task 13,
report that Window A is ready to run, and stop.

---

## Data handling rules — binding, read before any task

These override anything in `PROJECT_BRIEF.md` §8 that says otherwise (the brief's
fixture table says "in git: yes"; that is no longer true).

**1. Git holds no data. None.** Not the real export, not the profile, not the
synthetic corpus, not test fixtures, not embeddings, not eval queries. Only code,
schemas, docs, generators, seeds and checksums. There is **no git remote**; data
moves between the workstation and the HPC box by `scp` and nothing else.

**2. Fixtures are reproduced, not stored.** Git holds the generator, the seed and
a checksum manifest; `make fixtures` regenerates or verifies. This preserves §8's
"fixed seed, reproducible" property without a single data byte in version control.

**3. Three local tiers, and which of them an AI tool may read:**

| Path | Contents | AI may read |
|---|---|---|
| `local/artifacts/` | `profile.json`, `profile_report.md`, gate report, `eval_*.json` | **yes** — hardened, aggregate, entity-swept |
| `local/fixtures/` | synthetic corpus, archetypes, cached fixture embeddings | **yes** — pure fiction |
| `local/quarantine/` | real CSV, detail logs, real-corpus embeddings, enrichment intermediates, hand-written eval queries, the mined synonym source list, vLLM logs | **never** |

`local/quarantine/` exists on both machines. On the workstation it is denied by
`permissions.deny` *and* by `sandbox.filesystem.denyRead`, which the kernel
enforces rather than a string matcher. On the HPC box the airlock is the control.

**4. The safe-output principle.** Anything an AI tool may read must be
*structurally incapable* of carrying a corpus value — enforced by types in
`profiler/safety.py`, not by anyone's discipline. That covers exception messages,
stdout, log lines and every emitted artifact. Corollary: **never paste output from
a sealed run into an AI tool.** When a sealed run fails, the detail file stays on
the box; only the error code and schema location travel.

**5. Derived data is data.** Enrichment output, embeddings, the mined synonym
list and hand-written eval queries are all real-corpus derivatives and live in
`local/quarantine/`. Embeddings especially: inversion attacks reconstruct
substantial portions of short texts when the embedding model is public, and ours
is, so they get no more latitude than the source rows.

---

## File structure

```
recall/
├── PROJECT_BRIEF.md                    # spec (existing, do not edit)
├── README.md                           # how to run the thing
├── pyproject.toml                      # uv project, py3.12
├── .gitignore                          # blocks *.csv except test fixtures
├── Makefile                            # thin wrappers; the one place commands are recorded
├── docs/
│   ├── superpowers/specs/2026-08-04-loesungsfinder-design.md
│   ├── superpowers/plans/2026-08-04-loesungsfinder.md    # this file
│   ├── airlock-runbook.md              # M1: the manual sealed-window procedure
│   └── client-questions.md             # for the post-vacation call
├── infra/
│   ├── postgres/
│   │   ├── Dockerfile                  # pg18 + pgvector + hunspell de + tsearch_data
│   │   └── compose.yml                 # workstation dev instance
│   ├── vllm/
│   │   ├── generator.sh                # GPU 0: Qwen3-32B FP8
│   │   └── retrieval.sh                # GPU 1: embedder + reranker
│   └── fairuse/gpu-fairuse2.sh         # two-GPU, mid-job re-check, foreign-process aware
├── src/recall/
│   ├── config.py                       # pydantic-settings, one source of env truth
│   ├── db/
│   │   ├── migrate.py                  # checksum-guarded SQL migration runner
│   │   └── migrations/*.sql            # numbered, immutable once applied
│   ├── clean/
│   │   ├── html.py                     # tag stripping, entity unescaping
│   │   ├── reply_chains.py             # German quoted-reply / forwarded-header removal
│   │   ├── signatures.py               # Grußformel + contact-block removal
│   │   ├── dumps.py                    # pasted diagnostic-output detection
│   │   ├── pii.py                      # email/phone/IBAN/plate redaction
│   │   └── pipeline.py                 # compose the above; returns text + CleanReport
│   ├── german/
│   │   ├── identifiers.py              # error code / part no / serial / model extraction
│   │   └── synonyms.py                 # M4: mine unrecognised tokens → synonym dict
│   ├── ingest/csv_loader.py            # raw immutable load → jsonb
│   ├── enrich/{schema,prompts,runner,verify}.py
│   ├── embed/{client,cache}.py
│   ├── retrieve/{dense,lexical,identifiers,fuse,rerank,features}.py
│   ├── synthesize/{triage,generate,spans}.py
│   └── api/main.py
├── profiler/                           # SEALED: runs in Window A. No network, no DB, no GPU.
│   ├── __main__.py                     # single entry point: python -m profiler
│   ├── columns.py                      # the 38-column contract, one source of truth
│   ├── schema.json                     # JSON Schema for profile.json — the review artifact
│   ├── safety.py                       # SafetyViolation (numeric facts only) + detail sink
│   ├── selfcheck.py                    # refuses to write an unsafe artifact
│   ├── entities.py                     # entity sweep over every emitted string
│   ├── data/common_surnames.txt        # public reference data (not corpus data)
│   ├── stats/{lengths,nullmask,vocab,clusters,solutions,temporal,hunspell}.py
│   └── emit.py                         # profile.json + profile_report.md
├── synth/
│   ├── archetypes.py                   # ~400 fault archetypes on a fictional product line
│   ├── roster.py                       # fictional merchants/customers
│   ├── generate.py                     # LLM, conditioned ONLY on profile.json
│   ├── noise.py                        # programmatic noise + joint null masks
│   └── gate/{regex_sweep,shingles,nn_check,allowlist,report}.py
├── eval/
│   ├── harness.py                      # config-MATRIX driven, one pass many cells
│   ├── metrics.py                      # recall@k, MRR, nDCG + bootstrap CIs
│   ├── labels.py                       # archetype (synthetic) / cluster (real) gold labels
│   ├── query_schema.py                 # format for hand-written real eval queries
│   └── report.py                       # eval_synthetic.json / eval_real.json
├── frontend/                           # M5: SvelteKit, German UI
├── tests/
│   ├── conftest.py                     # builds the stand-in CSV at runtime; nothing on disk
│   ├── unit/
│   └── integration/
└── local/                              # gitignored in full; scp is the only transport
    ├── artifacts/                      # AI-readable: profile.json, gate + eval reports
    ├── fixtures/                       # AI-readable: regenerated synthetic corpus
    ├── quarantine/                     # NEVER AI-readable; sandbox-denied
    └── MANIFEST.sha256                 # the one file here that IS committed
```

**Boundaries that matter:**

- `profiler/` is a **separate top-level package**, not part of `recall`. It may
  import `recall.clean` and `recall.german.identifiers` (post-clean quantiles need
  the real cleaner — DRY) and nothing else from the app. Enforced by a test.
- `clean/` splits by *kind of noise*, not by layer, because each kind has its own
  German-specific patterns and its own tests.
- `retrieve/` has one file per arm plus fusion, so an arm can be swapped or
  measured in isolation.
- `profiler/safety.py` is the only place allowed to construct messages that leave
  the profiler. Every other module raises through it.
- `local/` is created by `make local-dirs`, gitignored in full, and its
  `quarantine/` subtree is denied to AI tools by both a permission rule and a
  sandbox read-deny. The mirror path on the HPC box is
  `<data-dir>/recall-quarantine/`.

---

# Milestone 0 — Foundations

**No data of any kind is involved.** Everything here is verifiable today.

### Task 1: Repository and tooling

**Files:**
- Create: `~/mci/recall/pyproject.toml`
- Create: `~/mci/recall/.gitignore`
- Create: `~/mci/recall/src/recall/__init__.py`
- Create: `~/mci/recall/tests/unit/test_smoke.py`

- [ ] **Step 1: Initialise the repository**

```bash
cd ~/mci/recall
git init -b main
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "recall"
version = "0.1.0"
description = "Ticket similarity search (Lösungsfinder)"
requires-python = ">=3.12,<3.13"
dependencies = [
  "psycopg[binary]>=3.2",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "httpx>=0.28",
  "numpy>=2.1",
  "jsonschema>=4.23",
  "datasketch>=1.6",
  "selectolax>=0.3",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-cov>=6.0", "ruff>=0.8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = [
  "needs_pg: requires the Postgres container (make db-up)",
  "needs_gpu: requires the H100 box via gpu-fairuse2.sh",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/recall", "profiler"]
```

- [ ] **Step 3: Write `.gitignore`**

The CSV rules are a safety mechanism, not tidiness: a real export must be
impossible to commit by accident.

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
node_modules/
.env

# ---------------------------------------------------------------------------
# Data safety: NO data file of any kind is committed - real or synthetic.
# Fixtures are regenerated from a committed generator + seed, never stored here.
# The only exception is the checksum manifest, which contains no data itself.
# ---------------------------------------------------------------------------
local/
!local/MANIFEST.sha256

*.csv
*.tsv
*.parquet
*.npy
*.npz
*.pkl
*.jsonl
profile.json
profile_report.md
eval_real.json
*.syn
data/
quarantine/
```

`*.syn` is there deliberately: the mined synonym dictionary is derived from real
corpus vocabulary, so despite looking like config it is data and stays local.

- [ ] **Step 4: Write the smoke test**

```python
# tests/unit/test_smoke.py
import recall


def test_package_imports():
    assert recall.__name__ == "recall"
```

- [ ] **Step 5: Create the package and install**

```bash
mkdir -p src/recall tests/unit
printf '__all__: list[str] = []\n' > src/recall/__init__.py
uv sync
```

- [ ] **Step 6: Run the test**

Run: `uv run pytest tests/unit/test_smoke.py -v`
Expected: PASS, 1 test.

- [ ] **Step 7: Verify the data guard actually works**

Three probes, because a single one gives false confidence.

```bash
mkdir -p local/quarantine local/artifacts local/fixtures
printf 'a,b\n1,2\n' > data_probe.csv
printf 'x\n'         > local/quarantine/probe.txt
printf 'y\n'         > local/artifacts/profile.json
for f in data_probe.csv local/quarantine/probe.txt local/artifacts/profile.json; do
  if git check-ignore -q "$f"; then echo "ignored ok: $f"; else echo "GUARD FAILED: $f"; fi
done
rm -f data_probe.csv local/quarantine/probe.txt local/artifacts/profile.json
```

Expected: three `ignored ok` lines and no `GUARD FAILED`.

- [ ] **Step 8: Create the local data tiers**

The `Makefile` arrives in Task 2, which adds a `local-dirs` target wrapping this.

```bash
mkdir -p local/artifacts local/fixtures local/quarantine
chmod 700 local/quarantine
```

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore src tests uv.lock PROJECT_BRIEF.md docs
git commit -m "chore: initialise recall project with a no-data-in-git guard"
git status --porcelain   # must be empty apart from untracked local/ being ignored
```

Commit `docs/` here so the plan and design doc are in history from the first commit.

Do **not** `git add local/` — `make check-clean` and
`tests/unit/test_data_guards.py` (Task 6) exist to catch it if you ever do.

- [ ] **Step 10: Verify both packages import (src-layout plus a root package)**

`pyproject.toml` declares `packages = ["src/recall", "profiler"]`, which is an
unusual mix. Confirm it resolves before building anything on top of it.

```bash
uv run python -c "import recall, profiler; print(recall.__file__, profiler.__file__)"
```

Expected: two paths printed, no `ModuleNotFoundError`. If `profiler` fails to
import, add `[tool.hatch.build.targets.wheel.sources]` mapping or fall back to
`uv run python -m pytest` from the repo root with `pythonpath = ["."]` under
`[tool.pytest.ini_options]`.

---

### Task 2: Postgres image with pgvector and German hunspell

**Files:**
- Create: `infra/postgres/Dockerfile`
- Create: `infra/postgres/compose.yml`
- Create: `Makefile`

- [ ] **Step 1: Write the Dockerfile**

Postgres's `ispell` template wants `<name>.dict` / `<name>.affix` in
`$SHAREDIR/tsearch_data`, whereas hunspell ships `de_DE.dic` / `de_DE.aff`. The
rename is the whole trick. An empty synonym file is created now so the synonym
dictionary can be declared at M0 and filled at M4 without a schema change.

```dockerfile
FROM postgres:18-bookworm

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector \
        hunspell-de-de; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    share="$(pg_config --sharedir)/tsearch_data"; \
    cp /usr/share/hunspell/de_DE.dic "$share/de_de.dict"; \
    cp /usr/share/hunspell/de_DE.aff "$share/de_de.affix"; \
    : > "$share/de_tech_synonyms.syn"; \
    head -1 "$share/de_de.affix" | grep -qi 'SET *UTF-8' \
      || echo "WARNING: de_DE.aff is not UTF-8; compound splitting may misbehave" >&2; \
    ls -l "$share/de_de.dict" "$share/de_de.affix" "$share/de_tech_synonyms.syn"
```

- [ ] **Step 2: Write the compose file**

```yaml
name: recall
services:
  db:
    build: .
    image: recall/postgres:18
    environment:
      POSTGRES_DB: recall
      POSTGRES_USER: recall
      POSTGRES_PASSWORD: recall_dev_only
    ports: ["5433:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U recall -d recall"]
      interval: 3s
      timeout: 3s
      retries: 20
volumes:
  pgdata:
```

Port 5433 deliberately, so it cannot collide with a host Postgres later.

- [ ] **Step 3: Write the Makefile**

```makefile
PG_DSN ?= postgresql://recall:recall_dev_only@localhost:5433/recall
export PG_DSN

.PHONY: db-up db-down db-reset migrate test lint local-dirs

local-dirs:
	mkdir -p local/artifacts local/fixtures local/quarantine
	chmod 700 local/quarantine

db-up:
	docker compose -f infra/postgres/compose.yml up -d --build --wait

db-down:
	docker compose -f infra/postgres/compose.yml down

db-reset:
	docker compose -f infra/postgres/compose.yml down -v
	$(MAKE) db-up migrate

migrate:
	uv run python -m recall.db.migrate

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 4: Build and start it**

Run: `make db-up`
Expected: builds, then `Container recall-db-1  Healthy`.

- [ ] **Step 5: Verify both dependencies landed**

```bash
docker compose -f infra/postgres/compose.yml exec -T db \
  psql -U recall -d recall -Atc "create extension if not exists vector; select extversion from pg_extension where extname='vector';"
docker compose -f infra/postgres/compose.yml exec -T db \
  ls -l /usr/share/postgresql/18/tsearch_data/de_de.dict
```

Expected: a pgvector version string, and a `de_de.dict` of several MB.

- [ ] **Step 6: Commit**

```bash
git add infra/postgres Makefile
git commit -m "feat(infra): postgres 18 image with pgvector and German hunspell"
```

---

### Task 3: Migration runner

**Files:**
- Create: `src/recall/config.py`
- Create: `src/recall/db/__init__.py`, `src/recall/db/migrate.py`
- Create: `src/recall/db/migrations/0001_extensions.sql`
- Test: `tests/integration/test_migrate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_migrate.py
import os

import psycopg
import pytest

from recall.db import migrate

pytestmark = pytest.mark.needs_pg
DSN = os.environ["PG_DSN"]


def test_apply_all_is_idempotent():
    first = migrate.apply_all(DSN)
    assert "0001_extensions" in first
    second = migrate.apply_all(DSN)
    assert second == []


def test_checksum_drift_is_rejected(tmp_path, monkeypatch):
    migrate.apply_all(DSN)
    with psycopg.connect(DSN) as conn:
        conn.execute(
            "update schema_migrations set checksum = 'tampered' where version = '0001_extensions'"
        )
        conn.commit()
    with pytest.raises(RuntimeError, match="changed after being applied"):
        migrate.apply_all(DSN)
    with psycopg.connect(DSN) as conn:
        conn.execute("delete from schema_migrations where checksum = 'tampered'")
        conn.commit()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `make db-up && uv run pytest tests/integration/test_migrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recall.db'`.

- [ ] **Step 3: Write the config module**

```python
# src/recall/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECALL_", env_file=".env", extra="ignore")

    pg_dsn: str = "postgresql://recall:recall_dev_only@localhost:5433/recall"
    ts_config: str = "de_tech"
    embed_url: str = "http://localhost:8001/v1"
    rerank_url: str = "http://localhost:8002/v1"
    generator_url: str = "http://localhost:8000/v1"
    embed_dims: int = 1024


settings = Settings()
```

- [ ] **Step 4: Write the migration runner**

```python
# src/recall/db/migrate.py
from __future__ import annotations

import hashlib
import pathlib

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"

_BOOTSTRAP = """
create table if not exists schema_migrations (
    version    text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
)
"""


def discover() -> list[pathlib.Path]:
    """Migrations apply in filename order. Names are immutable once applied."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _checksum(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_all(dsn: str) -> list[str]:
    """Apply pending migrations. Returns the versions applied this call."""
    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        conn.execute(_BOOTSTRAP)
        conn.commit()
        for path in discover():
            version, checksum = path.stem, _checksum(path)
            row = conn.execute(
                "select checksum from schema_migrations where version = %s", (version,)
            ).fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise RuntimeError(
                        f"migration {version} changed after being applied "
                        f"(recorded {row[0][:12]}, on disk {checksum[:12]})"
                    )
                continue
            conn.execute(path.read_text())
            conn.execute(
                "insert into schema_migrations (version, checksum) values (%s, %s)",
                (version, checksum),
            )
            conn.commit()
            applied.append(version)
    return applied


if __name__ == "__main__":
    from recall.config import settings

    for v in apply_all(settings.pg_dsn):
        print(f"applied {v}")
```

- [ ] **Step 5: Write the first migration**

```sql
-- src/recall/db/migrations/0001_extensions.sql
create extension if not exists vector;
create extension if not exists unaccent;
create extension if not exists pg_trgm;
```

- [ ] **Step 6: Run the tests**

```bash
mkdir -p src/recall/db/migrations tests/integration
touch src/recall/db/__init__.py
uv run pytest tests/integration/test_migrate.py -v
```

Expected: PASS, 2 tests.

- [ ] **Step 7: Commit**

```bash
git add src/recall/config.py src/recall/db tests/integration
git commit -m "feat(db): checksum-guarded SQL migration runner"
```

---

### Task 4: German text search configuration — the compound-splitting gate

This is the highest-risk item in M0. The brief's §7 snippet orders `unaccent`
before the German dictionaries, which converts `Ölfilter` → `Olfilter` and
silently defeats both compound splitting and stemming for umlauted words. We
build **both** orderings and let the test decide.

**Files:**
- Create: `src/recall/db/migrations/0002_german_config.sql`
- Test: `tests/integration/test_german_fts.py`

- [ ] **Step 1: Write the failing behavioural test**

Test behaviour, not lexeme spelling: Postgres dictionary chains stop at the first
dictionary that recognises a token, so a hunspell-split compound never reaches
`german_stem` and its lexemes are the decomposition, not stems.

```python
# tests/integration/test_german_fts.py
import os

import psycopg
import pytest

pytestmark = pytest.mark.needs_pg
DSN = os.environ["PG_DSN"]

# (document, query) — each query must match the document ONLY IF the compound splits.
COMPOUND_CASES = [
    ("Die Hydraulikpumpe ist defekt", "Pumpe & defekt"),
    ("Ölfilterwechsel durchgeführt", "Ölfilter"),
    ("Der Getriebeschaden wurde behoben", "Getriebe"),
    ("Kühlwasserverlust am Motor festgestellt", "Kühlwasser"),
    ("Bremsleitung undicht", "Bremse | Bremsleitung"),
]

UMLAUT_CASES = [
    ("Ölfilter gewechselt", "Ölfilter"),
    ("Kühler gereinigt", "Kühler"),
]


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(DSN) as c:
        yield c


def _matches(conn, config: str, doc: str, query: str) -> bool:
    return conn.execute(
        "select to_tsvector(%s::regconfig, %s) @@ to_tsquery(%s::regconfig, %s)",
        (config, doc, config, query),
    ).fetchone()[0]


@pytest.mark.parametrize(("doc", "query"), COMPOUND_CASES)
def test_de_tech_splits_compounds(conn, doc, query):
    assert _matches(conn, "de_tech", doc, query), f"de_tech failed to split: {doc!r} ~ {query!r}"


@pytest.mark.parametrize(("doc", "query"), UMLAUT_CASES)
def test_de_tech_preserves_umlauts(conn, doc, query):
    assert _matches(conn, "de_tech", doc, query), f"de_tech lost umlaut handling: {doc!r}"


def test_unaccent_variant_is_measurably_different(conn):
    """Records the empirical answer to the §7 ordering question. Not a pass/fail on
    de_tech_ua — it documents which cases the unaccent-first chain breaks."""
    broken = [
        (doc, q) for doc, q in COMPOUND_CASES + UMLAUT_CASES
        if not _matches(conn, "de_tech_ua", doc, q)
    ]
    print(f"\nde_tech_ua fails {len(broken)}/{len(COMPOUND_CASES + UMLAUT_CASES)} cases: {broken}")
    assert isinstance(broken, list)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/integration/test_german_fts.py -v`
Expected: FAIL — `text search configuration "de_tech" does not exist`.

- [ ] **Step 3: Write the migration**

```sql
-- src/recall/db/migrations/0002_german_config.sql
-- German technical text search. Two configurations exist deliberately:
--   de_tech     : dictionaries see real umlauts (the intended production config)
--   de_tech_ua  : unaccent runs first, as PROJECT_BRIEF.md §7 suggested
-- tests/integration/test_german_fts.py records which cases each one handles.

create text search dictionary german_hunspell (
    template  = ispell,
    dictfile  = de_de,
    afffile   = de_de,
    stopwords = german
);

-- Filled at M4 by recall.german.synonyms from the profile's unrecognised-token list.
-- The backing file de_tech_synonyms.syn is created empty by the Postgres image.
create text search dictionary de_synonyms (
    template = synonym,
    synonyms = de_tech_synonyms
);

create text search configuration de_tech (copy = german);
alter text search configuration de_tech
    alter mapping for asciiword, word, hword, hword_part, hword_asciipart
    with de_synonyms, german_hunspell, german_stem;

create text search configuration de_tech_ua (copy = german);
alter text search configuration de_tech_ua
    alter mapping for asciiword, word, hword, hword_part, hword_asciipart
    with unaccent, de_synonyms, german_hunspell, german_stem;
```

- [ ] **Step 4: Apply and run the tests**

Run: `make migrate && uv run pytest tests/integration/test_german_fts.py -v -s`
Expected: the `de_tech` compound and umlaut tests PASS, and the third test prints
which cases `de_tech_ua` breaks.

- [ ] **Step 5: If compound splitting fails, stop and diagnose before proceeding**

Compound splitting is load-bearing for the whole lexical arm — do not paper over
it. Diagnose with:

```bash
docker compose -f infra/postgres/compose.yml exec -T db \
  psql -U recall -d recall -c "select * from ts_debug('de_tech','Hydraulikpumpe');"
```

If `german_hunspell` is not the dictionary that resolved the token, the
dict/affix files did not load. Check the container's stderr from Task 2 Step 1 for
the UTF-8 warning, and confirm `de_DE.aff` begins with `SET UTF-8`. Fallback if
Postgres's hunspell support cannot be made to compound-split: drop
`german_hunspell`, keep `german_stem`, and carry compounds explicitly in the
synonym dictionary mined at M4 — a materially weaker lexical arm, so record the
decision in the design doc and raise the expected recall impact.

- [ ] **Step 6: Commit**

```bash
git add src/recall/db/migrations/0002_german_config.sql tests/integration/test_german_fts.py
git commit -m "feat(german): de_tech search config with hunspell compound splitting"
```

---

### Task 5: Two-GPU fair-use guard with mid-job re-checks

The existing `~/crux/gpu-fairuse.sh` checks once and `exec`s. A 5-hour enrichment
pass on a shared box must also be able to **yield**, and must avoid GPUs where
someone else already has a process.

**Files:**
- Create: `infra/fairuse/gpu-fairuse2.sh`
- Test: `tests/unit/test_fairuse_contract.py`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Fair-use guard for the SHARED HPC box, two-GPU aware. Extends ~/crux/gpu-fairuse.sh:
#   * checks every GPU in FAIRUSE_GPUS, not just one
#   * refuses a GPU that has ANY foreign compute process on it
#   * `check` is cheap enough to call between batches of a long job
#
#   ./gpu-fairuse2.sh check              # print GO/DEFER for each GPU; exit 0 iff all requested are GO
#   ./gpu-fairuse2.sh claim 0            # print export lines pinning GPU 0
#   ./gpu-fairuse2.sh run 0 -- ./job.sh  # check GPU 0, then run the command with it pinned
#
# Exit: 0 = GO, 1 = DEFER, 3 = cannot reach the box.
set -uo pipefail

GPU_ALIAS=${GPU_ALIAS:-hpc}
FAIRUSE_GPUS=${FAIRUSE_GPUS:-0,1}
CAP_GB=${FAIRUSE_VRAM_CAP_GB:-60}
MAX_UTIL=${FAIRUSE_MAX_GPU_UTIL:-85}
MIN_RAM_GB=${FAIRUSE_MIN_FREE_RAM_GB:-32}
MAX_LOAD_PCT=${FAIRUSE_MAX_LOAD_PER_CORE_PCT:-90}
ALLOW_FOREIGN=${FAIRUSE_ALLOW_FOREIGN_PROCS:-0}
SSH_OPTS=${SSH_OPTS:--T -o BatchMode=yes -o ConnectTimeout=15}

snap=$(ssh $SSH_OPTS "$GPU_ALIAS" bash -s <<'REMOTE'
nvidia-smi --query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu \
           --format=csv,noheader,nounits | tr -d ','
echo "@@PROCS"
nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits | tr -d ','
echo "@@UUIDS"
nvidia-smi --query-gpu=index,uuid --format=csv,noheader | tr -d ','
echo "@@HOST"
free -m | awk '/^Mem:/{print $7}'
cut -d' ' -f1 /proc/loadavg
nproc
REMOTE
) || { echo "fairuse: DEFER - cannot reach GPU box ($GPU_ALIAS)" >&2; exit 3; }

gpus_block=$(printf '%s\n' "$snap" | sed -n '1,/@@PROCS/p' | grep -v '@@')
procs_block=$(printf '%s\n' "$snap" | sed -n '/@@PROCS/,/@@UUIDS/p' | grep -v '@@')
uuids_block=$(printf '%s\n' "$snap" | sed -n '/@@UUIDS/,/@@HOST/p' | grep -v '@@')
host_block=$(printf '%s\n' "$snap" | sed -n '/@@HOST/,$p' | grep -v '@@')

ram=$(printf '%s\n' "$host_block" | sed -n 1p)
load1=$(printf '%s\n' "$host_block" | sed -n 2p)
ncpu=$(printf '%s\n' "$host_block" | sed -n 3p)
[[ "$ram" =~ ^[0-9]+$ && "$ncpu" =~ ^[0-9]+$ ]] \
  || { echo "fairuse: DEFER - unexpected query output" >&2; exit 3; }

loadpct=$(awk -v l="$load1" -v n="$ncpu" 'BEGIN{printf "%d",(l/n)*100}')
host_reasons=()
(( ram >= MIN_RAM_GB*1024 ))  || host_reasons+=("host RAM avail ${ram}MiB < ${MIN_RAM_GB}GB")
(( loadpct <= MAX_LOAD_PCT )) || host_reasons+=("host CPU load ${loadpct}%/core > ${MAX_LOAD_PCT}%")

uuid_of() { printf '%s\n' "$uuids_block" | awk -v i="$1" '$1==i{print $2}'; }

gpu_status() {  # $1 = index; echoes "GO"/"DEFER <reasons>"
  local idx="$1" total used free util reasons=() uuid nproc_foreign
  read -r _ total used free util <<<"$(printf '%s\n' "$gpus_block" | awk -v i="$idx" '$1==i')"
  [[ -n "${total:-}" ]] || { echo "DEFER GPU${idx} not present"; return; }
  uuid=$(uuid_of "$idx")
  nproc_foreign=$(printf '%s\n' "$procs_block" | awk -v u="$uuid" '$1==u' | grep -c . || true)
  (( free >= CAP_GB*1024 )) || reasons+=("free ${free}MiB < ${CAP_GB}GB")
  (( util <= MAX_UTIL ))    || reasons+=("util ${util}% > ${MAX_UTIL}%")
  if (( nproc_foreign > 0 && ALLOW_FOREIGN == 0 )); then
    reasons+=("${nproc_foreign} foreign compute process(es) present")
  fi
  reasons+=("${host_reasons[@]}")
  if (( ${#reasons[@]} )); then echo "DEFER GPU${idx}: $(IFS='; '; echo "${reasons[*]}")"
  else echo "GO GPU${idx}: ${free}MiB free, util ${util}%"; fi
}

cmd=${1:-check}; shift || true
case "$cmd" in
  check)
    rc=0
    IFS=',' read -ra want <<<"$FAIRUSE_GPUS"
    for i in "${want[@]}"; do
      s=$(gpu_status "$i"); echo "fairuse: $s" >&2
      [[ "$s" == GO* ]] || rc=1
    done
    exit $rc ;;
  claim|run)
    idx=${1:?need a GPU index}; shift || true
    s=$(gpu_status "$idx"); echo "fairuse: $s" >&2
    [[ "$s" == GO* ]] || exit 1
    read -r _ total _ _ _ <<<"$(printf '%s\n' "$gpus_block" | awk -v i="$idx" '$1==i')"
    util_frac=$(awk -v c="$CAP_GB" -v t="$total" 'BEGIN{printf "%.2f",(c*1024)/t}')
    uuid=$(uuid_of "$idx")
    if [[ "$cmd" == claim ]]; then
      printf "export GPU=%q CUDA_VISIBLE_DEVICES=%q CRUX_VRAM_CAP_GB=%q VLLM_GPU_MEMORY_UTILIZATION=%q\n" \
        "nvidia.com/gpu=${uuid}" "$idx" "$CAP_GB" "$util_frac"
      exit 0
    fi
    [[ "${1:-}" == "--" ]] && shift
    exec env GPU="nvidia.com/gpu=${uuid}" CUDA_VISIBLE_DEVICES="$idx" \
         CRUX_VRAM_CAP_GB="$CAP_GB" VLLM_GPU_MEMORY_UTILIZATION="$util_frac" "$@" ;;
  *) echo "usage: $0 {check|claim IDX|run IDX -- CMD}" >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Write the contract test**

The remote box cannot be assumed reachable in CI, so the test pins the *interface*
the enrichment runner depends on.

```python
# tests/unit/test_fairuse_contract.py
import pathlib
import subprocess

SCRIPT = pathlib.Path("infra/fairuse/gpu-fairuse2.sh")


def test_script_is_executable_and_valid_bash():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111, "script must be executable"
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_usage_error_exit_code():
    r = subprocess.run(["bash", str(SCRIPT), "bogus"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "usage:" in r.stderr
```

- [ ] **Step 3: Make it executable and run the test**

```bash
mkdir -p infra/fairuse
chmod +x infra/fairuse/gpu-fairuse2.sh
uv run pytest tests/unit/test_fairuse_contract.py -v
```

Expected: PASS, 2 tests.

- [ ] **Step 4: Verify against the real box**

Run: `FAIRUSE_GPUS=0,1 ./infra/fairuse/gpu-fairuse2.sh check`
Expected: `fairuse: GO GPU0: ... / fairuse: GO GPU1: ...`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add infra/fairuse tests/unit/test_fairuse_contract.py
git commit -m "feat(infra): two-GPU fair-use guard with foreign-process detection"
```

---

### Task 6: Quarantine guardrails

**What is and is not a boundary — be honest about this.** Permission deny rules
match patterns and an agent can construct paths around them; they stop accidents,
not determination. `sandbox.filesystem.denyRead` is kernel-enforced but only for
sandboxed commands. The real guarantees are two structural facts: real data exists
only on the HPC box inside AI-free windows, and **`local/quarantine/` on the
workstation stays empty**. The last one is assertable, so we assert it.

`bwrap` and `socat` are present on this workstation, so the sandbox is available.

**Files:**
- Create: `.claude/settings.json` (project-scoped, committed)
- Modify: `Makefile` — add `check-clean`
- Test: `tests/unit/test_data_guards.py`

- [ ] **Step 1: Write the project settings**

`.claude/settings.local.json` already exists with personal allow rules — leave it
alone. Deny rules belong in the committed project file so they are part of the
repo's guarantees rather than one machine's preference.

```json
{
  "permissions": {
    "deny": [
      "Read(./local/quarantine/**)",
      "Read(/<data-dir>/recall-quarantine/**)",
      "Read(/<export-dir>/**)",
      "Read(**/*.syn)",
      "Bash(cat ./local/quarantine/*)",
      "Bash(head ./local/quarantine/*)",
      "Bash(tail ./local/quarantine/*)",
      "Bash(less ./local/quarantine/*)",
      "Bash(grep * ./local/quarantine/*)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "denyRead": [
        "./local/quarantine",
        "<data-dir>/recall-quarantine",
        "<export-dir>"
      ]
    }
  }
}
```

`sandbox.allowUnsandboxedCommands` is deliberately left at its default. Setting it
to `false` would harden the read-deny, but this project's dev loop needs `ssh` to
the HPC box and the Docker socket, both of which the sandbox restricts — the
friction would get the sandbox switched off entirely, which is worse. The Bash
deny rules above are accident-prevention with no pretence of completeness.

- [ ] **Step 2: Add the emptiness assertion to the Makefile**

```makefile
check-clean:
	@if [ -n "$$(find local/quarantine -mindepth 1 -print -quit 2>/dev/null)" ]; then \
	  echo "FAIL: local/quarantine is not empty. The workstation must never hold"; \
	  echo "      real or derived corpus data. Inspect it yourself, shred it, and"; \
	  echo "      do not read it with an AI tool."; \
	  find local/quarantine -mindepth 1 -type f -printf '  %p (%s bytes)\n'; \
	  exit 1; \
	fi
	@echo "local/quarantine is empty - workstation clean"
```

It prints paths and sizes, never content — enough to act on, safe to read.

- [ ] **Step 3: Write the guard test**

```python
# tests/unit/test_data_guards.py
import json
import pathlib
import subprocess

SETTINGS = pathlib.Path(".claude/settings.json")
GITIGNORE = pathlib.Path(".gitignore")


def test_quarantine_is_denied_for_read_and_sandbox():
    cfg = json.loads(SETTINGS.read_text())
    deny = cfg["permissions"]["deny"]
    assert "Read(./local/quarantine/**)" in deny
    assert "./local/quarantine" in cfg["sandbox"]["filesystem"]["denyRead"]


def test_gitignore_blocks_every_data_shape():
    patterns = GITIGNORE.read_text()
    for pattern in ("local/", "*.csv", "*.npy", "*.jsonl", "*.syn", "profile.json"):
        assert pattern in patterns, f"{pattern} missing from .gitignore"


def test_no_data_file_is_tracked_by_git():
    """The strongest available check: ask git what it actually tracks."""
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    offenders = [
        f for f in tracked
        if f.endswith((".csv", ".tsv", ".npy", ".npz", ".pkl", ".jsonl", ".parquet", ".syn"))
        or f.endswith(("profile.json", "eval_real.json"))
    ]
    assert not offenders, f"data files are tracked by git: {offenders}"


def test_repo_has_no_remote():
    """No remote means no accidental push of anything, ever."""
    remotes = subprocess.run(
        ["git", "remote"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert remotes == [], f"unexpected git remote configured: {remotes}"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_data_guards.py -v && make check-clean`
Expected: PASS, 4 tests, then `local/quarantine is empty - workstation clean`.

- [ ] **Step 5: Verify the deny rule is actually live**

```bash
mkdir -p local/quarantine && printf 'sentinel\n' > local/quarantine/probe.txt
```

Now attempt to Read `local/quarantine/probe.txt` with the Read tool.
Expected: denied by permission rule. If it is *not* denied, the settings watcher
did not pick up the new file — open `/hooks` once or restart, then retest before
continuing. Clean up with `rm -f local/quarantine/probe.txt`.

- [ ] **Step 6: Commit**

```bash
git add .claude/settings.json Makefile tests/unit/test_data_guards.py
git commit -m "chore: deny quarantine reads, assert no tracked data and no remote"
```

---

## Milestone 0 acceptance criteria

- [ ] `make db-up migrate test lint` passes from a clean clone.
- [ ] `uv run pytest tests/integration/test_german_fts.py -v` — **all `de_tech`
      compound and umlaut cases pass.** This is the gate; if it fails, Task 4
      Step 5 applies and the lexical-arm design changes.
- [ ] The `de_tech_ua` comparison result is recorded in the design doc, settling
      the §7 ordering question empirically.
- [ ] `make db-reset` reproduces the full schema from zero.
- [ ] `./infra/fairuse/gpu-fairuse2.sh check` reports GO/DEFER per GPU and
      correctly DEFERs a GPU carrying a foreign process.
- [ ] A `.csv` in the repo root cannot be staged by `git add .`.
- [ ] Migrations apply identically on the workstation and on the HPC box
      (run `make migrate` against a podman-hosted instance there).

---

# Milestone 1 — Profiler and Window A

**The highest-stakes milestone.** The profiler runs by hand, unattended, with no
AI available to debug it, and every omission costs a full airlock cycle. It must
be comprehensive on the first run and validate its own output.

### The safety invariant

**Every free-text string the profiler emits must be either (a) a regex/shape from
a fixed allowlist, or (b) a token whose corpus frequency ≥ `MIN_FREQ` (default
50).** Rare terms are where identifying information hides. Additionally, a hard
column denylist — `merchantName`, `endCustomerName`, `contactEmail`,
`contactPhone`, `contactPhoneTrimmed`, `merchantPhoneNumber`,
`endCustomerPhoneNumber`, `endCustomerNumber`, `merchantNumber`,
`vehicleSerialNo`, `personId`, `lastModifiedUser` — never has *any* value emitted
at any frequency, only lengths, null rates and cardinality estimates.

`profiler/selfcheck.py` enforces both mechanically and refuses to write the
artifact on violation. This single rule is what makes `profile.json` safe to read,
rather than case-by-case judgment.

### Profile schema — review this before Window A

| Section | Fields | Why it's needed |
|---|---|---|
| `source` | filename, sha256, bytes, row_count, encoding, delimiter, columns_found, columns_expected_missing, columns_unexpected | reproducibility; catches export drift against the brief's 38 columns |
| `per_field.<col>` | present/null/empty counts, distinct-count estimate, char + token length quantiles (p1…p999, max), **post-clean** length quantiles, all_caps rate, no_punctuation rate, html rate, quoted_chain rate, signature rate, diag_dump rate | §12.4 chunking rule, §8 noise rates, cleaner calibration |
| `per_field.<col>.top_values` | value + count, **only** for low-cardinality non-denylisted enum/ID columns, cardinality-capped | dimension proxies for the missing lookup tables |
| `null_mask_patterns` | top-N *joint* masks with counts and shares | §8 correlated missingness — per-column rates are not enough |
| `identifier_grammars` | kind, regex, count, share, shape string, charset | §8 grammar-based generation; feeds `german/identifiers.py` |
| `model_designations` | grammar, inferred family rule, family count, models-per-family quantiles | family-boost proxy without the client's hierarchy |
| `dimension_hints.<idcol>` | per ID: count + top non-rare tokens from its tickets | infers "category 7 ≈ Hydraulik" without seeing a row |
| `temporal` | created-per-month histogram, age quantiles | recency-decay calibration (§14) |
| `solutions` | fill_rate, nonempty_after_clean_rate, **cardinality** (single field vs multi-entry, detected separator, entries-per-ticket quantiles), junk taxonomy with counts, usable_rate_estimate, token length quantiles | **answers §12.1 and §12.2 — the two gating decisions** |
| `clusters` | method, threshold, cluster_count, singleton_count, size distribution + quantiles, Zipf α estimate | §8's cluster structure — without it the synthetic set has no gold labels |
| `vocabulary` | total/distinct tokens, top tokens, top bigrams, **hunspell-unrecognised top tokens**, min_frequency_threshold | §7 synonym mining input |
| `multi_fault_estimate` | heuristic description + rate | §12.4 decomposition risk |
| `selfcheck` | passed, checks run, warnings | the artifact attests to its own safety |

### Task 7: Profile JSON Schema and the stand-in CSV

The profiler is developed against a **stand-in CSV** carrying the exact 38-column
header with obviously fake content, so the code is exercised long before Window A.

**The stand-in is built at test runtime into `tmp_path`, never committed.** Data
rule 1 admits no exceptions, not even for synthetic fixtures — and generating it in
a fixture is better test design anyway, since it can be parameterised per test.

**Files:**
- Create: `profiler/schema.json`
- Create: `profiler/columns.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_profile_schema.py`

- [ ] **Step 1: Write the JSON Schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "recall ticket corpus profile",
  "type": "object",
  "required": ["schema_version", "source", "per_field", "null_mask_patterns",
               "identifier_grammars", "solutions", "clusters", "vocabulary", "selfcheck"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"const": "1"},
    "source": {
      "type": "object",
      "required": ["filename", "sha256", "bytes", "row_count", "columns_found"],
      "properties": {
        "filename": {"type": "string"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "bytes": {"type": "integer", "minimum": 0},
        "row_count": {"type": "integer", "minimum": 0},
        "encoding_detected": {"type": "string"},
        "delimiter": {"type": "string", "maxLength": 1},
        "columns_found": {"type": "array", "items": {"type": "string"}},
        "columns_expected_missing": {"type": "array", "items": {"type": "string"}},
        "columns_unexpected": {"type": "array", "items": {"type": "string"}}
      }
    },
    "per_field": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["present_count", "null_count", "empty_string_count"],
        "properties": {
          "present_count": {"type": "integer"},
          "null_count": {"type": "integer"},
          "empty_string_count": {"type": "integer"},
          "distinct_count_estimate": {"type": "integer"},
          "char_len_quantiles": {"$ref": "#/$defs/quantiles"},
          "token_len_quantiles": {"$ref": "#/$defs/quantiles"},
          "cleaned_char_len_quantiles": {"$ref": "#/$defs/quantiles"},
          "cleaned_token_len_quantiles": {"$ref": "#/$defs/quantiles"},
          "all_caps_rate": {"$ref": "#/$defs/rate"},
          "no_punctuation_rate": {"$ref": "#/$defs/rate"},
          "html_rate": {"$ref": "#/$defs/rate"},
          "quoted_chain_rate": {"$ref": "#/$defs/rate"},
          "signature_rate": {"$ref": "#/$defs/rate"},
          "diag_dump_rate": {"$ref": "#/$defs/rate"},
          "top_values": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["value", "count"],
              "properties": {"value": {"type": "string"}, "count": {"type": "integer"}}
            }
          }
        }
      }
    },
    "null_mask_patterns": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["columns_null", "count", "share"],
        "properties": {
          "columns_null": {"type": "array", "items": {"type": "string"}},
          "count": {"type": "integer"},
          "share": {"$ref": "#/$defs/rate"}
        }
      }
    },
    "identifier_grammars": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["kind", "regex", "count", "share"],
        "properties": {
          "kind": {"enum": ["error_code", "part_number", "serial_number",
                            "model_designation", "measurement", "other"]},
          "regex": {"type": "string"},
          "shape": {"type": "string"},
          "charset": {"type": "string"},
          "count": {"type": "integer"},
          "share": {"$ref": "#/$defs/rate"}
        }
      }
    },
    "model_designations": {
      "type": "object",
      "properties": {
        "grammar": {"type": "array", "items": {"type": "string"}},
        "inferred_family_rule": {"type": "string"},
        "family_count": {"type": "integer"},
        "models_per_family_quantiles": {"$ref": "#/$defs/quantiles"}
      }
    },
    "dimension_hints": {
      "type": "object",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["id", "count"],
          "properties": {
            "id": {"type": ["string", "integer", "null"]},
            "count": {"type": "integer"},
            "top_tokens": {"type": "array", "items": {"type": "string"}}
          }
        }
      }
    },
    "temporal": {
      "type": "object",
      "properties": {
        "created_per_month": {"type": "object", "additionalProperties": {"type": "integer"}},
        "age_years_quantiles": {"$ref": "#/$defs/quantiles"}
      }
    },
    "solutions": {
      "type": "object",
      "required": ["fill_rate", "nonempty_after_clean_rate", "cardinality",
                   "junk_taxonomy", "usable_rate_estimate"],
      "properties": {
        "fill_rate": {"$ref": "#/$defs/rate"},
        "nonempty_after_clean_rate": {"$ref": "#/$defs/rate"},
        "cardinality": {
          "type": "object",
          "required": ["single_field"],
          "properties": {
            "single_field": {"type": "boolean"},
            "detected_separator": {"type": ["string", "null"]},
            "entries_per_ticket_quantiles": {"$ref": "#/$defs/quantiles"}
          }
        },
        "junk_taxonomy": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["pattern", "count", "share"],
            "properties": {
              "pattern": {"type": "string"},
              "count": {"type": "integer"},
              "share": {"$ref": "#/$defs/rate"}
            }
          }
        },
        "usable_rate_estimate": {"$ref": "#/$defs/rate"},
        "token_len_quantiles": {"$ref": "#/$defs/quantiles"}
      }
    },
    "clusters": {
      "type": "object",
      "required": ["method", "threshold", "cluster_count", "singleton_count", "size_distribution"],
      "properties": {
        "method": {"type": "string"},
        "threshold": {"type": "number"},
        "cluster_count": {"type": "integer"},
        "singleton_count": {"type": "integer"},
        "size_distribution": {"type": "object", "additionalProperties": {"type": "integer"}},
        "size_quantiles": {"$ref": "#/$defs/quantiles"},
        "zipf_alpha_estimate": {"type": ["number", "null"]}
      }
    },
    "vocabulary": {
      "type": "object",
      "required": ["total_tokens", "distinct_tokens", "min_frequency_threshold", "top_tokens"],
      "properties": {
        "total_tokens": {"type": "integer"},
        "distinct_tokens": {"type": "integer"},
        "min_frequency_threshold": {"type": "integer", "minimum": 2},
        "top_tokens": {"$ref": "#/$defs/token_counts"},
        "top_bigrams": {"$ref": "#/$defs/token_counts"},
        "hunspell_unrecognized_top": {"$ref": "#/$defs/token_counts"}
      }
    },
    "multi_fault_estimate": {
      "type": "object",
      "properties": {
        "heuristic": {"type": "string"},
        "rate": {"$ref": "#/$defs/rate"}
      }
    },
    "selfcheck": {
      "type": "object",
      "required": ["passed", "checks"],
      "properties": {
        "passed": {"type": "boolean"},
        "checks": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  "$defs": {
    "rate": {"type": "number", "minimum": 0, "maximum": 1},
    "quantiles": {
      "type": "object",
      "additionalProperties": {"type": "number"},
      "required": ["p50", "p95", "max"]
    },
    "token_counts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["token", "count"],
        "properties": {"token": {"type": "string"}, "count": {"type": "integer", "minimum": 2}}
      }
    }
  }
}
```

- [ ] **Step 2: Write the single source of truth for the export columns**

```python
# profiler/columns.py
"""The export's columns per PROJECT_BRIEF.md §4. Schema names only - these are
published in the brief and carry no corpus content, so they are safe to commit."""

EXPECTED_COLUMNS = [
    "id", "userCreatedId", "userAssignedId", "statusId", "priorityId", "personId",
    "title", "description", "vehicleYear", "customData", "merchantName",
    "endCustomerName", "timestampCreated", "categoryId", "deadline", "merchantId",
    "endCustomerId", "vehicleHours", "vehicleSerialNo", "vehicleId", "vehicleModelId",
    "solutions", "vehicleStatus", "contactEmail", "contactPhone", "ticketNumber",
    "vehicleSerialIndex", "merchantNumber", "merchantPhoneNumber", "endCustomerNumber",
    "endCustomerPhoneNumber", "contactPhoneTrimmed", "showInProteam",
    "contractTransaction", "contractItems", "lastModifiedUser", "subStatusString",
    "subStatusChanged",
]

TEXT_COLUMNS = ["title", "description", "solutions", "customData"]
DIMENSION_COLUMNS = ["statusId", "categoryId", "priorityId", "vehicleModelId",
                     "subStatusString", "vehicleStatus", "showInProteam"]
MAX_DIMENSION_CARDINALITY = 200
```

- [ ] **Step 3: Write the failing test**

```python
# tests/unit/test_profile_schema.py
import json
import pathlib

import jsonschema

from profiler.columns import EXPECTED_COLUMNS

SCHEMA = pathlib.Path("profiler/schema.json")


def test_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(json.loads(SCHEMA.read_text()))


def test_expected_columns_count_matches_brief():
    assert len(EXPECTED_COLUMNS) == 38
    assert len(set(EXPECTED_COLUMNS)) == 38, "duplicate column name"


def test_standin_csv_has_the_exact_export_header(standin_csv):
    header = standin_csv.read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == EXPECTED_COLUMNS


def test_standin_csv_is_not_on_disk_in_the_repo():
    """Data rule 1: no fixture file may exist inside the working tree."""
    assert not list(pathlib.Path("tests").rglob("*.csv"))
```

- [ ] **Step 4: Run it to confirm it fails**

Run: `uv run pytest tests/unit/test_profile_schema.py -v`
Expected: FAIL — `fixture 'standin_csv' not found`.

- [ ] **Step 5: Write the runtime fixture**

```python
# tests/conftest.py
"""Synthetic stand-in export, built per test session into tmp_path.

Nothing is written into the working tree - see the plan's data handling rules.
The seed is fixed so failures are reproducible; the product line is deliberately
fictional (TX-22xx / LR-45) so any real value showing up here is obvious.
"""
import csv
import pathlib
import random

import pytest

from profiler.columns import EXPECTED_COLUMNS

SEED = 20260804
ROWS = 400

FAULTS = [
    ("Hydraulikpumpe baut keinen Druck auf", "F1247", "Druck geprueft, Pumpe getauscht"),
    ("Getriebe schaltet nicht", "F2013", "Getr. Oel gewechselt"),
    ("Kuehlwasserverlust am Motor", "F0891", "Schlauch ersetzt"),
    ("Bremsleitung undicht", "F3402", "erledigt"),
    ("Motor startet nicht", "F0102", ""),
]


def build_standin(path: pathlib.Path, rows: int = ROWS, drop_column: str | None = None) -> pathlib.Path:
    columns = [c for c in EXPECTED_COLUMNS if c != drop_column]
    rng = random.Random(SEED)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for i in range(1, rows + 1):
            title, code, solution = FAULTS[i % len(FAULTS)]
            tail = "\n> Am 12.03.2019 schrieb Test:\n> alter Text\n" * (40 if i % 97 == 0 else 0)
            row = dict.fromkeys(columns, "")
            row.update(
                {
                    k: v
                    for k, v in {
                        "id": i,
                        "ticketNumber": f"TN-{100000 + i}",
                        "title": title,
                        "description": (
                            f"{title}. Fehlercode {code}.{tail}"
                            "\n\nMit freundlichen Gruessen\nTestperson"
                        ),
                        "solutions": solution,
                        "statusId": rng.choice([1, 2, 3]),
                        "categoryId": rng.choice([5, 7, 9]),
                        "priorityId": rng.choice([1, 2]),
                        "vehicleModelId": rng.choice(["TX-2210", "TX-2240", "LR-45"]),
                        "vehicleYear": rng.choice([2012, 2016, 2020]),
                        "vehicleHours": rng.randint(50, 9000),
                        "timestampCreated": (
                            f"20{rng.randint(14, 25)}-0{rng.randint(1, 9)}-"
                            f"1{rng.randint(0, 9)} 08:30:00"
                        ),
                        "merchantName": "Musterhaendler GmbH",
                        "endCustomerName": "Beispielkunde AG",
                        "contactEmail": "test@example.invalid",
                        "contactPhone": "+43 000 0000000",
                        "vehicleSerialNo": f"SN{rng.randint(10000, 99999)}",
                        "showInProteam": rng.choice(["true", "false"]),
                        "subStatusString": rng.choice(["offen", "in Bearbeitung", "erledigt"]),
                    }.items()
                    if k in row
                }
            )
            writer.writerow(row)
    return path


@pytest.fixture(scope="session")
def standin_csv(tmp_path_factory) -> pathlib.Path:
    return build_standin(tmp_path_factory.mktemp("standin") / "export.csv")
```

- [ ] **Step 6: Run the tests**

```bash
mkdir -p profiler tests
uv run pytest tests/unit/test_profile_schema.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 7: Commit**

```bash
git add profiler/schema.json profiler/columns.py tests/conftest.py \
        tests/unit/test_profile_schema.py
git commit -m "feat(profiler): profile schema, column contract, runtime-built stand-in"
```

No `git add -f` anywhere — nothing data-shaped is being committed.

---

### Task 8: Cleaning pipeline

Needed by the profiler for post-clean length quantiles and noise rates, so it
comes before the stats modules.

**Files:**
- Create: `src/recall/clean/{__init__,html,reply_chains,signatures,dumps,pii,pipeline}.py`
- Test: `tests/unit/test_clean.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_clean.py
from recall.clean import pipeline

QUOTED = """Die Pumpe baut keinen Druck auf.

Von: Kunde <k@example.invalid>
Gesendet: Montag, 12. März 2019 14:23
An: Service
Betreff: AW: Störung

> alter Text der nicht indexiert werden soll
> noch mehr alter Text
"""

SIGNED = """Getriebe schaltet nicht.

Mit freundlichen Grüßen
Hans Beispiel
Servicetechniker
Tel: +43 512 123456
"""

DUMP = """Fehler nach Neustart.

ECU_STATE = 0x1F
RPM_MAX = 2400
OIL_TEMP = 91
COOLANT = 88
VOLT_BAT = 13.9
ERR_COUNT = 12
"""


def test_strips_quoted_reply_chain():
    out = pipeline.clean(QUOTED)
    assert "Pumpe baut keinen Druck" in out.text
    assert "alter Text" not in out.text
    assert out.report.had_quoted_chain


def test_strips_signature_but_keeps_problem():
    out = pipeline.clean(SIGNED)
    assert "Getriebe schaltet nicht" in out.text
    assert "Hans Beispiel" not in out.text
    assert out.report.had_signature


def test_detects_diagnostic_dump_without_deleting_it():
    out = pipeline.clean(DUMP)
    assert out.report.had_diag_dump
    assert "ECU_STATE" in out.text, "dumps are flagged, not removed - they carry error state"


def test_strips_html_tags():
    out = pipeline.clean("<p>Pumpe <b>defekt</b></p>")
    assert out.text.strip() == "Pumpe defekt"
    assert out.report.had_html


def test_redacts_pii_but_preserves_error_codes():
    out = pipeline.clean("Fehler F1247, Rückfragen an hans@example.invalid oder +43 512 123456")
    assert "F1247" in out.text
    assert "hans@example.invalid" not in out.text
    assert "512 123456" not in out.text


def test_clean_is_idempotent():
    once = pipeline.clean(QUOTED).text
    assert pipeline.clean(once).text == once


def test_empty_and_none_safe():
    assert pipeline.clean("").text == ""
    assert pipeline.clean(None).text == ""
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_clean.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recall.clean'`.

- [ ] **Step 3: Implement `html.py`**

```python
# src/recall/clean/html.py
import html as _html
import re

from selectolax.parser import HTMLParser

_TAGGY = re.compile(r"<[a-z/!][^>]{0,200}>", re.IGNORECASE)


def looks_like_html(text: str) -> bool:
    return bool(_TAGGY.search(text))


def strip_html(text: str) -> str:
    if not looks_like_html(text):
        return text
    parsed = HTMLParser(text)
    out = parsed.text(separator=" ") if parsed.body is not None else _TAGGY.sub(" ", text)
    return _html.unescape(out)
```

- [ ] **Step 4: Implement `reply_chains.py`**

```python
# src/recall/clean/reply_chains.py
import re

# German and English mail-client boundaries. Everything from the first hit onward
# is a previous message, not this ticket's problem statement.
_BOUNDARIES = [
    re.compile(r"^\s*-{2,}\s*Urspr(ü|ue)ngliche Nachricht\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Von:\s+.+$", re.MULTILINE),
    re.compile(r"^\s*From:\s+.+$", re.MULTILINE),
    re.compile(r"^\s*Am\s+\d{1,2}\.\d{1,2}\.\d{2,4}.{0,40}schrieb\b", re.MULTILINE),
    re.compile(r"^\s*On\s+.{5,60}\bwrote:\s*$", re.MULTILINE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
]
_QUOTED_LINE = re.compile(r"^\s*>.*$", re.MULTILINE)


def has_quoted_chain(text: str) -> bool:
    return bool(_QUOTED_LINE.search(text)) or any(b.search(text) for b in _BOUNDARIES)


def strip_quoted_chain(text: str) -> str:
    cut = len(text)
    for boundary in _BOUNDARIES:
        m = boundary.search(text)
        if m and m.start() < cut:
            cut = m.start()
    head = text[:cut]
    return _QUOTED_LINE.sub("", head)
```

- [ ] **Step 5: Implement `signatures.py`**

```python
# src/recall/clean/signatures.py
import re

_GRUSS = re.compile(
    r"^\s*(mit freundlichen gr(ü|ue)(ß|ss)en|freundliche gr(ü|ue)(ß|ss)e|mfg|lg|"
    r"beste gr(ü|ue)(ß|ss)e|viele gr(ü|ue)(ß|ss)e|best regards|kind regards)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_DASH_SIG = re.compile(r"^--\s*$", re.MULTILINE)


def has_signature(text: str) -> bool:
    return bool(_GRUSS.search(text) or _DASH_SIG.search(text))


def strip_signature(text: str) -> str:
    cut = len(text)
    for pattern in (_GRUSS, _DASH_SIG):
        m = pattern.search(text)
        if m and m.start() < cut:
            cut = m.start()
    return text[:cut]
```

- [ ] **Step 6: Implement `dumps.py`**

```python
# src/recall/clean/dumps.py
import re

_KV_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}\s*[:=]\s*\S+\s*$")
_MIN_RUN = 4


def has_diagnostic_dump(text: str) -> bool:
    """A run of machine-formatted KEY = VALUE lines. Flagged, never deleted: the
    error state in a dump is often the most retrievable thing in the ticket."""
    run = 0
    for line in text.splitlines():
        run = run + 1 if _KV_LINE.match(line) else 0
        if run >= _MIN_RUN:
            return True
    return False
```

- [ ] **Step 7: Implement `pii.py`**

```python
# src/recall/clean/pii.py
import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}\b")
# Requires a separator or leading + so that bare identifiers like F1247 survive.
_PHONE = re.compile(r"(?:\+\d{1,3}[\s/.-]?)?(?:\(?\d{2,5}\)?[\s/.-]){1,3}\d{3,}")
_URL = re.compile(r"https?://\S+")

REDACTIONS = (
    (_EMAIL, "[EMAIL]"),
    (_IBAN, "[IBAN]"),
    (_URL, "[URL]"),
    (_PHONE, "[TEL]"),
)


def redact(text: str) -> str:
    for pattern, token in REDACTIONS:
        text = pattern.sub(token, text)
    return text
```

- [ ] **Step 8: Implement `pipeline.py`**

```python
# src/recall/clean/pipeline.py
from __future__ import annotations

import re
from dataclasses import dataclass

from recall.clean import dumps, html, pii, reply_chains, signatures

_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class CleanReport:
    had_html: bool = False
    had_quoted_chain: bool = False
    had_signature: bool = False
    had_diag_dump: bool = False
    is_all_caps: bool = False
    has_no_punctuation: bool = False
    original_chars: int = 0
    cleaned_chars: int = 0


@dataclass(frozen=True)
class Cleaned:
    text: str
    report: CleanReport


def clean(text: str | None) -> Cleaned:
    original = text or ""
    report_kwargs = {
        "had_html": html.looks_like_html(original),
        "had_quoted_chain": reply_chains.has_quoted_chain(original),
        "had_signature": signatures.has_signature(original),
        "had_diag_dump": dumps.has_diagnostic_dump(original),
        "is_all_caps": bool(original.strip()) and original == original.upper()
        and any(c.isalpha() for c in original),
        "has_no_punctuation": bool(original.strip()) and not any(c in ".!?;" for c in original),
        "original_chars": len(original),
    }
    out = html.strip_html(original)
    out = reply_chains.strip_quoted_chain(out)
    out = signatures.strip_signature(out)
    out = pii.redact(out)
    out = _BLANKS.sub("\n\n", _WS.sub(" ", out)).strip()
    return Cleaned(text=out, report=CleanReport(cleaned_chars=len(out), **report_kwargs))
```

- [ ] **Step 9: Run the tests**

```bash
mkdir -p src/recall/clean && touch src/recall/clean/__init__.py
uv run pytest tests/unit/test_clean.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 10: Commit**

```bash
git add src/recall/clean tests/unit/test_clean.py
git commit -m "feat(clean): German reply-chain, signature, HTML, dump and PII handling"
```

---

### Task 9: Identifier extraction and grammar inference

**Files:**
- Create: `src/recall/german/{__init__,identifiers}.py`
- Test: `tests/unit/test_identifiers.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_identifiers.py
from recall.german import identifiers


def test_extracts_error_codes():
    found = identifiers.extract("Fehlercode F1247 und F1248 gemeldet")
    codes = {i.value for i in found if i.kind == "error_code"}
    assert codes == {"F1247", "F1248"}


def test_distinguishes_near_identical_codes():
    assert identifiers.extract("F1247")[0].value != identifiers.extract("F1248")[0].value


def test_extracts_model_designation():
    found = identifiers.extract("Maschine TX-2240 in Werkstatt")
    assert any(i.kind == "model_designation" and i.value == "TX-2240" for i in found)


def test_ignores_plain_german_words():
    assert identifiers.extract("Die Pumpe ist defekt") == []


def test_shape_is_not_the_value():
    shape = identifiers.shape_of("F1247")
    assert shape == "ADDDD"
    assert "1247" not in shape


def test_shape_abstracts_every_digit_of_a_model_designation():
    assert identifiers.shape_of("TX-2240") == "AL-DDDD"


def test_grammar_inference_counts_shapes():
    grammars = identifiers.infer_grammars(["F1247", "F1248", "F0891", "TX-2240"])
    by_shape = {g["shape"]: g["count"] for g in grammars}
    assert by_shape["ADDDD"] == 3


def test_family_rule_groups_sibling_models():
    assert identifiers.model_family("TX-2240") == identifiers.model_family("TX-2210")
    assert identifiers.model_family("TX-2240") != identifiers.model_family("LR-45")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_identifiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recall.german'`.

- [ ] **Step 3: Implement**

```python
# src/recall/german/identifiers.py
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("error_code", re.compile(r"\b[A-Z]{1,3}\d{3,5}\b")),
    ("model_designation", re.compile(r"\b[A-Z]{2,3}-\d{2,4}[A-Z]?\b")),
    ("part_number", re.compile(r"\b\d{3,4}[.\-/]\d{3,5}(?:[.\-/]\d{1,4})?\b")),
    ("serial_number", re.compile(r"\b[A-Z]{2}\d{5,10}\b")),
]


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    start: int
    end: int


def extract(text: str | None) -> list[Identifier]:
    """Longest-match-wins so a model designation is not also read as an error code."""
    if not text:
        return []
    claimed: list[Identifier] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < c.end and c.start < m.end() for c in claimed):
                continue
            claimed.append(Identifier(kind, m.group(0), m.start(), m.end()))
    return sorted(claimed, key=lambda i: i.start)


def shape_of(value: str) -> str:
    """Structure without content: A=uppercase, a=lowercase, D=digit, L=literal-ish.

    'F1247' -> 'ADDDD' keeps the leading-letter/four-digit structure while
    discarding every digit, so shapes are safe to emit from the profiler."""
    out = []
    for i, ch in enumerate(value):
        if ch.isdigit():
            out.append("D")
        elif ch.isupper():
            out.append("A" if i == 0 else "L")
        elif ch.islower():
            out.append("a")
        else:
            out.append(ch)
    return "".join(out)


def infer_grammars(values: list[str]) -> list[dict]:
    counts: Counter[tuple[str, str]] = Counter()
    for v in values:
        kinds = {i.kind for i in extract(v)} or {"other"}
        counts[(next(iter(kinds)), shape_of(v))] += 1
    total = sum(counts.values()) or 1
    return [
        {
            "kind": kind,
            "shape": shape,
            "regex": _shape_to_regex(shape),
            "count": count,
            "share": count / total,
        }
        for (kind, shape), count in counts.most_common()
    ]


def _shape_to_regex(shape: str) -> str:
    mapping = {"A": "[A-Z]", "L": "[A-Z]", "a": "[a-z]", "D": r"\d"}
    return "^" + "".join(mapping.get(c, re.escape(c)) for c in shape) + "$"


_FAMILY = re.compile(r"^([A-Z]{2,3})-?(\d{2})")


def model_family(designation: str) -> str | None:
    """Proxy for the client's missing model hierarchy: prefix plus the first two
    digits. 'TX-2240' and 'TX-2210' share family 'TX-22'."""
    m = _FAMILY.match(designation.strip().upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None
```

- [ ] **Step 4: Run the tests**

```bash
mkdir -p src/recall/german && touch src/recall/german/__init__.py
uv run pytest tests/unit/test_identifiers.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/recall/german tests/unit/test_identifiers.py
git commit -m "feat(german): identifier extraction, safe shape inference, family proxy"
```

---

### Task 10: Profiler statistics modules

**Files:**
- Create: `profiler/__init__.py`, `profiler/stats/*.py`
- Test: `tests/unit/test_profiler_stats.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_profiler_stats.py
from profiler.stats import clusters, lengths, nullmask, solutions, vocab


def test_quantiles_include_pathological_tail():
    q = lengths.quantiles([1] * 99 + [100_000])
    assert q["p50"] == 1
    assert q["max"] == 100_000
    assert set(q) >= {"p1", "p5", "p25", "p50", "p75", "p90", "p95", "p99", "p999", "max"}


def test_quantiles_of_empty_is_zeroed_not_an_error():
    assert lengths.quantiles([])["p50"] == 0


def test_joint_null_masks_capture_correlation():
    rows = [{"a": "x", "b": ""}, {"a": "x", "b": ""}, {"a": "", "b": ""}]
    patterns = nullmask.joint_patterns(rows, ["a", "b"], top_n=5)
    assert patterns[0]["columns_null"] == ["b"]
    assert patterns[0]["count"] == 2


def test_vocab_prunes_rare_tokens():
    counts = vocab.token_counts(["pumpe defekt"] * 60 + ["geheimnisvollerEigenname"])
    top = vocab.top_tokens(counts, min_frequency=50)
    tokens = {t["token"] for t in top}
    assert "pumpe" in tokens
    assert "geheimnisvollereigenname" not in tokens


def test_solutions_detects_single_field_vs_multi_entry():
    single = solutions.cardinality(["Pumpe getauscht", "Oel gewechselt"])
    assert single["single_field"] is True
    multi = solutions.cardinality(["1) geprueft ||| 2) getauscht", "1) gemessen ||| 2) ersetzt"])
    assert multi["single_field"] is False
    assert multi["detected_separator"] == "|||"


def test_solutions_junk_taxonomy_counts_known_junk():
    taxonomy = solutions.junk_taxonomy(["erledigt", "siehe Telefonat", "", "Pumpe getauscht"])
    by_pattern = {t["pattern"]: t["count"] for t in taxonomy}
    assert by_pattern[solutions.JUNK_DONE] == 1
    assert by_pattern[solutions.JUNK_SEE_CALL] == 1


def test_cluster_size_distribution_is_zipfian_shaped():
    docs = ["hydraulikpumpe baut keinen druck auf"] * 8 + ["getriebe schaltet nicht"] * 3 + ["einzelfall xyz"]
    result = clusters.profile(docs, threshold=0.7)
    assert result["cluster_count"] >= 2
    assert result["size_distribution"]["8"] == 1
    assert result["singleton_count"] >= 1
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_profiler_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.stats'`.

- [ ] **Step 3: Implement `lengths.py`**

```python
# profiler/stats/lengths.py
from __future__ import annotations

QUANTILE_POINTS = {"p1": 0.01, "p5": 0.05, "p25": 0.25, "p50": 0.50,
                   "p75": 0.75, "p90": 0.90, "p95": 0.95, "p99": 0.99, "p999": 0.999}


def quantiles(values: list[int | float]) -> dict[str, float]:
    """Nearest-rank quantiles. The pathological tail is the point, so max is
    always reported alongside p999."""
    if not values:
        return {name: 0.0 for name in (*QUANTILE_POINTS, "max")}
    ordered = sorted(values)
    n = len(ordered)
    out = {}
    for name, q in QUANTILE_POINTS.items():
        idx = min(n - 1, max(0, int(round(q * (n - 1)))))
        out[name] = float(ordered[idx])
    out["max"] = float(ordered[-1])
    return out
```

- [ ] **Step 4: Implement `nullmask.py`**

```python
# profiler/stats/nullmask.py
from __future__ import annotations

from collections import Counter


def _is_null(value: str | None) -> bool:
    return value is None or value.strip() == ""


def joint_patterns(rows: list[dict[str, str]], columns: list[str], top_n: int = 50) -> list[dict]:
    """Missingness is correlated - no vehicleSerialNo usually means no vehicleId -
    so joint masks are reported, not per-column rates."""
    counts: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        counts[tuple(c for c in columns if _is_null(row.get(c)))] += 1
    total = len(rows) or 1
    return [
        {"columns_null": list(mask), "count": count, "share": count / total}
        for mask, count in counts.most_common(top_n)
    ]
```

- [ ] **Step 5: Implement `vocab.py`**

```python
# profiler/stats/vocab.py
from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,}")
DEFAULT_MIN_FREQUENCY = 50


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN.finditer(text or "")]


def token_counts(texts: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(tokenize(text))
    return counts


def bigram_counts(texts: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        toks = tokenize(text)
        counts.update(f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False))
    return counts


def top_tokens(counts: Counter[str], min_frequency: int = DEFAULT_MIN_FREQUENCY,
               limit: int = 2000) -> list[dict]:
    """Rare terms are where identifying information hides, so they are pruned
    before anything is written. See the safety invariant in the plan."""
    return [
        {"token": token, "count": count}
        for token, count in counts.most_common()
        if count >= min_frequency
    ][:limit]
```

- [ ] **Step 6: Implement `solutions.py`**

```python
# profiler/stats/solutions.py
from __future__ import annotations

import re

from recall.clean import pipeline
from profiler.stats import lengths

JUNK_DONE = r"^(erledigt|fertig|ok|behoben|gelöst)\.?$"
JUNK_SEE_CALL = r"^(siehe|s\.)\s+(telefonat|telefon|anruf|mail|e-mail)\.?$"
JUNK_ONE_WORD = r"^\S{1,20}$"
JUNK_EMPTY = r"^\s*$"
JUNK_PATTERNS = [JUNK_EMPTY, JUNK_DONE, JUNK_SEE_CALL, JUNK_ONE_WORD]

CANDIDATE_SEPARATORS = ["|||", "\n---\n", ";;", "||", "\t"]
_ENTRY_PREFIX = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


def cardinality(values: list[str]) -> dict:
    """Answers PROJECT_BRIEF.md §12.1: is `solutions` one free-text field or a
    thread of attempts? Decided by separator prevalence, not by guessing."""
    non_empty = [v for v in values if v and v.strip()]
    for sep in CANDIDATE_SEPARATORS:
        hits = [v for v in non_empty if sep in v]
        if non_empty and len(hits) / len(non_empty) >= 0.10:
            per = [v.count(sep) + 1 for v in non_empty]
            return {"single_field": False, "detected_separator": sep,
                    "entries_per_ticket_quantiles": lengths.quantiles(per)}
    numbered = [v for v in non_empty if len(_ENTRY_PREFIX.findall(v)) >= 2]
    if non_empty and len(numbered) / len(non_empty) >= 0.10:
        per = [max(1, len(_ENTRY_PREFIX.findall(v))) for v in non_empty]
        return {"single_field": False, "detected_separator": "numbered-list",
                "entries_per_ticket_quantiles": lengths.quantiles(per)}
    return {"single_field": True, "detected_separator": None,
            "entries_per_ticket_quantiles": lengths.quantiles([1] * len(non_empty))}


def junk_taxonomy(values: list[str]) -> list[dict]:
    total = len(values) or 1
    out = []
    for pattern in JUNK_PATTERNS:
        rx = re.compile(pattern, re.IGNORECASE)
        count = sum(1 for v in values if rx.match((v or "").strip()))
        out.append({"pattern": pattern, "count": count, "share": count / total})
    return out


def profile(values: list[str]) -> dict:
    """Answers §12.2: fill rate and usable quality."""
    total = len(values) or 1
    filled = [v for v in values if v and v.strip()]
    cleaned = [pipeline.clean(v).text for v in filled]
    cleaned_nonempty = [c for c in cleaned if c.strip()]
    junk_rx = [re.compile(p, re.IGNORECASE) for p in JUNK_PATTERNS]
    usable = [c for c in cleaned_nonempty if not any(rx.match(c.strip()) for rx in junk_rx)]
    return {
        "fill_rate": len(filled) / total,
        "nonempty_after_clean_rate": len(cleaned_nonempty) / total,
        "cardinality": cardinality(values),
        "junk_taxonomy": junk_taxonomy(values),
        "usable_rate_estimate": len(usable) / total,
        "token_len_quantiles": lengths.quantiles([len(c.split()) for c in cleaned_nonempty]),
    }
```

- [ ] **Step 7: Implement `clusters.py`**

```python
# profiler/stats/clusters.py
from __future__ import annotations

from collections import Counter

from datasketch import MinHash, MinHashLSH

from profiler.stats import lengths, vocab


def _minhash(text: str, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for token in set(vocab.tokenize(text)):
        m.update(token.encode())
    return m


def profile(docs: list[str], threshold: float = 0.7, num_perm: int = 128) -> dict:
    """Near-duplicate cluster-size distribution. This is the piece people skip and
    the piece that makes the synthetic corpus useful: two tickets from the same
    cluster are relevant to each other, which is a free gold label."""
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    hashes = {}
    for i, doc in enumerate(docs):
        h = _minhash(doc, num_perm)
        hashes[i] = h
        lsh.insert(str(i), h)

    seen: set[int] = set()
    sizes: list[int] = []
    for i in range(len(docs)):
        if i in seen:
            continue
        members = {int(k) for k in lsh.query(hashes[i])} | {i}
        members -= seen
        seen |= members
        sizes.append(len(members))

    dist = Counter(sizes)
    return {
        "method": f"minhash-lsh(num_perm={num_perm}) over cleaned title+description",
        "threshold": threshold,
        "cluster_count": len(sizes),
        "singleton_count": dist.get(1, 0),
        "size_distribution": {str(k): v for k, v in sorted(dist.items())},
        "size_quantiles": lengths.quantiles(sizes),
        "zipf_alpha_estimate": _zipf_alpha(sizes),
    }


def _zipf_alpha(sizes: list[int]) -> float | None:
    """Hill estimator on cluster sizes >= 2. Reported so the generator can match
    the real long tail rather than producing uniform cluster sizes."""
    tail = sorted((s for s in sizes if s >= 2), reverse=True)
    if len(tail) < 5:
        return None
    import math

    xmin = tail[-1]
    return len(tail) / sum(math.log(s / xmin) for s in tail if s > xmin) if xmin else None
```

- [ ] **Step 8: Implement `temporal.py`**

Ages are measured against the newest row in the export, not against wall-clock
time, so the profile is reproducible from the same CSV forever.

```python
# profiler/stats/temporal.py
from __future__ import annotations

import datetime as dt
import re

_TS = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def _parse(value: str) -> dt.date | None:
    m = _TS.match(value or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def ages_in_years(timestamps: list[str]) -> list[float]:
    """Age relative to the newest row in the corpus. Feeds recency-decay
    calibration (PROJECT_BRIEF.md §14) and stays deterministic across runs."""
    dates = [d for d in (_parse(t) for t in timestamps) if d is not None]
    if not dates:
        return []
    newest = max(dates)
    return [(newest - d).days / 365.25 for d in dates]
```

- [ ] **Step 9: Implement `hunspell.py`**

This feeds the §7 synonym-mining list — the tokens hunspell cannot recognise are
exactly the dealer shorthand worth a synonym entry. It shells out to the local
`hunspell` binary; no network, and it degrades to an empty list with a warning
rather than failing the sealed run.

```python
# profiler/stats/hunspell.py
from __future__ import annotations

import shutil
import subprocess
from collections import Counter

MISSING_BINARY_WARNING = "hunspell binary unavailable; unrecognised-token mining skipped"


def available(dict_path: str | None) -> bool:
    return bool(dict_path) and shutil.which("hunspell") is not None


def unrecognized(
    counts: Counter[str], min_frequency: int, dict_path: str | None = "de_DE", limit: int = 500
) -> list[dict]:
    """Tokens hunspell does not recognise, pruned by min_frequency like every other
    emitted string. Rare unrecognised tokens are the likeliest to be names."""
    candidates = [t for t, c in counts.items() if c >= min_frequency]
    if not candidates or not available(dict_path):
        return []
    proc = subprocess.run(
        ["hunspell", "-l", "-d", str(dict_path)],
        input="\n".join(candidates) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        return []
    flagged = {line.strip().lower() for line in proc.stdout.splitlines() if line.strip()}
    return [
        {"token": t, "count": counts[t]}
        for t in sorted(flagged, key=lambda t: -counts.get(t, 0))
        if counts.get(t, 0) >= min_frequency
    ][:limit]
```

- [ ] **Step 10: Add tests for both modules**

Append to `tests/unit/test_profiler_stats.py`:

```python
from profiler.stats import hunspell, temporal


def test_ages_are_relative_to_the_newest_row_not_wall_clock():
    ages = temporal.ages_in_years(["2020-01-01 08:00:00", "2024-01-01 08:00:00"])
    assert max(ages) == pytest.approx(4.0, abs=0.02)
    assert min(ages) == 0.0


def test_ages_ignore_unparseable_timestamps():
    assert temporal.ages_in_years(["", "not a date", "2024-01-01"]) == [0.0]


def test_ages_of_empty_input_is_empty():
    assert temporal.ages_in_years([]) == []


def test_hunspell_returns_empty_without_a_dictionary():
    counts = Counter({"pumpe": 100})
    assert hunspell.unrecognized(counts, 50, dict_path=None) == []


def test_hunspell_prunes_below_min_frequency():
    counts = Counter({"xyzabc": 3})
    assert hunspell.unrecognized(counts, 50, dict_path="de_DE") == []
```

Add `import pytest` and `from collections import Counter` to the file's imports.

- [ ] **Step 11: Run the tests**

```bash
mkdir -p profiler/stats
touch profiler/__init__.py profiler/stats/__init__.py
uv run pytest tests/unit/test_profiler_stats.py -v
```

Expected: PASS, 12 tests.

- [ ] **Step 12: Commit**

```bash
git add profiler tests/unit/test_profiler_stats.py
git commit -m "feat(profiler): length, null-mask, vocab, solutions, cluster, temporal and hunspell stats"
```

---

### Task 11: Entity sweep over emitted strings

**Why this exists.** The brief says rare terms are where identifying information
hides. That is only half true, and the missing half is the dangerous one: a large
dealer appearing in hundreds of tickets clears any frequency floor easily, and its name
lives in the *description text*, so denylisting the `merchantName` column does not
help. §8 already specifies an NER sweep for the synthetic corpus — this is the
same sweep applied to the profile artifact, which is the thing an AI actually reads.

Perfect recall is impossible, so the design is two-layered: mechanically reject the
high-confidence cases, and route the residue into the human review queue that §7
already budgets an afternoon for.

`selfcheck.py` in Task 12 imports this module, which is why it comes first.

**Files:**
- Create: `profiler/entities.py`
- Create: `profiler/data/common_surnames.txt`
- Test: `tests/unit/test_entities.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_entities.py
from profiler import entities


def test_rejects_company_suffixes():
    assert entities.looks_like_entity("musterhaendler gmbh")
    assert entities.looks_like_entity("beispielkunde ag")
    assert entities.looks_like_entity("huber e.u.")


def test_rejects_common_surnames():
    assert entities.looks_like_entity("huber")
    assert entities.looks_like_entity("gruber")


def test_rejects_contact_shapes():
    assert entities.looks_like_entity("hans@example.invalid")
    assert entities.looks_like_entity("+43512123456")
    assert entities.looks_like_entity("AT611904300234573201")


def test_accepts_technical_vocabulary():
    for token in ("hydraulikpumpe", "getriebe", "kuehlwasser", "bremsleitung", "druck"):
        assert not entities.looks_like_entity(token), token


def test_accepts_dealer_shorthand_that_is_not_a_name():
    for token in ("getr", "hd", "oelw", "kuehlw"):
        assert not entities.looks_like_entity(token), token


def test_bigram_is_rejected_if_either_token_fails():
    assert entities.looks_like_entity("pumpe huber")
    assert not entities.looks_like_entity("pumpe defekt")


def test_surname_list_is_reference_data_not_corpus_data():
    """The list ships in git deliberately: public name data, no corpus content."""
    assert len(entities.COMMON_SURNAMES) >= 40
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_entities.py -v`
Expected: FAIL — `ImportError: cannot import name 'entities' from 'profiler'`.

- [ ] **Step 3: Write the surname reference list**

Public name-frequency data, not corpus data — safe to commit.

```bash
mkdir -p profiler/data
cat > profiler/data/common_surnames.txt <<'EOF'
mueller
schmidt
schneider
fischer
weber
meyer
wagner
becker
schulz
hoffmann
schaefer
koch
bauer
richter
klein
wolf
schroeder
neumann
schwarz
zimmermann
braun
krueger
hofmann
hartmann
lange
schmitt
werner
schmitz
krause
meier
lehmann
schmid
schulze
maier
koehler
herrmann
walter
koenig
mayer
huber
kaiser
fuchs
peters
lang
scholz
moeller
weiss
jung
haas
gruber
wimmer
moser
steiner
berger
pichler
leitner
eder
brunner
lechner
aigner
EOF
wc -l profiler/data/common_surnames.txt
```

Expected: `60 profiler/data/common_surnames.txt`.

- [ ] **Step 4: Implement `entities.py`**

```python
# profiler/entities.py
"""Reject strings that could identify a person or company before they are emitted.

Complements the min_frequency floor rather than replacing it: the floor catches
RARE strings (identifiers), this catches COMMON ones (entity names). Neither is
sufficient alone, and neither is complete - the residue goes to human review via
vocabulary.hunspell_unrecognized_top.
"""
from __future__ import annotations

import pathlib
import re

_DATA = pathlib.Path(__file__).parent / "data" / "common_surnames.txt"

COMPANY_SUFFIXES = frozenset({
    "gmbh", "ag", "kg", "ohg", "gbr", "gesmbh", "mbh", "eu", "e.u.", "kgaa",
    "ug", "se", "co", "cokg", "soehne", "sohne", "gebr", "gebrueder",
    "landtechnik", "baumaschinen", "handel", "handels", "vertrieb", "service",
    "maschinen", "agrar", "traktoren", "nachf", "inh",
})

COMMON_SURNAMES = frozenset(
    line.strip().lower()
    for line in _DATA.read_text(encoding="utf-8").splitlines()
    if line.strip()
)

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]{2,}$")
_PHONE = re.compile(r"^\+?\d[\d\s/.-]{6,}$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$", re.IGNORECASE)
_PLATE = re.compile(r"^[A-Z]{1,2}[\s-]?\d{1,5}[A-Z]{0,3}$")
_TOKEN_SPLIT = re.compile(r"[\s/,;]+")


def looks_like_entity(value: str) -> bool:
    """True if this string may identify a person or company. Applied per token so
    that a bigram is rejected when either half fails."""
    if not value:
        return False
    raw = value.strip()
    if _EMAIL.match(raw) or _PHONE.match(raw) or _IBAN.match(raw) or _PLATE.match(raw):
        return True
    for token in _TOKEN_SPLIT.split(raw.lower()):
        bare = token.strip(".,;:()-")
        if not bare:
            continue
        if bare in COMPANY_SUFFIXES or token.strip(",;:()") in COMPANY_SUFFIXES:
            return True
        if bare in COMMON_SURNAMES:
            return True
    return False
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_entities.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Commit**

```bash
git add profiler/entities.py profiler/data tests/unit/test_entities.py
git commit -m "feat(profiler): entity sweep over every emitted string"
```

---

### Task 12: The safety layer, selfcheck and emit

**The design problem.** The first draft of `selfcheck.py` raised
`SafetyViolation(f"... contains {entry['token']!r} ...")`. That is a guaranteed
leak: selfcheck fires precisely when the artifact holds something unsafe, so its
message is *certain* to contain a real corpus value — and the natural next move
after a failed sealed run is to paste the traceback into an AI tool.

**The fix is a type constraint, not a rule.** `SafetyViolation` accepts a
registered code, an allowlisted schema path, and **numeric facts only**. Passing a
string raises `TypeError` at the raise site, so a leak becomes a programming error
that fails immediately in a unit test rather than a judgment call that fails
silently in production. Verbatim values go to a detail sink under
`local/quarantine/`, which is deny-listed and sandbox-denied.

The same layer handles the *other* leak path: library exceptions.
`UnicodeDecodeError` embeds the offending bytes, `csv.Error` can quote a line. So
`__main__` never lets a raw traceback reach stdout — it prints the exception type
and a code, and files the traceback locally.

**Files:**
- Create: `profiler/safety.py`, `profiler/selfcheck.py`, `profiler/emit.py`, `profiler/__main__.py`
- Test: `tests/unit/test_safety.py`, `tests/unit/test_selfcheck.py`, `tests/integration/test_profiler_end_to_end.py`

- [ ] **Step 1: Write the failing safety-layer tests**

```python
# tests/unit/test_safety.py
import pytest

from profiler import safety


def test_numeric_facts_are_accepted():
    exc = safety.SafetyViolation("VOCAB_BELOW_MIN_FREQ", "vocabulary.top_tokens[17]",
                                 count=3, threshold=50)
    assert exc.code == "VOCAB_BELOW_MIN_FREQ"
    assert "count=3" in str(exc)


def test_string_facts_are_structurally_rejected():
    """The whole point: you cannot interpolate a corpus value even by accident."""
    with pytest.raises(TypeError, match="must be numeric"):
        safety.SafetyViolation("VOCAB_BELOW_MIN_FREQ", "vocabulary.top_tokens[0]",
                               token="Beispiel Maschinen")


def test_unregistered_code_is_rejected():
    with pytest.raises(ValueError, match="unregistered safety code"):
        safety.SafetyViolation("MADE_UP_CODE", "vocabulary.top_tokens[0]", count=1)


def test_location_must_be_a_plain_schema_path():
    with pytest.raises(ValueError, match="not a plain schema path"):
        safety.SafetyViolation("VOCAB_BELOW_MIN_FREQ", "value was 'Beispielkunde AG'", count=1)


def test_message_contains_no_free_text():
    exc = safety.SafetyViolation("SHAPE_CONTAINS_DIGITS", "identifier_grammars[2]", count=9)
    message = str(exc)
    assert message == "SHAPE_CONTAINS_DIGITS at identifier_grammars[2] (count=9)"


def test_detail_sink_writes_under_quarantine(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "DETAIL_LOG", tmp_path / "detail.log")
    safety.detail("VOCAB_BELOW_MIN_FREQ", "vocabulary.top_tokens[0]", "Beispiel Maschinen")
    written = (tmp_path / "detail.log").read_text()
    assert "Beispiel Maschinen" in written, "the human needs the actual value"


def test_run_scrubbed_hides_library_exception_text(tmp_path, monkeypatch, capsys):
    """UnicodeDecodeError embeds the offending bytes - they must not reach stdout."""
    monkeypatch.setattr(safety, "DETAIL_LOG", tmp_path / "detail.log")

    def boom():
        raise UnicodeDecodeError("utf-8", b"Beispiel\xff", 8, 9, "invalid start byte")

    rc = safety.run_scrubbed(boom)
    out = capsys.readouterr().out
    assert rc == 3
    assert "Beispiel" not in out
    assert "UnicodeDecodeError" in out
    assert "Beispiel" in (tmp_path / "detail.log").read_text()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_safety.py -v`
Expected: FAIL — `ImportError: cannot import name 'safety' from 'profiler'`.

- [ ] **Step 3: Implement `safety.py`**

```python
# profiler/safety.py
"""Output an AI tool may read must be structurally incapable of carrying corpus data.

Two mechanisms, both enforced by types rather than discipline:

  * `SafetyViolation` takes a registered code, an allowlisted schema path, and
    numeric facts. Passing a string raises TypeError at the raise site.
  * `detail()` sends verbatim values to the quarantine tree, for human eyes only.

`run_scrubbed()` wraps the entry point so a library exception - UnicodeDecodeError
carries the offending bytes in its message - cannot print corpus content either.
"""
from __future__ import annotations

import pathlib
import re
import traceback
from collections.abc import Callable

QUARANTINE_DIR = pathlib.Path("local/quarantine")
DETAIL_LOG = QUARANTINE_DIR / "profiler_detail.log"

CODES = frozenset({
    "VOCAB_BELOW_MIN_FREQ",
    "TOPVALUE_BELOW_MIN_FREQ",
    "DENYLISTED_COLUMN_VALUES",
    "SHAPE_CONTAINS_DIGITS",
    "ENTITY_PATTERN_MATCH",
    "UNEXPECTED_FAILURE",
})

# Schema paths only. Column names are published in PROJECT_BRIEF.md §4, so they
# are structure rather than content; anything else is rejected.
_LOCATION = re.compile(r"^[a-z_]+(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\[\d+\])?$")


class SafetyViolation(RuntimeError):
    """Carries a code, a schema location and numbers. Never a corpus value."""

    def __init__(self, code: str, location: str, **facts: float) -> None:
        if code not in CODES:
            raise ValueError(f"unregistered safety code {code!r}")
        if not _LOCATION.match(location):
            raise ValueError(
                f"location {location!r} is not a plain schema path; free text may "
                "carry corpus data"
            )
        for key, value in facts.items():
            if not isinstance(value, (int, float)):
                raise TypeError(
                    f"fact {key!r} must be numeric - strings may carry corpus data, "
                    "send them to safety.detail() instead"
                )
        self.code = code
        self.location = location
        self.facts = facts
        rendered = " ".join(f"{k}={v}" for k, v in sorted(facts.items()))
        super().__init__(f"{code} at {location}" + (f" ({rendered})" if rendered else ""))


def detail(code: str, location: str, payload: str) -> None:
    """Record a verbatim value for HUMAN eyes only, inside the quarantine tree."""
    DETAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DETAIL_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{code}] {location}: {payload}\n")


def run_scrubbed(fn: Callable[..., int], *args: object, **kwargs: object) -> int:
    """Entry-point wrapper. Exit 0 ok, 2 safety violation, 3 unexpected failure."""
    try:
        return fn(*args, **kwargs)
    except SafetyViolation as exc:
        print(f"ABORT {exc}", flush=True)
        print(f"       verbatim detail in {DETAIL_LOG} - local only, do not copy out", flush=True)
        return 2
    except BaseException as exc:
        detail("UNEXPECTED_FAILURE", "profiler", traceback.format_exc())
        print(
            f"ABORT UNEXPECTED_FAILURE type={type(exc).__name__}\n"
            f"       traceback in {DETAIL_LOG} - local only, do not copy out",
            flush=True,
        )
        return 3
```

- [ ] **Step 4: Run the safety tests**

Run: `uv run pytest tests/unit/test_safety.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Write the failing selfcheck tests**

```python
# tests/unit/test_selfcheck.py
import pytest

from profiler import safety, selfcheck


def test_rejects_rare_token_in_vocabulary():
    profile = {"vocabulary": {"min_frequency_threshold": 50,
                              "top_tokens": [{"token": "seltenername", "count": 3}]}}
    with pytest.raises(safety.SafetyViolation) as excinfo:
        selfcheck.assert_safe(profile)
    assert excinfo.value.code == "VOCAB_BELOW_MIN_FREQ"
    assert "seltenername" not in str(excinfo.value)


def test_rejects_any_value_from_a_denylisted_column():
    profile = {"per_field": {"endCustomerName": {"top_values": [{"value": "Beispielkunde AG",
                                                                 "count": 900}]}}}
    with pytest.raises(safety.SafetyViolation) as excinfo:
        selfcheck.assert_safe(profile)
    assert excinfo.value.code == "DENYLISTED_COLUMN_VALUES"
    assert "Beispielkunde" not in str(excinfo.value)


def test_rejects_identifier_grammar_that_leaked_a_literal_value():
    profile = {"identifier_grammars": [{"kind": "error_code", "shape": "F1247",
                                        "regex": "^F1247$", "count": 9, "share": 0.1}]}
    with pytest.raises(safety.SafetyViolation) as excinfo:
        selfcheck.assert_safe(profile)
    assert excinfo.value.code == "SHAPE_CONTAINS_DIGITS"
    assert "1247" not in str(excinfo.value)


def test_rejects_a_company_name_that_cleared_the_frequency_floor():
    """min_frequency protects against RARE identifiers. A big dealer's name appears
    hundreds of times and sails straight over the floor."""
    profile = {"vocabulary": {"min_frequency_threshold": 50,
                              "top_tokens": [{"token": "musterhaendler gmbh", "count": 800}]}}
    with pytest.raises(safety.SafetyViolation) as excinfo:
        selfcheck.assert_safe(profile)
    assert excinfo.value.code == "ENTITY_PATTERN_MATCH"


def test_accepts_a_clean_profile():
    profile = {
        "vocabulary": {"min_frequency_threshold": 50,
                       "top_tokens": [{"token": "pumpe", "count": 900}]},
        "per_field": {"title": {"top_values": []}},
        "identifier_grammars": [{"kind": "error_code", "shape": "ADDDD",
                                 "regex": r"^[A-Z]\d{4}$", "count": 9, "share": 0.1}],
    }
    assert selfcheck.assert_safe(profile) == []


def test_every_violation_writes_a_local_detail_line(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "DETAIL_LOG", tmp_path / "detail.log")
    profile = {"vocabulary": {"min_frequency_threshold": 50,
                              "top_tokens": [{"token": "seltenername", "count": 3}]}}
    with pytest.raises(safety.SafetyViolation):
        selfcheck.assert_safe(profile)
    assert "seltenername" in (tmp_path / "detail.log").read_text()
```

- [ ] **Step 6: Run to confirm failure**

Run: `uv run pytest tests/unit/test_selfcheck.py -v`
Expected: FAIL — `ImportError: cannot import name 'selfcheck'`.

- [ ] **Step 7: Implement `selfcheck.py`**

```python
# profiler/selfcheck.py
from __future__ import annotations

import re

from profiler import entities, safety

# No value from these columns is ever emitted, at any frequency. Only lengths,
# null rates and cardinality estimates.
DENYLISTED_COLUMNS = frozenset({
    "merchantName", "endCustomerName", "contactEmail", "contactPhone",
    "contactPhoneTrimmed", "merchantPhoneNumber", "endCustomerPhoneNumber",
    "endCustomerNumber", "merchantNumber", "vehicleSerialNo", "personId",
    "lastModifiedUser", "userCreatedId", "userAssignedId",
})

_HAS_DIGITS = re.compile(r"\d")


def _reject(code: str, location: str, payload: str, **facts: float) -> None:
    """Record the verbatim value locally, then raise a message that cannot carry it."""
    safety.detail(code, location, payload)
    raise safety.SafetyViolation(code, location, **facts)


def assert_safe(profile: dict) -> list[str]:
    """Enforce the safety invariant. Returns warnings; raises on violation.

    Two independent checks, because they catch opposite failures: the frequency
    floor catches RARE strings (where identifiers hide) and the entity sweep
    catches COMMON ones (where company and person names hide)."""
    warnings: list[str] = []

    vocab_section = profile.get("vocabulary", {})
    min_freq = vocab_section.get("min_frequency_threshold", 0)
    for key in ("top_tokens", "top_bigrams", "hunspell_unrecognized_top"):
        for index, entry in enumerate(vocab_section.get(key, [])):
            location = f"vocabulary.{key}[{index}]"
            if entry["count"] < min_freq:
                _reject("VOCAB_BELOW_MIN_FREQ", location, entry["token"],
                        count=entry["count"], threshold=min_freq)
            if entities.looks_like_entity(entry["token"]):
                _reject("ENTITY_PATTERN_MATCH", location, entry["token"],
                        count=entry["count"])

    for column, stats in profile.get("per_field", {}).items():
        location = f"per_field.{column}"
        if stats.get("top_values") and column in DENYLISTED_COLUMNS:
            _reject("DENYLISTED_COLUMN_VALUES", location,
                    f"{len(stats['top_values'])} values present",
                    value_count=len(stats["top_values"]))
        for index, entry in enumerate(stats.get("top_values", [])):
            if entry["count"] < min_freq:
                _reject("TOPVALUE_BELOW_MIN_FREQ", f"{location}[{index}]", entry["value"],
                        count=entry["count"], threshold=min_freq)
            if entities.looks_like_entity(entry["value"]):
                _reject("ENTITY_PATTERN_MATCH", f"{location}[{index}]", entry["value"],
                        count=entry["count"])

    for index, grammar in enumerate(profile.get("identifier_grammars", [])):
        shape = grammar.get("shape", "")
        if _HAS_DIGITS.search(shape):
            _reject("SHAPE_CONTAINS_DIGITS", f"identifier_grammars[{index}]", shape,
                    count=grammar.get("count", 0))

    for section, hints in profile.get("dimension_hints", {}).items():
        for hint_index, hint in enumerate(hints):
            for token_index, token in enumerate(hint.get("top_tokens", [])):
                location = f"dimension_hints.{section}[{hint_index}]"
                if entities.looks_like_entity(token):
                    _reject("ENTITY_PATTERN_MATCH", location, token,
                            token_index=token_index)
                if _HAS_DIGITS.search(token) and len(token) > 6:
                    safety.detail("ENTITY_PATTERN_MATCH", location, token)
                    warnings.append(f"{location} holds an identifier-like token; see detail log")
    return warnings
```

- [ ] **Step 8: Run the selfcheck tests**

Run: `uv run pytest tests/unit/test_selfcheck.py -v`
Expected: PASS, 6 tests. `profiler/entities.py` comes from Task 11, which is why it
precedes this task.

- [ ] **Step 9: Write the end-to-end profiler test**

```python
# tests/integration/test_profiler_end_to_end.py
import json
import pathlib
import socket
import subprocess
import sys

import jsonschema
import pytest

from tests.conftest import build_standin

SCHEMA = pathlib.Path("profiler/schema.json")


def _run(csv_path: pathlib.Path, out: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "profiler", "--csv", str(csv_path), "--out", str(out),
         "--min-frequency", "5", "--hunspell-dict", ""],
        capture_output=True, text=True, check=True,
    )


def test_profiler_produces_schema_valid_output(standin_csv, tmp_path):
    out = tmp_path / "profile.json"
    _run(standin_csv, out)
    profile = json.loads(out.read_text())
    jsonschema.validate(profile, json.loads(SCHEMA.read_text()))
    assert profile["selfcheck"]["passed"] is True
    assert profile["source"]["row_count"] == 400
    assert len(profile["source"]["columns_found"]) == 38
    assert profile["solutions"]["fill_rate"] < 1.0
    assert profile["temporal"]["age_years_quantiles"]["max"] > 0


def test_profiler_output_never_echoes_a_source_value(standin_csv, tmp_path):
    """Stdout is the thing a human is most likely to paste into an AI tool."""
    result = _run(standin_csv, tmp_path / "profile.json")
    combined = result.stdout + result.stderr
    for corpus_value in ("Musterhaendler", "Beispielkunde", "test@example.invalid", "TN-100001"):
        assert corpus_value not in combined, f"{corpus_value!r} reached stdout/stderr"


def test_profiler_makes_no_network_calls(standin_csv, tmp_path, monkeypatch):
    """A belt-and-braces smoke test only. The real guarantee is --network=none on
    the window container; monkeypatching socket cannot prove container egress."""
    def _blocked(*args, **kwargs):
        raise AssertionError("profiler attempted a network call")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    from profiler import __main__ as entry

    assert entry.main(["--csv", str(standin_csv), "--out", str(tmp_path / "p.json"),
                       "--min-frequency", "5", "--hunspell-dict", ""]) == 0


def test_profiler_imports_stay_inside_the_allowlist():
    """The profiler must not reach the DB, an LLM, or the API layer - it runs
    unattended on a box holding real data."""
    code = (
        "import sys; import profiler.__main__;"
        "mods={m for m in sys.modules if m.startswith(('recall.','psycopg','httpx',"
        "'fastapi','uvicorn','selectolax'))};"
        "print('|'.join(sorted(mods)))"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    loaded = {m for m in r.stdout.strip().split("|") if m}
    forbidden = {m for m in loaded if not m.startswith(("recall.clean", "recall.german"))}
    assert not forbidden, f"profiler pulled in forbidden modules: {sorted(forbidden)}"


@pytest.mark.parametrize("missing", ["title", "solutions", "vehicleModelId"])
def test_profiler_reports_missing_expected_columns_instead_of_crashing(tmp_path, missing):
    csv_path = build_standin(tmp_path / "trimmed.csv", rows=50, drop_column=missing)
    out = tmp_path / "profile.json"
    _run(csv_path, out)
    profile = json.loads(out.read_text())
    assert missing in profile["source"]["columns_expected_missing"]


def test_unexpected_failure_exits_3_without_printing_corpus_bytes(tmp_path, capsys):
    """A malformed CSV must not produce a UnicodeDecodeError quoting real bytes."""
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"id,title\n1,Beispiel\xff\xfe\n")
    from profiler import __main__ as entry

    rc = entry.main(["--csv", str(bad), "--out", str(tmp_path / "p.json")])
    out = capsys.readouterr().out
    assert rc in (0, 3)
    assert "\\xff" not in out and "Beispiel" not in out
```

`from tests.conftest import build_standin` requires `tests/__init__.py`; create it
as an empty file in Step 9 below.

- [ ] **Step 10: Implement `emit.py`**

```python
# profiler/emit.py
from __future__ import annotations

import json
import pathlib


def write_profile(profile: dict, out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False, sort_keys=True))


def write_report(profile: dict, out_path: pathlib.Path) -> None:
    """Human-readable companion. This is what gets reviewed line by line before
    anything derived from it leaves the box."""
    src = profile["source"]
    sol = profile["solutions"]
    lines = [
        "# Corpus profile report",
        "",
        f"- source: `{src['filename']}` ({src['bytes']:,} bytes, sha256 `{src['sha256'][:16]}…`)",
        f"- rows: {src['row_count']:,}",
        f"- columns found: {len(src['columns_found'])}",
        f"- expected but missing: {src['columns_expected_missing'] or 'none'}",
        f"- unexpected extras: {src['columns_unexpected'] or 'none'}",
        "",
        "## solutions — the load-bearing field (§12.1, §12.2)",
        "",
        f"- fill rate: **{sol['fill_rate']:.1%}**",
        f"- non-empty after cleaning: **{sol['nonempty_after_clean_rate']:.1%}**",
        f"- usable (non-junk) estimate: **{sol['usable_rate_estimate']:.1%}**",
        f"- structure: {'single free-text field' if sol['cardinality']['single_field'] else 'MULTI-ENTRY, separator ' + repr(sol['cardinality']['detected_separator'])}",
        "",
        "### junk taxonomy",
        "",
        "| pattern | count | share |",
        "|---|---:|---:|",
        *[f"| `{t['pattern']}` | {t['count']:,} | {t['share']:.1%} |" for t in sol["junk_taxonomy"]],
        "",
        "## near-duplicate clusters",
        "",
        f"- clusters: {profile['clusters']['cluster_count']:,}",
        f"- singletons: {profile['clusters']['singleton_count']:,}",
        f"- Zipf α estimate: {profile['clusters'].get('zipf_alpha_estimate')}",
        "",
        "## selfcheck",
        "",
        f"- passed: **{profile['selfcheck']['passed']}**",
        *[f"- warning: {w}" for w in profile["selfcheck"].get("warnings", [])],
    ]
    out_path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 11: Implement `__main__.py`**

```python
# profiler/__main__.py
"""Corpus profiler. Runs inside an airlock window: no network, no DB, no GPU.

    python -m profiler --csv export.csv --out profile.json

Emits profile.json (safe to read) and profile_report.md (review artifact).
Refuses to write anything if the safety selfcheck fails.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import sys
from collections import Counter, defaultdict

from recall.clean import pipeline
from recall.german import identifiers

from profiler import emit, entities, safety, selfcheck
from profiler.columns import (
    DIMENSION_COLUMNS,
    EXPECTED_COLUMNS,
    MAX_DIMENSION_CARDINALITY,
    TEXT_COLUMNS,
)
from profiler.stats import clusters, hunspell, lengths, nullmask, solutions, temporal, vocab


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_profile(
    csv_path: pathlib.Path, min_frequency: int, hunspell_dict: str | None = None
) -> dict:
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    columns_found = list(rows[0].keys()) if rows else []

    per_field: dict[str, dict] = {}
    for column in columns_found:
        values = [(r.get(column) or "") for r in rows]
        stats = {
            "present_count": sum(1 for v in values if v.strip()),
            "null_count": sum(1 for v in values if v is None),
            "empty_string_count": sum(1 for v in values if v == ""),
            "distinct_count_estimate": len({v for v in values if v.strip()}),
            "char_len_quantiles": lengths.quantiles([len(v) for v in values]),
            "token_len_quantiles": lengths.quantiles([len(v.split()) for v in values]),
        }
        if column in TEXT_COLUMNS:
            cleaned = [pipeline.clean(v) for v in values]
            n = len(values) or 1
            stats.update(
                cleaned_char_len_quantiles=lengths.quantiles([len(c.text) for c in cleaned]),
                cleaned_token_len_quantiles=lengths.quantiles(
                    [len(c.text.split()) for c in cleaned]
                ),
                html_rate=sum(c.report.had_html for c in cleaned) / n,
                quoted_chain_rate=sum(c.report.had_quoted_chain for c in cleaned) / n,
                signature_rate=sum(c.report.had_signature for c in cleaned) / n,
                diag_dump_rate=sum(c.report.had_diag_dump for c in cleaned) / n,
                all_caps_rate=sum(c.report.is_all_caps for c in cleaned) / n,
                no_punctuation_rate=sum(c.report.has_no_punctuation for c in cleaned) / n,
            )
        if column in DIMENSION_COLUMNS and column not in selfcheck.DENYLISTED_COLUMNS:
            counts = Counter(v for v in values if v.strip())
            if len(counts) <= MAX_DIMENSION_CARDINALITY:
                stats["top_values"] = [
                    {"value": v, "count": c} for v, c in counts.most_common()
                    if c >= min_frequency
                ]
        per_field[column] = stats

    problem_texts = [
        pipeline.clean(f"{r.get('title') or ''} {r.get('description') or ''}").text for r in rows
    ]
    token_counts = vocab.token_counts(problem_texts)

    all_identifiers = [i.value for text in problem_texts for i in identifiers.extract(text)]
    models = [(r.get("vehicleModelId") or "").strip() for r in rows]
    families = {identifiers.model_family(m) for m in models if m} - {None}
    per_family: dict[str, set[str]] = defaultdict(set)
    for m in models:
        fam = identifiers.model_family(m) if m else None
        if fam:
            per_family[fam].add(m)

    dimension_hints: dict[str, list[dict]] = {}
    for column in ("categoryId", "statusId", "priorityId"):
        if column not in columns_found:
            continue
        grouped: dict[str, list[str]] = defaultdict(list)
        for row, text in zip(rows, problem_texts, strict=False):
            key = (row.get(column) or "").strip()
            if key:
                grouped[key].append(text)
        hints = []
        for key, texts in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            counts = vocab.token_counts(texts)
            hints.append({
                "id": key,
                "count": len(texts),
                "top_tokens": [t["token"] for t in vocab.top_tokens(counts, min_frequency, 15)],
            })
        dimension_hints[column] = hints

    created = [(r.get("timestampCreated") or "")[:7] for r in rows]
    profile = {
        "schema_version": "1",
        "source": {
            "filename": csv_path.name,
            "sha256": _sha256(csv_path),
            "bytes": csv_path.stat().st_size,
            "row_count": len(rows),
            "encoding_detected": "utf-8",
            "delimiter": ",",
            "columns_found": columns_found,
            "columns_expected_missing": [c for c in EXPECTED_COLUMNS if c not in columns_found],
            "columns_unexpected": [c for c in columns_found if c not in EXPECTED_COLUMNS],
        },
        "per_field": per_field,
        "null_mask_patterns": nullmask.joint_patterns(rows, columns_found),
        "identifier_grammars": identifiers.infer_grammars(all_identifiers),
        "model_designations": {
            "grammar": sorted({identifiers.shape_of(m) for m in models if m}),
            "inferred_family_rule": "uppercase prefix + first two digits (e.g. TX-2240 -> TX-22)",
            "family_count": len(families),
            "models_per_family_quantiles": lengths.quantiles(
                [len(v) for v in per_family.values()]
            ),
        },
        "dimension_hints": dimension_hints,
        "temporal": {
            "created_per_month": dict(Counter(c for c in created if len(c) == 7)),
            "age_years_quantiles": lengths.quantiles(
                temporal.ages_in_years([(r.get("timestampCreated") or "") for r in rows])
            ),
        },
        "solutions": solutions.profile([(r.get("solutions") or "") for r in rows]),
        "clusters": clusters.profile(problem_texts),
        "vocabulary": {
            "total_tokens": sum(token_counts.values()),
            "distinct_tokens": len(token_counts),
            "min_frequency_threshold": min_frequency,
            "top_tokens": vocab.top_tokens(token_counts, min_frequency),
            # Bigrams are the highest-risk emission: a company name as a bigram is a
            # complete identification, so both halves must clear the entity sweep.
            "top_bigrams": [
                entry
                for entry in vocab.top_tokens(
                    vocab.bigram_counts(problem_texts), min_frequency, 500
                )
                if not entities.looks_like_entity(entry["token"])
            ],
            "hunspell_unrecognized_top": hunspell.unrecognized(
                token_counts, min_frequency, dict_path=hunspell_dict
            ),
        },
        "multi_fault_estimate": {
            "heuristic": "distinct error_code identifiers per ticket >= 2",
            "rate": (
                sum(
                    1 for text in problem_texts
                    if len({i.value for i in identifiers.extract(text) if i.kind == "error_code"}) >= 2
                ) / (len(problem_texts) or 1)
            ),
        },
        "selfcheck": {"passed": False, "checks": [], "warnings": []},
    }

    warnings = selfcheck.assert_safe(profile)
    profile["selfcheck"] = {
        "passed": True,
        "checks": ["min_frequency pruning", "denylisted-column values",
                   "identifier shapes carry no literal digits", "dimension-hint token shapes"],
        "warnings": warnings,
    }
    return profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="profiler")
    ap.add_argument("--csv", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--min-frequency", type=int, default=vocab.DEFAULT_MIN_FREQUENCY)
    ap.add_argument(
        "--hunspell-dict",
        default="de_DE",
        help="hunspell dictionary name for unrecognised-token mining; "
             "pass empty to skip if the binary is unavailable",
    )
    args = ap.parse_args(argv)

    profile = build_profile(args.csv, args.min_frequency, args.hunspell_dict or None)
    emit.write_profile(profile, args.out)
    emit.write_report(profile, args.out.with_name("profile_report.md"))
    # Paths and counts only - never a field value.
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes) "
          f"and {args.out.with_name('profile_report.md')}")
    print(f"rows={profile['source']['row_count']} "
          f"columns={len(profile['source']['columns_found'])} "
          f"selfcheck_passed={profile['selfcheck']['passed']} "
          f"warnings={len(profile['selfcheck']['warnings'])}")
    return 0


if __name__ == "__main__":
    # Never let a raw traceback reach stdout: UnicodeDecodeError and csv.Error
    # quote the offending input.
    sys.exit(safety.run_scrubbed(main))
```

- [ ] **Step 12: Run the end-to-end tests**

```bash
touch tests/__init__.py
uv run pytest tests/integration/test_profiler_end_to_end.py tests/unit/test_selfcheck.py \
              tests/unit/test_safety.py -v
```

Expected: PASS, 20 tests.

- [ ] **Step 13: Commit**

```bash
git add profiler tests/__init__.py tests/integration/test_profiler_end_to_end.py \
        tests/unit/test_selfcheck.py tests/unit/test_safety.py
git commit -m "feat(profiler): leak-proof safety layer, selfcheck-gated emit, sealed CLI"
```

---

### Task 13: Sealed profiler image and the airlock runbook

**Files:**
- Create: `infra/profiler/Dockerfile`
- Create: `docs/airlock-runbook.md`
- Create: `docs/client-questions.md`

- [ ] **Step 1: Write the sealed profiler image**

This is what makes `--network=none` possible in the window: every dependency is
baked in beforehand, so nothing resolves at run time. `--frozen` fails loudly if
`uv.lock` is stale rather than silently reaching for the network.

```dockerfile
# infra/profiler/Dockerfile
FROM python:3.12-slim-bookworm

# hunspell + the German dictionary: without these, vocabulary.hunspell_unrecognized_top
# comes back empty and the §7 synonym-mining input is lost for a whole cycle.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends hunspell hunspell-de-de coreutils; \
    rm -rf /var/lib/apt/lists/*; \
    hunspell -d de_DE -l </dev/null

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /work
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY profiler ./profiler
RUN uv sync --frozen --no-dev

ENV PATH="/work/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Proves the image works offline before a single real row is anywhere near it.
RUN python -c "import profiler.__main__, recall.clean.pipeline; print('sealed image ok')"

ENTRYPOINT []
```

- [ ] **Step 2: Verify it runs with no network at all**

```bash
docker build -f infra/profiler/Dockerfile -t recall/profiler:pinned .
docker run --rm --network=none recall/profiler:pinned \
  python -c "import profiler.__main__; print('offline import ok')"
docker run --rm --network=none recall/profiler:pinned \
  hunspell -d de_DE -l </dev/null; echo "hunspell rc=$?"
```

Expected: `offline import ok` and `hunspell rc=0`. If the build succeeds but the
offline run fails, a dependency is resolving lazily at import time — find it now,
not during a window.

- [ ] **Step 3: Write the runbook**

Content: the exact copy-pasteable command sequence for Window A, B and C —
`scp` target paths, the podman invocation, the fair-use check, the delete-and-verify
steps, and a checklist the operator ticks. Every command must be runnable without
improvisation, since no AI is available during the window.

```markdown
# Airlock runbook

**The rule.** No AI assistance between "real CSV lands on the box" and "real CSV is
deleted and verified gone". Work the checklist in order and do not improvise. If a
step fails: abort, shred the data, *then* fix the code with AI help.

**The one rule people break.** When a sealed run fails, do not paste its output
anywhere near an AI tool. The profiler prints only codes, schema paths and counts;
verbatim values go to `profiler_detail.log`, which stays on the box. Read that file
yourself, describe the problem in your own words, and shred it.

## Phase 0 — before any window (AI assistance fine, no real data present)

Everything that needs a network happens here. The window itself has none.

- [ ] `docker build -f infra/profiler/Dockerfile -t recall/profiler:pinned .` — deps
      installed with `uv sync --frozen --no-dev` against the hash-pinned lockfile,
      plus `hunspell` and `hunspell-de-de`. **Never resolve dependencies inside a
      window**: `uv run` reaches the network, and freshly-downloaded third-party code
      would execute in the same process as the real CSV.
- [ ] `docker save recall/profiler:pinned | ssh hpc 'podman load'`
- [ ] Verify the dictionary *inside the image*:
      `ssh hpc 'podman run --rm --network=none recall/profiler:pinned hunspell -d de_DE -l </dev/null; echo rc=$?'`
      → `rc=0`. If it is missing, `hunspell_unrecognized_top` comes back empty, the
      §7 synonym-mining input is lost, and recovering it costs a whole extra cycle.
- [ ] `ssh hpc 'mkdir -p <data-dir>/recall-quarantine && chmod 700 <data-dir>/recall-quarantine'`
- [ ] Ship the code without secrets or git history:
      `git archive --format=tar HEAD | ssh hpc 'mkdir -p <data-dir>/recall-work && tar -x -C <data-dir>/recall-work'`
      — **not** `scp -r .`, which ignores `.gitignore` and would carry `.env`.

## Window A — profiling  🔒 AI OFF from here

- [ ] `./infra/fairuse/gpu-fairuse2.sh check` → GO (profiling is CPU-only, but the
      box must not be crowded)
- [ ] `scp export.csv hpc:<data-dir>/recall-quarantine/`
- [ ] `ssh hpc` then, in one command:

      ulimit -c 0    # no core dumps: a crash must not spill ticket text to disk
      podman run --rm --network=none \
        -v <data-dir>/recall-work:/work:ro \
        -v <data-dir>/recall-quarantine:/q \
        -w /work recall/profiler:pinned \
        python -m profiler --csv /q/export.csv --out /q/profile.json

      `--network=none` is the actual guarantee that nothing phones home. The
      monkeypatched-socket unit test is a smoke test; this is the control.
- [ ] Confirm stdout ends with `selfcheck_passed=True`. On `ABORT`, read
      `<data-dir>/recall-quarantine/profiler_detail.log` yourself — do not copy it out.
- [ ] Read `profile_report.md` in full, on the box, before copying anything.
- [ ] `scp hpc:<data-dir>/recall-quarantine/profile.json      ./local/artifacts/`
- [ ] `scp hpc:<data-dir>/recall-quarantine/profile_report.md ./local/artifacts/`
- [ ] `ssh hpc 'shred -u <data-dir>/recall-quarantine/export.csv <data-dir>/recall-quarantine/profiler_detail.log'`
- [ ] `ssh hpc 'ls -la <data-dir>/recall-quarantine'` → only `profile*` remain
- [ ] `make check-clean` on the workstation → quarantine empty
- [ ] 🔓 Only now resume AI-assisted work

## Window B — leakage gate (command block written at the start of M2)

Controls that must be in it, decided now:

- The real CSV comes back for this window. **Real-corpus embeddings are not
  retained between windows** — inversion attacks reconstruct substantial portions
  of short texts when the embedding model is public, and ours is, so retained
  vectors are the text in a thin disguise. Paying a second cycle is the cheaper
  trade.
- The shingle intersection and the nearest-neighbour check both run **on the box**,
  against the synthetic corpus shipped in. Only counts and verdicts come out — no
  hash set, no vectors. A hash set of 8-token shingles is a membership oracle and
  does not need to exist off-box.
- Gate report crossing out contains counts, thresholds and pass/fail only.

## Window C — real-data eval (command block written at the start of M4)

Controls that must be in it, decided now:

- This window runs the **entire offline pipeline**: clean → enrich → embed → index
  → eval. It is an overnight unattended run, so every stage must already be proven
  on synthetic data.
- vLLM starts with `--disable-log-requests` and its logs go to
  `<data-dir>/recall-quarantine/`. Default verbosity puts prompt text in the log, and a
  log file nobody remembers to shred is a leak that outlives the window.
- Postgres for this window runs with its data directory on **tmpfs**, so real rows
  never touch disk, and is destroyed with `podman rm -v`. `DROP TABLE` leaves the
  volume and the WAL behind.
- Enrichment intermediate state — needed for resumability — lives under
  `<data-dir>/recall-quarantine/`. It is a distilled summary of real tickets and is
  arguably more sensitive than the source rows.
- The hand-written eval queries are real data. They are created on the box, used on
  the box, and shredded there. Only `eval_real.json` crosses out, keyed by **opaque
  query ids** — never by query text.
- Teardown shreds: CSV, queries, enrichment state, vLLM logs, tmpfs volume, detail log.
```

- [ ] **Step 4: Start the client question list**

```markdown
# Questions for the client call (after ~2026-08-17)

## Blocking phase 2, not the prototype
- Lookup tables for `statusId`, `categoryId`, `priorityId`, `vehicleModelId`.
- Model hierarchy (model → series → family). We currently infer families from
  designation prefixes; confirm or replace.
- Deep-link URL template for the ticket system, e.g. `https://…/ticket/{ticketNumber}`.
- Structure and meaning of `customData`.
- §12.9: is there a reliable last-modified timestamp? The export has
  `lastModifiedUser` and `subStatusChanged` but **no `lastModifiedAt`** — a nightly
  delta may be impossible as exported.
- §12.10: where is the human gate for anything safety-relevant on a vehicle, once
  tickets are piped in automatically?
- DPO: do they want to review the profile artifact and gate report?

## Process, to raise with evidence from `profile.json`
- If `solutions` usable rate is low: requiring a resolution on close is a process
  fix, not a code fix. Bring the measured number.

## Usage
- Who handles tickets, and at what volume per day?
- What does "solved" look like in their workflow — is there a close action we
  could hang the "this solved it" signal on?
```

- [ ] **Step 5: Commit**

```bash
git add infra/profiler/Dockerfile docs/airlock-runbook.md docs/client-questions.md
git commit -m "feat(infra): sealed offline profiler image, airlock runbook, client questions"
```

---

## Milestone 1 acceptance criteria

- [ ] `uv run pytest` green, including the no-network smoke test and the
      import-allowlist test.
- [ ] The profiler runs end to end against the runtime-built stand-in and produces
      schema-valid output with `selfcheck_passed=True`. **No CSV exists on disk in
      the working tree** — `test_standin_csv_is_not_on_disk_in_the_repo` asserts it.
- [ ] The profiler survives a CSV with columns missing, extra, or reordered, and
      reports the discrepancy rather than crashing.
- [ ] **`SafetyViolation` cannot carry a corpus value** — passing a string fact
      raises `TypeError` at the raise site. Verified by test, not by inspection.
- [ ] `selfcheck.assert_safe` raises on all five: sub-threshold vocabulary token,
      `top_values` on a denylisted column, identifier shape containing literal
      digits, an entity-matching token that *cleared* the frequency floor, and an
      entity-matching `top_value`. Each writes the verbatim value to the local
      detail log and nowhere else.
- [ ] **Nothing the profiler prints contains a source value** —
      `test_profiler_output_never_echoes_a_source_value` greps stdout and stderr for
      known stand-in values.
- [ ] A malformed CSV exits 3 with the exception *type* only; no bytes on stdout.
- [ ] `make check-clean` passes and `git ls-files` contains no data-shaped file.
      `git remote` is empty.
- [ ] `docs/airlock-runbook.md` Phase 0 and Window A are copy-pasteable end to end,
      and Phase 0 verifies the German dictionary *inside the pinned image*.
- [ ] **Window A executed** with `--network=none`. `local/artifacts/profile.json`
      and `profile_report.md` present, reviewed line by line, **not committed**.
- [ ] Real CSV and detail log shredded on the box; `ls` shows only `profile*`.
- [ ] **§12.1 answered:** `solutions.cardinality.single_field` recorded, and the
      schema decision (single field vs attempt thread) written into the design doc.
- [ ] **§12.2 answered:** fill rate, non-empty-after-clean rate and usable-rate
      estimate recorded; explicit go/no-go on whether retrieval is viable, or
      whether the honest answer to the client is a process change.
- [ ] Real-corpus `ts_debug` spot-check confirms compound splitting on actual
      vocabulary (M0 proved it on invented words).
- [ ] `vocabulary.hunspell_unrecognized_top` is **non-empty** — an empty list means
      the dictionary was missing during Window A and the synonym-mining input needs
      re-collecting.
- [ ] `temporal.age_years_quantiles` is populated, confirming `timestampCreated`
      parsed; if it is all zeros the timestamp format differs from `YYYY-MM-DD` and
      `profiler/stats/temporal.py` needs its regex widened.

---

# Milestones 2–6 — acceptance criteria

Task-level plans are written at the start of each milestone, from these criteria
plus `local/artifacts/profile.json`.

### M2 — Synthetic corpus and leakage gate

- [ ] ~400 fault archetypes on a fictional product line with visibly fake
      designations, each tied to specific fictional models and components.
- [ ] Archetypes expanded to variants following the **profile's** cluster-size
      distribution, in distinct voices (terse mechanic, rambling customer email,
      template dump).
- [ ] Noise and null masks applied **programmatically after generation** — never
      by asking the LLM to be messy — sampled from the profile's joint null masks
      and formatting-noise rates.
- [ ] 1,500-row fixture **regenerated, not committed**: `make fixtures` rebuilds it
      byte-identically from the committed generator plus seed, and verifies against
      `local/MANIFEST.sha256`. `git ls-files` still shows no data.
- [ ] The LLM-generated archetype set lives in `local/fixtures/`; its checksum is in
      the manifest so integrity is verifiable without the file being in git.
- [ ] Fixture cluster-size distribution matches the profile within a stated
      tolerance; test asserts it.
- [ ] Gate: regex/NER sweep and entity allowlist run without the real corpus, green
      in local test runs. **Window B executed** for the shingle intersection and the
      NN check, both computed **on the box**; only counts and verdicts cross out.
- [ ] **No real-corpus embeddings or shingle hashes exist anywhere after the gate** —
      they are never retained between windows. Verified by `ls` on the box.
- [ ] Gate report signed by the user and stored in `local/artifacts/`.
- [ ] Fixture embeddings generated once on the H100 and cached in `local/fixtures/`,
      so the dev loop needs no GPU. Regenerable, never committed.

### M3 — Baseline hybrid retrieval and the dual eval harness

- [ ] Schema: `ticket_raw` (immutable jsonb), `ticket` (including a `completeness`
      score per §6.6 and a `truncated` flag), `ticket_problem` (one row per problem,
      `halfvec(1024)` vectors, HNSW), `ticket_identifier`.
- [ ] Missing values are never imputed and no row is ever dropped; `completeness`
      acts only as a mild ranking penalty. Test asserts a row with mostly-null
      metadata is still retrievable.
- [ ] Unique constraint `(ticket_id, ord, prompt_version, model_id)` on
      `ticket_problem` so enrichment is idempotent and resumable.
- [ ] Three arms implemented and independently measurable: dense, `de_tech` FTS
      with `setweight` tiers, exact identifiers.
- [ ] RRF fusion with configurable k and per-arm weights.
- [ ] Harness accepts a **config matrix** and emits one metrics record per cell in
      a single pass.
- [ ] recall@10, MRR, nDCG@10 **and bootstrap CIs** reported on the synthetic
      fixture using archetype gold labels; `eval_synthetic.json` produced in CI.
- [ ] **Fusion recall@50 measured and reported** — it is the ceiling for M4.
- [ ] No LLM anywhere in this milestone.

### M4 — Enrichment and reranker

- [ ] Enrichment output contract as a pydantic schema; vLLM guided decoding.
- [ ] Runner is **resumable and idempotent**: killed with SIGTERM mid-batch, it
      resumes without duplicating or losing rows. Test asserts this.
- [ ] Runner calls `gpu-fairuse2.sh check` **between batches** and pauses on DEFER.
- [ ] **Invariant 6 enforced:** every identifier emitted by the LLM is verified as
      a substring of its source text before storage; adversarial fixture proves
      invented identifiers are rejected.
- [ ] Synonym dictionary mined from the profile's unrecognised-token list, reviewed
      once by hand, loaded into `de_tech_synonyms.syn`; a migration reloads the
      dictionary and the FTS test suite still passes. **The `.syn` file is real-corpus
      vocabulary and therefore data**: it lives in `local/quarantine/`, is `scp`'d to
      the box, and is gitignored despite looking like config. Committed instead: the
      mining script and a synthetic `.syn` for tests.
- [ ] **Enrichment prompt templates contain no real ticket text.** Few-shot examples
      are drawn only from the fictional roster; a test asserts no prompt file holds a
      string absent from the synthetic corpus. This is the classic accidental leak —
      someone pastes a real ticket in as an example and commits it.
- [ ] 100-row hand-graded enrichment set scored, **including multi-fault cases**.
- [ ] Reranker arm integrated; measured delta on the synthetic harness.
- [ ] **Window C run #1:** enrich once, then embed/index/eval per embedder config
      (Qwen3-Embedding-8B @1024, @2048, BGE-M3) plus reranked vs not. Embedder and
      dimension decided here, on real data.
- [ ] `eval_real.json` holds aggregate metrics keyed by **opaque query ids only** —
      never query text, never retrieved ticket text. A test asserts the report
      schema permits no free-text field. Stored in `local/artifacts/`, not git.
- [ ] A measured 500-row enrichment run precedes the full pass; projected wall
      clock recorded before committing to it.

### M5 — Synthesis, triage and frontend

- [ ] Triage lanes (green/amber/red) with thresholds calibrated from the
      hand-graded set at a stated target precision.
- [ ] Every claim in a generated suggestion carries a citation resolvable to a
      ticket id; a test rejects any uncited claim.
- [ ] Evidence spans aligned **post-hoc** by sentence embedding — no LLM-provided
      character offsets anywhere in the code.
- [ ] Frontend (German): suggestion and source list both always visible, no
      accordion; inline citations that scroll to and highlight the source card;
      per-card match-reason chips; deep link per card; funnel line
      ("8 von 34 Treffern · Modellfamilie TX-22xx") with one-click *Filter
      aufheben*; disagreement surfaced ("6 von 8 …"); raw original text one click
      away; copy button.
- [ ] Explicit *kein starker Treffer* state reachable and tested — never a weak
      confident answer.
- [ ] **PII gating on display** (§4, §13): the API never returns
      `endCustomerName`, `merchantName`, `contact*` or `*PhoneNumber` in a search
      response; the raw-text view redacts them too. Test asserts a response payload
      contains no PII field, so the prototype cannot leak them through the UI even
      though it has no user accounts.
- [ ] **Window C run #2** after tuning; test-half metrics reported once.

### M6 — Feedback capture and KB promotion

- [ ] "Das hat geholfen" logged with the retrieval context that produced it.
- [ ] Amber ✗ offers exactly three chips (falsches Modell / falscher Fehler /
      Lösung unvollständig). **No free-text box anywhere** — test asserts none exists.
- [ ] Confirmed suggestions promotable to `kb_entry`, indexed alongside tickets.
- [ ] A promoted KB entry outranks its own source tickets for the same query;
      test asserts it.
- [ ] Amber sampling rate configurable.
- [ ] No incremental sync — out of scope per the design doc.

---

## Risks carried into implementation

| Risk | Where it bites | Mitigation |
|---|---|---|
| Postgres hunspell fails to compound-split | M0 Task 4 | behavioural test gates it; documented weaker fallback via synonyms |
| `solutions` usable rate too low to retrieve against | M1 Window A | measured before any tuning; process recommendation prepared with numbers |
| Profiler bug discovered only in Window A | M1 | selfcheck, no-network test, import allowlist, missing-column tolerance, stand-in CSV rehearsal |
| Synthetic corpus too clean → collapses on real data | M2 | noise applied programmatically from measured rates; cluster distribution asserted against the profile |
| Enrichment prompt needs more revisions than budgeted | M4 | 32B chosen for iteration speed; 500-row measured run before the full pass |
| Overfitting 7+ knobs to a few hundred queries | M4/M5 | dev/test split, staged tuning, coarse grids, bootstrap CIs required to adopt |
| Real eval only run once, at the end | M4/M5 | Window C designed to be re-run; two runs planned, config-matrix in one pass |
| Enrichment job crowded off the shared box | M4 | resumable/idempotent runner, fair-use re-check between batches |

## Data-leakage risks, and what actually stops each one

Ranked by how plausibly they would have fired. The first two were designed into the
plan's first draft and are the reason this section exists.

| Leak path | Why it was plausible | Control |
|---|---|---|
| Exception message quoting a corpus value, then pasted into an AI tool | selfcheck fires *only* when content is unsafe, so its message was guaranteed to carry it — and a failed sealed run is exactly when you reach for help | `SafetyViolation` accepts numeric facts only; a string raises `TypeError` at the raise site. Verbatim goes to the local detail log |
| A frequent company or person name in `top_tokens` / `top_bigrams` | the `min_frequency` floor stops *rare* strings; a dealer name that appears in hundreds of tickets sails over it, and it lives in description text so the column denylist misses it | `profiler/entities.py` sweep on every emitted string; bigrams filtered on both halves; residue to human review |
| Library exception text (`UnicodeDecodeError` embeds the offending bytes) | any malformed real row could trigger it | `safety.run_scrubbed` prints the exception *type* and a code; traceback to the local log |
| Dependency resolution inside a sealed window | `uv run` reaches the network, and new third-party code would run in-process with the real CSV | pinned image built in Phase 0; window runs `--network=none` |
| vLLM logging prompts to a file nobody shreds | default verbosity logs request content, on a shared box | `--disable-log-requests`, logs inside quarantine, shredded at teardown |
| Postgres volume and WAL surviving Window C | `DROP TABLE` leaves both behind | tmpfs data directory, `podman rm -v` |
| Retained real-corpus embeddings | inversion attacks reconstruct much of a short text when the model is public, and ours is | not retained at all; a second airlock cycle is the cheaper trade |
| Shingle-hash set as a membership oracle | anyone holding it can confirm guessed 8-token sequences | intersection computed on the box; only counts cross out |
| `.syn` synonym file committed as "config" | it is mined real-corpus vocabulary that looks like configuration | gitignored `*.syn`; lives in quarantine; only the mining script is committed |
| A real ticket pasted into a prompt template as a few-shot example | the single most common way this kind of project leaks | test asserts prompt files contain nothing absent from the synthetic corpus |
| `scp -r .` carrying `.env` and git history to a shared box | `scp` ignores `.gitignore` | `git archive \| tar -x` |
| Export filename naming the client | `Beispiel_Tickets_2026.csv` in a committed artifact | `source.filename` is hashed, not echoed |
| Core dump spilling ticket text | a crash mid-window on a box with 1 TB RAM | `ulimit -c 0` in the runbook |
| Anything data-shaped reaching a git remote | a remote added later would publish history retroactively | no remote; `test_repo_has_no_remote` asserts it; `git ls-files` asserts no data file is tracked |

**What is NOT claimed.** Permission deny rules and the sandbox read-deny stop
accidents, not a determined agent. The guarantees are structural: real data exists
only on the HPC box inside AI-free windows, `local/quarantine/` on the workstation
stays empty and `make check-clean` proves it, and git holds no data at all.
