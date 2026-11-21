# 0034. The insight report releases floored cells with a suppression ledger and accepts measured subtraction

Status: Accepted
Date: 2026-10-16

## Context

The insight report (Window D) tells the strategy what the corpus contains: where tickets come from,
how formats and fill vary over time and how many tickets are usable. The filter-tree view wanted
exact numbers for combinations of category, Baugruppe, model and field gates, but the first quality
section was split one dimension at a time, so any combination was an independence estimate. A joint
"cube" of 14 cuts gives exact numbers but, with overlapping cuts, a reader can subtract a released
cell from a coarser one and recover a withheld cell below the floor. Complementary suppression with
an LP gate was prototyped and did not converge on the stand-in: the quality section's inner counts
already pin cells once any joint cut exists.

## Decision

Two decisions from different dates sit here. The floor and ledger come from the insight report
design (2026-10-11, see also ADR 0023): every value and cell at k = 50 or more, with a suppression
ledger recording what was withheld and why, so an empty result differs from a suppressed one. The
cube is the operator's decision of 2026-10-16, taken after the alternative was prototyped. Release
the cube as a lattice
of floored cuts (every combination of up to three of four axes), with a closed-literal guard that
requires each cell to have count at least k and each axis value to be one that
`quality.by_dimension` already released. Subtraction is accepted on the same grounds as the earlier
accepted-residuals amendments of the stage-1 spec (what can be worked out is a count below k, never
a ticket or a person) and is measured instead of gated: an LP-based reader estimate of how many
withheld cells the cube newly pins (no bound in either direction) is published as
`quality.cube.measurement`, with a `stopped` field (`budget` or `solver`), capped by a soft
`--cube-budget` (the window pins 1800 s). Separately, report v2 (2026-10-12) decided that dealers,
customers, creators, assignees and persons are concentration numbers only and that no such id is
ever released.

## Consequences

- The view can grade each count exact, bounded or estimated. Suggestions are ordered on the worst
  case while a cube exists; verdicts are computed on the estimate, and a gain whose worst case does
  not rise is shown as an "uncertain gain". The worst case never turns a verdict into a loss
  (filter tree v2 spec, amendment A3).
- Some withheld cells are derivable. On the stand-in, 24 of 80 were newly derivable; on the real
  run the measurement stopped on its budget after checking most cells and only a small share of
  those were newly derivable, so the real figure is partial.
- A single run took about 32 minutes on the real export, and a new section needs a window to
  produce real numbers.
- `scipy` became a declared dependency (already locked through `datasketch`); `uv.lock` was edited
  by hand because `uv` is not installed on the workstation and still needs `uv lock --check`.
- Every new entry list must be declared in the guard or the real run is refused (ADR 0023).

## References

- `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md` (amendment A1)
- `docs/superpowers/specs/2026-10-12-insight-report-v2-design.md`
- `insight/cube.py`, `insight/guard.py`; commits d36ee22, 6407026, c020891, b07bf50
