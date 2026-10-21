# M2 — synthetic fixture and leakage gate

**Status:** approved 2026-08-17
**Milestone:** 2 of 6. Acceptance in `PROJECT_BRIEF.md` §15: *1.5k rows, gate green in CI,
repo unblocked for remote agents.*

## Purpose

Produce a 1,500-row synthetic corpus that behaves statistically like the client's real
export, and prove it is not derived from it. Once green, the fixture is committed and all
subsequent work — retrieval, eval, enrichment — proceeds without an airlock window.

The fixture is not a mock. M3 reports recall@10 and MRR on both corpora, so a number
measured here only transfers if the distributions match.

## Inputs

`local/artifacts/profile.json`, schema v2, produced by Window A round 3 over the real
export. It has passed `blessing.unblessed` with zero findings, which is what makes it
safe to read. Nothing else about the real corpus is available, and nothing else is needed.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Fidelity | Generated from `profile.json` | Distributions must transfer to M3's metrics; also self-updating when a new window runs |
| Text source | Local LLM on the H100, ~32 GB model | Natural German prose; invented vocabulary cannot copy a real n-gram |
| Cluster structure | LLM writes themes and variants, code controls counts | Variants must be different *approaches*, not reworded strings — collapsing them is what the product must never do |
| Row count | 1,500 | Per the brief; a small fraction of the real corpus |
| PII fields | Present in the fixture, excluded from the pipeline | See *Deferred* below |

### Deferred: PII treatment

`ansprechpartner` and `ansprechpartner-tel` (present in most real tickets, always filled) are
contact name and phone. Final treatment is **deferred**; until it is decided, nothing
downstream reads, indexes, embeds or surfaces them. The fixture still contains both
fields with obviously-fake values, so the structure stays faithful and the decision stays
testable when it is picked up. Recorded in `docs/STATE.md`.

## Architecture

```
local/artifacts/profile.json     already gated, safe to read
        │
        ▼
  fixtures/plan.py               pure function → FixturePlan (no LLM, no I/O)
        │
        ▼
  fixtures/generate.py           vLLM on the H100; response cache keyed by prompt hash
        │
        ▼
  fixtures/render.py             38-column CSV, double-encoded EAV customData
        │
        ▼
  fixtures/verify.py             does the output match the plan?
        │
        ▼
  local/fixtures/synthetic.csv   →  Window B leakage gate  →  commit to git
```

`fixtures/` is a new top-level package alongside `profiler/`, following its conventions:
a `__main__.py` CLI, pure functions where possible, and no dependency on `recall.*`
beyond what it already reuses.

**Generation needs no airlock window.** It reads a gated artifact and produces invented
text; no real data is present. The H100 is used for compute only. The gate is a separate
command that *does* need a window, because it compares against the real corpus. Keeping
them as two commands is deliberate — merging them would put an LLM in a window.

## `plan.py`

Pure function: `plan(profile: dict, rows: int = 1500, seed: int) -> FixturePlan`. The only
place `profile.json` is interpreted. No LLM, no network, no filesystem.

### Group-size scaling

Scaling group *counts* by the corpus ratio rounds the largest few groups to zero while still
owing a few hundred tickets — it would delete the corpus's most prominent structural
feature. Sizes are therefore scaled for the large groups and sampled for the small ones:

| band | real groups | real share | fixture |
|---|---|---|---|
| the handover group | 1 | roughly an eighth | **1 group**, scaled to the same share |
| other 50+ groups | a handful | under 2% | **3 groups**, scaled to the same share |
| 2–49 | hundreds | about a tenth | **about a tenth of the rows**, groups sampled from the real size distribution |
| singletons | most of the corpus | about three quarters | **remainder** |

Every band lands within 0.05 percentage points of the real corpus. Singletons take the
remainder, so the total is exactly `rows` no matter how the other bands round.

### Other derived targets

- **`solutions` fill** high (about 85–90%), usable rate nearly equal; junk is overwhelmingly
  empty strings, not filler text.
- **Fill by year**, reproducing the workflow change rather than a flat corpus: description
  and solutions fill rates differ strongly between years (description fill dips mid-period,
  solutions fill starts very low in the first year; real per-year figures omitted). Ticket
  dates spread over the export's date range.
- **`customData`**: the 26 emitted envelope fields, each at its measured presence share —
  the contact name and phone fields most common (most tickets), then `baugruppe`,
  `fehlercode`, the handover block and `operations` progressively rarer (real shares
  omitted). Descriptors per ticket: a median of a few, with a long tail.
- **`fehlercode` shape mix**, in the measured proportions (each of the ten leading shapes
  holds roughly 7–15%): `DDDD-D`, `DDDD-DD`, `DDDDD`, `DDDD`, `ALL_DD`, `DDD-DD`,
  `ALL_DDDD-D`, `ALDD_DDDDD`, `DDDD-DD#_DDDD-DD` (two codes in one field), `ALL_DDDD`.
