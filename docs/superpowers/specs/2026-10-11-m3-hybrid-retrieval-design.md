# M3 — Baseline hybrid retrieval and the dual eval harness

**Status:** design approved section by section with the operator, 2026-10-11.
**Milestone (PROJECT_BRIEF §15):** *Baseline hybrid retrieval + dual eval harness — recall@10 /
MRR reported on both corpora, no LLM in the loop.*
**Scope:** all of M3 in one spec, by operator decision — the index, retrieval, the synthetic
harness, the real harness, and Window C's command block.

## Decisions taken during design

| Decision | Choice | Why |
|---|---|---|
| Scope | All of M3 in one spec | Operator, 2026-10-11 |
| Relevance | **Same problem**, on both corpora | Both harnesses measure the same thing, so §9's divergence rule compares like with like; matches "every variant resolution must reach the technician" |
| Corpus | **Everything, all years, no rows dropped** | Invariant "rows are never dropped"; an old ticket with the right fix is still the right fix. Weak years get a completeness penalty in M4, not exclusion |
| Architecture | **Postgres-native, RRF fused in Python** | The lexical arm must be the real `de_tech` FTS with compound splitting, which exists only as Postgres configuration |

Rejected: an in-memory retriever (loses `de_tech`, so it would measure a lexical arm that never
ships); RRF inside one SQL CTE (harder to test, and M4's reranker wants candidates in Python).

## 1. Data model and index build

Migration **`0003_index.sql`** creates three tables.

- **`ticket_raw`** — immutable source: `ticket_id`, `row jsonb` (all 38 columns as exported),
  `source_sha256`. Never edited, never dropped.
- **`ticket`** — the projection retrieval reads:
  - `ticket_id`, `created` (date), `category_id`, `vehicle_model_id`
  - `problem_text` = title + cleaned description. This is §6.1's problem vector *minus* the
    enrichment fields (canonical problem, symptoms, components), which arrive in M4.
  - `solution_text` = cleaned solutions
  - `problem_vec vector(1024)`, `solution_vec vector(1024)` — e5, `passage:` prefix
  - `problem_tsv tsvector` — generated column, `to_tsvector('de_tech', problem_text)`
- **`eval_label`** — `ticket_id`, `problem_key`, `fehlercode`. `problem_key` is the planner group
  id on synthetic data and the normalised `fehlercode` on real data (upper-cased, whitespace
  removed); it is `null` when there is no code, and a `null` key is neither a query nor relevant
  to anything. **Kept in its own table so
  retrieval SQL structurally cannot read it.** Whatever defines relevance must be invisible to the
  retriever, or the metric is circular. Using `fehlercode` as an identifier *arm* is deferred to
  M4, where §12's "retrieval arm or filter facet" question is answered.

**PII:** `ansprechpartner` and `ansprechpartner-tel` are never read (parked decision 2026-08-17).
The `customData` parser extracts `fehlercode` and nothing else.

**Builder** — `python -m recall.index build --csv <path>`:
load → clean (`recall.clean.pipeline`) → embed (`profiler.gate.embedder.E5Embedder`, the same
class the gate uses, so GPU when present and CPU otherwise) → insert → then
`CREATE INDEX … USING hnsw (problem_vec vector_cosine_ops)` **after** the bulk load: faster than
maintaining it during inserts, and `CREATE INDEX CONCURRENTLY` cannot run through the migration
runner (`docs/STATE.md`, carried items). `solution_vec` is stored and not indexed — nothing queries
it in M3.

## 2. Retrieval

**`recall.retrieve.search(text, k=10, pool=100)`** — one pure entry point returning the top `k`
hits, each carrying its **per-arm ranks** so every result is explainable and the eval can score
each arm on its own.

1. **Symmetric normalisation.** The query passes through the same `recall.clean.pipeline` as the
   index. §5 calls index/query symmetry "the core trick".
2. **Dense arm.** e5 over `problem_vec`, `<=>` cosine via HNSW, top `pool`.
   **Prefix:** `passage:` on both sides. e5's own guidance for symmetric tasks is `query:` on both
   sides; `passage:` is chosen to keep the stored vectors identical to those the leakage gate
   measured, which is why the gate shares this embedder — switching would void finding 18's
   calibration for the vectors M3 stores. The harness A/Bs the two (§3), so this is a measured
   choice, not a guess.
3. **Lexical arm.** `de_tech` over `problem_tsv`, `ts_rank_cd`, top `pool`.
   **The query is an OR of its lexemes.** `plainto_tsquery` ANDs every term; a pasted ticket has
   dozens, so almost nothing would match and the arm would go silently empty. A unit test pins that
   a long query still returns candidates.
4. **Fusion.** RRF, `score = Σ 1/(60 + rank)`, a pure Python function. Unit tests: ties, a document
   present in one arm only, an empty arm.
5. **Self-exclusion.** When an indexed ticket is the query, its own id is excluded. Otherwise every
   synthetic query finds itself at rank 1 and the metric is perfect and meaningless.

**Absent from M3, deliberately:** metadata boosts (rerank-time, §6.5 → M4), the reranker (M4), the
`fehlercode` arm (M4), and any filter on empty solutions.

## 3. The eval harness

**One core, two wrappers.** `recall.eval.score(queries, relevant, retriever)` computes identical
metrics for both corpora, reported separately for **dense-only, lexical-only and fused** — the
evidence for whether hybrid retrieval earns its complexity — and for both dense prefixes.

**Metrics:** `recall@10`, `MRR`, `nDCG@10`, `n_queries`, label coverage.

- `recall@10` = hits ÷ **min(10, |relevant|)**. Plain hits ÷ |relevant| would cap a member of the
  216-ticket group at 10/215 and read as failure.
- **Macro-averaged per problem group**, not per query, so the one large group cannot contribute
  216 near-identical queries and dominate.

### `eval_synthetic.json` — "is the code correct"

- **Ground truth:** the planner group, **re-derived** from `build_plan(profile, rows, seed)`, not
  emitted as a new sidecar — changing the generator's output would force re-accepting the fixture.
  **The first implementation step verifies that ticket ids follow plan order**; if they do not,
  this point is revisited before anything else is built on it.
- **Queries:** every ticket in a group of size ≥ 2; the rest of its group is relevant. Singletons
  (the large majority) have nothing to find; they are counted and reported, not scored.
- The report records which corpus it ran on. **Numbers on a `--fake` corpus are code-correctness
  evidence, not quality evidence** — stub text near-duplicates itself.

### `eval_real.json` — "does it work"

- **Queries:** tickets created in the 6 months before the **latest `created` date in the
  export** (not the wall clock — the export is a snapshot, and a wall-clock window would drift
  empty) that carry a `fehlercode`.
- **Candidates:** only tickets created **before** that cutoff — a query-time filter, nothing deleted
  from the index, so the future cannot leak into the past.
- **Relevant:** a candidate with the same `problem_key`, from `eval_label`.
- **Stated bias:** only a minority of tickets carry a code, so this measures coded faults only, and the
  report says so.
- **Aggregates only:** no ticket ids, no text, keyed by opaque query ids where keyed at all. A
  key-set pin test mirrors the gate report's, so adding a field is a conscious act.

**Out of M3:** §9's 50–100 human-graded queries — they need a support engineer and belong with
M4/M5 answer quality.

## 4. Window C — the sealed real-data run

M3's Window C is **ingest → index → eval**, no LLM. The runbook's vLLM and enrichment-state
controls bind from M4. These bind now: **Postgres on tmpfs, destroyed with the run; only
`eval_real.json` crosses out; everything else is shredded.**

**Two containers, still sealed.** A **podman pod created `--network=none`**: containers in a pod
share one network namespace whose only interface is loopback, so the pipeline reaches Postgres on
`localhost` and nothing reaches anything else. Postgres runs from `recall/postgres:18` (where
`de_tech` and the compound dictionary live), data directory on **tmpfs**; `podman pod rm -f`
destroys it, so real rows never touch disk.
**Unverified:** the rehearsal's first step proves that a `--network=none` pod's shared loopback
works on the box, as CDI was proven before being relied on.

**`window.sh`** gains a contract flag **`WINDOW_POD=1`**. When set, `cmd_run` creates the pod,
starts tmpfs Postgres, waits for readiness, runs `WINDOW_CMD` in the pod, and **tears the pod down
on a trap**, failure included. Window C's command:

```
python -m recall.window_c --csv /q/export.csv --out /q/eval_real.json
```

which migrates, builds and evaluates. It claims GPU 0 like Window B, with the same thread cap and
provenance flags. `WINDOW_OUT=(eval_real.json)`. Expected cost: minutes — one problem and one
solution vector per ticket at the measured ~96 docs/s on the H100, plus load and HNSW build.

**`rehearse-window-c.sh`** mirrors B's, carrying over what B taught:

- the command read back out of `--dry-run`, never a copy
- the stale-image guard over **both** `profiler/` and `src/recall/`, `LC_ALL=C`
- CUDA build present; embedder on `cuda` with a card, `cpu` without
- `eval_real.json` exists, key set pinned, **no ticket ids, no corpus tokens**
- **the pod and its tmpfs are gone afterwards**; only the artifact remains in quarantine

The fixture stands in for the export. Locally there are no pods: docker's
`--network container:<pg>` shares the namespace instead — the equivalent mechanism, not the same
one — so the rehearsal must also run once on the box.

**Ships:** both images — `recall/postgres:18` (small) and the 9.3 GB pipeline image.

## Testing

- **Unit:** RRF (ties, single-arm, empty arm), OR-tsquery construction, metric functions
  (min(10,|rel|) recall, macro-averaging, MRR, nDCG against hand-computed values), self-exclusion,
  `customData` → `fehlercode` parsing that provably never returns `ansprechpartner`.
- **Integration (`needs_pg`, plus `needs_model` for the dense arm):** build an index from a small
  fixture, assert both arms return candidates, a long query reaches the lexical arm, the
  cutoff filter excludes post-cutoff candidates, `eval_label` is never referenced by retrieval SQL.
- **Report safety:** key-set pin on `eval_real.json`; a test that serialises a report and finds no
  ticket id and no corpus token.
- **Rehearsal:** `make window-c-rehearsal`, green locally and once on the box.

## Rule carried from M2

**If a test fails and the test looks wrong, stop and report it rather than adjusting the test.**
And: a test that passes for the wrong reason is worse than no test. Every new assertion here must
be one that has been seen to fail for the right reason — self-exclusion, the OR-tsquery, the cutoff
filter and the `eval_label` isolation are each written so the wrong implementation fails them.
