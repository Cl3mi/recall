# Architecture decision records

One decision per file, `NNNN-short-title.md`: Status, Date (when the decision was taken),
Context, Decision, Consequences, References. See [0001](0001-record-architecture-decisions.md)
for the process. Records 0002 onward were written retroactively from the specs, plans,
`docs/STATE.md` findings and commit history; where the sources record a choice but not the
comparison behind it, the record says so. System overview: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

## Constraints and principles

| ADR | Decision |
|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions as ADRs |
| [0002](0002-real-data-only-in-airlock-windows.md) | Real data only in manual, AI-free airlock windows on the box |
| [0003](0003-retain-nothing-derived-from-real-data-between-windows.md) | Nothing derived from real data is retained between windows |
| [0004](0004-local-inference-and-german-only-corpus.md) | Local inference, German end to end |
| [0005](0005-synthetic-metrics-prove-code-not-quality.md) | Synthetic metrics prove the code, not retrieval quality |
| [0018](0018-near-duplicate-variants-are-never-collapsed.md) | Variants of a problem are never collapsed to one answer |

## Retrieval and data model

| ADR | Decision |
|---|---|
| [0006](0006-postgres-native-hybrid-retrieval-with-rrf-in-python.md) | Postgres-native hybrid retrieval, RRF in Python |
| [0007](0007-native-fts-no-bm25-extension-identifier-arm-deferred.md) | Native full text, no BM25 extension, identifier arm deferred |
| [0008](0008-german-fts-with-derived-compound-dictionary.md) | `de_tech` with a derived compound dictionary |
| [0009](0009-e5-large-pinned-offline-embedder.md) | e5-large, pinned, offline, shared by gate and index |
| [0010](0010-problem-vector-only-solution-text-stored-separately.md) | Problem-only searchable vector; solution stored separately |
| [0011](0011-query-prefix-on-query-side-passage-prefix-stored.md) | `query:` on queries, `passage:` stored |
| [0012](0012-or-of-lexemes-lexical-query.md) | OR-of-lexemes lexical query |
| [0013](0013-one-cleaning-pipeline-for-index-query-and-profiler.md) | One cleaning pipeline for index, query and profiler |
| [0014](0014-relevance-labels-in-a-separate-table.md) | Relevance labels in a separate table |
| [0015](0015-database-holds-a-projection-not-the-raw-rows.md) | Database holds a projection, not raw rows |
| [0016](0016-index-the-whole-corpus-and-drop-no-rows.md) | Index the whole corpus, drop no rows |
| [0017](0017-contact-pii-fields-are-never-read.md) | Contact PII fields are never read |
| [0019](0019-reranker-in-process-and-opt-in.md) | Reranker in-process, GPU only, opt-in after M4 |
| [0041](0041-checksum-guarded-sql-migrations-and-late-hnsw-build.md) | Checksummed SQL migrations; HNSW built by the loader |

## Evaluation

| ADR | Decision |
|---|---|
| [0020](0020-group-macro-metrics-and-recall-denominator.md) | Group-macro metrics, recall over min(k, relevant) |
| [0021](0021-real-eval-temporal-holdout-with-fehlercode-proxy.md) | Temporal holdout with `fehlercode` as the proxy label (Proposed) |
| [0022](0022-window-c-tmpfs-postgres-in-an-isolated-pod.md) | Window C: tmpfs Postgres in a network-less pod (Proposed) |
| [0042](0042-m3-is-built-and-scored-on-the-dev3-stand-in-with-recipe-labels.md) | M3 built and scored on the dev3 stand-in, recipe id as truth |
| [0043](0043-same-serial-history-is-reported-in-m3-and-used-only-after-real-data.md) | Same-serial history reported, not used, until real data |
| [0044](0044-window-c-is-a-narrow-no-llm-baseline-with-its-own-entry-point-and-image.md) | Window C: narrow no-LLM baseline, own entry point and image (Proposed) |

## Data protection and release controls

