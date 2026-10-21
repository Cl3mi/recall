# Window A v2 — profiling what round 1 could not see

**Status:** design approved 2026-08-10, not yet implemented.
**Supersedes nothing.** This extends the Window A profiler; the round-1 artifact in
`local/artifacts/profile.json` stays valid and remains the basis for current planning.

## Why

Round 1 answered both gating questions — `solutions` is a single free-text field (§12.1)
and nearly all of it is substantive (§12.2) — and overturned three architectural premises.
But every content-derived statistic it produced (clusters, vocabulary, identifier
grammars, multi-fault rate, dimension-hint tokens) was computed from `title +
description` **only**. `customData` was measured for length and never inspected, despite
being present in nearly all rows at a median of a few hundred characters.

So the round-1 finding "identifier occurrences are rare, about 1% of tickets at most" means
*rare in title+description*. If this client records error codes as a structured field inside
`customData`, our extractor never looked — and that single fact decides whether the
identifier retrieval arm is well-founded or should be dropped from v1.

Four of the five questions blocking M2 are answerable by profiling differently rather
than by waiting for the client. This is that pass.

## Scope

**In:** five additions to the profiler, a `schema_version` bump to `"2"`, `selfcheck`
extensions including a whole-artifact catch-all, a fix to `source.filename`, and an
adversarial stand-in that exercises all of it.

**Out:** token emission from `customData` (see "Deliberately deferred"), any change to
retrieval, enrichment, or the M2 generator. This pass gathers evidence; the decisions it
informs are made afterwards.

## The five additions

### 1. `customData` structure — `profiler/stats/customdata.py`

*Answers:* are the error codes in there? What is this field, structurally? (§4's
"Structure and meaning of `customData`", currently a client question.)

Parse each value: JSON first, then `key=value`, then a delimited fallback. Record which
format won and the parse-success rate. Per key emit:

- **key name** — subject to the presence floor and entity sweep below
- **fill rate** — share of present rows whose value is non-empty
- **`kind`** — one of `empty | numeric | identifier_like | prose | short_text`
- **value character-length quantiles**
- **value shapes** — floored, capped, and only for short values

Classification is deterministic and testable. **Rules are evaluated in the order listed
and the first match wins**, so a key cannot be two kinds:

| `kind` | rule |
|---|---|
| `empty` | ≥95% of values blank |
| `numeric` | ≥90% match `^\d+([.,]\d+)?$` |
| `identifier_like` | ≥70% are ≤32 chars and contain a digit |
| `prose` | mean word-tokens per value ≥5 **and** mean chars-per-token ≤12 |
| `short_text` | everything else |

### 2. Identifier discovery by shape — `profiler/stats/shapes.py`

*Answers:* what identifier formats actually exist, as opposed to the ones we guessed?

Round 1 counted tokens matching regexes written in advance. This inverts it: histogram
the character-class shape of every digit-bearing token across `title`, `description`,
`solutions` and `customData`, ranked by frequency, recording which columns each shape
occurred in. If codes are written `MOT-4711` or `07.1234.556`, the shape surfaces and we
discover the format instead of assuming it.

Only shapes with ≥`min_frequency` occurrences are emitted, capped at the top 50, plus a
count of shapes suppressed — rare shapes are where unusual values sit.

### 3. `vehicleModelId` in `dimension_hints`

*Answers:* can we derive a model-family proxy without the client's hierarchy?

Round 1 found `vehicleModelId` is an opaque numeric FK — a few dozen distinct values, zero
families inferred — which killed the prefix-based family proxy and blocked §5's
family-match boost. We cannot recover names, but we can recover *behaviour*: per model
ID, the top non-rare vocabulary of its tickets. Models sharing hydraulics vocabulary are
plausibly one family. `dimension_hints` already does exactly this for `categoryId`, so
this is a one-line change to the column list.

### 4. Cluster characterisation — `clusters.largest`

*Answers:* what is the dominant near-duplicate group (a large share of the corpus)?

For clusters with ≥`min_frequency` members, emit size, share, and floored,
entity-swept top tokens — capped at the 20 largest, plus a count of qualifying clusters
omitted. That decides whether the group is a template to exclude, an
auto-generated type needing its own lane, or the most valuable recurring fault in the
corpus.

### 5. Missingness over time — `temporal.fill_by_month`

*Answers:* is the high missing-description rate (about a third of tickets) a workflow reality or a system change?

Per-month non-empty rate for `description` and `solutions`. Flat across all months means
workflow; a step at a date means a system change, and recent data may be materially
better than the corpus average — which would change the eval holdout design.

## Safety controls

