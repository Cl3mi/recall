# 0036. The insight HTML view is a single local offline file and is never hosted

Status: Accepted
Date: 2026-10-13

## Context

A guarded `report.json` is readable by an AI, but a person deciding the corpus strategy needs
charts, filters and a builder for trying filter paths. The report is derived from NDA data. Even
with floors and guards, it is NDA-derived, so a hosted page (for example a published artifact)
would send it to a third party and the page could load remote scripts or leak through the network.
The page also cannot recompute anything: tickets never leave the airlock, so every number must come
from the report.

## Decision

`python -m insight.view report.json report.html` writes one self-contained page with no network
access (a content security policy forbids it), with values reaching the DOM only through
`textContent`, never `innerHTML`. It runs the guard first and refuses a report the guard rejects. It
is never published as a hosted artifact (the filter-tree spec: the page "stays a local file",
NDA-derived). The corpus model lives in `view_model.js` and is inlined at render so the page stays
one file; the builder is still in `view.py`, because the spec's separate `view_lab.js` and the
later stages (composer, saved trees, exploration, comparison) were not built. The model is tested in node (golden, truth,
smoke and in-page check harnesses), including a "no cube, no change" golden test that runs the
pre-cube model beside the current one.

## Consequences

- The page can be opened anywhere offline and carries no remote dependency or tracking.
- It can only slice what the report already split that way; filters on dimensions without a joint
  split change size but show the overall quality rate, marked with an asterisk, and every card says
  which filters it responds to.
- Browser, stub-DOM and node tests are an extra test toolchain (JavaScript in a Python repo).
- Sharing the view with others means sending the file rather than a link; a hosted copy is ruled
  out by the "local file" rule.
- The estimator's certainty grades (exact, bounded, estimated) are a related view decision that has
  no ADR of its own (see ADR 0034 for how verdicts and suggestions use them).

## References

- `docs/STATE.md` (HTML view, filter tree v2 stages 1-2)
- `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md`
- `insight/view.py`, `insight/view_model.js`, `tests/integration/insight_view_*.js`
