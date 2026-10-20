"""Decide every number in the fixture from the profile artifact.

Pure: no LLM, no network, no filesystem. This is the only place profile.json is
interpreted, so the fixture's fidelity is decided in one readable place and can be
tested without generating a single word of German.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field

# At or above this many members, a group is a LARGE group - both here and in the
# profiler's banding, which is what the acceptance test compares against.
LARGE_GROUP = 50

# Below this, a scaled large group has vanished outright rather than been demoted: not
# one ticket of it survives anywhere. That is the one case the row-count guard refuses.
# An earlier version floored undersized groups up to a minimum of 2 instead of refusing,
# which manufactured the very minimum it was supposed to detect.
MIN_LARGE_GROUP = 1


def group_sizes(profile: dict, rows: int, seed: int) -> list[int]:
    """One entry per near-duplicate group; the list sums to `rows`.

    The large band keeps its measured TICKET SHARE (the user's decision, 2026-08-17).
    At 1,500 rows the real 2,034/163/59/58 groups scale to 190/15/6/5, and 15, 6 and 5
    are mid-band sizes by the profiler's 2-49 definition - so a fixture cannot have four
    groups of 50+, correct band shares and correct within-band proportions at once. The
    groups that scale below 50 are demoted into the mid band at their scaled size, and
    the surviving large group absorbs the band's remaining tickets so the band's share
    is exact: 190 + 26 = 216 = 14.40%, against a real 14.40%.

    Mid groups are sampled at their real, unscaled size - a size-14 group in the fixture
    is a genuine size-14 group from the corpus - until the mid budget is spent, and
    singletons take whatever remains so the total is exact however the rest rounds.
    """
    rng = random.Random(seed)
    real_rows = profile["source"]["row_count"]
    dist = {int(size): n for size, n in profile["clusters"]["size_distribution"].items()}
    scale = rows / real_rows

    large = sorted(
        (size for size, n in dist.items() if size >= LARGE_GROUP for _ in range(n)),
        reverse=True,
    )
    scaled = [round(size * scale) for size in large]
    if scaled and min(scaled) < MIN_LARGE_GROUP:
        smallest_real, smallest_scaled = next(
            (real, small) for real, small in zip(large, scaled, strict=True) if small == min(scaled)
        )
        raise ValueError(
            f"rows={rows} is too small to hold the scaled large groups: a real group "
            f"of {smallest_real} tickets scales to {smallest_scaled}, under the "
            f"minimum of {MIN_LARGE_GROUP}, so it would vanish from the fixture "
            f"and its tickets be silently redistributed"
        )

    budget = round(sum(size * n for size, n in dist.items() if size >= LARGE_GROUP) * scale)
    survivors = [size for size in scaled if size >= LARGE_GROUP]
    demoted = [size for size in scaled if size < LARGE_GROUP]
    if survivors:
        survivors[0] += budget - sum(survivors)
    elif budget:
        survivors = [budget]
    sizes = list(survivors)

    # Demoted groups are mid groups now, so they are paid for out of the mid budget
    # rather than added on top of it. Adding them on top is where the old planner's
    # +1.67 point mid drift and -1.74 point large drift came from, in mirror image.
    mid_budget = round(sum(s * n for s, n in dist.items() if 2 <= s < LARGE_GROUP) * scale)
    spent = 0
    placed = []
    for size in demoted:
        if size >= 2 and spent + size <= mid_budget:
            placed.append(size)
            spent += size
    sizes.extend(placed)

    # An unscaled mid group must not outrank a demoted one: a real 58-ticket group
    # scales to 5 here, and a sampled 14 above it would put a former large structure
    # below a mid one. Capping the pool at the smallest demoted size keeps the rank
    # order the corpus has, without touching the budget, which is unrelated to rank.
    mid_cap = min(placed) if placed else LARGE_GROUP - 1
    pool = [s for s, n in dist.items() if 2 <= s <= mid_cap for _ in range(n)]
    rng.shuffle(pool)
    for size in pool:
        if spent + size <= mid_budget:
            sizes.append(size)
            spent += size

    singletons = rows - sum(sizes)
    if singletons < 0:
        raise ValueError(
            f"rows={rows} is too small to hold the scaled large groups "
            f"({sum(sizes)} tickets); the fixture would lose its structure"
        )
    sizes.extend([1] * singletons)
    return sizes


@dataclass(frozen=True)
class CustomField:
    """One customData field the client records, and how to synthesise its values."""

    name: str
    kind: str
    share: float
    shape_mix: list[tuple[str, float]]  # (shape, weight); weights sum to 1.0
    # Fields filled by the same form share a block. 21 real fields share present_count
    # 2549 exactly; they are one handover form, present or absent together, and that
    # correlation is the structural cause of the corpus's largest near-duplicate group.
    #
    # None means "no form": the field stands alone. A shared DEFAULT must never read as
    # a shared form. This defaulted to 0, which is also the first id plan() hands out, so
    # any two hand-built fields that omitted `block=` were merged into a phantom form and
    # the second silently inherited the first's row set - baugruppe's planned 378 rows
    # came out as fehlercode's 264, breaching the +/-2.0 point share tolerance. Explicit
    # ids still group normally, 0 included, so `block=0` twice means what it looks like.
    block: int | None = None


def block_key(field: CustomField, index: int) -> object:
    """The key that decides which fields are one form.

    Shared by the renderer and the verifier deliberately: if they disagreed about what a
    form is, the verifier would bless exactly the fixtures the renderer got wrong. A
    field with `block=None` carries no form and gets a key nothing else can collide with.
    """
    return field.block if field.block is not None else ("solo", index)


@dataclass(frozen=True)
class FixturePlan:
    rows: int
    seed: int
    group_sizes: list[int]
    solutions_fill: float
    fill_by_year: dict[str, dict[str, float]]
    custom_fields: list[CustomField]
    # Tickets per calendar month in the real corpus. The fixture spreads its rows in
    # this proportion; cycling the years evenly gave 2020, with 71 real tickets, a
    # sixth of the fixture.
    month_weights: dict[str, int] = dataclass_field(default_factory=dict)


def plan(profile: dict, rows: int = 1500, seed: int = 7) -> FixturePlan:
    """Every number the fixture needs, derived from the profile artifact."""
    real_rows = profile["source"]["row_count"]

    by_year: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for column, months in profile.get("temporal", {}).get("fill_by_month", {}).items():
        for month, rate in months.items():
            by_year[month[:4]][column].append(rate)
    fill_by_year = {
        year: {column: sum(v) / len(v) for column, v in columns.items()}
        for year, columns in by_year.items()
    }

    fields = []
    block_ids: dict[int, int] = {}
    for field in profile.get("custom_data", {}).get("envelope", {}).get("fields", []):
        shapes = field.get("value_shapes", [])
        total = sum(s["count"] for s in shapes)
        present = field["present_count"]
        block_ids.setdefault(present, len(block_ids))
        fields.append(
            CustomField(
                name=field["name"],
                kind=field["kind"],
                share=present / real_rows,
                shape_mix=[(s["shape"], s["count"] / total) for s in shapes] if total else [],
                block=block_ids[present],
            )
        )

    return FixturePlan(
        rows=rows,
        seed=seed,
        group_sizes=group_sizes(profile, rows, seed),
        solutions_fill=profile.get("solutions", {}).get("fill_rate", 0.0),
        fill_by_year=fill_by_year,
        custom_fields=fields,
        month_weights=dict(profile.get("temporal", {}).get("created_per_month", {})),
    )
