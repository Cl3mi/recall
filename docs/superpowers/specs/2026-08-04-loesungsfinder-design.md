# Lösungsfinder — decisions closed in the 2026-08-04 planning session

This is a **delta on `PROJECT_BRIEF.md`**, not a replacement. The brief remains the
spec for problem, scope, invariants and requirements. This document records only
what the planning session decided, corrected, or discovered — and is the
authority where it contradicts the brief.

---

## 1. Machine topology and data residency

The brief's §3 assumed one "client machine" with a dedicated 80 GB GPU. Reality:

| Machine | Role | Real ticket data? |
|---|---|---|
| Workstation (`<repo-root>`) | development; Postgres for dev/test | **never** |
| Shared HPC box (ssh `hpc`) | inference, indexing, sealed data runs | only inside an airlock window |
| Client's own systems | out of scope — this is a prototype engagement | n/a |

**GPUs:** 2 × NVIDIA H100 **PCIe**, 81,559 MiB each, MIG disabled. Shared with
other users; fair use enforced via `~/crux/gpu-fairuse.sh` (cap 60 GB/GPU).
PCIe means no meaningful NVLink → **one model per card, never tensor-parallel
across the pair.**

### The airlock protocol (supersedes the brief's residency assumptions)

Real data may reside on the HPC box only inside a sealed window:

1. `scp` the real CSV into a container on the box.
2. Run the prepared script **manually — no AI assistance during the window.**
3. The script writes its artifact on the box.
4. Delete the container and the real CSV.
5. Only then may an AI touch that filesystem again.

Anything an AI later reads must be interpretable **without** the underlying rows.
Three windows are required:

| Window | Needs real CSV | Produces | Cost |
|---|---|---|---|
| **A** — profiling | yes | `profile.json` + `profile_report.md`, AI-readable | full cycle |
| **B** — leakage gate | **yes** | signed gate report: counts, thresholds, verdicts | full cycle |
| **C** — real eval | yes | `eval_real.json`, aggregate metrics keyed by opaque ids | overnight, run ≥2× |

**Reversed decision — nothing derived from the real corpus is retained between
windows.** An earlier draft kept real-corpus embeddings and 8-token shingle hashes
on the box so the gate could skip a cycle. That was wrong. Inversion attacks
reconstruct substantial portions of short texts from embeddings, and they work
*better* when the embedding model is public — ours is — so retained vectors are the
text in a thin disguise. A shingle-hash set is separately a membership oracle.
Window B therefore re-imports the real CSV, computes the intersection and the
nearest-neighbour check **on the box**, and emits only counts and verdicts. One
extra manual cycle is much the cheaper trade.

Real-data-derived eval queries the user hand-writes are themselves real data:
they live and die inside Window C; only metrics cross out, keyed by opaque ids.

**Everything an AI may read must be structurally incapable of carrying a corpus
value** — a type constraint in `profiler/safety.py`, not a discipline rule. The
plan's "Data handling rules" section is binding and supersedes §8's fixture table:
git holds **no data of any kind**, not even synthetic fixtures (regenerated from a
committed seed instead), there is **no git remote**, and data moves between the
workstation and the HPC box by `scp` only. Permission deny rules and the sandbox
read-deny stop accidents; they are not the boundary. The boundaries are the
AI-free window and an empty `local/quarantine/` on the workstation.

---

## 2. Closed decisions from §12

### §12.6 Generator — **Qwen3-32B, FP8, one card**

Under the 60 GB fair-use cap: ~33 GB FP8 weights + ~3 GB activations/graphs
leaves ~24 GB KV. Qwen3-32B is 64 layers × 8 KV heads × 128 → ~256 KiB/token →
~94k tokens KV at fp16, ~190k with `--kv-cache-dtype fp8` (native on Hopper,
negligible quality cost on grounded summarisation).

**The 70B path is rejected.** At INT4 it is ~38 GB of weights against a 60 GB cap,
leaving <60k tokens of KV for a model needing ~320 KiB/token — 4–5 concurrent
synthesis requests and shallow enrichment batches where 4-bit kernels are worst.

