# 0033. A catalog is released only with a passing leak report for the exact bytes of the draft

Status: Accepted
Date: 2026-10-21

## Context

The catalog is the only artifact that carries LLM-written text derived from real tickets across the
airlock. The guard checks the catalog alone, but the leaks that matter are relations between the
catalog and the corpus: a word only one dealer ever wrote, a name that sits in an identity column,
a sentence lifted from some other ticket. The operator edits the draft by hand on the box, so a
report produced before an edit says nothing about the edited file.

## Decision

`catalog leakcheck` runs four checks against the whole corpus: a vocabulary floor (every distinct
recipe word occurs in at least k tickets, min dealers and min vehicles), an identity denylist (no
recipe word is or contains a token from the identity columns), a corpus-wide verbatim check (no
5-word run of a recipe string occurs in any ticket) and the closed-allowlist guard. Its report holds
check names, pass or fail, counts and opaque recipe ids, never a word or a value, and is bound to
the SHA-256 of the draft's canonical JSON (sorted keys, compact separators), so any change of
content makes the report stale (`STALE_REPORT`), while a whitespace-only or key-order-only edit does
not. `catalog release` refuses unless the report passed for that draft and the guard accepts the
catalog (`catalog.release_gate`). The gate is an operator requirement, hard minimums apply
(k at least 50, 5 vehicles, 5 dealers), `--allow-weak-floor` can never release, and every check
must be present in the report. The same checks also run inside
`catalog.build`, so offending recipes are rejected early. Any edit to the draft invalidates the
report and requires `leakcheck` again. A test requires every catalog in `local/released` or
`local/artifacts` to have a valid sibling report (it skips if there is none).

## Consequences

- The release cannot be forced by editing the draft after checking it.
- The identity denylist is deliberately strict (the example in the `leakcheck.py` docstring: a
  dealer called "Service Nord" puts "service" and "nord" on the list and drops any recipe using
  them). A rejected recipe costs coverage; a leaked name
  costs the release. Strict was chosen.
- Together with the strict vocabulary floor this lowers the yield of recipes (ADR 0031).
- The checks are tested with planted leaks and mutation suites, which is the evidence they work;
  they find relations the guard cannot, but not every possible disclosure.

## References

- `catalog/leakcheck.py`, `catalog/release_gate.py`, `catalog/verbatim.py`, `catalog/scrub.py`
- Commits a6fcd2f, b60c974, d2a51e7, ba6139b, ecd49d4
- `docs/superpowers/specs/2026-10-21-window-e-design.md`
