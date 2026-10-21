# Cluster structure — one problem, many resolutions

**Status:** approved 2026-08-19
**Closes:** M2 finding 8 (`docs/STATE.md`)
**Supersedes:** the *Cluster structure* row of
`docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md`, which said "LLM
writes themes and variants, code controls counts" without saying *which field* varies.

## The problem

The fixture has no near-duplicate structure at all. Measured on the band-rejected
2026-08-19 fixture (`local/fixtures/export.bands-rejected-2026-08-19.csv`):

| | |
|---|---|
| intended multi-member groups | 51 |
| groups that actually cluster | **1** (a pair) |
| group 0 (the largest group, about a seventh of the fixture) | spread over **143** clusters, purity 0.06 |
| member-pair token Jaccard | 0.139 / 0.259 / 0.161 — needs **≥ 0.70** |

Bands came out with singletons and mid roughly 0.8 / 0.2 and large **0.0000**, against real
bands of roughly 0.76 / 0.10 / 0.14 (singletons / mid / large). The mass did not vanish; groups fragmented into the mid and
singleton bands.

**Cause.** Clustering is `minhash-lsh(num_perm=128)` over the *token set* of cleaned
`title + description`, threshold 0.7 — two tickets cluster only if they share ~70% of their
combined vocabulary. The generator's prompt demands *"Jedes Ticket muss einen
unterschiedlichen Loesungsweg beschreiben — andere Diagnose … Nicht dieselbe Loesung anders
formuliert"*, so the model varies the **problem statement** too. Genuinely different problem
text is not a near-duplicate. The two requirements are mutually exclusive and the model was
obeying the one it was given.

This matters more than a band number. `PROJECT_BRIEF.md` §8: cluster structure is what gives
"free gold labels — a real eval harness the remote agents can iterate against. Without it,
dedup logic, the frequency signal, and every recall metric are untestable." M3 has nothing to
measure recall@10 or MRR against until this is fixed.

## The decision

**Within a group, the problem text is shared and the resolutions differ.**

This is not a compromise, it is what the corpus actually is. The real largest cluster's top
tokens are handover-slip vocabulary shared across a large number of tickets — repeated
handover boilerplate. Finding 3 already established that cluster "is a form, not a fault". Recurring
faults behave the same way: two technicians logging the same problem write similar problem
text, and the variety lives in what they *did about it*.

It also matches the retrieval architecture already chosen in `PROJECT_BRIEF.md` §6.1 — the
primary vector represents the **problem**, a separate vector the **solution**, because
"mixing the solution into the primary vector dilutes it". Clustering runs over
`title + description`: the problem. Variety belongs in `solutions`.

## No information is lost — the binding requirement

The concern this design must answer: moving variety out of the description must not drop
anything the application needs downstream.

`PROJECT_BRIEF.md` §5 enriches each ticket into canonical problem, symptoms, error codes,
components, root cause, resolution steps, resolution type, solution_quality. Where each comes
from, after this change:

| Enriched field | Source | Under this design |
|---|---|---|
| canonical problem, symptoms | `title` + `description` | Shared within the group — **correct**, they *are* the same problem |
| root cause, resolution steps, resolution type | `solutions` | Per ticket, and distinct — the variety lives here |
| error codes | `customData.fehlercode` | Per row, untouched by this change |
| components | `customData.baugruppe` | Per row, untouched by this change |
| solution_quality | `solutions` | Per ticket, unchanged |

The one thing genuinely at risk is the per-ticket **diagnosis**, which today sits in `BEFUND`.
It is not dropped, it is relocated: **each `LOESUNG` must state its own diagnosis as well as
its repair.** That is a hard requirement on the prompt and is asserted by a test, not left to
the model's discretion. A resolution that says only "Filter getauscht" has lost the diagnosis;
one that says "Druckabfall auf verschmutzten Filter zurückgeführt, Filter getauscht" has not.

