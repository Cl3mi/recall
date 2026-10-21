# Filter tree v2, stage 1: the joint quality cube — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `quality.cube` to `report.json`: 14 floored cuts over category × Baugruppe × model × gate pattern, plus a published, time-boxed measurement of how many withheld cells the cube newly lets a reader work out. The filter tree (stages 2–5) can then give exact numbers for common branches.

**Architecture:**
- A new `insight/cube.py` builds the cells from the same tickets and grades as `insight/quality.py`. Each cell has the shape of `quality._group`, and cells under k are withheld through `release.release`.
- The same module measures derivability. It runs an LP over every combination of axis values, before and after adding the cube, using scipy's HiGHS solver.
- `insight/guard.py` gains closed literals, a released-field path and a cross-check that the cube names only values `quality.by_dimension` released.
- The report builder computes grades once and passes them to both sections.
- The CLI gains `--cube-budget`, and the Window D command pins it at 1800.

**Tech Stack:**
- Python 3.12, scipy 1.18 (`linprog`, method `highs`, sparse matrices) and numpy.
- Tests: pytest, run with `../../.venv/bin/python -m pytest`; `uv` is not installed on this workstation.
- ruff, line length 100.

**Spec:** `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md`, section 1 and amendment A1.

**Verified before writing:** every code block below was applied in a throwaway worktree. The insight tests and the full suite passed there; the two Postgres files that need `PG_DSN` were excluded. ruff was clean. The measurement was timed on synthetic tickets of the real shape (tens of thousands of tickets, a handful of categories, about ten Baugruppen, a few dozen models): one pass took 869 s. That is why the budget defaults to 1800 s and the window pins it.

## Binding constraints (read first)

- **Never read anything under `local/quarantine/` or `<export-dir>/`.** Nothing in this plan needs real data. The stand-in in `tests/insight_standin.py` is synthetic.
- A harness hook blocks any Bash command whose text mentions the export's file extension. Tests build the stand-in internally, so run them with plain `pytest` commands. Edit files that contain the export's file name with the Edit tool, never with `sed` in Bash. If a command is blocked, ask the operator to run it; do not work around the hook.
- Run Python as `../../.venv/bin/python` from the worktree root. Tests: `../../.venv/bin/python -m pytest -q <files>`. Lint: `../../.venv/bin/ruff check . && ../../.venv/bin/ruff format --check .`.
- The two Postgres test files need `PG_DSN`. Exclude them from full runs with `--ignore=tests/integration/test_german_fts.py --ignore=tests/integration/test_migrate.py`.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `insight/release.py` | modify | two new released fields, `cat` and `baug`, swept as codes |
| `insight/quality.py` | modify | `build` accepts precomputed grades |
| `insight/cube.py` | **create** | axes, cuts, cells (`build`); the derivability measurement (`measure`) |
| `insight/guard.py` | modify | keys, literals, released path, withheld section, value cross-check |
| `insight/report.py` | modify | grades once; cube and measurement into `quality` |
| `insight/__main__.py` | modify | `--cube-budget`, one more output line |
| `pyproject.toml` | modify | `scipy` declared (it is already locked, through `datasketch`) |
| `infra/profiler/window.sh` | modify | the sealed command pins `--cube-budget 1800` |
| `infra/profiler/rehearse-window-d.sh` | modify | checks the flag, the output line and the cube section |
| `tests/unit/test_insight_cube.py` | **create** | cube and measurement unit tests |
| `tests/unit/test_insight_{release,quality,guard}.py`, `tests/unit/test_window_d_contract.py`, `tests/integration/test_insight_{report,cli}.py` | modify | as each task says |
| `docs/airlock-runbook.md`, `docs/STATE.md` | modify | the window takes longer; what was built |

---

### Task 0: Branch and baseline

**Files:** none

- [ ] **Step 1: Branch from the current HEAD**

```bash
git switch -c feat/insight-cube
```

- [ ] **Step 2: Record the baseline**

Run: `../../.venv/bin/python -m pytest -q --ignore=tests/integration/test_german_fts.py --ignore=tests/integration/test_migrate.py 2>&1 | tail -3`
Expected: `0 failed` (note the passed/skipped counts for the final check).

---

### Task 1: The cube's category and Baugruppe axes are released fields

**Files:**
- Modify: `insight/release.py` (`_SWEEPS`)
- Test: `tests/unit/test_insight_release.py`

- [ ] **Step 1: Write the failing test.** Append to `tests/unit/test_insight_release.py`:

```python
@pytest.mark.parametrize("field", ["cat", "baug"])
def test_the_cube_axes_are_swept_as_codes(field):
    assert not release.flagged(field, "40112")
    assert release.flagged(field, "Huber GmbH")
    assert release.flagged(field, "info@example.de")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_release.py -k cube_axes`
Expected: FAIL with `KeyError: 'cat'`.

- [ ] **Step 3: Add the sweeps.** In `insight/release.py`, extend `_SWEEPS`:

```python
    "prefix": _prefix_flagged,
    "shape": _shape_flagged,
    # The joint quality cube's category and Baugruppe axes (insight.cube): ids, swept as codes.
    "cat": _code_flagged,
    "baug": _code_flagged,
}
```

- [ ] **Step 4: Run the release and guard tests**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_release.py tests/unit/test_insight_guard.py`
Expected: all pass. No report uses the keys `cat` or `baug` yet, so the guard is unaffected.

- [ ] **Step 5: Commit**

```bash
git add insight/release.py tests/unit/test_insight_release.py
git commit -m "feat(release): cat and baug are released fields, swept as codes, for the quality cube"
```

---

### Task 2: `quality.build` accepts precomputed grades

The cube needs the same grades. Grading clusters every solution, which is the slow part, so it must run once.

**Files:**
- Modify: `insight/quality.py` (`build`)
- Test: `tests/unit/test_insight_quality.py`

- [ ] **Step 1: Write the failing test.** Append to `tests/unit/test_insight_quality.py`:

```python
def test_build_reuses_grades_it_is_given(tickets):
    graded = quality.grades(tickets, K)
    assert quality.build(tickets, K, graded) == quality.build(tickets, K)
```

Also change the existing defaults test, which pins the whole tuple, so it pins `k` only:

```python
def test_k_defaults_to_the_release_floor():
    assert quality.build.__defaults__[0] == release.K
```

- [ ] **Step 2: Run them and watch the first fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_quality.py -k "reuses or defaults"`
Expected: `test_build_reuses_grades_it_is_given` FAILS with `TypeError: build() takes from 1 to 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement.** In `insight/quality.py` replace the first two lines of `build`:

```python
def build(tickets: list[Ticket], k: int = release.K, graded: list[Grade] | None = None) -> dict:
    """`graded` is `grades(tickets, k)` when the caller has it already: the cube needs the same
    grades, and grading clusters every solution, which is the slow part."""
    graded = grades(tickets, k) if graded is None else graded
    pairs = list(zip(tickets, graded, strict=True))