**The brief's reasoning is corrected on one point:** the binding constraint is not
synthesis quality but **enrichment iteration speed**. A planned corpus of several tens of thousands of rows × ~1.5k in / ~400
out ≈ 98M prefill + 26M decode tokens ≈ 4–7 h at 32B/FP8 (overnight) vs 15–20 h
at 70B/INT4 (a workweek across the 3–5 prompt revisions you will actually need).
(Row count here is the brief's planned corpus size, several tens of thousands; the
real export is smaller, see below.)
Enrichment is also the *harder* job — extraction plus judgment on messy German —
whereas synthesis is grounded summarisation where retrieval dominates.

### §12.7 BM25 — **native Postgres FTS + a dedicated identifier arm**

Native `de_tech` FTS, plus a third retrieval arm doing **exact identifier
matching** (normalised identifier table, btree/GIN + `pg_trgm` for near misses).
No BM25 extension in v1.

Rationale: the §7 German dictionary work is the highest-value lexical lever and
is shaped like a Postgres `text search configuration`. VectorChord-bm25 and
ParadeDB `pg_search` bring their own analyzer chains; proper BM25 *without*
compound splitting is a worse trade than `ts_rank_cd` *with* it. RRF fuses on
rank, not score, which further narrows the gap. And `pg_search`'s licence needs
checking before it is even shortlisted.

`ts_rank_cd` has no IDF, so `F1247` would not outweigh `defekt` — fixed directly
by the identifier arm rather than by a better scorer.

**Deferred upgrade, no extension needed:** generate candidates from the GIN-indexed
`de_tech` tsvector, then compute true BM25 in SQL over the top ~200 using a
materialised IDF/doc-length table. **Trigger:** lexical recall@50 trailing dense
badly *after* the identifier arm exists.

### §12.5 Embedding stack — **quality-first, split across the two cards**

| Component | Choice | Licence | Why |
|---|---|---|---|
| Embedder | **Qwen3-Embedding-8B** | Apache-2.0 | online cost is one short forward pass; offline cost is one-time (~32M tokens, <1 h). Size is nearly free → take the quality. |
| Reranker | **Qwen3-Reranker-4B** (8B = measured upgrade) | Apache-2.0 | the only per-query cost: 50 pairs × ~1k tok ≈ 50k tok prefill. 4B keeps it in the few-hundred-ms range. |
| Gate detector + baseline | **BGE-M3** | MIT | deliberately *not* the model under test; also the control the Qwen3 pair must beat. |
| Challenger to check | Llama-Embed-Nemotron-8B | verify NVIDIA terms | claims top multilingual MTEB. |
| **Excluded** | jina-embeddings-v3, jina-reranker-v2 | CC-BY-NC | non-commercial — disqualifying. |

**GPU 0** = generator. **GPU 1** = embedder + reranker (~24 GB fp16 together),
leaving room to hold a challenger resident during bake-offs.

**Forced by pgvector, not preference:** pgvector indexes `vector` only up to 2000
dims and `halfvec` up to 4000. Qwen3-Embedding-8B's native 4096 dims **cannot be
HNSW-indexed**. Use Matryoshka truncation to **`halfvec(1024)`** as the default,
with 2048 as the alternative to measure in Window C.

Learned-sparse vectors: **store them, keep them out of v1's critical path.** The
forward pass produces them free; wiring a fourth scoring arm is unmeasured
complexity. Promote later if the harness asks.

### §12.4 Chunking — **none; enrichment-driven semantic decomposition instead**

§6.1 already made chunking moot: the primary vector is built from the *enriched
projection* (canonical problem, symptoms, components), so **enrichment is the
length normaliser** — a 4,000-token email collapses to a ~200-token canonical
problem. With a 32k-context embedder there is no chunk size to tune.

The real failure mode is not long documents but **multi-fault tickets collapsing
into one averaged vector**. Fix: a `ticket_problem` child table, one row per
distinct problem the enricher identifies (usually exactly one), each with its own
vector, all FK'd to the parent, deduplicated by parent at retrieval. That *is*
parent-document retrieval, with semantically meaningful children instead of
arbitrary slices. The table exists from day one even while v1 writes one row per
ticket, so real decomposition is a data migration rather than a rewrite.

Length still matters in three narrower places: `setweight` tiers on the lexical
side (title A, canonical problem + symptoms B, cleaned description C, solutions
D); **head-plus-tail** truncation when feeding the enricher pathological rows,
with a visible `truncated` flag; and sentence-level evidence spans computed
on demand for the ~10 displayed cards, never as a corpus-wide sentence index.

