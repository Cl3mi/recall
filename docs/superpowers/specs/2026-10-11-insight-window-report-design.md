# Insight window — a real-data overview that an agent may read

**Status:** design approved in brainstorming 2026-10-11, not yet implemented.
**Supersedes nothing.** `profile.json` (schema v2) stays valid. This adds a second sealed
run beside Window A and Window B; it does not change either.

## Why

The Window A profiler describes the *structure* of the real export: fill rates,
cluster-size distribution, the `customData` field inventory, identifier shapes, tickets by
month. It never says *what the tickets are about*: which Baugruppe and vehicles dominate,
which problem kinds exist, which solutions were offered for which problem. Those are the
facts the RAG strategy turns on (what to index, how to narrow context, where retrieval has
nothing to return), and today they exist only in rows nobody but a human may read.

## Scope

**In:** one new sealed window ("insight window") that reads the same 38-column export and
emits two tiers of output: `report.json` (agent-readable, gated) and a human-only bundle
(never leaves the box). A static HTML view over `report.json` is a follow-up, not part of
this spec.

**Out:** any change to retrieval, to the fixture generator, or to `profile.json`. No client
contact. No data in git.

## Decisions taken during brainstorming

| Decision | Choice |
|---|---|
| Release line | Two tiers. Counts, ratios, codes and tokens above the floor, plus **reviewed** LLM labels, cross into `report.json`. Real examples stay in the human bundle. |
| Label control | **Free text plus human review.** The LLM writes a short label per cluster, an automated scrub rejects risky ones, the operator approves survivors by hand. |
| Input | The same 38-column export Window A profiled. The five columns named in the request are a view of it: `title`, `description`, `solutions`, `vehicleSerialNo`, and `baugruppe` taken from the `customData` envelope. |
| Window shape | One new window, two stages, one operator-run script. Not an extension of Window A (which claims no GPU), not two windows (each cycle costs human effort). |
| Floor | `k = 50`, the profiler's existing `min_frequency_threshold`, applied to every released value **and every cross-tab cell**. Cells under `k` fold into `other`. |
| Model in the container | Weights are mounted **read-only** from the box's HF cache, not baked into the image. The image is already 9.32 GB and a `ship` already takes about an hour. Default model is `Qwen/Qwen2.5-32B-Instruct-AWQ`, which is already cached on the box and fits the 60 GB cap (see finding 7 in STATE.md). |

## Window shape

```
Stage 1  deterministic     counts, floors, cross-tabs, serial prefix buckets, token stats
Stage 2  GPU               e5 embeddings -> hierarchical clusters -> LLM label candidates
Review   human, AI-free    scrub rejects unsafe labels; operator approves the rest in a file
Assemble                   approved labels + stages 1-2 -> report.json -> blessing gate
```

The operator runs it by hand with no AI present, exactly as Window A and B. Errors carry a
code and a schema path, never a value. Verbatim detail goes to a local log that is shredded.
The sealed run is `--network=none`, thread-capped (default 32), and claims its GPU by UUID
through `gpu-fairuse2.sh claim`.

The review step is **inside** the window because labels are derived from real data. Only
`approved_labels.json` crosses; candidates and rejects stay in the human bundle.

## `report.json` contents

**0. Provenance and suppression ledger.** Input SHA-256, code commit, image digest, model
identities (embedder and labeller), `k`, seeds, row counts. For every section, how many
values were withheld and why, so a reader can tell an empty result from a suppressed one.
This is the `values_traced` lesson applied from the start.

**1. Where tickets come from**
- Baugruppe: distribution above `k`, long-tail shape (distinct count, top-k concentration,
  Gini), fill rate, per-year trend, code grammar.
- Title: shape-normalised templates and frequent n-grams above `k`.
- Vehicle: tickets-per-serial quantiles, share held by the top 1% of serials, repeat-fault
  rate, **serial prefix buckets only** (never a full serial), model family, build year.
- Cross-tabs of Baugruppe x model family x year, cells under `k` folded into `other`.

**2. Problem clusters** (e5 embeddings, hierarchical)
- Per cluster at or above `k`: size and share, reviewed label, distinctive tokens, Baugruppe
  purity, model-family mix, time trend, intra-cluster dispersion.
- Cluster kind: near-duplicate block (like the handover form) versus
  genuinely diverse.