```

- [ ] **Step 4: Run the quality tests**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_quality.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add insight/quality.py tests/unit/test_insight_quality.py
git commit -m "refactor(quality): build takes precomputed grades so the cube grades once"
```

---

### Task 3: `insight/cube.py` builds the floored cuts

**Files:**
- Create: `insight/cube.py`
- Create: `tests/unit/test_insight_cube.py`

- [ ] **Step 1: Write the failing tests.** Create `tests/unit/test_insight_cube.py` with exactly this content (the measurement tests follow in Task 4):

```python
import pytest

from insight import crosstab, cube, origin, quality, release
from insight.extract import Ticket

K = 3


def mk(i: int, **kw) -> Ticket:
    """A ticket whose problem text shares no word with any other."""
    base = dict(
        title=f"unikat{chr(97 + i // 26)}{chr(97 + i % 26)}",
        description="",
        solutions="",
        baugruppe=(),
        serial=None,
        model=None,
        created_year=None,
        vehicle_year=None,
    )
    base.update(kw)
    return Ticket(**base)


def section(tickets, k=K):
    graded = quality.grades(tickets, k)
    out = quality.build(tickets, k, graded)
    out["cube"] = cube.build(tickets, graded, out["by_dimension"], k)
    return out


def origin_section(tickets, k=K):
    return {
        "baugruppe": origin.baugruppe(tickets, k),
        "baugruppe_model_year": crosstab.baugruppe_model_year(tickets, k),
    }


def cut(built, name):
    return next(c for c in built["cube"]["cuts"] if c["axes"] == name)


def test_the_cuts_are_every_combination_of_up_to_three_axes():
    assert len(cube.CUTS) == 14
    assert len(set(cube.CUT_NAMES)) == 14
    assert all(1 <= len(c) <= 3 for c in cube.CUTS)
    assert "cat+baug+model+gates" not in cube.CUT_NAMES


def test_axis_values_are_the_released_values_then_the_sentinels():
    by_dimension = {
        "categoryId": {"values": [{"value": "40111"}, {"value": "40110"}]},
        "baugruppe": {"values": [{"value": "5"}]},
        "model_id": {"values": []},
    }
    u = cube.universes(by_dimension)
    assert u["cat"] == ("40110", "40111", "_other", "_none")
    assert u["baug"] == ("5", "_other", "_none")
    assert u["model"] == ("_other", "_none")
    assert len(u["gates"]) == 8 and u["gates"][0] == "000" and u["gates"][-1] == "111"


def test_a_ticket_counts_once_per_baugruppe_value_and_unreleased_ids_become_other():
    u = {"cat": ("_other", "_none"), "baug": ("12", "5", "_other", "_none"), "model": ("_none",)}
    u["gates"] = ("000",)
    both = cube.atom_of(mk(0, baugruppe=("5", "12", "5")), u)
    assert cube.keys_of(both, ("baug",), u) == [("12",), ("5",)]
    rare = cube.atom_of(mk(1, baugruppe=("99",)), u)
    assert cube.keys_of(rare, ("baug",), u) == [("_other",)]
    none = cube.atom_of(mk(2), u)
    assert cube.keys_of(none, ("cat", "baug"), u) == [("_none", "_none")]


def test_the_gate_pattern_reads_error_code_description_serial_in_that_order():
    u = {"cat": ("_none",), "baug": ("_none",), "model": ("_none",), "gates": ()}
    atom = cube.atom_of(mk(0, fehlercode="1234-5", serial="S1"), u)
    assert atom.gates == "101"
    assert cube.GATE_ORDER == "fehlercode+description+serial"


@pytest.mark.parametrize("field", ["cat", "baug", "model"])
@pytest.mark.parametrize("value", cube.SENTINELS)
def test_the_sentinels_pass_the_code_sweep(field, value):
    assert not release.flagged(field, value)


def test_a_cell_is_floored_like_every_released_group():
    tickets = [mk(i, category="40110", model="731015") for i in range(4)]
    tickets += [mk(4 + i, category="40111", model="731015") for i in range(2)]
    built = section(tickets)
    cells = cut(built, "cat+model")["cells"]
    assert [(c["cat"], c["model"], c["count"]) for c in cells] == [("40110", "731015", 4)]
    assert cut(built, "cat+model")["withheld"]["below_floor"] == {"distinct": 1, "rows": 2}
    assert all(c["count"] >= K for block in built["cube"]["cuts"] for c in block["cells"])


def test_a_cell_has_the_shape_of_a_quality_group():
    tickets = [mk(i, category="40110") for i in range(4)]
    cell = cut(section(tickets), "cat")["cells"][0]
    graded = quality.grades(tickets, K)
    expected = quality._group(zip(tickets, graded, strict=True))
    assert {k: v for k, v in cell.items() if k != "cat"} == expected


def test_cells_are_sorted_so_row_order_does_not_matter():
    tickets = [mk(i, category=c) for i, c in enumerate(["40111"] * 3 + ["40110"] * 3)]
    forward = section(tickets)["cube"]
    backward = section(tickets[::-1])["cube"]
    assert forward == backward
    assert [c["cat"] for c in cut({"cube": forward}, "cat")["cells"]] == ["40110", "40111"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_cube.py`
Expected: collection error `ImportError: cannot import name 'cube' from 'insight'`.

- [ ] **Step 3: Implement.** Create `insight/cube.py` with exactly this content:

```python
"""Spec 2026-10-16 (filter tree v2) section 1: the joint quality cube, so a branch of the filter
tree gets an exact number instead of an independence estimate.

Four axes - category, Baugruppe, model and a three-bit gate pattern (error code, description,
serial present) - and every combination of up to three of them is released as its own CUT. A cell
has the shape of `quality._group` and is floored like every released group: under k it is
withheld and counted in its cut's tally.

The axis values are exactly what `quality.by_dimension` released, so the cube names nothing the
report does not already name; anything else is `_other`, and a missing value is `_none`.

Overlapping cuts let a reader subtract one cell from another. That is accepted on the grounds of
amendment 8 of the stage-1 spec (a count below k is not personal data, and the report already
publishes inner counts of that kind) - amendment A1 of the filter tree v2 spec, taken after
complementary suppression was prototyped and did not converge. It is MEASURED instead:
`measure` counts the withheld cells the cube lets a reader pin exactly that the report
without the cube did not, and the number is published.
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from insight import origin, release
from insight.extract import Ticket
from insight.quality import FIELDS, Grade, _group

AXES = ("cat", "baug", "model", "gates")
GATES = ("fehlercode", "description", "serial")
GATE_ORDER = "+".join(GATES)
OTHER, NONE = "_other", "_none"
SENTINELS = (OTHER, NONE)
CUTS: tuple[tuple[str, ...], ...] = tuple(
    cut for n in (1, 2, 3) for cut in itertools.combinations(AXES, n)
)
CUT_NAMES = tuple("+".join(cut) for cut in CUTS)
# Where each axis takes its values from in the quality section.
SOURCES = {"cat": "categoryId", "baug": "baugruppe", "model": "model_id"}
# Random directions the measurement tries before a cell gets its own two LPs.
SCREEN = 12
# Seconds the measurement's exact LPs may take; the CLI's --cube-budget overrides it. Measured on
# synthetic tickets of the real shape (tens of thousands of tickets, a few dozen models): one pass took 869 s.
BUDGET = 1800.0

Axes = tuple[str, ...]
Key = tuple[str, ...]
Universe = dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Atom:
    """The finest grain the measurement reasons about. Never released."""

    cat: str
    ids: frozenset[str]  # Baugruppe axis values, never NONE: an empty set is "no Baugruppe"
    model: str
    gates: str
    pairable: bool = True  # at most origin.MAX_PAIR_IDS raw ids, so origin's pairs count it

    def order(self) -> tuple:
        return (self.cat, tuple(sorted(self.ids)), self.model, self.gates, self.pairable)


# Fields a cell reports whose value follows from the atom alone: each is one more equation.
ATOM_FIELDS: dict[str, Callable[[Atom], bool]] = {
    "fehlercode": lambda a: a.gates[0] == "1",
    "description": lambda a: a.gates[1] == "1",
    "serial": lambda a: a.gates[2] == "1",
    "model_id": lambda a: a.model != NONE,
    "baugruppe": lambda a: bool(a.ids),
}


def universes(by_dimension: dict) -> Universe:
    """Axis values: exactly what `quality.by_dimension` released, then the two sentinels."""

    def released(dimension: str) -> tuple[str, ...]:
        return tuple(sorted(e["value"] for e in by_dimension[dimension]["values"])) + SENTINELS

    out = {axis: released(source) for axis, source in SOURCES.items()}
    out["gates"] = tuple("".join(bits) for bits in itertools.product("01", repeat=len(GATES)))
    return out


def axis_value(value: str | None, universe: tuple[str, ...]) -> str:
    if not value:
        return NONE
    return value if value in universe and value not in SENTINELS else OTHER


def atom_of(ticket: Ticket, u: Universe) -> Atom:
    return Atom(
        cat=axis_value(ticket.category, u["cat"]),
        ids=frozenset(axis_value(i, u["baug"]) for i in ticket.baugruppe),
        model=axis_value(ticket.model, u["model"]),
        gates="".join("1" if FIELDS[g](ticket) else "0" for g in GATES),
        pairable=len(set(ticket.baugruppe)) <= origin.MAX_PAIR_IDS,
    )


def keys_of(atom: Atom, cut: Axes, u: Universe) -> list[Key]:
    """The cells of `cut` an atom counts in: one, or one per Baugruppe value it carries."""
    values = {
        "cat": (atom.cat,),
        "baug": tuple(sorted(atom.ids)) or (NONE,),
        "model": (atom.model,),
        "gates": (atom.gates,),
    }
    return list(itertools.product(*(values[a] for a in cut)))


def build(
    tickets: list[Ticket], grades: list[Grade], by_dimension: dict, k: int = release.K
) -> dict:
    """The `quality.cube` block, without the measurement (see `measure`)."""
    u = universes(by_dimension)
    atoms = [atom_of(t, u) for t in tickets]
    cuts = []
    for cut in CUTS:
        members: dict[Key, list[tuple[Ticket, Grade]]] = {}
        for ticket, grade, atom in zip(tickets, grades, atoms, strict=True):
            for key in keys_of(atom, cut, u):
                members.setdefault(key, []).append((ticket, grade))
        fields = tuple(None if axis == "gates" else axis for axis in cut)
        kept, withheld = release.release(
            Counter({key: len(m) for key, m in members.items()}), fields, k
        )
        cuts.append(
            {
                "axes": "+".join(cut),
                "cells": [
                    {**dict(zip(cut, key, strict=True)), **_group(members[key])}
                    for key, _ in sorted(kept)
                ],
                "withheld": withheld,
            }
        )
    return {"gates": GATE_ORDER, "cuts": cuts}
```

- [ ] **Step 4: Run the tests**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_cube.py`
Expected: all pass (13 test cases, counting each parametrized case).

- [ ] **Step 5: Lint and commit**

```bash
../../.venv/bin/ruff check insight/cube.py tests/unit/test_insight_cube.py
../../.venv/bin/ruff format --check insight/cube.py tests/unit/test_insight_cube.py
git add insight/cube.py tests/unit/test_insight_cube.py
git commit -m "feat(insight): the joint quality cube - 14 floored cuts over category, Baugruppe, model and gates"
```

---

### Task 4: The derivability measurement

Amendment A1: subtraction across cuts is accepted, as amendment 8 accepts inner counts, and it is **measured**. The measurement:
- uses an LP over every combination of axis values (Baugruppe sets up to pairs, plus every combination that occurs)
- counts the withheld cells below k that the cube newly pins, comparing the released numbers with and without the cube
- screens with random vertices, then runs exact LPs until a deadline
- never fails a run, whether it is slow or the solver errors

**Files:**
- Modify: `insight/cube.py` (append)
- Test: `tests/unit/test_insight_cube.py` (append)

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_insight_cube.py`:

```python
def _split_category():
    """Category 40110 has three tickets of model 731015 and one of a model under the floor;
    40111 has three of 731015. Without the cube the lone ticket could be in either category;
    the cube's category x model cells place it in 40110."""
    tickets = [mk(i, category="40110", model="731015") for i in range(3)]
    tickets += [mk(3, category="40110", model="832050")]
    tickets += [mk(4 + i, category="40111", model="731015") for i in range(3)]
    return tickets


def test_the_measurement_counts_a_cell_only_the_cube_exposes():
    tickets = _split_category()
    measured = cube.measure(tickets, section(tickets), origin_section(tickets), K)
    # (40110, other model) in cat+model, cat+model+gates and cat+baug+model.
    assert measured == {"withheld_cells": 7, "checked": 7, "newly_derivable": 3}


def test_the_measurement_does_not_count_what_the_report_already_exposes():
    """One category only: the report without the cube already pins every cell."""
    tickets = _split_category()[:4]
    measured = cube.measure(tickets, section(tickets), origin_section(tickets), K)
    assert measured["newly_derivable"] == 0
    assert measured["checked"] == measured["withheld_cells"] > 0


def test_a_budget_of_zero_measures_nothing_and_says_so():
    tickets = _split_category()
    measured = cube.measure(tickets, section(tickets), origin_section(tickets), K, budget=0)
    assert measured == {"withheld_cells": 7, "checked": 0, "newly_derivable": 0}


def test_an_exhausted_budget_leaves_cells_unchecked_instead_of_running_on():
    tickets = _split_category()
    ticks = iter([0.0] + [10.0] * 1000)
    measured = cube.measure(
        tickets, section(tickets), origin_section(tickets), K, budget=5, clock=lambda: next(ticks)
    )
    assert measured["checked"] < measured["withheld_cells"]
    assert measured["newly_derivable"] == 0


def test_a_failing_solver_ends_the_measurement_not_the_run(monkeypatch):
    tickets = _split_category()

    def fail(self, c):
        raise RuntimeError("the cube measurement LP failed with status 4")

    monkeypatch.setattr(cube.Solver, "optimum", fail)
    measured = cube.measure(tickets, section(tickets), origin_section(tickets), K)
    assert measured == {"withheld_cells": 7, "checked": 0, "newly_derivable": 0}


def test_nothing_is_measured_when_every_cell_clears_the_floor():
    tickets = [mk(i, category="40110") for i in range(4)]
    measured = cube.measure(tickets, section(tickets), origin_section(tickets), K)
    assert measured["withheld_cells"] == 0


def test_an_empty_corpus_builds_an_empty_cube():
    built = section([])
    assert [c["axes"] for c in built["cube"]["cuts"]] == list(cube.CUT_NAMES)
    assert all(c["cells"] == [] for c in built["cube"]["cuts"])
    assert cube.measure([], built, origin_section([]), K)["withheld_cells"] == 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_cube.py -k "measure or budget or solver or floor or empty"`