**Residual risk:** if the enricher misses a secondary fault it is invisible to the
dense arm. Mitigated because the lexical arm indexes full cleaned text regardless
— the two arms fail differently, which is the point of hybrid. The hand-graded
enrichment set must deliberately include multi-fault cases.

### §12.8 RRF and cutoffs — **defaults now, policy binding, tuning from the harness**

Defaults: dense top-100, FTS top-100, identifier top-50 → RRF k=60, weights
1.0 / 1.0 / **1.5** (identifier is precision-heavy and sparse) → top-50 into
Qwen3-Reranker-4B → top-10 to synthesis.

**Division of labour: RRF is for recall, rerank features are for precision.** The
identifier arm belongs in fusion so an exact error-code hit enters the candidate
set even when dense and lexical both miss it. Exact model match, family match,
adjacent year, similar hours, resolution-confirmed, completeness and recency
decay apply as *rerank-time features*, not fusion weights.

Policy (binding, because 7+ knobs over a few hundred queries overfits by default):

1. **Split the real query set** into dev (tune) and test (reported once). Never
   tune on test.
2. **Tune in stages:** fusion recall@50 with the reranker off first — it is the
   hard ceiling on everything downstream — then the rerank cutoff against
   nDCG@10, then the boosts. Never jointly.
3. **Coarse grids only:** k ∈ {20, 60, 100}, weights on a simplex in 0.25 steps.
   No Bayesian optimisation over 300 queries.
4. **Bootstrap confidence intervals, and a change must clear its CI to be
   adopted.** At 300 queries a 2-point recall difference is noise.

Set the rerank cutoff from *measured* fusion recall@50, not latency intuition: if
fusion recall@50 is 70%, the reranker's ceiling is 70% and widening to top-100
beats any reranker tuning.

**Operational constraint this creates:** each real eval is an overnight sealed
window with no AI available mid-run, so no tune-observe-retune loop is possible.
**The harness must accept a config matrix and emit metrics for every cell in one
pass.** Widen grids and accept wasted cells; compute is free, manual attention is
not.

§10's triage thresholds are *not* derivable from the automated harness — "is this
suggestion correct" ≠ "is this ticket in the same cluster". Green-lane calibration
at ~90% precision needs the 50–100 hand-graded queries.

### §12.3 Leakage-gate sign-off — **the user signs, backed by the automated report**

A client DPO review becomes a post-vacation agenda item, not a critical-path
blocker. The airlock is the control.

### §12.9 sync, §12.10 automation liability — **out of scope**

No incremental sync, no periodic re-import or re-indexing in the prototype.
§12.10 stays on the client list as a phase-2 precondition; it does not arise while
§13 excludes automatic ingestion.

### §12.1 / §12.2 `solutions` — **answered by Window A, as decision rules**

Cannot be answered before profiling. The profiler must report cardinality
(single field vs multi-entry, detected separator, entries-per-ticket quantiles),
fill rate, post-clean non-empty rate, junk taxonomy, and a usable-rate estimate.
Decision rules:

- **Multi-entry detected** → model attempts separately; distinguish "what was
  tried" from "what worked". Schema change, richer system.
- **Usable rate very low** → the honest answer to the client is that the fix is
  process (require a resolution on close), not code — stated *before* it becomes
  someone's fault.

---

## 3. Corrections to the brief worth flagging

**§7's SQL snippet is probably wrong.** It orders the dictionary chain
`unaccent, german_hunspell, german_stem`. `unaccent` converts ö→o, ü→u, ä→a
*before* dictionary lookup, so `Ölfilter` becomes `Olfilter`, which the German
hunspell dictionary does not contain — silently disabling both compound splitting
and stemming for every umlauted word, which in this corpus is a lot of them.

Resolution: build **two** configurations at M0 and let a test decide, since this
needs no real data — `de_tech` (`de_synonyms, german_hunspell, german_stem`) and
`de_tech_ua` (with `unaccent` first). Umlaut-insensitivity, if wanted, belongs in
the synonym dictionary, not in a filtering dict ahead of the analyzer.

