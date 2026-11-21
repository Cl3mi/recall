# Experiments

Raw results of every measurement that shaped a decision, in date order. Rationale lives in the
ADRs (`docs/adr/`), system shape in `docs/ARCHITECTURE.md`, open work in the plan state files.
Numbers come from tracked docs, `local/artifacts/` or released aggregates only. Real-data entries
stay qualitative, the way `docs/STATE.md` words them: no row values, no exact real-corpus counts.

## How to read an entry

Every entry has six fields:

- **Config:** what was run, with which flags.
- **Foundation:** the system under test: the code commit, the corpus (an ID from the table
  below), the embedder, the index, the labels, the hardware. `unknown` means the source did not
  record it. It does not mean "the same as before".
- **Evidence:** `real` (client data, inside an airlock window) or `synthetic` (stand-in or
  fixture). Under ADR-0005, synthetic retrieval scores show that the code works and where the arms
  differ. They are not evidence of retrieval quality on real tickets.
- **Result:** numbers and observations, as measured.
- **Decision:** what was done because of the result, with its commit or ADR.
- **Valid while:** what must stay unchanged for the result to hold. If any of it has changed,
  re-run before relying on the result.

Entries are append-only. A later run that overturns an earlier one gets its own entry and names
the entry it supersedes. The status index is the only section that is edited in place.

## Foundations referenced by entries

| ID | What it is | Source of truth |
|---|---|---|
| `REAL` | The client's ticket export (38 columns, tens of thousands of tickets, recent years). Only read inside sealed windows; only floored aggregates leave. | ADR-0002, ADR-0024, `docs/export.header.txt` |
| `FIX-R3`, `FIX-R7` | M2 fixture rounds 3 and 7: 1,500 rows each, generated from Window A's `profile.json` by `Qwen2.5-32B-Instruct` (t=0.8). R7 is the acceptance candidate at `local/fixtures/export.csv`. R3 is the only round independent of R7 (0.1% of documents shared). R4–R6 share 71–87% of R7's documents and are not valid comparisons. | `docs/STATE.md` findings 9, 12 |
| `FAKE` | `--fake` stub corpora (templated stub German, about 106 chars per document, seeds 7 and 23). | `docs/STATE.md` |
| `DEV3C` | The `dev3-confusable` stand-in: 12 **invented** recipes (R001–R008, plus near-twins R009–R012 of R001, R002, R003 and R004 that share the component and most of the symptom but have a different cause and fix). 510 tickets on 3 vehicles, written by `Qwen2.5-32B-Instruct-AWQ`, `verify` clean. Built at `eb487f6`. Not regenerated from 2026-11-10 through 2026-11-15. It is **not** derived from the real catalog (Window E released none). | `docs/superpowers/plans/2026-11-05-m3-retrieval-on-dev3-standin.md` |
| `E5` | `intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`, masked-mean pooling, `query:`/`passage:` prefixes. The device (CPU or GPU) does not change the vectors (within 1e-4). | ADR-0009, ADR-0011, ADR-0039 |
| `HASH` | `HashingEmbedder`, a character-trigram stub used before e5 existed. Its cosine distribution is not e5's. | `docs/STATE.md` finding 18 |
| `IDX-M3` | Postgres with pgvector HNSW (problem vector only), `de_tech` German full-text search with a derived compound dictionary, an OR-of-lexemes lexical query, RRF `k=60` in Python, and one cleaning pipeline for index and query. | ADR-0006, 0007, 0008, 0010, 0012, 0013, 0041 |
| `LBL-RECIPE` | Relevance means the same recipe id. Labels are kept in their own table. Metrics are macro-averaged over groups, with recall@k divided by min(k, number of relevant tickets). | ADR-0014, ADR-0020, ADR-0042 |
| `WS` | Workstation: i5-9400F (6 cores), GTX 1660 SUPER. | `docs/STATE.md` |
| `BOX` | Shared HPC box: AMD EPYC 9534 (256 threads), 1 TB RAM, NVIDIA H100 PCIe, driver 550.163.01, CUDA 12.6 wheels. Load from other users varies a lot (load average from about 1 to about 226), so timings depend on contention. | `docs/STATE.md`, ADR-0038 |

## Status index (the only section edited in place)