**This design retains more than the current one for roughly a third of rows.** Fill-by-year
blanks the description of about a third of group-0 rows (faithful — the real corpus was measured with
those blanks present). Today a blanked row loses its unique diagnosis outright, because the
diagnosis was only ever in the description. Under this design the diagnosis survives in
`solutions`, which is not blanked at the same time for most rows.

Rows where *both* description and solution are blanked keep only a title. That is faithful to
the real corpus and is unchanged by this design.

## Design

**Prompt** (one per group, per batch). Asks for one problem and N resolutions:

```
Fehlerbild: <theme>
Serie <series>

Schreibe EIN Fehlerbild und dazu <N> unterschiedliche Loesungswege.
Alle Tickets beschreiben DASSELBE Problem mit demselben Wortlaut.
Nur der Loesungsweg unterscheidet sich - andere Diagnose, anderes Ersatzteil,
andere Reihenfolge. Nicht dieselbe Loesung anders formuliert.
Jeder Loesungsweg nennt SEINE EIGENE Diagnose und die Reparatur.

TITEL: <kurz>
BEFUND: <2-3 Saetze>
LOESUNG 1: <2-3 Saetze>
LOESUNG 2: <2-3 Saetze>
...
```

The word "unterschiedlich" is retained deliberately:
`test_the_prompt_asks_for_different_approaches_not_rewordings` pins it, and its intent — that
variants must not be rewordings — still holds. It now applies to the resolutions.

**Parsing** returns one problem (title, description) plus an ordered list of resolutions. A
record without a title is still not a ticket, per finding 4.

**Group assembly.** Every member gets the group's shared title and description, and its own
resolution. Finding 7's batching is preserved: the ask stays capped at `GROUP_BATCH` and the
two-top-up bound (`TOPUP_ATTEMPTS`) is unchanged, but **later batches reuse batch 0's problem
text**. Without that, an 11-batch group would produce 11 different problem statements and
fragment exactly as it does today. Code controls the structure; the model writes the variants.

**Singletons are unchanged.** They must *not* cluster and currently do not. `_prompt_distinct`
and `SINGLETON_BATCH` stay as they are, and their 46 cached responses stay valid.

**Padding** is unchanged in mechanism, and its byte-identical padded tickets now agree with the
design rather than fighting it — though the projected padding is 12, all of it in singleton
batches.

## Expected result

Bands become arithmetic rather than hope, because a group is now one cluster by construction:

| band | real | expected |
|---|---|---|
| singletons | about three quarters | the same share, by construction |
| mid (2–49) | about a tenth | the same share, by construction |
| large (≥50) | about a seventh | the same share, by construction |

All three inside the design doc's ±1.0 point tolerance. Every other measured dimension already
passes and must not regress: `customData` field shares 26/26, `fehlercode` shape mix 10/10,
fill-by-year 12/12, descriptor quantiles p90–p999 all 21.

## Stated costs

- **Problem text is byte-identical within a group**, so cluster purity is 1.00 where the real
  corpus has some noise. This errs toward clusters being *detectable*, which is what the eval
  harness needs. §8 injects formatting noise programmatically afterwards; that is a separate
  step and not in this design.
- **Description length distribution flattens within a group** — every row of the largest group shares one length.
  Not among `verify`'s checks nor the acceptance criteria, but it is a real fidelity loss and
  should not be discovered later as a surprise.
- **Regeneration cost:** every variants prompt changes, so ~60 new model calls. The 46
  singleton batches stay cached.

## Testing

- A group's members share `title` and `description`, and each carries a distinct, non-empty
  solution.
- Problem-text token Jaccard within a group is ≥ 0.70 (it clusters) **while** the mutual
  Jaccard between its solutions is low (they are genuinely different, not rewordings). One
  pair of assertions pins both halves of the design.
- A multi-batch group still yields one shared problem across all batches.
- The two-top-up bound and per-group `groups_short` accounting are unchanged.
- Acceptance: `test_the_generated_fixture_profiles_like_the_real_corpus` must pass on the
  regenerated fixture. A drift means the planner or the prompt is wrong, not the tolerance.