Expected: FAIL with `AttributeError: module 'insight.cube' has no attribute 'measure'`. `test_a_failing_solver...` fails on `cube.Solver` the same way.

- [ ] **Step 3: Implement.** In `insight/cube.py`, add the two imports beside `import itertools`:

```python
import itertools
import math
import time
```

Then append the measurement to the end of the file:

```python
# ---------- the measurement ----------


@dataclass(frozen=True)
class Known:
    """One released number: the atoms, each counted `coef[atom]` times, sum to `value` - or, with
    `at_least`, to at least `value`."""

    coef: dict[Atom, int]
    value: int
    at_least: bool = False


def space(u: Universe, observed: list[Atom]) -> list[Atom]:
    """Every atom a reader cannot rule out without the data: each combination of category, model
    and gate pattern with no Baugruppe, one, or two of them - plus every atom that occurs, so the
    true counts are always a solution. Larger unobserved sets are left out, which only makes the
    reader stronger and the measurement larger."""
    ids = [v for v in u["baug"] if v != NONE]
    sets = [frozenset()] + [frozenset(c) for n in (1, 2) for c in itertools.combinations(ids, n)]
    product = {
        Atom(cat, s, model, gates)
        for cat in u["cat"]
        for s in sets
        for model in u["model"]
        for gates in u["gates"]
    }
    return sorted(product | set(observed), key=Atom.order)


def _where(atoms: list[Atom], test: Callable[[Atom], bool]) -> dict[Atom, int]:
    return {a: 1 for a in atoms if test(a)}


def _group_knowns(coef: dict[Atom, int], group: dict) -> list[Known]:
    """A released `_group`: its count, and the fill of every field the atom itself decides."""
    out = [Known(coef, group["count"])]
    for name, holds in ATOM_FIELDS.items():
        out.append(Known({a: w for a, w in coef.items() if holds(a)}, group["fields"][name]))
    return out


def report_knowns(section: dict, origin_section: dict, atoms: list[Atom]) -> list[Known]:
    """What the report says about the atoms without the cube. A section split by year adds nothing
    here (its years sum to a one-axis number released anyway), except the Baugruppe x model x year
    table, which bounds a Baugruppe x model cell from below. Withheld tallies outside the cube are
    left out, which can only make a cell look newly exposed, never hide one."""
    out = _group_knowns(_where(atoms, lambda a: True), section["overall"])
    dims = section["by_dimension"]
    for e in dims["categoryId"]["values"]:
        out += _group_knowns(_where(atoms, lambda a, v=e["value"]: a.cat == v), e)
    for e in dims["model_id"]["values"]:
        out += _group_knowns(_where(atoms, lambda a, v=e["value"]: a.model == v), e)
    for e in dims["baugruppe"]["values"]:
        out += _group_knowns(_where(atoms, lambda a, v=e["value"]: v in a.ids), e)
    for name, holds in ATOM_FIELDS.items():
        out += _group_knowns(_where(atoms, holds), section["by_field"][name])
    for e in origin_section["baugruppe"].get("pairs", []):
        pair = {e["value"], e["partner"]}
        test = lambda a, p=pair: p <= a.ids and a.pairable  # noqa: E731
        out.append(Known(_where(atoms, test), e["count"]))
    table: Counter = Counter()
    for e in origin_section["baugruppe_model_year"].get("cells", []):
        table[(e["value"], e["model"])] += e["count"]
    for (b, m), n in sorted(table.items()):
        test = lambda a, b=b, m=m: b in a.ids and a.model == m  # noqa: E731
        out.append(Known(_where(atoms, test), n, at_least=True))
    return out


def exposed(low: float, high: float) -> bool:
    """Only one integer fits between low and high: the cell is known exactly."""
    return math.floor(high + 1e-6) - math.ceil(low - 1e-6) < 1


class Solver:
    """Every non-negative atom vector the knowns allow, asked for the range of a cell."""

    def __init__(self, columns: list[Atom], truth: Counter, knowns: list[Known]) -> None:
        import numpy as np

        self.columns = columns
        self.column = {a: j for j, a in enumerate(columns)}
        eq = [k for k in knowns if not k.at_least]
        ub = [k for k in knowns if k.at_least]
        self.system = {
            "A_eq": self.matrix([k.coef for k in eq]) if eq else None,
            "b_eq": [k.value for k in eq] if eq else None,
            "A_ub": -self.matrix([k.coef for k in ub]) if ub else None,
            "b_ub": [-k.value for k in ub] if ub else None,
        }
        self.truth = np.array([truth.get(a, 0) for a in columns], dtype=float)

    def matrix(self, rows: list[dict[Atom, int]]):
        from scipy.sparse import coo_matrix

        r, c, v = [], [], []
        for i, coef in enumerate(rows):
            for a, w in coef.items():
                r.append(i)
                c.append(self.column[a])
                v.append(w)
        return coo_matrix((v, (r, c)), shape=(len(rows), len(self.columns))).tocsr()

    def optimum(self, c) -> float:
        from scipy.optimize import linprog

        res = linprog(c, bounds=(0, None), method="highs", **self.system)
        if res.status != 0:
            raise RuntimeError(f"the cube measurement LP failed with status {res.status}")
        return res

    def screen(self, targets: list[dict[Atom, int]]):
        """(lows, highs) seen over the true counts and SCREEN random vertices. A cell whose seen
        range is not `exposed` is proven free; any other needs `range`. Deterministic: sorted
        columns and a fixed seed."""
        import numpy as np

        t = self.matrix(targets)
        rng = np.random.default_rng(0)
        seen = [t @ self.truth]
        for _ in range(SCREEN):
            seen.append(t @ self.optimum(rng.uniform(-1.0, 1.0, len(self.columns))).x)
        stacked = np.vstack(seen)
        return stacked.min(axis=0), stacked.max(axis=0)

    def range(self, target: dict[Atom, int]) -> tuple[float, float]:
        import numpy as np

        c = np.zeros(len(self.columns))
        for a, w in target.items():
            c[self.column[a]] = w
        return float(self.optimum(c).fun), float(-self.optimum(-c).fun)


def measure(
    tickets: list[Ticket],
    section: dict,
    origin_section: dict,
    k: int = release.K,
    budget: float = BUDGET,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """How many withheld cube cells a reader can pin exactly with the cube that the report without
    it did not pin. `section` is the finished quality section, cube included.

    The exact LPs stop at `budget` seconds, and a budget of 0 skips the measurement; `checked`
    says how many of the `withheld_cells` were settled, so a partial measurement reads as
    partial. Neither a slow nor a failing solver stops the run."""
    u = universes(section["by_dimension"])
    atoms = [atom_of(t, u) for t in tickets]
    truth = Counter(atoms)
    columns = space(u, atoms)
    holders: dict[tuple[Axes, Key], dict[Atom, int]] = {}
    for atom in columns:
        for cut in CUTS:
            for key in keys_of(atom, cut, u):
                holders.setdefault((cut, key), {})[atom] = 1
    counts: Counter = Counter()
    for atom, n in truth.items():
        for cut in CUTS:
            for key in keys_of(atom, cut, u):
                counts[(cut, key)] += n

    shown: set[tuple[Axes, Key]] = set()
    cube_knowns: list[Known] = []
    for cut, block in zip(CUTS, section["cube"]["cuts"], strict=True):
        for cell in block["cells"]:
            key = tuple(cell[axis] for axis in cut)
            shown.add((cut, key))
            cube_knowns += _group_knowns(holders[(cut, key)], cell)
        hidden: Counter = Counter()
        for c in counts:
            if c[0] == cut and c not in shown:
                hidden.update(holders[c])
        tally = block["withheld"]
        cube_knowns.append(
            Known(dict(hidden), tally["below_floor"]["rows"] + tally["entity_like"]["rows"])
        )
    targets = sorted(c for c, n in counts.items() if c not in shown and n < k)
    out = {"withheld_cells": len(targets), "checked": 0, "newly_derivable": 0}
    if not targets or budget <= 0:
        return out  # a budget of 0 is "do not measure": nothing is checked
    deadline = clock() + budget
    base = report_knowns(section, origin_section, columns)
    cells = [holders[c] for c in targets]
    try:
        before = Solver(columns, truth, base)
        after = Solver(columns, truth, base + cube_knowns)
        after_lo, after_hi = after.screen(cells)
        before_lo, before_hi = before.screen(cells)
        for i, cell in enumerate(cells):
            if not exposed(after_lo[i], after_hi[i]):
                out["checked"] += 1  # free with the cube, so not newly pinned
                continue
            if clock() > deadline:
                continue
            if not exposed(*after.range(cell)):
                out["checked"] += 1
                continue
            pinned_before = exposed(before_lo[i], before_hi[i]) and exposed(*before.range(cell))
            out["checked"] += 1
            out["newly_derivable"] += not pinned_before
    except RuntimeError:
        # A solver failure ends the measurement, not the window: `checked` says how far it got.
        pass
    return out
```

