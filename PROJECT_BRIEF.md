# Project brief — ticket similarity search ("Lösungsfinder")

This is a design brief, not a spec. It captures decisions already made and flags
what is still open.

## 1. Problem

A machinery dealer/service network runs a ticket system. When a new support
ticket arrives, the handling employee has no good way to find how similar
problems were solved before. Keyword search over the existing system is
inadequate.

**Goal:** given the text of a new ticket, surface the most similar historical
tickets that have a successful resolution, and synthesize a grounded, cited
suggestion for how to handle it.

**Users:** internal support staff and service technicians. German-speaking,
domain experts, low tolerance for a tool that is confidently wrong.

## 2. Scope for the first prototype

In scope:
- Ingest a one-off CSV export (~65,000 tickets).
- Hybrid retrieval (semantic + lexical) with metadata filtering.
- LLM-generated suggestion with citations to source tickets.
- Simple web frontend: paste ticket text → suggestion + checkable source list.
- Lightweight human verification loop.
- Fully local inference.

Explicitly **not** in scope yet (see §13).

## 3. Invariants (non-negotiable)

1. **No real ticket data leaves the client machine.** Not in logs, not in error
   traces, not in test fixtures, not in prompts to any remote model.
2. **Remote coding agents only ever see synthetic data.** The synthetic
   generation and leakage gate (§8) are prerequisites for remote-assisted
   development.
3. **All inference is local.** No API calls to hosted model providers from the
   application at runtime. Single NVIDIA GPU, 80 GB VRAM, fully available.
4. **The raw export is immutable.** Store it verbatim; every derived artifact is
   reproducible from it. Never edit rows in place.
5. **No retrieval-quality decision is made on synthetic metrics.** Synthetic
   evals prove code correctness. Only the real-data eval proves quality.
6. **The generator never invents identifiers.** Any error code, part number, or
   model designation emitted by an LLM must be verified as a substring of the
   source text before it is stored or displayed.
7. **Corpus language is German throughout.** No translation to English at any
   stage — not for embedding, not for enrichment, not for prompts.

## 4. Data

Single CSV export, ~65,000 rows, all German, inconsistent quality, many missing
values. Manual cleanup is not an option at this volume.

### Columns as exported

```
id, userCreatedId, userAssignedId, statusId, priorityId, personId, title,
description, vehicleYear, customData, merchantName, endCustomerName,
timestampCreated, categoryId, deadline, merchantId, endCustomerId, vehicleHours,
vehicleSerialNo, vehicleId, vehicleModelId, solutions, vehicleStatus,
contactEmail, contactPhone, ticketNumber, vehicleSerialIndex, merchantNumber,
merchantPhoneNumber, endCustomerNumber, endCustomerPhoneNumber,
contactPhoneTrimmed, showInProteam, contractTransaction, contractItems,
lastModifiedUser, subStatusString, subStatusChanged
```

### Field roles

| Role | Fields |
|---|---|
| Problem text | `title`, `description`, possibly `customData` |
| Resolution text | `solutions` — **the load-bearing field** |
| Filterable metadata | `vehicleModelId`, `vehicleYear`, `vehicleHours`, `categoryId`, `statusId`, `priorityId`, `subStatusString` |
| PII — never embedded, access-controlled on display | `endCustomerName`, `merchantName`, `contactEmail`, `contactPhone*`, `*PhoneNumber`, `endCustomerNumber`, `personId` |
| Display / linking | `ticketNumber`, `timestampCreated` |
| Probably ignorable v1 | `contractTransaction`, `contractItems`, `showInProteam`, `deadline`, `vehicleSerialIndex` |

### Still needed from the client

- **Lookup/dimension tables** for `statusId`, `categoryId`, `priorityId`,
  `vehicleModelId`. IDs alone are unusable for filtering and for the LLM.
- **Model hierarchy** (model → series → family). Filtering on exact
  `vehicleModelId` is too narrow; sibling models share faults.
- **Deep-link URL template** for the existing ticket system, e.g.
  `https://…/ticket/{ticketNumber}`.
- Structure of `customData` and of `solutions` (see §12.1).

## 5. Architecture

### Offline path (one-off, then nightly delta)

```
CSV export
  → raw load (immutable, jsonb)
  → clean: strip signatures, quoted reply chains, HTML, boilerplate, PII
  → LLM enrichment: canonical problem, symptoms, error codes, components,
    root cause, resolution steps, resolution type, solution_quality,
    enrichment_confidence
  → identifier verification (invariant 6)
  → embed + index in Postgres (pgvector + German FTS)
```

Enrichment over 65k tickets with continuous batching is an overnight job, not a
scaling problem.