Also note Postgres dictionary chains **stop at the first dictionary that
recognises a token**. A compound that hunspell splits never reaches
`german_stem`, so expected lexemes are the decomposition, not stems. Test
*behaviour* (`to_tsvector(...) @@ to_tsquery('Pumpe & defekt')`) rather than
lexeme spelling.

### §7 ordering, settled empirically at M0

Both configurations were built (`0002_german_config.sql`) and measured
(`tests/integration/test_german_fts.py`). Results below.

**Finding 1 — the prediction holds, and the damage is narrower than expected.**
`de_tech_ua` fails **exactly 2 of the 7 gate cases**, both umlaut *compounds*:
`Ölfilterwechsel ~ Ölfilter` and `Kühlwasserverlust ~ Kühlwasser`. Under
`de_tech` these split (`{öl, filter, wechsel}`, `{kühl, wasser, verlust}`); under
`de_tech_ua` the document unaccents to `Olfilterwechsel` before lookup, which
igerman98 does not contain, so nothing splits and the whole word stems to
`olfilterwechsel`. The *simple* umlaut cases (`Ölfilter ~ Ölfilter`,
`Kühler ~ Kühler`) still match under `de_tech_ua` because query and document
undergo the same folding — which is why the count is 2 and not 4. **`de_tech` is
the production configuration.**

**Finding 2 — a correction to this document's own premise.** Calling `de_tech`
"the one where dictionaries see real umlauts" is true but incomplete:
**`german_stem` folds umlauts by itself** (Snowball German transliterates
ä/ö/ü → a/o/u). So in `de_tech`, a token hunspell does *not* resolve still loses
its umlauts — `Kühlxyz` → `kuhlxyz`, resolved by `german_stem`, with no
`unaccent` anywhere in the chain. Before the compound fix below, `Ölfilter`
lexized to `olfilt` in `de_tech` for the same reason. **The `de_tech` vs
`de_tech_ua` distinction therefore only bites for tokens hunspell actually
resolves** — it is a gate on compound splitting, not umlaut preservation as such.

**Compound splitting needed a derived dictionary; stock `de_de` cannot do it.**
igerman98 declares `COMPOUNDBEGIN`/`MIDDLE`/`END` in its affix file but grants
those flags to words through hunspell **affix flag continuation** (`SFX j 0 0/xoc .`
gives class `j` the flags `x`, `o`, `c`). PostgreSQL's `spell.c` does not
implement flag continuation, so it sees **zero** `COMPOUNDBEGIN` entries out of
21,214 compound-capable ones: no compound is ever legal, every compound lexizes
to `NULL`, falls through to `german_stem` and is stemmed whole. With `de_de` the
gate fails 4 of 7. `infra/postgres/derive-compound-dict.pl` resolves the
continuation classes at image-build time into `de_compound.dict`/`.affix`,
marking capitalised entries (German nouns) `x`/`y`/`z`; with it, all 7 cases pass
and `ts_debug('de_tech','Hydraulikpumpe')` reports `german_hunspell`, not
`german_stem`. This replaced the planned fallback of dropping compound splitting,
which would have meant a materially weaker lexical arm. Honest trade-offs: the
derivation is **deliberately permissive** — any noun may begin, sit inside or end
a compound, favouring retrieval recall over linguistic precision — and some
parses emit duplicate lexemes (`Ölfilter` → `{öl, filter, öl, filtern, öl,
filter}`), which `to_tsvector` dedupes. `Motor`, `Werkstatt` and `Anmeldung` are
not over-split.

**Why permissive marking does not over-split — and what does NOT protect it.**
The script also sets `COMPOUNDMIN 4`, but **PostgreSQL parses that directive and
does not enforce it**: a synthetic dictionary splits a 6-character word into
3-character parts even at `COMPOUNDMIN 20`, and on the real corpus `Ölfilter`
emits the 2-character part `öl`. The setting is retained because it is correct by
hunspell semantics, but it is inert here and must not be cited as a safeguard.
The actual protection is that **PostgreSQL prefers a whole-word dictionary hit**
over a decomposition, which is why `Motor` and `Werkstatt` survive intact.