- [ ] **Step 4: Run the cube tests**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_cube.py`
Expected: all pass (20 test cases). The hand-built case must give exactly `{"withheld_cells": 7, "checked": 7, "newly_derivable": 3}`: the lone below-floor ticket is placed in category 40110 by three cuts.

- [ ] **Step 5: Mutation check (do not commit).** In `measure`, temporarily replace `out["newly_derivable"] += not pinned_before` with `out["newly_derivable"] += 1`. Run the cube tests. `test_the_measurement_does_not_count_what_the_report_already_exposes` must FAIL. Revert the change.

- [ ] **Step 6: Lint and commit**

```bash
../../.venv/bin/ruff check insight/cube.py tests/unit/test_insight_cube.py
../../.venv/bin/ruff format --check insight/cube.py tests/unit/test_insight_cube.py
git add insight/cube.py tests/unit/test_insight_cube.py
git commit -m "feat(insight): measure how many withheld cube cells subtraction newly exposes (amendment A1)"
```

---

### Task 5: The guard accepts the cube and nothing more

**Files:**
- Modify: `insight/guard.py`
- Test: `tests/unit/test_insight_guard.py`

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_insight_guard.py`, change the import line to:

```python
from insight import concentration, cube, dimensions, formats, guard, release
```

and append:

```python
def cube_report(cells, axes="cat"):
    """A quality section that released category 40112 and Baugruppe 5, and a cube cut over it."""
    return {
        "quality": {
            "by_dimension": {
                "categoryId": {"values": [{"value": "40112", "count": 60}]},
                "baugruppe": {"values": [{"value": "5", "count": 60}]},
                "model_id": {"values": []},
            },
            "cube": {"gates": cube.GATE_ORDER, "cuts": [{"axes": axes, "cells": cells}]},
        }
    }


def test_a_floored_cube_cell_of_released_values_passes():
    cells = [{"cat": "40112", "baug": "5", "gates": "101", "count": 60}]
    assert guard.unaccounted(cube_report(cells, "cat+baug+gates"), 50) == []


@pytest.mark.parametrize("value", cube.SENTINELS)
def test_the_cube_sentinels_pass(value):
    assert guard.unaccounted(cube_report([{"cat": value, "count": 60}]), 50) == []


def test_a_cube_cell_below_the_floor_is_refused():
    assert guard.unaccounted(cube_report([{"cat": "40112", "count": 49}]), 50) == [
        ("quality.cube.cuts.cells", "BELOW_FLOOR")
    ]


def test_a_cube_value_the_quality_section_did_not_release_is_refused():
    assert guard.unaccounted(cube_report([{"cat": "40999", "count": 60}]), 50) == [
        ("quality.cube.cuts.cells", "UNRELEASED_VALUE")
    ]


def test_a_released_value_of_another_axis_is_refused():
    """'5' is a released Baugruppe, not a released category."""
    assert guard.unaccounted(cube_report([{"cat": "5", "count": 60}]), 50) == [
        ("quality.cube.cuts.cells", "UNRELEASED_VALUE")
    ]


def test_a_cube_cell_must_carry_exactly_its_cuts_axes():
    assert guard.unaccounted(cube_report([{"cat": "40112", "count": 60}], "cat+baug"), 50) == [
        ("quality.cube.cuts.cells", "CUT_MISMATCH")
    ]


@pytest.mark.parametrize("pattern", ["012", "10", "1011", "abc"])
def test_a_gate_pattern_is_three_bits(pattern):
    found = guard.unaccounted(cube_report([{"gates": pattern, "count": 60}], "gates"), 50)
    assert found == [("quality.cube.cuts.cells.gates", "UNACCOUNTED_STRING")]


def test_an_unknown_cut_name_is_refused():
    found = guard.unaccounted(cube_report([{"cat": "40112", "count": 60}], "cat+year"), 50)
    assert ("quality.cube.cuts.axes", "UNACCOUNTED_STRING") in found


def test_a_list_where_a_released_value_belongs_does_not_crash_the_cross_check():
    report = cube_report([{"cat": "40112", "count": 60}])
    report["quality"]["by_dimension"]["categoryId"]["values"].append({"value": ["x"], "count": 60})
    assert ("quality.by_dimension.categoryId.values", "UNACCOUNTED_TYPE") in guard.unaccounted(
        report, 50
    )


def test_a_malformed_cube_is_refused_without_crashing_the_cross_check():
    report = cube_report([])
    report["quality"]["cube"]["cuts"] = [{"axes": 7, "cells": "not a list"}]
    assert guard.unaccounted(report, 50) == [("quality.cube.cuts.cells", "UNACCOUNTED_STRING")]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_guard.py -k "cube or gate or cut or list_where"`