### Online path (per query)

```
pasted ticket text
  → extraction pass: same normalization as index time
    (canonical problem, error codes, model, category)
  → hybrid retrieval: dense (pgvector HNSW) + lexical (German FTS/BM25),
    fused with RRF, soft metadata filtering
  → cross-encoder rerank top ~50 → top ~10
  → near-duplicate clustering (frequency signal)
  → confidence triage → synthesis with citations, or abstain
  → frontend: suggestion + checkable source tickets
```

**Symmetry between index-time and query-time normalization is the core trick.**
Both sides get projected into the same normalized space, which is what lets a
messy new ticket match a messy old ticket.

## 6. Key design decisions (already made)

1. **Do not embed the raw row.** The primary vector represents the *problem*
   only (title + cleaned description + canonical problem + symptoms +
   components). A separate vector represents the *solution* text. Query-to-
   problem is a symmetric similarity task; mixing the solution into the primary
   vector dilutes it.
2. **Enrichment is the data-cleaning layer.** 65k rows will not be cleaned by
   hand; they get a clean derived projection instead, with the raw rows intact
   underneath.
3. **Hybrid retrieval is mandatory.** The domain is full of exact tokens — error
   codes, part numbers, model designations. `F1247` and `F1248` are near-
   identical vectors and completely different faults. Dense-only will fail here.
4. **Reranking before synthesis.** Highest quality-per-effort component after
   enrichment.
5. **Soft metadata filtering, not hard `WHERE`.** Retrieve with a permissive
   filter (product family, resolved, non-empty solution), then boost at rerank
   time for exact model / adjacent year / similar hours. Hard filters return
   empty result sets and destroy trust.
6. **Missing values are never imputed and rows are never dropped.** Enrichment
   is allowed — required — to emit `null`. A `completeness` score acts as a mild
   ranking penalty.
7. **Retrieval is the product; the summary is the garnish.** The source ticket
   list is always visible, never hidden behind a "sources" accordion.
8. **Two-tier over time:** verified suggestions get promoted into a curated KB
   that is indexed alongside tickets and ranked above them. Human effort
   compounds into the knowledge base nobody had time to write.

## 7. German-language handling

Two cheap changes that materially move recall:

**Compound decomposition.** `to_tsvector('german')` stems but does not split
compounds, so `Hydraulikpumpe` will not match `Pumpe defekt`. In a German
technical corpus this is most of the vocabulary, not an edge case.

```sql
create extension unaccent;

create text search dictionary german_hunspell (
  template = ispell, dictfile = de_de, afffile = de_de, stopwords = german);

create text search configuration de_tech (copy = german);
alter text search configuration de_tech
  alter mapping for asciiword, word, hword, hword_part
  with unaccent, german_hunspell, german_stem;
```

Verify with `ts_debug` on real tickets that compounds actually split.

**Dealer shorthand synonyms.** Needed (`Getr.` → `Getriebe`, `HD` →
`Hydraulik`), but mined rather than hand-written: extract top tokens Hunspell
fails to recognize → batch to the local LLM for canonical-form proposals → one
support engineer reviews a ~200-line list once → load as a `synonym`
dictionary in the same config. Bounded one-afternoon human task, permanent
payoff.

## 8. Synthetic dataset (development enabler)

**Purpose:** allow remote coding agents to work on the codebase without any
exposure to real data.

**The failure mode to avoid:** generating clean, well-formed German tickets.
Everything then works beautifully on synthetic data and collapses on the real
corpus. **Ugliness is the specification, not an artifact.**

### Two artifacts

| Artifact | Rows | Purpose | In git |
|---|---|---|---|
| Fixture set | ~1,500 | unit/integration tests, CI, day-to-day agent work | yes, fixed seed |
| Mirror set | ~65,000 | perf, index tuning, end-to-end smoke runs | no, but shareable |

Build the fixture first. Generate the mirror only when throughput numbers are
needed.

### Generate from a profile, not from rows

**Do not paraphrase real tickets row by row.** Paraphrase-based synthesis is the
leakiest available approach — models retain entities, and a reworded real ticket
can still identify a real customer, dealer, or machine.

**Stage 1 — profile the real CSV into a small JSON artifact (statistics only,
no LLM):**
- Per-field length quantiles, including the pathological tails.
- **Joint** null-mask patterns with frequencies — not per-column rates.
  Missingness is correlated (no `vehicleSerialNo` usually means no `vehicleId`).
- Format grammars for identifiers: regex shapes + frequencies for error codes,
  part numbers, serial numbers, model designations. New values are generated
  from the grammar; real values are never reused.
