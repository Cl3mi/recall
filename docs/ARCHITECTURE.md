# Architecture

## Overview

Recall (Lösungsfinder) is a local German service-ticket retrieval prototype: given a
technician's fault description, find earlier tickets about the same problem and their
solutions. PROJECT_BRIEF.md describes the intended system; this document describes what is
built. The approved M3 spec is `superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md`;
the M4 reranker spec is `superpowers/specs/2026-11-13-m4-reranker-design.md`.

Two facts shape every design choice:

1. **The client's ticket export is under NDA and AI agents may never see it.** Real rows are
   touched only inside manual, AI-free "airlock windows" on a shared H100 box. Only numeric
   aggregates and guarded reports ever come back. Everything an AI session can see is either
   synthetic or has passed a closed-allowlist guard.
2. **There is no real-data quality number yet.** Retrieval is built and measured on invented
   stand-in corpora; the first real-data measurement (Window C) is built and rehearsed on
   synthetic data but has not run.

There is no serving layer. The deliverable today is a library (`recall`), an indexer, an
evaluator and the pipelines that produce its inputs. No HTTP API, UI or LLM answer generation
exists.

```
 real export (NDA)                      workstation (AI-assisted, synthetic only)
       │                                      ▲
       ▼ airlock windows, box, no AI           │ numbers / guarded reports only
 ┌─────────────────────────────────────────────┴───────────────────────────────┐
 │ A profile.json   B gate_report.json   D report.json   E catalog.json   C eval_real.json │
 └──────┬──────────────────┬───────────────────┬──────────────┬────────────────┘
        │                  │                   │              │
        ▼                  │                   │              ▼
   fixtures (M2) ──────────┘ clears it     view.html     dev3 (3-vehicle fixture + labels)
   synthetic export                                          │
        └────────────────────────────┬───────────────────────┘
                                     ▼
                   recall: clean → embed → index (Postgres) → retrieve → eval
```

## Layers

| Layer | Code | Role |
|---|---|---|
| Data-protection guard | `tools/guard/` | Claude Code hook that denies reads of client data, enforces the airlock, lints new output code, and is the only exit for aggregates. |
| Sealed output | `src/recall/sealed.py` | The one place code that can see real rows may create files or logs. |
| Product library | `src/recall/` | Cleaning, German identifiers, schema, index, retrieval, rerank, evaluation. |
| Window pipelines | `profiler/`, `insight/`, `catalog/`, `recall.window_c` | Programs that run on real data inside a window and emit only releasable artifacts. |
| Synthetic data | `fixtures/`, `dev3/` | Invented exports for development, built from released artifacts only. |
| Infra | `infra/`, `Makefile` | Images, the window driver, the sealed runtimes, fair-use GPU claim, dev Postgres. |

Dependency direction: `recall.clean`, `recall.german` and `recall.db` import nothing else
from the repo. `recall.index` and `recall.eval` reach into `insight.extract` (row → `Ticket`)
and `profiler.gate.embedder` (the e5 embedder), so `profiler/` and `insight/` are runtime
dependencies of the product library, not only of the windows. `catalog`, `dev3` and
`fixtures` are not imported by `recall`.

## Components

### Cleaning and German text (`recall.clean`, `recall.german`)

`clean.pipeline.clean()` is the single text normaliser used by indexing, querying and the
profiler, so index and query text are symmetric. Order: HTML strip → quoted reply chains →
signature → PII redaction → whitespace collapse. It returns the text plus a `CleanReport`
(booleans and lengths; no values). Known cost: the phone pattern redacts part numbers such
as `1234.56789` to `[TEL]`. `german.identifiers` extracts and shapes error codes, serials and
model designations; real `fehlercode` values look like `1234-5`.

### Database (`recall.db`, `infra/postgres`)

Postgres 18 with pgvector, built from `infra/postgres/Dockerfile`. `db.migrate` applies
`migrations/NNNN_*.sql` in filename order and records a checksum per version; a migration
edited after being applied raises. Schema:

- `ticket`: one projection row per ticket: `created`, `category_id`, `vehicle_model_id`,
  `vehicle_serial` (casefolded), cleaned `problem_text` (title + description) and
  `solution_text`, `problem_vec vector(1024)`, nullable `solution_vec`, a stored generated
  `problem_tsv` (`to_tsvector('de_tech', problem_text)`, GIN indexed), `source_sha256` of the
  input rows. Identity columns (dealer, customer, contact) and the raw row never enter the DB.
- `eval_label(ticket_id, problem_key, fehlercode)`: what counts as "the same problem", in its
  own table so retrieval SQL cannot read it. `tests/integration/test_index_build.py` pins that
  `retrieve.py` never names it.