Expected: several FAIL with `UNDECLARED_KEY` findings, because `cube`, `cuts`, `cat`, `baug` and `gates` are unknown keys.

- [ ] **Step 3: Implement.** In `insight/guard.py`:

(a) Replace the one-line `from insight import concentration, ...` with:

```python
from insight import (
    concentration,
    cube,
    dimensions,
    formats,
    lifecycle,
    quality,
    release,
    timeline,
)
```

(b) Add these keys to `KEYS`, each in alphabetical position: `"axes"`, `"baug"`, `"cat"`, `"checked"`, `"cube"`, `"cuts"`, `"gates"`, `"measurement"`, `"newly_derivable"`, `"withheld_cells"`.

(c) Append to `SECTIONS`, after `"quality.by_lifecycle.warranty.states_withheld",`:

```python
    "quality.cube.cuts.withheld",
```

(d) Add to `RELEASED_AT`, as its last entry:

```python
    "quality.cube.cuts.cells": {"cat", "baug", "model"},
```

(e) Add to `LITERALS`, as its last entries:

```python
    "quality.cube.gates": re.compile(re.escape(cube.GATE_ORDER)),
    "quality.cube.cuts.axes": _labels(cube.CUT_NAMES),
    "quality.cube.cuts.cells.gates": re.compile(f"[01]{{{len(cube.GATES)}}}"),
```

(f) Replace `_found` with these three functions:

```python
def _entries(node: object, key: str) -> list[dict]:
    """The dicts in `node[key]`, or none: the cube check runs on whatever arrived, and a wrong
    type there is `_scan`'s to refuse, not this check's to crash on."""
    value = node.get(key) if isinstance(node, dict) else None
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def _cube_found(report: dict) -> _Found:
    """A cube cell names only values `quality.by_dimension` released (or a sentinel), and exactly
    the axes of its cut. The floor and the sweep are `_scan`'s; this is the cross-reference that
    keeps the cube from naming a value no other section was allowed to name."""
    section = report.get("quality")
    block = section.get("cube") if isinstance(section, dict) else None
    if not isinstance(block, dict):
        return []
    dims = section.get("by_dimension")
    dims = dims if isinstance(dims, dict) else {}
    allowed = {
        axis: {
            e["value"] for e in _entries(dims.get(source), "values") if isinstance(e.get("value"), str)
        }
        | set(cube.SENTINELS)
        for axis, source in cube.SOURCES.items()
    }
    found: _Found = []
    path = "quality.cube.cuts.cells"
    for cut in _entries(block, "cuts"):
        named = set(cut["axes"].split("+")) if isinstance(cut.get("axes"), str) else set()
        for cell in _entries(cut, "cells"):
            carried = sorted(axis for axis in cube.AXES if axis in cell)
            if set(carried) != named:
                found.append((path, "CUT_MISMATCH", "+".join(carried)))
            for axis, values in allowed.items():
                if isinstance(cell.get(axis), str) and cell[axis] not in values:
                    found.append((path, "UNRELEASED_VALUE", cell[axis]))
    return found


def _found(report: object, k: int) -> _Found:
    if not isinstance(report, dict):
        return [("<root>", "UNACCOUNTED_TYPE", type(report).__name__)]
    found: _Found = []
    _scan(report, "", k, found)
    found.extend(_cube_found(report))
    return sorted(found, key=lambda item: (item[0], item[1]))
```

Run `../../.venv/bin/ruff format insight/guard.py` afterwards; the set comprehension is wrapped by the formatter.

- [ ] **Step 4: Run the guard tests**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_insight_guard.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add insight/guard.py tests/unit/test_insight_guard.py
git commit -m "feat(guard): the quality cube - closed literals, a released path, and values only quality released"
```

---

### Task 6: The report carries the cube and its measurement

**Files:**
- Modify: `insight/report.py`, `pyproject.toml`
- Test: `tests/integration/test_insight_report.py`

- [ ] **Step 1: Write the failing tests.** In `tests/integration/test_insight_report.py`:

(a) change the import line to:

```python
from insight import cube, extract, guard, origin, release, report
```

(b) in `build_with`, add one option, so every existing build skips the slow measurement:

```python
        "serial_prefixes": True,
        # The derivability measurement costs seconds per build; the tests about it ask for it.
        "cube_budget": 0,
    }
```

(c) append:

```python
@pytest.fixture(scope="module")
def measured(rows):
    return build_with(rows, cube_budget=cube.BUDGET)


def test_the_cube_releases_every_cut_floored(built):
    block = built["quality"]["cube"]
    assert block["gates"] == cube.GATE_ORDER
    assert [c["axes"] for c in block["cuts"]] == list(cube.CUT_NAMES)
    assert all(cell["count"] >= K for c in block["cuts"] for cell in c["cells"])
    # The stand-in is large enough for every cut to release something and withhold something.
    assert all(c["cells"] for c in block["cuts"])
    assert sum(c["withheld"]["below_floor"]["distinct"] for c in block["cuts"]) > 0


def test_the_one_axis_cube_cuts_agree_with_the_quality_section(built):
    """Same tickets, same floor: a released category in the cube is the quality section's group."""
    q = built["quality"]
    by_value = {e["value"]: e for e in q["by_dimension"]["categoryId"]["values"]}
    for cell in next(c for c in q["cube"]["cuts"] if c["axes"] == "cat")["cells"]:
        if cell["cat"] in by_value:
            expected = {k: v for k, v in by_value[cell["cat"]].items() if k not in ("value",)}
            assert {k: v for k, v in cell.items() if k != "cat"} == expected


def test_an_unmeasured_build_says_it_checked_nothing(built):
    measurement = built["quality"]["cube"]["measurement"]
    assert measurement["checked"] == 0 and measurement["newly_derivable"] == 0
    assert measurement["withheld_cells"] > 0


def test_a_measured_build_settles_every_cell_and_publishes_the_count(measured):
    measurement = measured["quality"]["cube"]["measurement"]
    assert measurement["checked"] == measurement["withheld_cells"] > 0
    assert 0 <= measurement["newly_derivable"] <= measurement["withheld_cells"]
    guard.assert_safe(measured, K)