- Noise share, and stability across seeds and thresholds (adjusted Rand index), so the
  reader knows which clusters to trust.

**3. Solutions**
- A solution-type taxonomy **derived from the reviewed labels**, not fixed in advance.
- Cluster x solution-type matrix, cells under `k` folded.
- Solution diversity per cluster (distinct approaches), serving the rule that every variant
  approach must reach the technician and near-duplicates are never collapsed.
- Clusters whose tickets have no usable solution: where retrieval has nothing to return.

**4. RAG-decision evidence**
- Token-length quantiles per field against the e5 512-token limit, with the truncation share.
- Identifier density (fehlercodes, part numbers): how much a lexical arm can earn.
- Leave-one-out coverage: per ticket, is there a neighbour with a usable solution above a
  similarity threshold? Reported as a curve over thresholds.
- Field ablation: neighbour agreement using title only, then plus description, then plus a
  Baugruppe filter.
- Narrowing value: candidate-set reduction from filtering by Baugruppe or model family,
  against the share of true neighbours kept.
- Boilerplate and template share, with an exclude-or-structure recommendation.

## Human-only bundle

Examples per cluster, raw and rejected label candidates, serial and Baugruppe lists. It is
read by the operator and shredded with the window; `fetch --clean` must leave only
`report.json`, matching the Window B teardown that finding 16 fixed.

## Safety controls

- **Every released string is blessed.** `report.json` passes `profiler.blessing.unblessed`
  with zero offenders, and the catch-all wired into `selfcheck.assert_safe` is extended to
  the new sections. The agent-side gate in STATE.md applies unchanged.
- **Cell floors.** A cross-tab can single out one vehicle even when each marginal clears
  `k`. Every cell is floored, not only the margins.
- **Serials.** Prefix buckets only, bucket width chosen so each bucket holds at least `k`
  tickets. No full serial, no suffix.
- **Tokens.** Distinctive tokens pass the existing hunspell and entity filters. Names are
  the leak this guards against.
- **Labels are the only free text.** Scrub rule: a label is rejected if it holds a digit, a
  serial-like shape, an email or phone pattern, or a capitalised word the German dictionary
  does not know. Maximum six words. Approval is a manual edit by the operator; there is no
  auto-approve path.
- **Nothing derived survives between windows.** Embeddings and cluster assignments are
  discarded with the window, per the airlock protocol.

## Testing

- An adversarial stand-in corpus (as Window A v2 used) with planted names, serials, emails
  and a rare Baugruppe, asserting none appear in `report.json` and each is counted in the
  suppression ledger.
- Red-green on the scrub: each rejection rule must fail a label built to violate it.
- A rehearsal script mirroring `rehearse-window-b.sh`, run on `--fake` data, **asserting**
  rather than noting the provenance fields and the stale-image guard (finding 20).
- Cell-floor test: a cross-tab whose margins pass `k` but whose smallest cell does not.

## Acceptance criteria

1. The rehearsal passes end to end on stand-in data, including the review step with a
   scripted operator.
2. `report.json` has zero unblessed strings and every section present, or explicitly
   suppressed in the ledger.
3. The planted-leak test finds no planted value in the report.
4. Output is identical on CPU and GPU within the tolerance finding 18 established, so the
   device stays out of the identity.
5. A real run produces `report.json` and the human bundle; after `fetch --clean` only
   `report.json` remains on the box.

## What this pass cannot answer

Whether the reviewed labels are *right* is the operator's judgement, not a measurement.
Leave-one-out coverage and field ablation use embedding neighbours as a proxy for relevance;
they do not replace the hand-written `eval_real.json` queries M3 plans for Window C.

## Amendments from planning (2026-10-11)

Found while writing Plan 1, against the code rather than the brainstorm.

1. **Titles release floored tokens and bigrams, not "shape-normalised templates".** Window A v2
   already rules "never shape prose"; a title is prose.
2. **Serial prefix buckets are opt-in** (`--serial-prefixes`, default off) and need an operator
   ruling before a real window passes the flag, because `vehicleSerialNo` is on
   `profiler.selfcheck.DENYLISTED_COLUMNS` ("no value emitted at any frequency"). A bucket never
   releases more than half of any serial it covers, never more than 8 characters, and is
   floored on distinct VEHICLES rather than tickets, so one vehicle with many tickets cannot
   form a bucket on its own.