| # | Date | Topic | Evidence | Still holds? |
|---|---|---|---|---|
| E01 | 2026-08-26 | M2 fixture round 7 fidelity | synthetic vs real profile | yes, while the profile and generator stay the same |
| E02 | 2026-09-07 | Leakage gate baseline percentile (stub) | synthetic | the decision holds; the margins are superseded by E05 |
| E03 | 2026-09-07 | e5 CPU throughput, stub vs real-length text | synthetic | yes (WS) |
| E04 | 2026-09-07 | Box rehearsal and thread scaling | synthetic | the direction holds; figures are from a contended box |
| E05 | 2026-09-08 | Calibration re-measured with e5 | synthetic | yes |
| E06 | 2026-09-11 | GPU vs CPU encode, WS | synthetic | yes |
| E07 | 2026-09-13 | GPU vs CPU encode, BOX H100 | synthetic | yes |
| E08 | 2026-10-13 | Insight report runs 1–2 | real | yes, for this export |
| E09 | 2026-10-15 | Insight run 3, usable share | real | yes; its Baugruppe reading is superseded by E10 |
| E10 | 2026-10-16 | Insight run 4, joint quality cube | real | yes |
| E11 | 2026-11-05 | Window E catalog runs 1–3 | real | yes; no real catalog has been released |
| E12 | 2026-11-10 | M3 retrieval arms on DEV3C | synthetic | yes; the fusion reading was corrected in E13 |
| E13 | 2026-11-11 | M3 per-group and `fused_query` | synthetic | yes |
| E14 | 2026-11-12 | M3 `fused_dense2`, fusion default | synthetic | yes |
| E15 | 2026-11-13 | M4 Phase A, recall at depth | synthetic | yes |
| E16 | 2026-11-15 | M4 Phase C, cross-encoder bake-off | synthetic | yes |

No retrieval number on `REAL` exists yet. M3 Task 8 (Window C, ADR-0021/0044) is the first one.

---

## E01 · 2026-08-26 — M2 fixture generator, round 7 acceptance
Config: `python -m fixtures --profile local/artifacts/profile.json --rows 1500` with the real
writer. This was round 7 of seven generation rounds, after the voice, designation and dedup fixes
(findings 7–9).
Foundation: generator code at `46fcb8c` (finding 9 closed); writer `Qwen2.5-32B-Instruct` t=0.8
on BOX; target = Window A `profile.json` (schema_version 2) of `REAL`. Output: `FIX-R7`.
Evidence: synthetic, compared with real aggregates.
Result: all three cluster bands within ±0.0001 of the real ones; no intended singleton collides;
every intended group clusters; `customData` field shares 26/26; `fehlercode` shape mix 10/10;
fill-by-year 12/12; descriptor quantiles match; `verify` clean; padding 1 of 1,500.
Decision: `FIX-R7` becomes the acceptance candidate, uncommitted until the Window B leakage gate
passes (ADR-0029, ADR-0030).
Valid while: `profile.json` is not regenerated and the generator's prompts and dedup are unchanged.

## E02 · 2026-08-27 → 2026-09-07 — Leakage gate: neighbour baseline percentile (finding 12)
Config: the Window B gate's nearest-neighbour check (cross p99 must not exceed the
synthetic-vs-synthetic baseline) run over `FIX-R7` against itself, then against `FIX-R3` as a
clean comparison.
Foundation: gate code `a78e0f5`…`0f5b937`; embedder `HASH` (no model existed yet); WS.
Evidence: synthetic.
Result: the baseline p99 over the whole fixture is 1.000000. 41 of 1,500 rows (2.7%) have a
neighbour at cosine about 1.0, so the check could never fail. The intended singletons alone give
0.926838. R7 against R3 gives cross_p99 0.898644. Baseline by percentile: p99 1.000 (saturated),
**p95 0.965943**, p90 0.942546, p75 0.852062 (would fail a clean fixture), p50 0.751427 (would
fail).
Decision: `BASELINE_PERCENTILE = 95` (`a7540b7`), with `CROSS_PERCENTILE` kept at 99.
`baseline_saturated` is reported beside the verdict (`0f5b937`).
Valid while: superseded in part by E05. The p95 choice holds under e5, but these margins are stub
numbers. Do not quote them for e5.