- HNSW (`vector_cosine_ops`) on `problem_vec` is created by `index.build` after the bulk load,
  because `CREATE INDEX CONCURRENTLY` cannot run through the migration runner.

German full text: the `de_tech` configuration maps words through `de_synonyms` (currently an
empty synonym file), then `german_hunspell`, then `german_stem`. The hunspell dictionary is
`de_compound`, derived at image-build time by `derive-compound-dict.pl`, because PostgreSQL's
ispell does not implement the affix-flag continuation that `hunspell-de-de` uses to permit
compounds; with the stock dictionary no compound is ever split. `de_tech_ua` (unaccent first)
exists for comparison. Do not replace the dictionary with stock `de_de`.

### Indexing (`recall.index`)

`index.build(dsn, rows, embedder, labels=None)` replaces the whole index: extract `Ticket`s,
clean problem and solution text, embed both with e5 using the `passage: ` prefix in batches
of 64, check the vector width is 1024, `truncate ticket cascade`, insert, then build HNSW.
The problem key is the supplied label (dev3 recipe id) or the normalised `fehlercode`
(upper-cased, whitespace removed; `None` when blank). Only `problem_vec` is searched;
`solution_vec` is stored for later use.

### Retrieval (`recall.retrieve`)

`search()` cleans the query like indexed text, then runs two arms of `POOL = 100`:

- **dense**: e5 with the `query: ` prefix, cosine order over `problem_vec`;
- **lexical**: `to_tsquery('de_tech', …)` over an OR of up to 64 distinct query words
  (`plainto_tsquery` would AND dozens of terms and match nothing), ranked by `ts_rank_cd`.

Both arms take the same SQL filter: `exclude_id` (a ticket must not find itself) and
`before` (only candidates created before a date, so the future cannot leak into a query).
Arms are fused by Python RRF, `score = Σ weight / (60 + rank)`, with deterministic tie-breaks
(best rank, then id). An optional `weights` map scales an arm. Each `Hit` records its per-arm
ranks and, when a reranker ran, its score. Retrieval never reads `eval_label`.

### Reranking (`recall.rerank`, opt-in)

With a reranker and `depth ≥ k`, the fused top `depth` are re-scored and reordered by the
reranker alone; the top k are returned. The reranker reads problem plus solution text
(`DOC_TEXTS = ("problem_solution",)`). `BgeReranker` is `BAAI/bge-reranker-v2-m3`, pinned by
revision, loaded offline, fp16, GPU only (it raises with no CUDA device). A pair is cut to
512 content tokens with the query capped at 128, and problem and solution split the rest, so a
long description cannot push out the fix. `OverlapReranker` is a deterministic CPU stand-in
for tests; its identity starts `overlap:` so it cannot pass as a model.

M4 outcome: on the stand-in corpus no cell met the win bar, so the reranker stays opt-in.
`Settings.rerank_model/depth/text` default to `None`. The real-data run is the only thing
that can judge it.

### Evaluation (`recall.eval`, `recall.eval_real`)

Shared metrics: macro-averaged (per problem group) recall@k divided by `min(k, |relevant|)`,
MRR and nDCG@k; a query with no relevant document is counted as unscored. Six variants
(`dense_passage`, `dense_query`, `lexical`, `fused`, `fused_query`, `fused_dense2`) over three
query modes (`full`, `title`, first 8 `head` words) show whether hybrid retrieval earns its
complexity. Optional extras: recall at several depths (`all` = both pools) and reranked cells
`rr_<model>_<text>` computed from one retrieval, with p50/p95 rerank seconds.

- `eval.run_synthetic`: every ticket whose group has ≥ 2 members is a query; the rest of its
  group is relevant. Labels come from a dev3 label file. Per-group output is allowed for
  synthetic data only.
- `eval_real.run_real`: queries are labelled tickets from the last six calendar months
  (`holdout_cutoff`); candidates are strictly earlier tickets; relevance is the same
  normalised `fehlercode`, composite codes counting as one label (a proxy, stated as such).
  Output has fixed keys, counts and numbers only. `validate_report` enforces that frozen
  schema, including count-consistency rules, and discloses no values. Label coverage is
  reported before quality.

### Settings (`recall.config`)

`pydantic-settings` with env prefix `RECALL_`. Only `pg_dsn` is consumed today (migrations,
the eval CLI). `embed_url`, `generator_url`, `embed_dims` and `ts_config` are declared but
unused: e5 runs in-process and nothing generates answers yet. Window C deliberately never
imports `recall.config`.

### Embedder (`profiler.gate.embedder`)

