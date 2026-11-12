# M3 implementation plan: hybrid retrieval and eval, built on the dev3 stand-in

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Read the state file first:
> `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.state.md`.

**Goal:** finish M3 (baseline hybrid retrieval and its eval harness) and use the synthetic numbers
to decide what M4 builds first.

**Architecture:** Postgres-native retrieval (pgvector dense arm, `de_tech` lexical arm), RRF fused
in Python, one scoring core in `src/recall/eval.py`. Spec: `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md`.

**Tech Stack:** Python 3.12, psycopg 3, pgvector, `multilingual-e5-large`, pytest, ruff (line length 100).

---

## Status (2026-11-11)

| Task | What | State |
|---|---|---|
| 1-7 | index, retrieval, scoring, synthetic wrapper, label loader, query modes | **done**, commits below |
| 8 | real-data wrapper and Window C | **deferred by design**, needs an operator window (see Task 8) |
| 9-13 | missing fused variant, per-group metrics, run, fusion decision, M4 gate | **open, start at Task 9** |

Done commits: `9cbc6d6` migration and builder, `ae352df` fusion, OR-query, metrics, `3707857` search,
`8232788` synthetic eval, `3641837` label loader and CLI, `2124f77` query modes. Unit tests for these
are green; the Postgres integration tests need `make db-up`.

**What the first real-writer run found** (details under Results): the ceiling is lifted, `query:`
beats `passage:` by 5 to 13 points, and the fusion verdict is still open because the one `fused` row
was built from the `passage:` dense arm. Twin-pair separation was never measured. Tasks 9 to 12 close
those gaps.

## Amendments to the spec

1. **Synthetic ground truth is the dev3 label, not a re-derived planner group.** `dev3` writes a
   label file mapping every ticket to `recipe_id`, vehicle and persona. `eval_label.problem_key` =
   `recipe_id`; relevant = same recipe, same or other vehicle.