## E03 · 2026-09-07 — e5 CPU throughput: rehearsal text vs real-length text
Config: `neighbours._encode`, `batch_size=16`, 512 documents after a 32-document warm-up.
Foundation: `E5` on CPU, code at `830f9b6`/`27e3877`; WS (6 cores).
Evidence: synthetic.
Result: `FAKE` stub (106 chars) 13.51 docs/s; text built to the real token-length mix (~600
chars) 1.21 docs/s, an 11x gap. A window needs about 20,000 encode passes (cross plus
self-baseline), about 4.4 h on WS.
Decision: never budget a window from a rehearsal figure. Run the window on BOX (see E04).
Valid while: document length and encode count are as stated. Changing the batch size or the
model voids it.

## E04 · 2026-09-07 — Overnight Window B rehearsal on BOX, thread scaling (findings 16, 17)
Config: the sealed gate on 1,500+1,500 `FAKE` rows, 32 of 256 threads, then 256-document encode
probes at 8, 32 and 128 threads.
Foundation: image `recall/profiler:pinned` 3.55 GB, CPU-only torch; `E5`; BOX at load
about 194 with 22 users. `manifest.code_commit` and `image_digest` were both `unknown`
(finding 14).
Evidence: synthetic.
Result: gate exit 0 after 173 s, 13 passed and 1 failed (finding 16, shred list). cross_p99
0.989657, baseline_p95 0.99727, not saturated. On stub data that green means little.
Real-length rate: 8 threads 0.77, **32 threads 2.08**, 128 threads 1.10 docs/s (about 6.9 / 2.5 /
4.8 h per window). 32 threads on BOX is only about 1.7x WS.
Decision: thread cap `--threads` default 32 with `OMP`/`MKL` caps; manifest provenance pinned;
shred list completed (`2a4126b`, ADR-0038).
Valid while: single samples on a contended box. The direction (more threads is not faster, the
peak is near 32) is supported. The individual figures are not a calibrated curve.

## E05 · 2026-09-08 — Finding 12's calibration re-measured with e5 (finding 18)
Config: E02's computation repeated with the real embedder. The stub run was repeated first and
reproduced E02 exactly.
Foundation: `E5` (CPU) vs `HASH`; `FIX-R7` against `FIX-R3`; gate at `a7540b7`; WS.
Evidence: synthetic.
Result (HASH → E5): cross_p99 0.898644 → **0.965460**; baseline p95 0.966890 → **0.997127**;
margin at p95 +0.068 → **+0.032**; p75 fails → passes (+0.0049); p50 fails under both; rows
twinned above 0.999: 2.7% → **3.5%** (p95 saturates at 5%). R7 documents: median 166 chars,
against several hundred in `REAL`.
Decision: p95 stands (`7ecdc38`). Nothing changes in the code. The margin is half of what E02
implied, and the reasons given for rejecting p75 were specific to the stub.
Valid while: `E5` stays the gate's embedder and fixtures stay below about 5% twinned rows. A
fixture with more cluster mass trips `baseline_saturated` sooner.

## E06 · 2026-09-11 — GPU vs CPU for the sealed embedder, workstation
Config: the same corpora end to end, 4,500 encode passes including container start, model load,
shingles and the PII sweep.
Foundation: `E5`, CUDA torch 2.14.0 cu126 image (`877fc98`); WS CPU (6 threads) vs GTX 1660
SUPER.
Evidence: synthetic.
Result: CPU 284 s (15.85 encodes/s), GPU **50 s (90.00 encodes/s)**, 5.7x. The image grew from
3.51 GB to 9.32 GB (a `ship` takes about 1 h at 2.5 MB/s).
Decision: run Window B on GPU 0, reversing the 2026-09-07 CPU-only ruling (`877fc98`, ADR-0037).
The device is kept out of the embedder's identity, which E07 justifies.
Valid while: the cu126 wheel line and the driver (at least 525.60.13) hold.