**Residual gap — Fugen-s modifiers, measured not assumed.** German linking-form
compounds split to the *surface* form, which does not unify with the base lemma:
`Wartung` → `{warten}` but `Wartungsintervall` → `{wartungs, intervall}`. So a
query for `Wartung` **misses** a document containing only `Wartungsintervall`,
while `Intervall` matches it. Same for `Störung`/`Störungsmeldung`,
`Rechnung`/`Rechnungsnummer`. This is an *incomplete* fix, not a regression —
before the derived dictionary these lexized to `NULL` and missed as well, and the
head now matches where nothing did. It matters because **none of the 7 gate cases
is `-s`-linked**, so the class would otherwise pass unmeasured while
under-performing, and `Wartungsintervall`/`Störungsmeldung`/`Rechnungsnummer` is
exactly this corpus's vocabulary. `tests/integration/test_german_fts.py` pins it
with `xfail(strict=True)` — modifier cases expected to fail, head cases expected
to pass — so it fails loudly if ever fixed. **The M4 mined synonym dictionary is
the intended lever** (`wartungs → wartung`), which is a second reason the §7
synonym work is worth its afternoon.

### The workstation sandbox is off, deliberately — measured at M0

The plan specified `sandbox.enabled: true` so `filesystem.denyRead` on
`local/quarantine/` would be kernel-enforced rather than a string match. Measured,
that setting **breaks the dev loop outright** rather than merely adding friction:

- **Postgres is unreachable.** The sandbox proxies HTTP; a raw TCP connection to
  `localhost:5433` has no allow-setting. `make test` and `make migrate` both fail,
  so Milestone 0's own acceptance criterion (`make db-up migrate test lint`) cannot
  pass.
- **`ssh` to the HPC box fails** ("Network is unreachable"), which `gpu-fairuse2.sh`
  and every airlock window depend on.
- **`make check-clean` reports a false `clean`.** It uses `find` over the denied
  directory, so it cannot distinguish "empty" from "cannot look" — enabling the
  sandbox actively *weakened* the one guarantee the plan calls assertable.

Two problems were fixable and the fixes are kept: `allowAllUnixSockets` for the
Docker socket, and `allowWrite: ["~/.cache/uv"]` because a sandboxed `uv` cannot
write its own cache. Ruff also needed `.claude` excluded — several entries there
are character devices it cannot read at all.

**Resolution: `sandbox.enabled: false`.** The `permissions.deny` rules are retained
and work regardless, being tool-level. The `sandbox` block is retained, configured
and inert, so it can be switched on for an AI-only session that touches no
database. This follows the plan's own reasoning — it predicted the friction "would
get the sandbox switched off entirely, which is worse" — and its own statement that
the real guarantees are structural: real data exists only on the HPC box inside
AI-free windows, `local/quarantine/` on the workstation stays empty, and
`make check-clean` proves it. **That proof is only valid unsandboxed**, which is how
an operator runs it.

### The export is several times smaller than planned — measured 2026-08-06

The structural preflight (`profiler/preflight.py`, shape only, no field values) on the
real export reports **tens of thousands of data rows at under 2 kB per ticket**. The
brief's §2 and §4 assume several times more. That is **roughly 4× fewer than planned**, and
it moves several things:

- **Retrieval quality is the real casualty, and it is a client conversation.** The
  premise is "find how similar problems were solved before". With 4× fewer priors there
  are fewer near-duplicate clusters and a lower chance any incoming ticket has a good
  match at all. This compounds §14's garbage-in ceiling rather than replacing it, and
  the honest expectation for recall@10 should be set lower before tuning starts, not
  after. Window A's `clusters.size_distribution` and `singleton_count` are the numbers
  that settle it: a high singleton share on a corpus this size is the signal that the corpus is
  too thin for this approach, and that is a go/no-go worth stating early.
- **Enrichment stops being an overnight job.** Rescaling §12.6's arithmetic: ~24.2M
  prefill + ~6.4M decode, **≈1–2 hours** at 32B/FP8 rather than 4–7.
- **§12.6's *stated* binding constraint no longer binds.** The 70B path was rejected
  because iteration speed dominated — "15–20 h per pass, a workweek across the 3–5
  prompt revisions you will actually need". At the real row count a 70B/INT4 pass is
  ~4–5 h, so 3–5 revisions is a long weekend, not a workweek. **The decision still stands**, but
  now on its other leg only: ~38 GB of INT4 weights against the 60 GB fair-use cap
  leaves <60k tokens of KV for a model needing ~320 KiB/token, and 4-bit kernels are
  worst exactly at the shallow batch depths enrichment uses. That argument is
  independent of corpus size. Recording this so the choice is not later defended with a
  reason that has stopped being true.