`E5Embedder` is `intfloat/multilingual-e5-large` at a pinned revision, offline
(`local_files_only`), masked-mean pooling, 512-token truncation, CUDA if present else CPU.
The device is not part of `identity`; a test pins that the vectors agree across devices.
`HashingEmbedder` is a deterministic trigram stand-in whose identity starts `hashing:`.

## Window pipelines (real data, AI-free)

`infra/profiler/window.sh --window a|b|c|d|e` drives all windows. Each window declares its
allowlisted output files, a shred list, an optional GPU claim and its command. `fetch` can
only copy the allowlisted files; `all` stops at the human review gate; a human must read the
report in full on the box before anything crosses.

| Window | Program | GPU | Crosses out | Purpose |
|---|---|---|---|---|
| A | `profiler` | no | `profile.json`, `profile_report.md` | Corpus profile: field fill, shapes, floored vocabulary, clusters. `selfcheck` and `blessing` refuse any unaccounted string. |
| B | `profiler.gate` | yes | `gate_report.json` | Leakage gate: checks whether the synthetic fixture shares shingles, near neighbours (e5 cosine), PII or roster names with the real corpus. |
| C | `recall.window_c` | yes | `eval_real.json` | First real-data retrieval baseline (see below). |
| D | `insight` | no | `report.json` | Deterministic insight report: origin, formats, time, concentration (numbers only), lifecycle, quality "usable share" and a joint quality cube, all floored at k = 50 and re-checked by `insight.guard`. `insight.view` renders it to one offline HTML page. |
| E | `catalog` | yes | `catalog.json`, `catalog.leak_report.json` | Problem catalog: clusters become abstract LLM-written "recipes". Operator edits the draft; `release` writes the catalog only for a passing leak report on those exact bytes. |

Common mechanics: `--network=none`, `ulimit -c 0` and `--ulimit core=0`, CPU cap 32 threads
(clamped on the box), GPU claimed by UUID through `infra/fairuse/gpu-fairuse2.sh` (shared
box, 60 GB cap), errors as a code plus counts, never a value. Window E is two containers on an
internal Podman network (an AWQ Qwen2.5-32B vLLM server and the catalog build) torn down on
any exit, followed by a no-network leak check. `profiler.safety.run_scrubbed` keeps raw
tracebacks off stdout.

### Window C in detail

Data flow: operator-staged immutable input → clean/embed/index → temporal retrieval and
scoring → sealed `eval_real.json` → full human review on the box → sealed workstation
staging → exact-schema validation → existing aggregate exporter → approved released
aggregate.

- `recall.window_c` is the only entry point. It requires `RECALL_WINDOW_C=1`, a fixed
  disposable DSN (`127.0.0.1:5432`), offline e5 and the exact 38-column header. All
  library output is discarded; only fixed codes (`C_START`, `C_DONE`, `E_INPUT`, `E_REPORT`,
  `E_FAILURE`) reach the sealed log, and the report is written by `sealed_atomic_json`.
  Exit codes: 2 report invalid, 3 failure, 4 bad input.
- `infra/profiler/window-c-runtime.sh` owns the runtime: pinned local image IDs, no pulls,
  GPU preflight with no data mount, a Postgres container plus a read-only worker. On Podman
  they share a pod created with `--network=none`; under Docker (rehearsal) the worker joins
  the database container's network namespace. No published ports; worker root is read-only,
  scratch is tmpfs, `/q` is the sole persistent writable mount. All Postgres data and WAL
  live on tmpfs and anonymous volumes are rejected. Runtime logs are discarded. One trap
  removes the exact containers and pod and fails loudly (`E_TEARDOWN`) if it cannot.
- Operator steps are explicit: `preflight`, `push`, `run`, `verify`, review on the box,
  `fetch`, `release`, `clean`. C refuses `all` and `fetch --clean`, and `--yes` cannot answer
  the review prompt. Images are built on the box from a clean published snapshot
  (`infra/eval/Dockerfile.window-c`, weights baked in).
- This baseline has no LLM and no reranker.

## Synthetic data chain

The fixtures exist so retrieval can be built without real text:

1. `fixtures` (M2) reads the gated Window A profile and plans every number (group sizes,
   fill by year, shape mixes), has an LLM write German fault text per near-duplicate group,
   renders rows in the real 38-column shape (double-encoded EAV `customData` included), and
   `verify` checks them against the plan. The LLM client (`fixtures.llm`) is cached and has a
   GPU-free fake. Sampling is not reproducible, so the generated fixture is the artifact.
2. `dev3` (M3 stand-in) reads only a released `catalog.json` (re-checked by `catalog.guard`,
   floors enforced) and writes three invented vehicles' tickets with ground-truth recipe
   labels (`tickets.csv`, `labels.jsonl`). This is the corpus the M3 and M4 measurements ran
   on. `dev3.standin` builds an invented catalog for tests.

