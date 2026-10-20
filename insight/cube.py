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
import math
import time
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
# synthetic tickets of the real shape (corpus-sized, a few dozen models): one pass took 869 s.
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
        # A released value spelled like a sentinel is listed once, as the sentinel; `axis_value`
        # files it under `_other`, so a universe stays a set.
        values = {e["value"] for e in by_dimension[dimension]["values"]} - set(SENTINELS)
        return tuple(sorted(values)) + SENTINELS

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
        ids=frozenset(axis_value(i, u["baug"]) for i in ticket.baugruppe if i),
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


# ---------- the measurement ----------


@dataclass(frozen=True)
class Known:
    """One thing a reader knows: the atoms, each counted `coef[atom]` times, sum to `value`
    (`kind` "eq"), to at least it ("ge") or to at most it ("le"). `name` is for tests only."""

    coef: dict[Atom, int]
    value: int
    kind: str = "eq"
    name: str = ""

    def holds(self, truth: Counter) -> bool:
        total = sum(w * truth.get(a, 0) for a, w in self.coef.items())
        return {"eq": total == self.value, "ge": total >= self.value, "le": total <= self.value}[
            self.kind
        ]


class MeasurementFailed(RuntimeError):
    """The solver did not return an optimum. The true counts always satisfy the system, so this
    is a numerical failure or a modelling bug - never a property of the data."""


def space(u: Universe, observed: list[Atom]) -> list[Atom]:
    """Every atom a reader cannot rule out without the data: each combination of category, model
    and gate pattern with no Baugruppe, one, or two of them - plus every atom that occurs, so the
    true counts are always a solution. A reader would also allow larger unobserved sets; leaving
    them out is one of the ways this is an estimate, not a bound (see `measure`)."""
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


def _ones(atoms: list[Atom]) -> dict[Atom, int]:
    return dict.fromkeys(atoms, 1)


def _group_knowns(coef: dict[Atom, int], group: dict, name: str = "") -> list[Known]:
    """A released `_group`: its count, and the fill of every field the atom itself decides."""
    out = [Known(coef, group["count"], name=name)]
    for field, holds in ATOM_FIELDS.items():
        out.append(Known({a: w for a, w in coef.items() if holds(a)}, group["fields"][field]))
    return out


def report_knowns(section: dict, origin_section: dict, atoms: list[Atom]) -> list[Known]:
    """What the report says about the atoms without the cube. A section split by year adds nothing
    here (its years sum to a one-axis number released anyway), except the Baugruppe x model x year
    table, which bounds a Baugruppe x model cell from below. The report's withheld tallies are
    left out (see `measure` on why the result is an estimate)."""
    by_cat: dict[str, list[Atom]] = {}
    by_model: dict[str, list[Atom]] = {}
    by_baug: dict[str, list[Atom]] = {}
    for a in atoms:
        by_cat.setdefault(a.cat, []).append(a)
        by_model.setdefault(a.model, []).append(a)
        for i in a.ids:
            by_baug.setdefault(i, []).append(a)
    out = _group_knowns(_ones(atoms), section["overall"])
    dims = section["by_dimension"]
    for e in dims["categoryId"]["values"]:
        out += _group_knowns(_ones(by_cat.get(e["value"], [])), e)
    for e in dims["model_id"]["values"]:
        out += _group_knowns(_ones(by_model.get(e["value"], [])), e)
    for e in dims["baugruppe"]["values"]:
        out += _group_knowns(_ones(by_baug.get(e["value"], [])), e)
    for field, holds in ATOM_FIELDS.items():
        out += _group_knowns(_ones([a for a in atoms if holds(a)]), section["by_field"][field])
    for e in origin_section["baugruppe"].get("pairs", []):
        partner = e["partner"]
        both = [a for a in by_baug.get(e["value"], []) if partner in a.ids and a.pairable]
        out.append(Known(_ones(both), e["count"], name="pair"))
    table: Counter = Counter()
    for e in origin_section["baugruppe_model_year"].get("cells", []):
        table[(e["value"], e["model"])] += e["count"]
    for (b, m), n in sorted(table.items()):
        inside = [a for a in by_baug.get(b, []) if a.model == m]
        out.append(Known(_ones(inside), n, kind="ge", name="table"))
    return out


def exposed(low: float, high: float) -> bool:
    """Only one integer fits between low and high: the cell is known exactly. The tolerance is far
    above the solver's feasibility tolerance and far below any real gap: vertex values here are
    integers or simple fractions."""
    return math.floor(high + 1e-4) - math.ceil(low - 1e-4) < 1


