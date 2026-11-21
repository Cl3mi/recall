# 0017. Contact name and phone fields are never read, indexed, embedded or surfaced

Status: Accepted (interim; the final PII treatment is still deferred)
Date: 2026-08-17

## Context

`ansprechpartner` and `ansprechpartner-tel` (contact name and phone) are present in most real
tickets and always filled when present. Their final treatment (drop at ingest, mask before embedding,
or index without surfacing) is a product decision that was not made during M2. The brief lists contact and
person fields as PII that must never be embedded and are access-controlled on display.

## Decision

Until the treatment is decided, nothing downstream reads, indexes, embeds or surfaces these fields.
`insight.extract` never carries them across the row boundary (so `index.build` cannot see them),
the M3 spec states that the `customData` parser feeds the index `fehlercode` and nothing else
from that envelope, and the fixture still contains both fields with obviously fake values so the
structure stays faithful and the decision stays testable.

## Consequences

- No retrieval feature or display can leak a contact name or phone by accident.
- A technician cannot be shown who raised a ticket, and no "same contact" signal exists.
- Names and phones can still appear inside free text; the PII redaction in the cleaning pipeline
  (ADR 0013) and the entity sweeps (ADR 0023) are the controls there, and a deny-list of names
  cannot be complete.
- The deferral must be resolved before any user-facing display exists.
- The same rule is why the Window B roster check cannot trace names (ADR 0030): names exist only
  inside `customData`, which is not to be read. `insight.extract` also reads a few other envelope
  fields (Baugruppe and date descriptors), so "`fehlercode` and nothing else" is the M3 spec's
  wording for the index, not a statement about every extractor.

## References

- `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md` ("Deferred: PII treatment")
- `docs/superpowers/specs/2026-10-11-m3-hybrid-retrieval-design.md` section 1 ("PII")
- `insight/extract.py`