Scores on these corpora show the code is correct, not that retrieval works on real tickets.

## Data-protection guard (`tools/guard`)

A Claude Code hook (`run-guard.sh` → `guard.py` → `recall_guard`):

- `policy`: read allowlist by default (tracked files, `local/released/`, `local/artifacts/`,
  `local/fixtures/`, scratchpad); `local/sealed/` and `local/quarantine/` and data-file
  suffixes denied; `sniff` catches client data whatever the file is called.
- `bashcheck`: analyses command text for paths, programs, scripts and git use; unresolvable
  paths (`$VAR`, `$(...)`) are denied.
- `airlock`: while the marker exists every tool call is denied; a human closes it.
- `lint` (pre-commit): new `open(..., "w")`, `FileHandler`, `to_csv` and similar in `src/`,
  `profiler/`, `insight/`, `fixtures/` must go through `recall.sealed`. Best effort, not a
  security boundary.
- `release` / `export_aggregate.py`: the only exit from the sealed root. Accepts numbers,
  booleans, nulls and containers of them, and writes to `local/released/`.
- `store`: session ledger and audit log inside the sealed root.

`recall.sealed` marks a directory with a `.sealed` file; the guard denies anything under or
next to a marker. The guard, its registration and the marker are operator-maintained.

Other protective layers inside the pipelines: `insight.extract.Ticket` hides free text and
identifiers from `repr`; `insight.release` defines one "may this value leave" rule shared by
builders and guard; the catalog has a closed schema, a scrubber, a verbatim-run detector and
a corpus-wide leak check.

## Deployment topology and tooling

- **Workstation** (Arch Linux, Docker, no Podman): `make db-up` runs Postgres on `:5433` from
  `infra/postgres/compose.yml`; `make migrate`, `make test`, `make lint`. Python 3.12, `uv`
  with a CUDA 12.6 PyTorch wheel pinned in `pyproject.toml` (the only index with torch 2.14).
- **Box** (shared H100, Podman, GPU through the `podman-gpu` UUID wrapper and the fair-use
  claim): images are built there from the published snapshot. Image set: the profiler image
  (`infra/profiler/Dockerfile`: weights baked in; carries `insight`, `catalog`, `fixtures`),
  the Window C image, the M4 eval image (`infra/eval/Dockerfile`: HF cache mounted
  read-only), the pinned Postgres image, and a pinned vLLM image for Window E.
- **Rehearsals** (`make window-{a,b,c,d,e}-rehearsal`): synthetic end-to-end runs of the real
  window commands. The rehearsal reads the command back out of `window.sh --dry-run` so it
  cannot rehearse something the window does not run.
- **Publishing**: `make publish` pushes a scanned snapshot of allowlisted paths as one new
  commit, never `git push`, because local history holds NDA material.

## Decisions

The reasons behind these designs are recorded in `docs/adr/` (index: `docs/adr/README.md`):
data handling and windows in 0002, 0003, 0023-0028; retrieval and schema in 0006-0017 and 0041;
the reranker in 0019; evaluation and Window C in 0005, 0020-0022 and 0042-0044; synthetic data,
catalog and insight in 0029-0036; compute in 0037-0040. The README also lists decisions still open
and decisions that have no record yet. Window C's records (0021, 0022, 0044) are Proposed.

## Tests

`tests/unit` (pure, synthetic), `tests/integration` (Postgres, marked `needs_pg`; includes the
JS view-model harnesses run in node), `tests/leak` (hostile-LLM and release-gate suites),
`tests/guard`. Other markers: `needs_gpu`, `needs_model`. Window scripts are tested with
mocked runtimes plus the contract tests `test_window_{c,d,e}_contract.py`.

## Verification limits and remaining work

Synthetic unit and mocked shell checks are available. Actual Postgres integration, image
builds, Docker rehearsal and native Podman/GPU rehearsal of Window C remain unverified in
the restricted agent sandbox. Podman infra-command and GPU-wrapper compatibility must be
proved on the box before any real-data window. Host tmpfs and swap arrangements need operator
inspection; tmpfs alone does not establish the no-disk requirement. Two Window D dry-run
regex tests were failing before Window C work (output splits before `unknown`).

Not built: any API or UI, answer generation, same-serial history boost, a `fehlercode` arm,
CPU reranker fallback, synonym mining into `de_synonyms`, and Window C evaluation of the
reranker. Next is the real-data Window C run (M3 Task 8).

The operator added `sealed_atomic_json`; it owns private temporary report files and cleans
ordinary failures. Window C cleanup also covers its precise private filename patterns after
a hard kill. This helper and all guards remain operator-maintained.