class Solver:
    """Every non-negative atom vector the knowns allow, asked for the range of a cell."""

    def __init__(self, columns: list[Atom], truth: Counter, knowns: list[Known]) -> None:
        import numpy as np
        from scipy.sparse import vstack

        self.columns = columns
        self.column = {a: j for j, a in enumerate(columns)}
        eq = [k for k in knowns if k.kind == "eq"]
        ub = [k for k in knowns if k.kind != "eq"]
        sign = [-1 if k.kind == "ge" else 1 for k in ub]
        self.system = {
            "A_eq": self.matrix([k.coef for k in eq]) if eq else None,
            "b_eq": [k.value for k in eq] if eq else None,
            "A_ub": vstack([s * self.matrix([k.coef]) for s, k in zip(sign, ub, strict=True)])
            if ub
            else None,
            "b_ub": [s * k.value for s, k in zip(sign, ub, strict=True)] if ub else None,
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

    def optimum(self, c):
        from scipy.optimize import linprog

        res = linprog(c, bounds=(0, None), method="highs", **self.system)
        if res.status != 0:
            raise MeasurementFailed(f"the cube measurement LP failed with status {res.status}")
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


@dataclass(frozen=True)
class System:
    """Everything `measure` reasons with, built once; public so tests can check it."""

    columns: list[Atom]
    truth: Counter
    base: list[Known]  # the report without the cube
    cube: list[Known]  # what the cube adds
    targets: list[dict[Atom, int]]  # the withheld cube cells below k


def system(tickets: list[Ticket], section: dict, origin_section: dict, k: int) -> System:
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

    cube_knowns: list[Known] = []
    targets = []
    for cut, block in zip(CUTS, section["cube"]["cuts"], strict=True):
        shown = {tuple(cell[axis] for axis in cut): cell for cell in block["cells"]}
        name = "+".join(cut)
        for key, cell in shown.items():
            cube_knowns += _group_knowns(holders[(cut, key)], cell, name=name)
        # A reader knows the cut's withheld rows and that each withheld cell is below the floor
        # (the cube's values were all released before, so nothing is withheld as entity-like) -
        # for EVERY combination not shown, since a reader cannot tell an empty one from a small one.
        hidden = [c for c in holders if c[0] == cut and c[1] not in shown]
        withheld = block["withheld"]
        # Only while nothing was withheld as entity-like: such a cell may hold k or more.
        below_k = withheld["entity_like"]["distinct"] == 0
        tally: Counter = Counter()
        for c in hidden:
            tally.update(holders[c])
            if below_k:
                cube_knowns.append(Known(holders[c], k - 1, kind="le", name=name))
        rows = withheld["below_floor"]["rows"] + withheld["entity_like"]["rows"]
        cube_knowns.append(Known(dict(tally), rows, name="tally:" + name))
        targets += [holders[c] for c in sorted(hidden) if 0 < counts[c] < k]
    return System(
        columns, truth, report_knowns(section, origin_section, columns), cube_knowns, targets
    )


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

    An ESTIMATE, by an LP reader, with no bound in either direction: the reader is given more than
    a real one has in places (only Baugruppe sets up to pairs are possible) and less in others (no
    integer reasoning, no withheld tallies outside the cube).

    The clock is checked after setup, between the screens and before each cell's exact LPs, so
    the budget is a soft cap (one screen can overrun it); a budget of 0 skips the
    measurement. `checked` says how many of the `withheld_cells` were settled, and `stopped` why it
    ended early ("budget" or "solver"), or None. Neither a slow nor a failing solver stops the run.
    """
    if not budget >= 0:  # also refuses NaN, which would never reach the deadline
        raise ValueError("the cube measurement budget must be a number of seconds, 0 or more")
    out = {"withheld_cells": 0, "checked": 0, "newly_derivable": 0, "stopped": None}
    s = system(tickets, section, origin_section, k)
    out["withheld_cells"] = len(s.targets)
    if not s.targets:
        return out
    if budget <= 0:
        out["stopped"] = "budget"  # a budget of 0 is "do not measure": nothing is checked
        return out
    deadline = clock() + budget
    try:
        after = Solver(s.columns, s.truth, s.base + s.cube)
        lows, highs = after.screen(s.targets)
        pending = [i for i in range(len(s.targets)) if exposed(lows[i], highs[i])]
        out["checked"] = len(s.targets) - len(pending)  # free with the cube: not newly pinned
        if not pending:
            return out
        if clock() > deadline:
            out["stopped"] = "budget"
            return out
        before = Solver(s.columns, s.truth, s.base)
        was_low, was_high = before.screen([s.targets[i] for i in pending])
        for j, i in enumerate(pending):
            if clock() > deadline:
                out["stopped"] = "budget"
                break
            if not exposed(*after.range(s.targets[i])):
                out["checked"] += 1
                continue
            pinned_before = exposed(was_low[j], was_high[j]) and exposed(
                *before.range(s.targets[i])
            )
            out["checked"] += 1  # only once the cell is decided: a failed LP decided nothing
            out["newly_derivable"] += not pinned_before
    except MeasurementFailed:
        # Ends the measurement, not the window; `checked` says how far it got.
        out["stopped"] = "solver"
    return out