- **The eval holdout window must widen.** §9 wants a few hundred queries from the most
  recent N months; at this corpus size the monthly volume is ~4× lower, so N grows
  proportionally — and a wider window means older tickets, which interacts with §14's
  recency drift.
- **The synthetic fixture is now a several-times larger fraction of the real corpus than
  planned.** M2's requirement that the fixture's cluster-size distribution match the
  profile becomes more sensitive, not less: at this ratio the fixture is a substantial
  fraction of what it models.

Also measured, all clean and none of it assumed: **utf-8** (not latin-1), **comma**
delimiter (not the semicolon a German Excel export usually produces), **38/38 columns
matching the published contract** with no missing and no unexpected extras, and **zero
ragged rows**. Structurally this export is in far better shape than §4's "inconsistent
quality" warning implies — that warning is about content, which Window A measures.

**Open with the client:** is this the complete corpus, or is the export filtered — by
date, status, category or merchant? The answer changes the retrieval-quality expectation
above, and it is the first thing to establish, because everything downstream is sized
off it.

### Window A results — measured 2026-08-10, and what they change

`local/artifacts/profile.json`, `selfcheck_passed=True`, independent
entity sweep clean. Both gating questions are answered, and three architectural premises
turn out not to hold for this corpus.

**§12.1 answered — `solutions` is a single free-text field.** No separator, no attempt
thread. The richer "what was tried vs what worked" schema is **not** needed; M3's data
model stays as drafted.

**§12.2 answered — fill and usable rates both high (most tickets, about 85–90%).** Essentially
every non-empty solution is substantive (only a handful of junk entries corpus-wide; the
remaining "junk" share is simply the empties). Solutions are short, a few dozen tokens at
the upper tail. **The prepared "the fix is process, not code" conversation is
not needed** — this is a strong resolution corpus.

#### 1. The identifier arm is unfounded — identifiers are very rare in the tickets

The brief's §6.3 asserts "the domain is full of exact tokens — error codes, part
numbers, model designations", and §12.7 built a whole third retrieval arm on it, given
the **highest** RRF weight (1.5), specifically to fix `ts_rank_cd`'s lack of IDF so that
`F1247` outweighs `defekt`. Measured: **identifier occurrences are rare, an upper bound
of about 1% of tickets.** The arm would fire on roughly one query in a hundred.

Enrichment will not rescue this: invariant 6 forbids the LLM inventing identifiers, so
it can only extract what is already in the text.

**Consequence, and it is the serious one.** The plan's answer to "`F1247` and `F1248`
are near-identical vectors and completely different faults" *was* the identifier arm.
That answer does not apply here, so the discrimination problem is unsolved and now rests
entirely on dense + lexical retrieval over very little text (below). This is the thing
most likely to cap retrieval quality, and it should be measured early at M3 rather than
discovered at M4.

Recommended: keep `german/identifiers.py` (built, cheap, and Window C may differ), but
drop the identifier arm from v1's critical path, do not weight it 1.5, and do not let
M3's acceptance depend on it.

#### 2. The model-family proxy is dead — `vehicleModelId` is a numeric FK

Shapes are `DDDDD`/`DDDDDD`, a few dozen distinct values, present in about two thirds of
rows, and `model_family()` inferred **zero** families. §3 of this document claimed we could "build
against profile-derived proxies: … the model-designation grammar yields a family
hierarchy by prefix". **That proxy does not exist for this corpus.**

So §5's soft-filter and the rerank-time "exact model / family match" boost cannot be
built without the client's model hierarchy. This moves the §4 client dependency from
"deferred, not blocking" to **blocking for the family-boost feature specifically**. The
good news is the ask is small: a few dozen model IDs and their hierarchy.

#### 3. The corpus is terse, not ugly — this inverts §8's premise