def test_the_measurement_does_not_depend_on_the_order_of_the_rows(rows, measured):
    again = build_with(rows[::-1], cube_budget=cube.BUDGET)
    assert again["quality"]["cube"] == measured["quality"]["cube"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `../../.venv/bin/python -m pytest -q tests/integration/test_insight_report.py -x`
Expected: FAIL with `TypeError: build() got an unexpected keyword argument 'cube_budget'`.

- [ ] **Step 3: Implement.** In `insight/report.py`:

(a) add `cube,` to the `from insight import (...)` list, after `crosstab,`.

(b) add a keyword parameter to `build`, after `serial_prefixes: bool = False,`:

```python
    cube_budget: float = cube.BUDGET,
```

(c) after `tickets = extract.tickets(rows)`, compute the origin and quality sections first. The measurement reads the origin section, and the cube reuses the grades:

```python
    graded = quality.grades(tickets, k)
    origin_section = {
        "baugruppe": origin.baugruppe(tickets, k),
        "vehicles": origin.vehicles(tickets, k, serial_prefixes),
        "titles": origin.titles(tickets, k),
        "baugruppe_model_year": crosstab.baugruppe_model_year(tickets, k),
    }
    quality_section = quality.build(tickets, k, graded)
    quality_section["cube"] = cube.build(tickets, graded, quality_section["by_dimension"], k)
    quality_section["cube"]["measurement"] = cube.measure(
        tickets, quality_section, origin_section, k, cube_budget
    )
```

(d) in the `built = {...}` literal, replace the whole `"origin": {...}` block with `"origin": origin_section,`, and replace `"quality": quality.build(tickets, k),` with `"quality": quality_section,`.

(e) in `pyproject.toml`, add `"scipy>=1.18",` to `dependencies`, after `"numpy>=2.1",`. Then refresh the lock if `uv` is available: `uv lock`, which only records the new direct dependency, since scipy 1.18.0 is already locked through `datasketch`. **`uv` is not installed on this workstation:** leave `uv.lock` unchanged and add a line to the STATE.md entry (Task 9) that the operator must run `uv lock` before the image is rebuilt.

- [ ] **Step 4: Run the report tests**

Run: `../../.venv/bin/python -m pytest -q tests/integration/test_insight_report.py`
Expected: all pass. This covers the existing closed-set tests: every declared key, literal path, released path and withheld section is emitted by the stand-in, and the guard accepts the build.

- [ ] **Step 5: Commit**

```bash
git add insight/report.py pyproject.toml tests/integration/test_insight_report.py
git commit -m "feat(insight): the report carries quality.cube and its derivability measurement"
```

---

### Task 7: `--cube-budget` on the CLI

**Files:**
- Modify: `insight/__main__.py`
- Test: `tests/integration/test_insight_cli.py`

- [ ] **Step 1: Write the failing tests.** In `tests/integration/test_insight_cli.py`:

(a) in `run()`, add the flag before `*provenance_args()`, so the existing tests skip the measurement. A later `--cube-budget` in `extra` overrides it, because argparse keeps the last value:

```python
        "--allow-weak-floor",
        "--cube-budget",
        "0",
        *provenance_args(),
        *extra,
```

(b) replace `test_help_exits_zero` and append the new tests:

```python
def test_help_exits_zero(capsys):
    assert safety.run_scrubbed(main, ["--help"]) == 0
    printed = capsys.readouterr().out
    assert "--allow-weak-floor" in printed
    assert "--cube-budget" in printed


def test_a_run_prints_how_much_of_the_cube_it_measured(tmp_path, capsys):
    code, out = run(tmp_path, "--cube-budget", "600")
    assert code == 0
    measurement = json.loads(out.read_text(encoding="utf-8"))["quality"]["cube"]["measurement"]
    printed = capsys.readouterr().out
    assert f"cube_newly_derivable={measurement['newly_derivable']}" in printed
    cells = measurement["withheld_cells"]
    assert f"cube_checked={cells}/{cells}" in printed


@pytest.mark.parametrize("bad", ["-1", "nan"])
def test_a_negative_or_nan_cube_budget_is_refused(tmp_path, bad, capsys):
    code, out = run(tmp_path, "--cube-budget", bad)
    assert code == 4
    assert "--cube-budget" in capsys.readouterr().out
    assert not out.exists()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `../../.venv/bin/python -m pytest -q tests/integration/test_insight_cli.py`
Expected: FAIL. With the unknown flag, every run exits with code 4 (`BAD_ARGUMENT`).

- [ ] **Step 3: Implement.** In `insight/__main__.py`:

(a) `from insight import cube, extract, guard, release, report`

(b) after the `--serial-prefixes` argument:

```python
    # Seconds the cube's derivability measurement may spend on exact LPs; it never stops the run,
    # and the report says how many cells it settled.
    parser.add_argument("--cube-budget", type=float, default=cube.BUDGET)
```

(c) directly before `if args.min_frequency < vocab.MIN_FREQUENCY_FLOOR:` (`not >= 0` also refuses NaN):

```python
    if not args.cube_budget >= 0:
        return _abort("BAD_ARGUMENT", "--cube-budget must be a number of seconds, 0 or more")
```

(d) pass `cube_budget=args.cube_budget,` to `report.build(...)`, after `serial_prefixes=...`.

(e) after the existing `print(f"rows=... ledger_rows=...")`:

```python
    measured = built["quality"]["cube"]["measurement"]
    print(
        f"cube_newly_derivable={measured['newly_derivable']} "
        f"cube_checked={measured['checked']}/{measured['withheld_cells']}"
    )
```

- [ ] **Step 4: Run the CLI tests**

Run: `../../.venv/bin/python -m pytest -q tests/integration/test_insight_cli.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add insight/__main__.py tests/integration/test_insight_cli.py
git commit -m "feat(insight): --cube-budget caps the derivability measurement; the CLI prints how far it got"
```

---

### Task 8: The window pins the budget; the rehearsal checks the cube

**Files:**
- Modify: `infra/profiler/window.sh`, `infra/profiler/rehearse-window-d.sh`
- Test: `tests/unit/test_window_d_contract.py`

These files contain the export's file name, so **edit them with the Edit tool, not `sed`** (see Binding constraints).

- [ ] **Step 1: Write the failing test.** In `tests/unit/test_window_d_contract.py`, `test_the_sealed_command_is_the_insight_cli_with_the_floor_spelled_out`, add `"--cube-budget 1800",` to the flag tuple after `"--min-frequency 50",`.

- [ ] **Step 2: Run it and watch it fail**

Run: `../../.venv/bin/python -m pytest -q tests/unit/test_window_d_contract.py -k floor_spelled_out`
Expected: FAIL. The assertion shows `'--cube-budget 1800'` and the command.

- [ ] **Step 3: Implement.**

(a) In `infra/profiler/window.sh`, case `d`:
- Extend the comment above `WINDOW_CMD` with:

```bash
      # value its guard would refuse, before any real row is read. --cube-budget 1800 caps the
      # cube's derivability measurement (two LP passes, ~15 min each on data of the real shape);
      # it never fails the run, and the report says how many cells it settled.
```

  The first of these lines replaces the existing `# value its guard would refuse, before any real row is read.`
- In `WINDOW_CMD`, insert `--cube-budget 1800 ` directly after `--min-frequency 50 `.

(b) In `infra/profiler/rehearse-window-d.sh`:
- In the flag loop, add `"--cube-budget 1800"` before `"--code-commit"`.
- After the `columns_expected_missing=0` check, add the check below. Do not use a regex backreference: this machine's `grep` is ugrep, which rejects one.

```bash
grep -q 'cube_checked=' <<<"$OUT" && ok "the cube measurement reported how far it got" \
  || bad "no cube_checked line - the measurement did not report"
```

- In the `PLANNED` Python heredoc, add `from insight import cube` after the `PLAN` import, and add three checks to the `checks` dict:

```python
    "cube has every cut": [c["axes"] for c in r["quality"]["cube"]["cuts"]]
    == list(cube.CUT_NAMES),
    "cube cells floored": all(
        cell["count"] >= 50 for c in r["quality"]["cube"]["cuts"] for cell in c["cells"]
    ),
    "cube measured": r["quality"]["cube"]["measurement"]["checked"]
    == r["quality"]["cube"]["measurement"]["withheld_cells"],
```

- Change the success note to `note "fehlercode, serials, delivery dates, concentration, readiness, quality and the cube match"`.

- [ ] **Step 4: Check syntax and run the contract tests**

Run: `bash -n infra/profiler/rehearse-window-d.sh && bash -n infra/profiler/window.sh && ../../.venv/bin/python -m pytest -q tests/unit/test_window_d_contract.py`
Expected: no syntax output; all tests pass.

- [ ] **Step 5: Commit**

```bash
git add infra/profiler/window.sh infra/profiler/rehearse-window-d.sh tests/unit/test_window_d_contract.py
git commit -m "test(airlock): Window D pins --cube-budget 1800 and the rehearsal checks the cube"
```

---

### Task 9: Docs, full verification, rehearsal

**Files:**
- Modify: `docs/airlock-runbook.md` (Window D), `docs/STATE.md`

- [ ] **Step 1: Runbook.** In `docs/airlock-runbook.md`, section "Window D", subsection "The window", add after the three-command block:

```markdown
      `run` now also builds the **joint quality cube** and measures it: two LP passes of about
      15 minutes each on data of the real shape, capped by `--cube-budget 1800`. Expect the run
      to take up to ~40 minutes longer than before. It prints
      `cube_newly_derivable=N cube_checked=X/Y`. `X < Y` means the budget ran out: the report is
      still valid and guarded, the measurement is partial, and the report says so. Write both
      numbers down; neither one stops the window.
```

- [ ] **Step 2: STATE.md.** Add a section above "Quality score v2":

```markdown
### Filter tree v2, stage 1 (joint quality cube) — BUILT <date> on `feat/insight-cube`

`quality.cube` in `report.json`: 14 cuts (every combination of up to three of category, Baugruppe,
model and a 3-bit gate pattern: error code, description, serial), each cell shaped like a quality
group and floored at k. Axis values are exactly the values `quality.by_dimension` released, plus
`_other` and `_none`; the guard cross-checks that. Spec:
`docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md` (section 1, amendment A1).

**Amendment A1 (operator decision, 2026-10-16):** complementary suppression with an LP gate was
prototyped and did not converge on the stand-in; the existing quality section's inner counts
already pin cells once any joint cut exists. Subtraction across cuts is accepted as amendment 8
accepts inner counts, and MEASURED: `quality.cube.measurement` = withheld cells below k, how many
were checked, how many the cube newly pins. `--cube-budget` (window: 1800 s) caps it; it never
fails a run. Measured cost on synthetic data of the real shape: 869 s per pass.

**Operator to do before the next window:** <only if uv was unavailable> run `uv lock` (scipy is
now a declared dependency; it was already locked through datasketch), rebuild and ship the image,
`make window-d-rehearsal`. Then one Window D run gives the real cube.

**Next:** stages 2–5 of the spec (estimator and grades, composer and management, exploration,
comparison) can be built against the stand-in now.
```

Replace `<date>` with today's date. Keep the `uv lock` sentence only if Task 6 Step 3(e) could not run `uv lock`.

- [ ] **Step 3: Full suite and lint**

Run: `../../.venv/bin/python -m pytest -q --ignore=tests/integration/test_german_fts.py --ignore=tests/integration/test_migrate.py 2>&1 | tail -3 && ../../.venv/bin/ruff check . && ../../.venv/bin/ruff format --check .`
Expected: `0 failed`. Passed = baseline + the new tests. ruff: `All checks passed!` and `already formatted`.

- [ ] **Step 4: Rehearsal (needs docker; skip and say so if it is unavailable)**

Run: `make window-d-rehearsal` (with `RECALL_REHEARSAL_PYTHON=../../.venv/bin/python` if needed)
Expected: `0 failed`, including the three new cube checks, the `--cube-budget 1800` flag check and the `cube_checked=` line.

- [ ] **Step 5: Commit**

```bash
git add docs/airlock-runbook.md docs/STATE.md
git commit -m "docs: the quality cube - runbook timing and STATE entry"
```

---

## Amendments during execution (2026-10-16)

Review after each task found real defects in the plan's own code. Each fix has a test that fails
on the code above; the commits name the reviewed commit. Read the branch, not the blocks above,
for the current code.

- `7c7175c` - the grades-reuse test now proves `build` does not grade again.
- `a48662c` (Task 3 review) - a released value spelled like a sentinel is listed once; a blank
  Baugruppe id is no Baugruppe; end-to-end tests for multi-valued Baugruppe, `_other`, gates,
  `_none`, the released-universe invariant and row order.
- `4dccf49` (Task 5 review, a guard bypass) - `_cube_found` walked only the builder's shape, so
  `cuts`/`cells` given as dicts or nested lists reached the released path unchecked;
  `_dicts_at` now follows `_scan`'s path rule. Adversarial tests added.
- `fe43522` (Task 4 review) - the tallies covered only occupied combinations (inflating
  `newly_derivable`); every unshown combination is now bounded by k - 1 and in the tally;
  `MeasurementFailed` and `stopped`; the budget covers the screens; `measure` validates its budget;
  `system()` is public so tests check that the truth satisfies every equation.
- `faac0a0` (Tasks 6-7 review) - `uv.lock` declares scipy (by hand; `uv` absent here).
- `936b5a3` (final review) - the guard floors gates-only cube cells (no released field, so `_scan`
  never did); `checked` counts a cell only once its LPs decided it; the k - 1 bounds apply only
  while a cut withheld nothing as entity-like.
- Task 9 Step 1's runbook text was extended with the `--cube-budget 1800` flag in the command and
  `cube_stopped=`.