The existing invariant is unchanged: every emitted string is an allowlisted shape, or a
token clearing `MIN_FREQ` **and** the entity sweep. These controls extend it to the new
emission paths.

### Key names need a presence floor, not a token floor

`customData` is *custom* — the field most likely to carry client-specific naming — and a
key name is not a corpus token, so the existing floor does not apply to it at all. A
structural key appears in a large share of rows; a bespoke one in a handful.

**A key name is emitted only if the key is present in ≥`min_frequency` rows AND in ≥1%
of total rows**, then passed through the entity sweep. The absolute floor is the main
control; the 1% guard covers small corpora. Suppressed keys are counted, never named.

### Shapes get a closed, schema-enforced alphabet

New `$def`, applied in `schema.json` and re-checked in `selfcheck`:

```json
"shape": { "type": "string", "pattern": "^[ALaD_\\-./:#]{1,16}$" }
```

`A`/`L` upper, `a` lower, `D` digit, `_` whitespace, `-./:` preserved separators, `#`
everything else. No letter or digit survives. This generalises the existing
`SHAPE_CONTAINS_DIGITS` check into a structural guarantee.

**`identifiers.shape_of` is tightened to this alphabet**, since it currently passes
arbitrary punctuation through unchanged. Both existing shape tests (`ADDDD`, `AL-DDDD`)
still pass; only exotic punctuation changes, mapping to `#`.

### Never shape prose; cap shape length

A character-class shape preserves word lengths and punctuation positions — `Aaaa_Aaaaa`
for a two-word name. Over a long value that is a fingerprint, and fingerprints are
invertible against a candidate list.

**Values longer than 64 characters are not shaped**; they increment a `long_value_count`
instead. Shapes are truncated at 16 characters, matching the schema pattern. Per key,
only shapes with ≥`min_frequency` occurrences are emitted, top 10 by frequency, plus a
count of shapes suppressed.

### Only characterise large clusters

Clusters with fewer than `min_frequency` members are not characterised. A three-ticket
cluster's "top tokens" is a summary of three tickets: each token clears the corpus floor
individually, but the combination narrows. We only care about large clusters anyway.

### Every new emission routes through `selfcheck`, plus a catch-all

Per-section checks cover key names, shapes, cluster tokens and the new dimension column.
Then a **final catch-all** walks the entire profile. It must classify **both dict keys
and string values** — an earlier draft covered only values, and validating that draft
against the round-1 artifact rejected 887 legitimate strings, most of them dict keys like
`p50`, `sha256`, `2021-03` (a month key) and the cluster-size buckets.

**A dict key is blessed if it is:**

1. a key declared for that object in `schema.json` — the schema is already the authority
   on legitimate structure, and `additionalProperties: false` at the top level means an
   unknown section fails validation before it reaches here
2. a column name, for the objects the schema keys by column (`per_field`,
   `dimension_hints`, `temporal.fill_by_month`)
3. a structural pattern: `^p\d+$` or `max` (quantiles), `^\d{4}-\d{2}$` (months),
   `^\d+$` (cluster-size buckets)
4. a `customData` key name that passed the presence floor and the entity sweep

**A string value is blessed if it is:**

1. a column name (`EXPECTED_COLUMNS` ∪ `columns_found`)
2. a shape matching the closed alphabet
3. a token present in a frequency-floored, entity-swept list
4. a floored, entity-swept value at one of these paths: `per_field.*.top_values[].value`,
   `dimension_hints.*[].id`, `custom_data.keys[].key`
5. an author-written literal at an explicitly exempted path: `schema_version`,
   `source.encoding_detected`, `source.delimiter`, `source.sha256`, `source.filename`,
   `clusters.method`, `model_designations.inferred_family_rule`,
   `multi_fault_estimate.heuristic`, `solutions.junk_taxonomy[].pattern`,
   `solutions.cardinality.detected_separator`, `identifier_grammars[].kind`,
   `identifier_grammars[].regex`, `custom_data.format`, `custom_data.keys[].kind`,
   `selfcheck.checks[]`, `selfcheck.warnings[]`

The Bug 5 protection survives this widening: categories 4 and 5 are enumerated **by
path**, so a new section emitting strings at a **new** path matches nothing and aborts.
Adding a section therefore forces an explicit decision about how its strings are
protected — which is precisely the decision that was never made for
`dimension_hints[].id`.

**On failure this aborts the run** — `SafetyViolation`, exit 2, nothing written, schema
path to stdout and the value to the quarantine detail log. That is consistent with every
other safety violation, and it is the behaviour that would have caught the
`dimension_hints[].id` hole automatically instead of relying on someone thinking to look.
The risk of aborting a real window for a benign unblessed string is carried by
`make window-a-rehearsal`, which runs the identical code path on synthetic data.