## E07 · 2026-09-13 — GPU run on BOX H100 (10 passed, 0 failed)
Config: the sealed image, `--network=none`, a CDI device pinned by UUID, the same corpora as E04.
Foundation: `E5`; BOX H100 PCIe, driver 550.163.01, CUDA 12.6; box idle (load 0.83).
Evidence: synthetic.
Result: real-length rate: CPU at load about 200: 2.08 docs/s; **CPU idle 4.97**; **H100 idle
96.24 docs/s** (about 3.4 min per window). The fair speedup is **19.4x**; contention alone costs
2.4x. GPU cross_p99 0.989657 and baseline_p95 0.99727 are identical to E04's CPU run to six
decimal places.
Decision: GPU path confirmed (`1e8d858`). The verdict does not depend on the device.
Valid while: same weights and same torch build. Compare timings only at similar box load.

## E08 · 2026-10-12 / 2026-10-13 — Insight report runs 1 and 2 (Window D)
Config: `python -m insight --csv <export> --out report.json`, floor k=50, serial prefixes off, in
the sealed image without GPU. Run 1 = stage 1; run 2 = report v2 (Baugruppe fixed, ten sections).
Foundation: insight v2 code (`2aaa257` era, merged 2026-10-13); `REAL`, full export; BOX.
Evidence: real (floored aggregates, guard `unaccounted: 0`).
Result: run 1 found Baugruppe empty, an extractor bug: the field is a list of id strings. Findings
that stand: about three quarters of tickets are singletons. cat-A is about three quarters of
tickets. cat-B (about a sixth) is only the handover slip. Cleaning destroys every part number.
Real `fehlercode` looks like `DDDD-D(D)`, not the identifier regex, and is filled for under a
fifth of tickets. Model-id fill collapsed in recent years while the serial stays above 90%. Over a
third of tickets have an earlier ticket on the same serial (median gap about 3 months). Solutions
are mostly workflow boilerplate. About 60% have title+description+solution. About half of the
mid-period tickets are title-only.
Decision: strategy order: drop cat-B, strip workflow boilerplate before embedding, derive the
model from serial/vehicle, add a same-serial history step (ADR-0043), keep `fehlercode` as an
exact-match list field, weight the title on description-less tickets.
Valid while: the same export. A new export, a changed category taxonomy or changed cleaning
(ADR-0013) needs a re-run.

## E09 · 2026-10-15 — Insight run 3: usable-share quality score
Config: Window D with `insight/quality.py`. A ticket is usable if it has real problem text and a
solution of at least N words after workflow notes are stripped. Floor 50, full export.
Foundation: commit `d3bdc8a`; `REAL`; BOX.
Evidence: real.
Result: usable about three quarters at ≥3 words, **about 70% at 5**, about half at 12. cat-B
nearly 0% usable, cat-A about 85%, cat-C about three quarters. Without cat-B, about 85% of the
corpus is usable. Delivery date and warranty are handover-slip fields. Status has a single value.
Baugruppe looked like the best quality signal.
Decision: the usable share replaces field fill as the quality score (ADR-0035).
Valid while: the phrase list in `insight/quality.py` is unchanged. The Baugruppe reading is
superseded by E10.

## E10 · 2026-10-16 — Insight run 4: joint quality cube
Config: Window D with `quality.cube` (14 cuts over category, Baugruppe, model and a 3-bit gate
pattern), `--cube-budget 1800`. Took 32 min. The derivability measurement stopped on its budget.
Foundation: cube code `11b4264`…`936b5a3`; `REAL`; BOX.
Evidence: real.
Result: dropping cat-B is the only category-level cut needed (cat-A about 85% usable). The gate
patterns and Baugruppe only looked useful because of the handover slips: inside cat-A, "serial
only" is about 85%, the same as having a description. Error code without a description is the
one weak pattern (about two thirds usable). Requiring Baugruppe costs about two thirds of tickets
for a few points. Models are 70–90% usable after the drop.
Decision: corpus = everything except cat-B, filtered per ticket by the usable grade, not by
metadata proxies (ADR-0034, ADR-0035, `e9c8306`).
Valid while: the same export and the same usable rule.