| ADR | Decision |
|---|---|
| [0023](0023-structurally-safe-artifacts-closed-allowlists-and-floors.md) | Closed allowlists, floors, ledgers |
| [0024](0024-numbers-only-release-gate-for-aggregates.md) | Numbers-only release gate |
| [0025](0025-client-data-guard-hook-and-sealed-root.md) | Guard hook and sealed output root |
| [0026](0026-publish-by-allowlisted-snapshot-never-git-push.md) | Publish by allowlisted snapshot |
| [0027](0027-window-driver-enforces-a-per-window-contract.md) | Window driver enforces a per-window contract |
| [0028](0028-rehearse-the-real-window-command-on-synthetic-data.md) | Rehearse the real window command |

## Synthetic data, catalog and insight

| ADR | Decision |
|---|---|
| [0029](0029-synthetic-fixture-generated-from-a-profile-not-from-rows.md) | Fixture generated from a profile, not rows |
| [0030](0030-leakage-gate-zero-tolerance-and-hash-manifest.md) | Leakage gate: zero tolerance, hash manifest |
| [0031](0031-problem-catalog-is-the-only-real-derived-release-and-feeds-dev3.md) | Problem catalog as the only real-derived release; dev3 |
| [0032](0032-window-e-two-sealed-containers-on-an-internal-network.md) | Window E: two containers on an internal network |
| [0033](0033-catalog-release-requires-a-leak-report-for-the-exact-draft.md) | Catalog release needs a leak report for the exact draft |
| [0034](0034-insight-report-floors-ledger-and-measured-subtraction.md) | Insight floors, ledger, measured subtraction |
| [0035](0035-usable-share-quality-score-replaces-field-fill.md) | Usable-share quality score |
| [0036](0036-insight-view-is-a-local-offline-file.md) | Insight view is a local offline file |

## Compute and infrastructure

| ADR | Decision |
|---|---|
| [0037](0037-cuda-torch-in-the-sealed-image.md) | CUDA torch in the sealed image |
| [0038](0038-shared-gpu-fair-use-claim-and-thread-cap.md) | Shared GPU fair-use claim and thread cap |
| [0039](0039-model-weights-are-baked-or-mounted-never-fetched-at-run-time.md) | Weights baked or mounted, never fetched |
| [0040](0040-generator-models-qwen-sized-to-the-fair-use-cap.md) | Qwen 32B generators sized to the cap |

## Not yet decided (candidates)

Final PII treatment (0017 is interim); a `fehlercode` or identifier retrieval arm (0007, 0014);
synonym mining into `de_synonyms` (0008); stripping solution boilerplate before embedding (0013);
dropping the handover category from the index (0016); a serving layer and its API; the generator's
model family (0040); whether to keep `solution_vec` (0010); the sandbox setting in
`.claude/settings.json`, which the guard spec calls the second layer but which is disabled (0025);
the unrecorded real-data work of the insight plan (a two-tier release with human-reviewed LLM
labels, planned and never built).

## Decisions found in the sources with no ADR yet

These were identified while verifying the records against the plans and are only thinly sourced
here, so they are listed rather than written up: the workstation preflight and `--syntax` probe
(runbook); sealed-run hygiene (frozen dependency install, code baked in with no `/work` mount,
detail log kept on the box); the M3 tuning policy (dev/test split, staged tuning, bootstrap
intervals, config matrix) and the dropped model-family boost and chunking in the August design; the
Window A closed shape alphabet and "no `customData` tokens until a v3 decision"; the insight view's
exact/bounded/estimated certainty grades; the joint null-mask handover block and band arithmetic
in the fixture generator; the principle that a cache or report must carry the identity of what
produced it (finding 1); and the catalog drafting policy (majority rule, repair rounds, hash-ordered
samples capped per dealer).

## Verification status

The records were checked in November 2026 by reading every plan and spec end to end plus
`docs/STATE.md`, the runbook and the handoffs, and by checking code and commit hashes. Two records
(0021, 0022) and 0044 are Proposed because the Window C plan itself marks their details as pending
operator review.