2. **Build against the dev3 stand-in, not the old 1,500-row fixture.** Invented text proves the code
   and the metrics, not retrieval quality on real tickets (the report's own caveat).
3. **Same-serial history is a retrieval signal** (STATE.md: over a third of real tickets have an
   earlier ticket on the same serial). M3 only *reports* how often a same-serial earlier ticket is
   relevant; using it as a signal is M4.
4. **Tests must not name or read data files** (guard). Tests build corpora in memory with
   `tests/catalog_corpus.py`; the CLI takes `--corpus` and `--labels` as arguments.
5. **Query-side prefix (new, 2026-11-11).** The spec chose `passage:` on both sides. The stand-in
   results favour `query:` on the query side. Only the query side changes; stored vectors keep
   `passage:`, so the leakage gate's calibration is untouched. The default changes in Task 12 and
   only if Task 11 confirms it.

## Tasks 1-8 (original plan)

- [x] **1. Migration `0003_index.sql`**: `ticket_raw`, `ticket`, `eval_label`.
- [x] **2. `recall.retrieve.fuse`** (pure RRF): ties, one-arm-only, empty arm, per-arm ranks.
- [x] **3. `recall.retrieve.or_query`**: OR of lexemes, capped.
- [x] **4. `recall.index.build`**: load, clean, embed, insert, HNSW after the bulk load; labels only
  into `eval_label`.
- [x] **5. `recall.retrieve.search`**: dense and lexical arms, symmetric cleaning, self-exclusion,
  date cutoff.
- [x] **6. `recall.eval.score`**: recall@k over `min(k, |relevant|)`, MRR, nDCG, macro per group.
- [x] **7. `recall.eval` synthetic wrapper and CLI**: both e5 prefixes, lexical, fused, three query
  modes, label loader, aggregates-only report with a key-set pin.
- [ ] **8. Real-data wrapper and Window C.** Deferred. Not executable from this plan. When the
  operator schedules a window, write its own plan from spec sections 3 (`eval_real.json`) and 4
  (Window C: pod with tmpfs Postgres, `WINDOW_POD=1`, rehearsal). Prerequisites before starting:
  Task 11 shows the harness is sound, Task 12 has fixed the fusion default, and the operator has a
  window and a catalog decision (see the handoff doc). Two rules carry over:
  `run_synthetic`-style per-group output must stay **off** on real data (a group key there is a
  `fehlercode`), and `eval_real.json` stays aggregates only with a key-set pin test.

## Tasks 9-13 (open)

Run unit tests with `env -i PATH=/usr/bin:/bin HOME=<home> .venv/bin/python -m pytest -q <paths>`
(`<home>` is your home directory; the `env -i` clean environment is deliberate).
Integration tests need Postgres: `make db-up`, then add
`PG_DSN=postgresql://recall:recall_dev_only@localhost:5433/recall` to that `env -i` command. Lint
with `.venv/bin/ruff check` and `.venv/bin/ruff format` (if `ruff format` touches
`tests/unit/test_dev3_main.py`, `git checkout tests/unit/test_dev3_main.py`). Commit messages are a
plain `git commit -m "..."` ending with the attribution lines from the session reminder.

### Task 9: score fusion with the `query:` dense arm

Why: the existing `fused` variant uses the `passage:` dense arm, so it was compared against an arm
that is not one of its inputs. Add the variant that matters, keep `fused` as the baseline.

**Files:**
- Modify: `src/recall/eval.py` (the `VARIANTS` dict, line 26)
- Create: `tests/unit/test_eval_variants.py`
- Modify: `tests/integration/test_eval_synthetic.py` (line 19, the `VARIANTS` set)

- [x] **Step 1: Write the failing tests**

`tests/unit/test_eval_variants.py`:

```python
from recall import eval as ev


def test_the_fused_query_variant_asks_with_the_query_prefix_and_uses_both_arms():
    variant = ev.VARIANTS["fused_query"]
    assert variant == {"prefix": ev.QUERY_PREFIX}  # no "arms": both arms, as for "fused"


def test_the_variants_are_exactly_these():
    assert set(ev.VARIANTS) == {"dense_passage", "dense_query", "lexical", "fused", "fused_query"}
```

In `tests/integration/test_eval_synthetic.py` change line 19 to:

```python
VARIANTS = {"dense_passage", "dense_query", "lexical", "fused", "fused_query"}
```

- [x] **Step 2: Run them to see them fail**

Run: `env -i PATH=/usr/bin:/bin HOME=<home> .venv/bin/python -m pytest -q tests/unit/test_eval_variants.py`
Expected: 2 failed (`KeyError: 'fused_query'` and a set mismatch).

- [x] **Step 3: Implement**

In `src/recall/eval.py` replace the `VARIANTS` dict with:

```python
VARIANTS = {
    "dense_passage": {"arms": ("dense",), "prefix": index.PASSAGE},
    "dense_query": {"arms": ("dense",), "prefix": QUERY_PREFIX},
    "lexical": {"arms": ("lexical",)},
    "fused": {},  # dense with the search default prefix (passage:) plus lexical
    "fused_query": {"prefix": QUERY_PREFIX},  # dense with query: plus lexical
}
```

- [x] **Step 4: Run unit and integration tests**

Run the unit file again (expected: 2 passed), then with `PG_DSN` set:
`... pytest -q tests/integration/test_eval_synthetic.py tests/integration/test_eval_modes.py`
Expected: all passed.

- [x] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/recall/eval.py tests/unit/test_eval_variants.py
.venv/bin/ruff format src/recall/eval.py tests/unit/test_eval_variants.py
git add src/recall/eval.py tests/unit/test_eval_variants.py tests/integration/test_eval_synthetic.py
git commit -m "feat(m3): score fusion with the query-prefixed dense arm as its own variant"
```

> **Milestone: fused_query variant in** - state must be checkpointed here before continuing.

### Task 10: per-group metrics, synthetic only

Why: the report is macro only, so twin-pair separation (R001/R009, R002/R010, R003/R012,
R004/R011) cannot be read. Per-group numbers are opt-in, because on real data a group key is a
`fehlercode` and must never leave the sealed root.

**Files:**
- Modify: `src/recall/eval.py` (`score` at line 71, `run_synthetic` at line 104, `main` at line 180)
- Modify: `tests/unit/test_eval_metrics.py` (append)
- Modify: `tests/integration/test_eval_synthetic.py` (append)

- [x] **Step 1: Write the failing tests**

Append to `tests/unit/test_eval_metrics.py`:

```python
def test_per_group_numbers_are_absent_by_default_and_exact_when_asked():
    rankings = {"q1": ["a"], "q2": ["x"], "q3": ["b"]}
    relevant = {"q1": {"a"}, "q2": {"a"}, "q3": {"b"}}
    group = {"q1": "G1", "q2": "G1", "q3": "G2"}
    assert "groups" not in ev.score(rankings, relevant, group)
    groups = ev.score(rankings, relevant, group, per_group=True)["groups"]
    assert set(groups) == {"G1", "G2"}
    assert groups["G1"]["n_queries"] == 2
    assert groups["G1"]["recall_at_10"] == pytest.approx(0.5)  # q1 finds it, q2 does not
    assert groups["G2"]["recall_at_10"] == 1.0
    assert set(groups["G1"]) == {"n_queries", "recall_at_10", "mrr", "ndcg_at_10"}
```

Append to `tests/integration/test_eval_synthetic.py`:

```python
def test_per_group_numbers_are_off_unless_asked_and_name_the_groups_when_on(conn):
    assert "groups" not in ev.run_synthetic(conn, EMBEDDER, k=10)["modes"]["full"]["fused"]
    on = ev.run_synthetic(conn, EMBEDDER, k=10, per_group=True)
    assert set(on["modes"]["full"]["fused"]["groups"]) == {"R0", "R1"}  # SINGLE has no query
```

- [x] **Step 2: Run to see them fail**

Run: `env -i PATH=/usr/bin:/bin HOME=<home> .venv/bin/python -m pytest -q tests/unit/test_eval_metrics.py`
Expected: 1 failed (`TypeError: score() got an unexpected keyword argument 'per_group'`).

- [x] **Step 3: Implement**

Replace `score` in `src/recall/eval.py` with:

```python
def score(
    rankings: dict[str, list[str]],
    relevant: dict[str, set[str]],
    group: dict[str, str],
    k: int = 10,
    per_group: bool = False,
) -> dict:
    """Macro-averaged recall@k, MRR and nDCG@k. A query with no relevant document is counted
    in `n_unscored` and otherwise ignored; with nothing scorable the metrics are None.

    `per_group` adds the same three numbers for every group under "groups". It is for synthetic
    corpora only: a group key on real data is a fehlercode, which must not leave the sealed root."""
    by_group: dict[str, list[QueryMetrics]] = defaultdict(list)
    unscored = 0
    for query, ranked in rankings.items():
        wanted = relevant.get(query, set())
        if not wanted:
            unscored += 1
            continue
        by_group[group[query]].append(query_metrics(ranked, wanted, k))

    def mean(ms: list[QueryMetrics], pick) -> float:
        return sum(pick(m) for m in ms) / len(ms)

    def macro(pick) -> float | None:
        if not by_group:
            return None
        return sum(mean(ms, pick) for ms in by_group.values()) / len(by_group)

    result = {
        "k": k,
        "n_queries": sum(len(ms) for ms in by_group.values()),
        "n_unscored": unscored,
        "n_groups": len(by_group),
        f"recall_at_{k}": macro(lambda m: m.recall),
        "mrr": macro(lambda m: m.rr),
        f"ndcg_at_{k}": macro(lambda m: m.ndcg),
    }
    if per_group:
        result["groups"] = {
            name: {
                "n_queries": len(ms),
                f"recall_at_{k}": mean(ms, lambda m: m.recall),
                "mrr": mean(ms, lambda m: m.rr),
                f"ndcg_at_{k}": mean(ms, lambda m: m.ndcg),
            }
            for name, ms in sorted(by_group.items())
        }
    return result
```

In `run_synthetic` change the signature to
`def run_synthetic(conn, embedder, k: int = 10, per_group: bool = False) -> dict:` and the scoring
line to `modes[mode][name] = score(rankings, relevant, group, k, per_group)`.

In `main` add after the `--k` argument:

```python
    parser.add_argument(
        "--per-group",
        action="store_true",
        help="synthetic labels only: on real data a group key is a fehlercode",
    )
```

and call `run_synthetic(conn, embedder, k=args.k, per_group=args.per_group)`.

- [x] **Step 4: Run all eval tests**

Run: unit file (expected: all passed, including the existing key-set pin
`test_the_report_carries_exactly_these_keys`, which proves the default output did not change), then
with `PG_DSN`: `... pytest -q tests/integration/test_eval_synthetic.py tests/integration/test_eval_modes.py`
Expected: all passed (`test_the_report_holds_aggregates_only` still pins the top-level keys).

- [x] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/recall/eval.py tests/unit/test_eval_metrics.py tests/integration/test_eval_synthetic.py
.venv/bin/ruff format src/recall/eval.py tests/unit/test_eval_metrics.py tests/integration/test_eval_synthetic.py
git add src/recall/eval.py tests/unit/test_eval_metrics.py tests/integration/test_eval_synthetic.py
git commit -m "feat(m3): opt-in per-group metrics for synthetic corpora"
```

### Task 11: re-run the eval on the stand-in (the user runs it)

**Files:** none changed; results go into this plan.

- [x] **Step 1: Get the code onto the GPU box.** `make publish` on the workstation, then `git pull`
  in the box's checkout. If the repo is private again the box cannot pull: ask the user whether to
  make it public for the pull. Confirm with `git log --oneline -1` on both sides.
- [x] **Step 2: Bring the box up.** The Postgres container and the fixture are described in
  `docs/handoff-hpc-continuation-2026-11-10.md` (evening update). Rootless containers die with the
  last ssh session: restart the container and hold a session open before the run. The fixture
  (`dev3-confusable`) is already on the box; do not regenerate it, because the eval is only
  comparable on the same corpus.
- [x] **Step 3: The user runs the eval** with the command from that handoff section, adding
  `--per-group` (the guard blocks agent commands that name data files) and pastes the JSON.
- [x] **Step 4: Record the results** in this plan under "Results, 2026-11-11" (table for
  `fused_query` next to `fused`, and the per-group recall@10 for the twin pairs), then commit
  `docs(m3): ...`.

Read the output with this table:

| Question | Where | Decision |
|---|---|---|
| Is `query:` still better than `passage:`? | `dense_query` vs `dense_passage` | yes: Task 12 step A |
| Does fusion beat its own inputs? | `fused_query` vs max(`dense_query`, `lexical`), per mode | beats in all three: keep RRF, skip Task 12 step B |
| Do the twins fail? | per-group recall of R009-R012 and R001-R004 | clearly lower than the other groups: Task 13 says reranker |

> **Milestone: per-group results in hand** - state must be checkpointed here before continuing.

### Task 12: apply the fusion and prefix decision

Do only the steps the Task 11 table calls for.

**Files:**
- Modify: `src/recall/index.py` (line 22 area), `src/recall/retrieve.py`, `src/recall/eval.py`
- Modify: `tests/unit/test_retrieve_fusion.py` (append), `tests/unit/test_eval_variants.py`

**Step A: make `query:` the default query prefix** (only if `dense_query` beat `dense_passage`)

- [x] **A1. Write the failing test** in `tests/unit/test_eval_variants.py`:

```python
from recall import index, retrieve


def test_queries_default_to_the_query_prefix_and_stored_vectors_keep_passage():
    import inspect

    assert inspect.signature(retrieve.search).parameters["prefix"].default == index.QUERY
    assert index.PASSAGE == "passage: "  # stored vectors, same as the leakage gate measured
    assert ev.VARIANTS["fused"] == {"prefix": index.PASSAGE}  # the baseline stays the baseline
```

- [x] **A2. Run it**: expected FAIL (`AttributeError: module 'recall.index' has no attribute 'QUERY'`).
- [x] **A3. Implement.** In `src/recall/index.py` after the `PASSAGE` line add
  `QUERY = "query: "  # e5 prefix for what a technician types; stored vectors stay PASSAGE`.
  In `src/recall/retrieve.py` change `prefix: str = index.PASSAGE,` to `prefix: str = index.QUERY,`
  and the docstring sentence "(the stored vectors use "passage: ")" stays true. In
  `src/recall/eval.py` set `QUERY_PREFIX = index.QUERY` (line 21) and change the `"fused"` entry to
  `"fused": {"prefix": index.PASSAGE},  # baseline: dense with passage: plus lexical`.
- [x] **A4. Run the whole suite** (with `PG_DSN`): `... pytest -q`. Expected: all passed. A test
  that pinned the old default is a real finding: stop and report it, do not adjust the test blindly.
- [x] **A5. Commit**: `git add` the touched files, `git commit -m "feat(m3): queries use the query prefix by default"`.

**Step B: weighted fusion** (only if `fused_query` is below max(`dense_query`, `lexical`) in some mode)

- [x] **B1. Write the failing test** (append to `tests/unit/test_retrieve_fusion.py`):

```python
def test_a_heavier_arm_outvotes_the_other():
    arms = {"dense": ["b", "a"], "lexical": ["a", "b"]}
    assert [h.doc_id for h in retrieve.fuse(arms)] == ["a", "b"]  # a tie, broken by id
    weighted = retrieve.fuse(arms, weights={"dense": 2.0})
    assert [h.doc_id for h in weighted] == ["b", "a"]
```

- [x] **B2. Run it**: expected FAIL (`TypeError: fuse() got an unexpected keyword argument 'weights'`).
- [x] **B3. Implement.** In `src/recall/retrieve.py` change `fuse` to
  `def fuse(arms, *, limit=None, weights: dict[str, float] | None = None)`, change the score line to
  `scores[doc_id] = scores.get(doc_id, 0.0) + (weights or {}).get(arm, 1.0) / (RRF_K + position)`,
  add `weights: dict[str, float] | None = None` to `search` (after `prefix`) and pass
  `fuse(found, limit=k, weights=weights)`. In `src/recall/eval.py` add one variant:
  `"fused_dense2": {"prefix": QUERY_PREFIX, "weights": {"dense": 2.0}},` and add it to the variant
  sets in `tests/unit/test_eval_variants.py` and `tests/integration/test_eval_synthetic.py`.
  One weight only: lexical is unusually regular on invented text, so do not tune several.
- [ ] **B4. Run the suite, commit** (`feat(m3): weighted rank fusion and one dense-weighted variant`),
  then repeat Task 11 steps 1 to 4 once to score `fused_dense2`.

> **Milestone: fusion decision applied** - state must be checkpointed here before continuing.

### Task 13: M4 gate (a decision, not code)

- [ ] **Step 1:** write the M4 start into this plan, from the per-group numbers:
  - twin groups clearly below the others even with the best dense arm: the next plan is a
    **reranker** (GPU time, latency and a model to ship into the sealed environment, so it needs this
    evidence);
  - loss spread evenly across groups: skip the reranker, put the effort into Task 8 (real wrapper,
    Window C) instead.
- [ ] **Step 2:** if a same-serial boost is wanted, its next plan implements it **behind a flag** and
  judges it on real data only. This fixture has 3 vehicles, so its same-serial share is 0.93 by
  construction and would overstate the boost.
- [ ] **Step 3:** the `fehlercode` arm waits for real data: the stand-in generates codes from a shape
  pattern, so an exact-code arm would look perfect or useless for reasons unrelated to real tickets.
- [ ] **Step 4:** update the memory entry `m3-standin-eval-2026-11-10` and the handoff, commit docs.

## What this plan deliberately does not do

- No change to `catalog/` or `dev3/`, no lowering of `MIN_RECIPES` (operator decision).
- No metadata boosts, reranker or `fehlercode` arm before Task 13 says so.
- No quality claims from stand-in numbers.

## Environment

`make db-up` starts Postgres on port 5433 (docker compose); the Postgres tests read `PG_DSN`. The
GPU box, its Postgres container and the fixture are described in
`docs/handoff-hpc-continuation-2026-11-10.md`.

## Results, 2026-11-10 (confusable stand-in, real 32B writer, e5 on CPU)

**Corpus.** 12 invented recipes (8 plus 4 near-twins of R001, R002, R003, R004 that share component
and mostly symptom but have another cause and fix; same title templates), 510 tickets on 3
vehicles, text by `Qwen2.5-32B-Instruct-AWQ`, `verify` clean. Index: `multilingual-e5-large`
(pinned revision), pgvector HNSW, `de_tech` lexical arm, RRF `k=60`. k=10, macro over 12 groups.
Synthetic text, so these numbers show the harness works and where the arms differ, **not** retrieval
quality on real tickets (the report's own caveat).

recall@10 (MRR in brackets). `fused` = dense with the `passage:` prefix plus lexical:

| query | dense `query:` | dense `passage:` | lexical | fused |
|---|---|---|---|---|
| full | 0.820 (0.944) | 0.753 (0.943) | 0.666 (0.759) | 0.789 (0.936) |
| title | 0.673 (0.811) | 0.542 (0.801) | 0.685 (0.720) | 0.627 (0.802) |
| head | 0.699 (0.832) | 0.594 (0.796) | 0.682 (0.735) | 0.665 (0.805) |

`same_serial_relevant_share` = 0.93.

**Correction, 2026-11-11.** The first write-up said plain RRF was below the best single arm in every
mode. That compared `fused` with `dense_query`, which is not one of its inputs (the `fused` row
uses the `passage:` dense arm). Against its own inputs: on `full` it beats both (0.789 vs 0.753 and
0.666); on `title` and `head` it sits between them, below lexical and above dense `passage:`. Whether
fusion beats the best arm with the `query:` dense arm was not run: that is Task 9 and Task 11.

**Readings.**

1. **The ceiling is lifted.** The earlier run (fake writer, hashing embedder) scored about 1.0 on every
   arm because tickets of a recipe shared words literally. With real wording and twins, `full` tops
   out at 0.82 and `title` at 0.69. Precision can fail now.
2. **Fusion's verdict is open** (see the correction): it helps on full tickets over its inputs and
   does not on short queries, and the `query:` fused variant is untested.
3. **The arms are not interchangeable.** Dense gains about 15 points from `title` to `full`; lexical
   is flat at 0.67 to 0.69 whatever the query length, so it is the weakest arm on full tickets and
   the best on a bare title.
4. **Use the `query:` prefix for queries.** It beats `passage:` by 5 to 13 points in every mode
   (amendment 5, Task 12 step A).
5. **`same_serial_relevant_share` is inflated by construction.** With only 3 vehicles, 93% of a
   ticket's relevant neighbours share its serial. It shows the signal exists; it does not size it.
   STATE.md's real figure (over a third of tickets have an earlier same-serial ticket) is the one
   to plan with.
6. **Not answered:** the report is macro only, so twin-pair separation (R001/R009, R002/R010,
   R003/R012, R004/R011) is unmeasured: Task 10 and Task 11.

## Results, 2026-11-11 (same corpus, same index, adds `fused_query` and `--per-group`)

Run on the GPU box from the published snapshot of `1f9824f` (e5 on CPU, same pinned revision, same
`dev3-confusable` fixture, not regenerated). The four variants that existed before reproduce the
2026-11-10 numbers to the last digit, so the two runs are comparable.

recall@10 (MRR in brackets), macro over 12 groups:

| query | dense `query:` | dense `passage:` | lexical | `fused` (passage:) | `fused_query` |
|---|---|---|---|---|---|
| full | **0.820** (0.944) | 0.753 (0.943) | 0.666 (0.759) | 0.789 (0.936) | 0.806 (0.910) |
| title | 0.673 (0.811) | 0.542 (0.801) | 0.685 (0.720) | 0.627 (0.802) | **0.688** (0.782) |
| head | 0.699 (0.832) | 0.594 (0.796) | 0.682 (0.735) | 0.665 (0.805) | **0.736** (0.819) |

Per-group recall@10, full / title / head. Twin pairs are R001/R009, R002/R010, R003/R012,
R004/R011; R001-R003 have 102-103 tickets, every other group 22 (R004: 26).

| group | role | dense `query:` | lexical | `fused_query` |
|---|---|---|---|---|
| R001 | original | 0.94 / 0.75 / 0.77 | 0.98 / 0.94 / 0.97 | 0.96 / 0.86 / 0.84 |
| R009 | twin of R001 | 0.50 / 0.25 / 0.27 | 0.11 / 0.08 / 0.08 | 0.36 / 0.14 / 0.17 |
| R002 | original | 0.94 / 0.82 / 0.82 | 0.93 / 0.85 / 0.84 | 0.96 / 0.86 / 0.90 |
| R010 | twin of R002 | 0.55 / 0.30 / 0.36 | 0.47 / 0.31 / 0.36 | 0.58 / 0.39 / 0.36 |
| R003 | original | 0.97 / 0.86 / 0.97 | 0.13 / 0.03 / 0.05 | 0.98 / 0.93 / 0.96 |
| R012 | twin of R003 | 0.84 / 0.14 / 0.16 | 0.97 / 0.98 / 0.98 | 0.83 / 0.07 / 0.47 |
| R004 | original (small) | 0.60 / 0.39 / 0.54 | 0.45 / 0.42 / 0.45 | 0.60 / 0.44 / 0.59 |
| R011 | twin of R004 | 0.59 / 0.57 / 0.57 | 0.60 / 0.61 / 0.63 | 0.64 / 0.63 / 0.64 |
| R005-R008 | no twin (mean) | 0.98 / 0.99 / 0.98 | 0.84 / 1.00 / 0.96 | 0.95 / 0.98 / 0.98 |

**Answers to the Task 11 table.**

1. **`query:` beats `passage:`** in every mode, by 6.7 / 13.1 / 10.5 points. Task 12 step A applies.
2. **Fusion does not beat its own inputs in every mode.** `fused_query` vs max(`dense_query`,
   `lexical`): full -1.4 points (0.806 vs 0.820), title +0.3 (a tie), head +3.7. Its MRR is below
   dense `query:` in all three modes. By the table's rule Task 12 step B applies (one dense-weighted
   variant, then one more run). `fused_query` beats the old `fused` by 1.7 / 6.1 / 7.1 points, so the
   `query:` arm is the better input for fusion either way.
3. **The twins fail; the other groups do not.** The small side of each pair (R004, R009-R012)
   averages 0.60 / 0.33 / 0.45 under `fused_query` against 0.95 / 0.98 / 0.98 for the four groups
   without a twin, and the best single arm does not close the gap (dense `query:` 0.62 / 0.33 / 0.38).
   The loss is concentrated, not spread evenly, which is the reranker branch of Task 13's rule.
   Task 13 is the operator's decision; this only records what the rule reads.

**Readings.**

1. **The arms fail on different twins, and in opposite directions.** Lexical cannot tell R003 from
   R012 (0.13 vs 0.97) or R009 from R001 (0.11 vs 0.98): the shared wording sends both twins to the
   same side. Dense keeps the large originals (0.94-0.97) and loses the small twins. Fusion inherits
   both: it rescues R012 on head queries (0.47, dense alone 0.16) and drags R009 below dense alone
   (0.36 vs 0.50 on full).
2. **Group size matters in the pairs.** Where an original of about 100 tickets has a twin of 22, the
   twin loses; R004/R011 (26 and 22) are both near 0.6. The report cannot show what fills the top 10,
   so "the large twin crowds it out" is the likely reading, not a measured one.
3. **MRR stays high for twins on full queries** (dense `query:` 0.79-0.97): the first hit is often
   right and the rest of the top 10 is not. That is the shape a reranker over a deeper candidate list
   can fix, if the right tickets are in that list; this run does not measure recall beyond 10.
4. Same caveat as before: invented text, so these numbers locate failure modes, not quality on real
   tickets.