## E11 · 2026-10-28 → 2026-11-05 — Window E problem catalog, runs 1–3
Config: clustering of eligible `REAL` tickets, floors k=50 / 5 vehicles / 5 dealers (cluster cap
`eligible // k`), an LLM drafter with majority rule and up to 3 repair rounds, four checks plus a
leak check bound to the draft's SHA-256.
Foundation: run 1 `9f94f43`, run 2 `c658bcf`, run 3 `f656ace`; drafter `Qwen2.5-32B` on BOX
H100; `REAL`.
Evidence: real.
Result: run 1 aborted (a `None` serial or dealer id). Run 2 drafted 0 recipes. Run 3 drafted **3
recipes**; most candidates were refused as `gemischt` (mixed clusters). Sampling from the cluster
centre barely moved it, so the clusters themselves are mixed. `dev3` needs at least 4 recipes
(`MIN_RECIPES`). The 3-recipe draft is unread and unreleased. The k=50 floor keeps the long tail
of rare problems out of any catalog by design.
Decision: build M3 on an invented stand-in meanwhile (`DEV3C`, ADR-0042). Image `12a27dc` is
built and has not been run.
Valid while: no real catalog is released. **Every retrieval result below (E12–E16) uses invented
recipes, not real problem clusters, and will overstate real recall** (no long tail).

## E12 · 2026-11-10 — M3 retrieval arms on the confusable stand-in
Config: synthetic eval, k=10, variants dense `query:`, dense `passage:`, lexical, `fused` (RRF of
dense `passage:` and lexical), under full, title and head queries.
Foundation: code at or before `67c6d9e` (the exact snapshot was not recorded); `DEV3C`; `E5` on
CPU; `IDX-M3`; `LBL-RECIPE`; BOX.
Evidence: synthetic.
Result: recall@10 (MRR):

| query | dense `query:` | dense `passage:` | lexical | fused |
|---|---|---|---|---|
| full | 0.820 (0.944) | 0.753 (0.943) | 0.666 (0.759) | 0.789 (0.936) |
| title | 0.673 (0.811) | 0.542 (0.801) | 0.685 (0.720) | 0.627 (0.802) |
| head | 0.699 (0.832) | 0.594 (0.796) | 0.682 (0.735) | 0.665 (0.805) |

`same_serial_relevant_share` 0.93, inflated because the stand-in has only 3 vehicles. The
earlier fake-writer and hashing-embedder run scored about 1.0 on every arm, so it was not a test.
Decision: use the `query:` prefix for queries (ADR-0011). Twin separation is unmeasured; Tasks
10–11 follow.
Valid while: `DEV3C`, `E5`, `IDX-M3`. The first write-up's "fusion below the best arm" compared
the wrong arms and is corrected in E13.

## E13 · 2026-11-11 — M3 per-group metrics and `fused_query`
Config: E12 plus `fused_query` (RRF over dense `query:` and lexical) and `--per-group`.
Foundation: published snapshot of `1f9824f`; `DEV3C` (not regenerated); same index; `E5` on CPU;
BOX. The E12 variants reproduce to the last digit.
Evidence: synthetic.
Result: `fused_query` recall@10 full / title / head = 0.806 / 0.688 / 0.736 (MRR 0.910 / 0.782 /
0.819). Small twins (R004, R009–R012) average 0.60 / 0.33 / 0.45, against 0.95 / 0.98 / 0.98 for
the groups without a twin. Lexical cannot separate R003 from R012 (0.13 vs 0.97) or R009 from
R001 (0.11 vs 0.98). Dense keeps the large originals and loses the small twins. MRR stays high
for twins: the first hit is right, the rest of the top 10 is not.
Decision: `query:` is the better fusion input (+1.7 / +6.1 / +7.1 over `fused`). The loss is
concentrated in the twins, which points to a reranker (Task 13 rule).
Valid while: `DEV3C`'s group sizes (twins of about 22 next to originals of about 100) and
`LBL-RECIPE`.

## E14 · 2026-11-12 — M3 `fused_dense2` and the fusion default
Config: one dense-weighted RRF variant (dense ×2) added to E13's set.
Foundation: published snapshot of `f0a5934` (`query:` is the search default, `0f901bc`; weighted
RRF `38d0403`); `DEV3C`; same index; BOX. The earlier variants reproduce exactly.
Evidence: synthetic.
Result: `fused_dense2` recall@10 0.813 / 0.679 / 0.720 (MRR full 0.938). No fused variant beats
its best input in every mode (−0.7 / −0.6 / +2.1 points). The fused variants differ by 1–2 points;
the small twins trail the rest by 35–66 points.
Decision: `search` defaults to `query:` plus plain RRF (`weights=None`). `fused_dense2` stays as a
comparison. Fusion weights are not tuned on invented text (`0fd48f4`, ADR-0006). The operator
chose a reranker for M4 (`eacfc31`).
Valid while: `DEV3C`. Whether lexical earns its place is for real data (Task 8) to decide.