- Category / model / status / priority frequency tables; temporal distribution.
- `solutions` fill rate and junk-solution taxonomy (`erledigt`,
  `siehe Telefonat`, one-word, empty).
- Formatting-noise rates: % with quoted reply chains, signatures, HTML,
  pasted diagnostic dumps, no punctuation, ALL CAPS.
- **Near-duplicate cluster-size distribution** — count of distinct recurring
  problems and tickets per problem (expect Zipfian).
- Vocabulary/n-gram frequencies with rare terms pruned (rare terms are where
  identifying information hides).

This artifact is small enough to review line by line. **That human review is a
formal gate before anything leaves the machine.**

**Stage 2 — generate with the local LLM, conditioned only on the profile:**
- Invent a fictional product line with obviously fake designations (`TX-2200`,
  `LR-45`) so any leak is visually obvious.
- Generate ~400 fault archetypes tied to specific fictional models/components.
- Expand each into 1–40 variants following the real cluster-size distribution,
  in different voices (terse mechanic, rambling customer email, template dump).
- Apply noise and null masks **programmatically afterwards** — append
  signatures, inject quoted chains, blank fields per sampled masks, corrupt
  casing. Do not ask the LLM to be messy; it produces uniform mess. Mechanical
  noise injection is controllable and reproducible.

**Why cluster structure matters:** it is the piece people skip and the piece
that makes the synthetic set useful. Any two tickets from the same archetype are
relevant to each other, which gives free gold labels — a real eval harness the
remote agents can iterate against. Without it, dedup logic, the frequency
signal, and every recall metric are untestable.

### Leakage gate — automated build step, fails loudly

- Regex/NER sweep: German name patterns, phone numbers, emails, addresses,
  IBANs, plate numbers.
- **Shingle intersection:** hash all 8-token shingles in both corpora; assert
  empty intersection modulo a stopword allowlist.
- **Nearest-neighbour check:** embed both corpora, flag any synthetic row with
  cosine > 0.95 against any real row.
- **Entity allowlist:** merchant/customer names drawn from a generated
  fictional roster; assert no real-roster name appears anywhere.

Emit a signed gate report artifact. That file is the answer when the client's
DPO asks how leakage was ruled out.

## 9. Evaluation

Two separate reports, never conflated:

| Report | Runs where | Visible to | Answers |
|---|---|---|---|
| `eval_synthetic.json` | CI | remote agents | is the code correct |
| `eval_real.json` | client machine only | aggregate metrics only | does the system work |

**Real-data harness (build in week one, before tuning anything):** hold out the
most recent N months of resolved tickets as queries. For each, ask whether the
system retrieves historical tickets whose resolution matches the held-out
ticket's actual resolution. Group by resolution signature or cluster on enriched
fields; same-cluster counts as relevant. Yields recall@10, MRR, nDCG over a few
hundred queries.

Layer on a small human-graded set (50–100 queries rated by an actual support
engineer) for end-to-end answer quality.

**Divergence rule:** if a change helps synthetic and hurts real, the profile is
wrong — fix the generator, don't shrug.

Without this harness you will tune chunk sizes by vibes and be unable to tell
the client whether the reranker justified its latency.

## 10. Human-in-the-loop

Route by confidence so only a fraction of requests ask anything.

| Lane | Trigger | Behaviour | Asked of user |
|---|---|---|---|
| Green | high rerank score, ≥3 tickets agreeing, model-family match | show suggestion normally | nothing |
| Amber | decent but thin or partially conflicting evidence | show suggestion labelled *Entwurf — bitte prüfen* | one binary click: *Passt die Ursache?* ✓/✗ |
| Red | weak or contradictory evidence | suppress synthesis, show ranked list only | nothing |

- On ✗: three single-tap chips (wrong model / wrong fault / solution
  incomplete). **Never a free-text box** — it kills participation and yields
  data you can't aggregate.
- If amber volume is too high, sample it (ask on every third).
- Thresholds calibrated from the real eval harness at a target precision
  (e.g. green ≈ 90% precision). Log the score distribution; revisit quarterly.
- **Highest-value signal is not the thumbs.** It is *"this solved it"* at ticket
  close: one click, at a moment the user is already in the system, and it is
  ground truth rather than an opinion about a summary. Make it the primary loop.
- Confirmed amber suggestions get promoted to curated KB entries (§6.8).

## 11. Frontend requirements

- Suggestion and source-ticket list both always visible. No sources accordion.
- **Inline clickable citations** per claim; clicking scrolls to and highlights
  the source card.
- **Evidence-span highlighting** inside each source ticket. Do not ask the LLM
  for character offsets — it gets them subtly wrong. Align post-hoc: split
  retrieved tickets into sentences, embed, match each summary sentence to its
  best-scoring source sentence above a threshold.