§8 says "**Ugliness is the specification, not an artifact**" and M2 is built to inject
signatures, quoted chains, HTML and casing corruption. Measured on `description`: HTML, quoted reply chains, diagnostic dumps and
ALL CAPS are each around or below 1% (essentially absent), signatures are a small
minority, and missing punctuation affects roughly one in ten.

What is actually hard about this corpus is **brevity**: `title`, `description` and
`solutions` are all only a handful to a few dozen tokens at the median, with a long but
thin tail (the longest description is in the hundreds of tokens).

`description` is present in only about two thirds of rows — so for **about a third of
tickets the entire problem statement is a very short title**. The median ticket carries
about ten tokens of problem text, and the *solution* is longer than the problem.

**M2's generator spec changes materially.** Generating verbose well-formed German tickets
and then dirtying them would reproduce the exact failure §8 warns about, in reverse:
everything would work on synthetic data and collapse on a real corpus of four-word
titles. The fixture must be **short, often title-only, and mostly clean**, with the
measured noise rates above rather than imagined ugliness. Task 8's cleaning pipeline is
largely idle here — keep it as cheap insurance, but it is not the value centre.

**Enrichment's stated purpose also needs restating.** §12.4 argues "enrichment is the
length normaliser — a 4,000-token email collapses to a ~200-token canonical problem".
There are no 4,000-token emails; the longest description is a few hundred tokens. Enrichment here
must *expand* terse text into canonical problem, symptoms and components — a different
job with a different risk profile, because expansion invites hallucination where
compression did not. §12.4's conclusion (no chunking) stands, now on firmer evidence.

#### 4. Gold labels are thin and skewed — about three quarters singletons, one dominant cluster

About three quarters of tickets have no near-duplicate at all. Only a few hundred
multi-member clusters exist, and **one holds a large share of the corpus** (almost
certainly a template or auto-generated ticket type, worth identifying and handling
separately). Excluding it, multi-member clusters cover only about a tenth of tickets.
The size distribution is a very steep Zipf-like tail.

**Read this carefully rather than as a verdict on the product.** MinHash-LSH at threshold
0.7 measures near-duplicate *token overlap*, and it is being run over ~11 tokens. At that
length two tickets describing the same fault in different words will not reach Jaccard
0.7. So a three-quarters singleton share does **not** establish that three quarters of problems are unique — it
establishes that lexical near-duplication is rare, which at this text length is close to
tautological.

What it does establish is that **§9's "same-cluster counts as relevant" gold labels are
too thin and too skewed to carry the real-data harness.** The fallback §9 mentions —
"group by resolution signature or cluster on enriched fields" — must become the primary
design, and M3's harness plan needs rewriting around it. Clustering on *enriched* fields
(canonical problem, components) rather than raw text is the natural move, but it makes
the eval harness depend on enrichment, which reorders M3 and M4.

#### 5. Smaller confirmations

- **Synonym mining is under budget**: about a hundred hunspell-unrecognised tokens against
  §7's "~200-line list, one afternoon"; the vocabulary is small (a few hundred tokens above
  the frequency floor).
- **Multi-fault decomposition is a non-issue**: well under 1% by the error-code heuristic. The
  `ticket_problem` child table stays (cheap, and the heuristic is weak given identifier
  scarcity), but real decomposition is not a v1 concern.
- **Missingness is heavy and correlated**: a few dozen distinct joint null masks, the
  largest having many columns null across a small minority of rows. §6.6's `completeness`
  penalty matters.
- **The export is stale**: data ends many months before the profiling date. §9's "most
  recent N months" holdout is already historical, and §14's recency-drift warning applies
  to the eval set itself. The last 6 covered months hold roughly a tenth of tickets —
  enough for a few hundred eval queries only if gold labelling does not also require a
  cluster-mate.

**Client dependencies from §4 are deferred, not blocking.** Lookup tables, model
hierarchy and the deep-link template all wait for the post-vacation call. Build
against profile-derived proxies: per-ID top non-rare tokens give category labels
without seeing a row, and the model-designation grammar yields a family hierarchy
by prefix.

---

## 4. One open choice

**Frontend stack.** Not a §12 item, so it was never decided. Default proposal:
**SvelteKit + FastAPI** — §11's inline citations, scroll-to-highlight, evidence
spans and chips are genuinely interactive, and the workstation already has
pnpm/node plus Svelte tooling. Confirm or override at M5.