3. **`report.json` is checked by `insight.guard`, not `profiler.blessing`.** `blessing.unblessed`
   is bound to `profiler/schema.json` and to module-level path lists, so extending it would
   change a safety control. The guard applies the same rule: every dict key declared, every
   string accounted for, every released value at or above `k` and swept.
4. **The entity sweep is per released field.** `looks_like_entity` flags product codes such as
   `B-10` and `TX-2210` through its licence-plate pattern alone. Baugruppe, model and
   serial-prefix values therefore get every check except the plate shape (company suffixes,
   surnames, e-mail, phone and IBAN still apply), the narrower sibling of the exemption
   `PRODUCT_DIMENSION_COLUMNS` documents for `vehicleModelId`. Free-text tokens also withhold
   any part that carries a digit and is longer than six characters, mirroring the
   identifier-like rule `selfcheck` applies to dimension-hint tokens.
5. **Baugruppe covers about a quarter of tickets** (per `profile.json`), so every
   Baugruppe section carries a coverage block.
6. **Plan split.** Plan 1 is the deterministic stage with no model. Stage 2 (clusters, labels,
   review, coverage and ablation evidence) and the window itself are separate plans.
7. **Token lengths in plan 1 are whitespace tokens, labelled as such.** The e5 truncation share
   needs the tokenizer and belongs to stage 2.
8. **Floors count tickets or vehicles depending on what is released.** Serial prefix buckets
   count distinct vehicles, because the released string is part of an identifier. Cross-tab
   cells count tickets, because no component of a cell is a serial and a cell describes a model
   line and a year. A distinct-vehicle floor of `k` there would suppress most real cells.
9. **Cells and values under the floor are withheld and tallied, not folded into `other`.** The
   report states how many distinct values and rows were withheld per reason, as numbers only.
10. **Accepted residuals at `k = 50`.** Margins, cells and the withheld tally are all published,
    so when exactly one cell of a margin is withheld a reader can subtract to learn its count,
    which is some number below `k` about a product line and not personal data.
    `tickets_per_serial_quantiles.max` is an unfloored count that identifies nothing. Equal
    counts are ordered by key, so the report does not depend on the row order of the export.
11. **Identifier density is measured raw and after cleaning.** The cleaning pipeline's phone
    pattern redacts a part number such as `1234.56789`, which is what the part-number pattern
    matches, so the cleaned text a RAG index would hold has lost it. Reporting `tickets` beside
    `tickets_after_cleaning` turns that loss into a number and is itself a data-quality finding.
    Blank problem texts are excluded from clustering and counted, and the largest cluster's
    share is withheld when that cluster is smaller than the floor.
12. **The guard refuses anything it was not told about.** Every key is declared, every string is
    accounted for by path and shape and matched in full, every value must be a JSON leaf, dict
    or list (a tuple would be written as an unexamined list), and the root must be a dict. A
    code field also withholds a value over 16 characters that carries a digit, which is what a
    VIN or serial typed into a free-ish field looks like. Provenance arguments are validated
    before any data is read, so a bad value costs nothing. Known limit, inherited and not
    introduced: `profiler.entities` knows company suffixes, common surnames and contact shapes,
    so an uncommon lowercase name that clears the floor of 50 would pass a free-text token
    sweep; the floor is what bounds it.
13. **`report.build` isolates its inputs, and clustering is canonical.** It deep-copies `source`
    and `provenance`, accepts exactly the expected keys, checks `row_count` against the rows and
    computes the provenance fields it owns, so a caller cannot alias or override what was
    guarded.
    Documents are sorted before the near-duplicate clustering, which is greedy and otherwise
    order-dependent on chains of overlapping texts, so the whole report is a function of the
    set of rows and not of their order.
14. **The CLI cannot destroy the input or leave a misleading report.** It refuses `--out` equal
    to the input under any spelling, symlink or hardlink; removes any stale report before
    anything else; writes under a temporary name and moves it into place; aborts when required
    columns are missing (printing only a count) instead of emitting an all-zero report; replies
    to argument errors with a fixed code that never echoes the value; and refuses a floor below
    the release floor unless `--allow-weak-floor` is passed.