## E15 · 2026-11-13 — M4 Phase A: candidate recall at depth (rerank gate)
Config: E14's eval with `--per-group --depths 10,50,100,all` (`all` = depth 200, the union of
both pools). Recall at depth d divides by min(d, number of relevant tickets).
Foundation: published snapshot of `9d7a489` (depths `96304af`); `DEV3C`; `E5` on CPU; same index;
BOX. All 18 M3 cells reproduce to the last digit. Artifact `local/artifacts/m4-phase-a.json`.
Evidence: synthetic.
Result: `fused_query` small twins at @10 / @50 / @100 / @all: full 0.599 / 0.700 / 0.890 / 0.938;
title 0.334 / 0.634 / 0.882 / 0.939; head 0.446 / 0.684 / 0.885 / 0.965. No-twin groups are at
0.95 or above at every depth. R010 and R012 have ceilings below 0.9 even over the union. For
R001–R003, the drop at depth comes from the metric's denominator, not from retrieval.
Decision: gate is **go, N = 100** (@100 is at least 0.80 in every mode; @100 − @50 = 0.19 / 0.25 /
0.20) (`9557885`).
Valid while: `DEV3C` and fused retrieval unchanged. Any change to the corpus or fusion moves the
pool.

## E16 · 2026-11-15 — M4 Phase C: cross-encoder bake-off over the fused top 100
Config: cells `rr_<model>_<text>`, with model bge or qwen3_4b and document text `problem` or
`problem_solution`, `--depth 100`, 510 queries per mode. **Baseline `fused_query`.** Rules fixed
before the run: (1) small-twin lift of at least +0.15 in every mode; (2) no-twin change of at
least −0.02; (3) macro recall@10 change of at least 0; (4) macro MRR change on full queries of at
least −0.02.
Foundation: CUDA eval image `infra/eval/Dockerfile` (`6617267`) with
`TORCH_DISABLE_NATIVE_JIT=1` (`264075b`), weights mounted read-only (revisions in the M4 state
file); eval code `9ceeea2` + `b995cfd`; `DEV3C`; `E5`; same index; BOX H100. All 6 M3 cells × 3
modes equal E15 (270 numbers, largest difference 0). Artifact `local/artifacts/m4-phase-c.json`.
Evidence: synthetic.
Result: small-twin mean recall@10 (full / title / head, average lift):

| cell | full | title | head | avg lift |
|---|---|---|---|---|
| `fused_query` (base) | 0.599 | 0.334 | 0.446 | |
| `rr_bge_problem` | 0.574 | 0.338 | 0.421 | −0.015 |
| `rr_bge_problem_solution` | 0.637 | 0.323 | 0.482 | +0.021 |
| `rr_qwen3_4b_problem` | 0.567 | 0.239 | 0.325 | −0.083 |
| `rr_qwen3_4b_problem_solution` | 0.689 | 0.267 | 0.324 | −0.033 |

Macro on full queries, recall@10 / MRR / nDCG@10: base 0.806 / 0.910 / 0.826; bge problem 0.809
/ 0.933 / 0.828; bge problem+solution 0.828 / 0.892 / 0.834; qwen problem 0.815 / 0.901 / 0.832;
qwen problem+solution 0.861 / 0.911 / 0.866. Rule 1 and rule 3 fail in every cell; rules 2 and 4
pass in every cell. R008 rises from 0.80 to 1.00 in every cell. The solution text helps R004
(0.60 → 0.72) and costs R003 under bge (0.98 → 0.80). Short queries gain almost nothing. Rerank
p50 / p95 seconds per query: bge 0.10 / 0.16 and 0.13 / 0.21; qwen 1.51 / 2.28 and 2.13 / 2.90.
Decision: no cell passes. `rr_bge_problem_solution` (largest average lift) stays **opt-in**:
`Settings.rerank_*` default to `None`. The Qwen adapter and the `problem` text are removed
(`23011a1`, ADR-0019).
Valid while: `DEV3C`'s invented twins. A null result here does not show that a reranker cannot
help on real tickets, and a lift here would not show that it can. Re-judge in Window C (M3 Task
8).