- **`vehicleModelId`** as an opaque numeric FK over a few dozen values, not a designation.

## `generate.py`

One prompt per group, asking the model for *N genuinely different approaches to the same
fault* — differing in method and detail, not in wording. Singletons are generated in
batches of distinct faults.

- **Model:** configurable; default a ~32B instruct model with strong German. Served by
  vLLM on `hpc` with `--disable-log-requests`. The box is shared and fair-use capped
  at 60 GB VRAM, so a ~32 GB model leaves room for other users — run
  `infra/fairuse/gpu-fairuse2.sh check` first, as the window script already does.
- **The model never sees real data.** Its prompts contain plan numbers and invented seed
  themes only. Asserted by a test, not by intent.
- **Caching:** every response is cached under `local/fixtures/cache/` keyed by a hash of
  the prompt. A partial failure resumes; a re-run costs nothing.
- **Reproducibility:** LLM sampling is not reproducible, so the *artifact* is the fixture.
  It is generated once, verified, gated and committed. Correctness is guaranteed by
  `verify.py`, not by hoping generation repeats.

## `render.py`

Assembles the 38-column CSV per `profiler/columns.py`.

`customData` is built exactly as the client builds it: a list of descriptors
`{group, key, label, value, text, type}`, serialised with `json.dumps` and then serialised
**again**, so the field opens with a quote. Round 2 and 3 were spent discovering this
format because the old stand-in used a plain object; the fixture must not repeat that.

The file is named `export.csv` when it stands in for a real export, since `source.filename`
is withheld as `<non-conforming>` otherwise.

## `verify.py`

Checks the rendered fixture against the plan and fails loudly on drift: row count, group
size distribution, per-column fill rates, fill-by-year, `customData` field presence
shares, `fehlercode` shape mix, and that every `customData` value round-trips through
`profiler.stats.customdata.parse_records`.

## Leakage gate — Window B

Controls fixed by `docs/airlock-runbook.md` and unchanged here: both checks run **on the
box**; real-corpus embeddings are not retained between windows; only counts, thresholds
and verdicts cross out. No shingle set leaves — a set of 8-token shingles is a membership
oracle and does not need to exist off-box. No vectors leave.

Green requires **both**:

1. **Zero** synthetic documents share a content-bearing 8-token shingle with any real
   document. Stopwords are removed first, so a shared run of German function words cannot
   mask a real collision. The bar is zero rather than a tolerance: a threshold here is
   something we would later be tempted to relax, and a single hit is worth investigating
   rather than excusing.
2. The 99th-percentile nearest-neighbour cosine between synthetic and real documents is
   below a threshold calibrated in the same window against a synthetic-vs-synthetic
   baseline. Reported alongside the baseline so the number is interpretable.

The gate emits `gate_report.json` — counts, thresholds, verdicts. `infra/profiler/window.sh`
already carries Window B's allowlist and shred list and refuses to run until this command
block exists.

## Testing

The strongest acceptance test costs nothing new: **we already own a corpus profiler.** Run
it over `synthetic.csv` and compare the resulting profile to the real one on every
measured dimension. "The fixture profiles like the real corpus" is a better check than any
hand-written assertion.

Unit tests:

- `plan.py` against a fixed profile fixture → exact expected group sizes and shares
- the scaling rule specifically: the handover group survives at its scaled size and is not rounded away
- `render.py` round-trips through `customdata.parse_records`, and `detect_envelope`
  identifies it
- `verify.py` catches a deliberately planted distribution mismatch
- no prompt contains any string drawn from a real artifact

## Acceptance

- [ ] 1,500 rows, 38 columns, schema-conformant
- [ ] `verify.py` green
- [ ] profiling the fixture reproduces the real profile on every dimension in
      `plan.py`, within these tolerances: group-band shares ±1.0 percentage point;
      per-column fill rates ±2.0 points; `customData` field presence shares ±2.0 points;
      `fehlercode` shape-mix proportions ±3.0 points; fill-by-year ±5.0 points (fewer
      rows per year makes this the noisiest)
- [ ] Window B gate green: zero 8-token shingle collisions, NN cosine below the
      calibrated threshold
- [ ] fixture committed; `make test` green without any real data present

## Out of scope

Retrieval, the eval harness, recall@10 / MRR — all M3. Enrichment and reranking — M4.
The PII treatment decision — deferred, see above.

## Risks

- **The gate fails on common German phrasing.** Likeliest failure. Mitigation: the
  vocabulary is invented rather than drawn from the profile's top tokens, and stopwords
  are stripped before shingling. If it still fails, the finding is real and the generator
  changes — the threshold does not.
- **The model produces variants that differ only in wording**, making the near-duplicate
  groups fake. Mitigation: prompt for differing method and detail; spot-check group
  members during review.
- **The box is busy.** Generation is not time-critical and the fair-use check gates it.