### `source.filename` stops depending on operator discipline

The plan's leak table states "`source.filename` is hashed, not echoed"; the code echoes
it. Today the only mitigation is the runbook instructing a rename — discipline, which
this project refuses to rely on everywhere else.

**Emit `filename` only if it equals `export.csv`; otherwise emit the literal
`"<non-conforming>"` and add a warning.** The sha256 already provides reproducibility.

## Deliberately deferred

**No tokens are emitted from `customData` in v2.** The driving question — are the error
codes there? — is answered entirely by shapes. Token emission would add no answer while
adding the only genuinely new exposure in the design: free text from the least understood
field, protected by nothing stronger than `description` receives.

`kind` is still classified and reported, so if the key inventory reveals a prose key worth
mining, that becomes a v3 decision made *with* the inventory rather than blind.

## Testing

### The adversarial stand-in

`tests/conftest.py::build_standin` currently leaves `customData` empty, so none of this
code would be exercised against anything resembling the real field. It grows a synthetic
`customData` planting one instance of every failure mode:

| Planted | Expected |
|---|---|
| well-formed error-code key | surfaces; dominant shape `ADDDD` |
| numeric key | `kind: numeric`; shapes only |
| free-text key | `kind: prose`; **no tokens emitted** |
| key whose values are names and phone numbers | values never appear anywhere |
| key present in ~0.3% of rows | suppressed by the presence floor; counted |
| key *named* after a person or company | suppressed by the entity sweep |
| malformed JSON in a share of rows | counted in `parse_success_rate`; never echoed |
| value with exotic punctuation | shape maps it to `#`; alphabet holds |
| value longer than 64 characters | not shaped; `long_value_count` increments |

One test then greps the **entire emitted artifact** for every planted secret and asserts
none appears — the same shape as the existing
`test_profiler_output_never_echoes_a_source_value`.

### Red-green on the catch-all

Inject an unblessed string into an otherwise-valid profile; assert `SafetyViolation`,
assert the message carries the schema path and not the value. Then disable the check and
assert the test fails. Same discipline as the traceback-leak tests, which caught a real
regression precisely because they were red-green verified.

A property test on the shape alphabet: for arbitrary input, no character of the input
survives into the output except permitted separators.

### Rehearsal integration

`make window-a-rehearsal` gains assertions for the new sections — `custom_data.format`
parsed, key inventory non-empty, discovered shapes present, `clusters.largest`
populated. Because the rehearsal runs the same code path as the window, a benign miss in
the blessing list surfaces on the workstation.

### The human review gate must keep pace

`profile.json` is reviewed on the box before anything crosses. If sections are added to
the JSON without surfacing them in `profile_report.md`, that review silently degrades to
covering a fraction of the artifact. `emit.write_report` therefore grows with the schema:
`customData` keys with fill rates and dominant shapes, the top discovered identifier
shapes, and the large-cluster summaries.

## Acceptance criteria

- [ ] `make test lint` green; the round-1 suite still passes unchanged.
- [ ] `make window-a-rehearsal` green, including assertions for all new sections.
- [ ] The adversarial stand-in exercises every row of the table above, and the
      whole-artifact grep finds none of the planted secrets.
- [ ] The catch-all is red-green verified: it fails the suite when disabled.
- [ ] `shape_of` output is alphabet-conformant under a property test.
- [ ] A non-`export.csv` filename yields `"<non-conforming>"` plus a warning.
- [ ] `schema_version` is `"2"` and the emitted profile validates against `schema.json`.
- [ ] **The catch-all accepts the round-1 artifact unchanged.** Validating an earlier
      draft of it against `local/artifacts/profile.json` rejected 887 legitimate strings,
      which is how the dict-key gap was found; a test must pin that it now passes, so the
      blessing rules cannot silently drift away from what the profiler actually emits.
- [ ] `profile_report.md` surfaces every new section.
- [ ] Sealed image rebuilt; offline import and German dictionary verified inside it.

## What this pass cannot answer

Two questions remain genuinely client-only, and should go to the post-vacation call
regardless of what this pass finds:

- **The `vehicleModelId` values → model → series → family mapping.** The vocabulary
  proxy above is a substitute for ranking purposes, not a replacement for the hierarchy.
- **Whether a fresher export exists.** The data ends many months before
  profiling, so the "most recent N months" eval holdout is already historical.

And one limit of testing itself: the suite proves the code is correct against *our* idea
of `customData`. If the real field is XML, proprietary, or unstructured, the run returns
`format: "unknown"` with a low parse rate. **That is a valid and informative result, not
a failure** — it still tells us the error codes are not in a parseable structure there.