- **Deep link to the real ticket system** on every card. One line of config,
  more trust than any UI polish, because users can fall back to the system they
  already believe.
- **Show the funnel:** "8 von 34 Treffern · Modellfamilie TX-22xx" plus a
  one-click *Filter aufheben*. Silent filtering is the fastest way to lose a
  user who knows a relevant case exists.
- **Per-card match reasons as chips:** same model / error-code hit / relevance
  score / resolution-confirmed.
- **Surface disagreement:** "6 of 8 cases resolved by X, 2 by Y" beats a
  confident single answer and is honest about what the corpus says.
- Raw original ticket text one click away — the cleaned version is indexed, but
  the original email is sometimes what the technician needs.
- Explicit *no strong match* state. Never degrade into a weak confident answer.
- Copy button for pasting into the existing ticket system.
- UI language: German.

## 12. Open decisions for the planning session

Work these in order; the first two gate everything else.

1. **Is `solutions` a single free-text field or a collection of entries per
   ticket?** If it is a thread of multiple attempts including failed ones, model
   attempts separately and distinguish "what was tried" from "what worked" —
   richer system, different schema. Blocks the data model.
2. **What is the fill rate and usable quality of `solutions`?** Profile first.
   If it is very low, the honest answer to the client is that the fix is process
   (require a resolution on close), not code — and that has to be said before it
   becomes someone's fault.
3. **Who signs off on the leakage gate, and when?** If the DPO wants to review
   the profile artifact and gate report before synthetic data leaves the
   building, that review is on the critical path for all remote-agent work.
   Schedule it in week one.
4. Chunking strategy for long `description` values — parent-document retrieval
   is assumed, but confirm the chunk size and overlap against real length
   quantiles.
5. Embedding model choice, and whether to use a model that emits both dense and
   learned-sparse vectors (convenient for hybrid) versus separate dense + BM25.
   Verify current best German-capable options and their licences at
   implementation time.
6. Generator size. A ~27–32B instruct model at FP8/AWQ leaves ~40 GB for KV
   cache, which matters when stuffing 10 tickets into a prompt. A 70B at 4-bit
   fits but the KV headroom gets tight; for *summarizing retrieved text*
   retrieval quality dominates generator quality. Confirm the tradeoff.
7. BM25 implementation: native Postgres FTS vs a BM25 extension. Affects
   scoring quality and the deployment footprint.
8. RRF weighting and rerank cutoffs — set from the eval harness, not by hand.
9. Incremental sync mechanism for the production phase: nightly delta on a
   modified timestamp, or CDC.
10. Automation liability: if tickets are eventually piped in automatically,
    where is the human gate for anything safety-relevant on a vehicle? Needs an
    explicit written decision from the client.

## 13. Non-goals for v1

- Automatic ingestion of incoming tickets (planned later; frontend paste only
  for now).
- Multi-tenant access control beyond basic PII gating.
- Writing back into the client's ticket system.
- Fine-tuning any model. Retrieval quality, not model weights, is the lever.
- Chat-style multi-turn interaction over the corpus.

## 14. Risks to state to the client now

- **Garbage-in ceiling.** Sparse or terse historical solutions cannot be
  rescued by any retrieval architecture.
- **Recency drift.** A 2014 resolution may reference a discontinued part or a
  superseded procedure. Decay old tickets in ranking; always show the date.
- **Automation liability.** See §12.10.
- **Jargon budget.** Mixed German/English dealer shorthand means custom
  dictionary and synonym work. Unglamorous, and longer than it looks.

## 15. Proposed milestones

| # | Milestone | Acceptance |
|---|---|---|
| 1 | Profile the real CSV | profile artifact reviewed; go/no-go on `solutions`; `ts_debug` confirms compound splitting |
| 2 | Synthetic fixture + leakage gate | 1.5k rows, gate green in CI, repo unblocked for remote agents |
| 3 | Baseline hybrid retrieval + dual eval harness | recall@10 / MRR reported on both corpora, no LLM in the loop |
| 4 | Enrichment pass + reranker | identifier verification passing; measured delta on the real harness |
| 5 | Synthesis + triage + frontend | citations checkable; thresholds calibrated from milestone 4 |
| 6 | Feedback capture + KB promotion + incremental sync | "this solved it" logged; nightly delta running |

Milestones 1–3 are largely doable on synthetic data and benefit most from
remote agents. Milestones 4–5 are inherently on-prem — plan for debugging
quality issues on a machine you cannot paste logs out of, so invest early in
on-prem-runnable eval scripts that emit a shareable aggregate report.
