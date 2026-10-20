"""Check the rendered fixture against the plan.

Generation is not reproducible, so correctness cannot come from repeating it. It comes
from checking the result. Every tolerance here is the one written in the design doc.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from fixtures.plan import FixturePlan, block_key
from profiler.stats import customdata
from recall.german.identifiers import shape_of

FIELD_SHARE_TOLERANCE = 0.02
FILL_TOLERANCE = 0.02
SHAPE_MIX_TOLERANCE = 0.03
FILL_BY_YEAR_TOLERANCE = 0.05

# Below this many rows the shape-mix tolerance is arithmetically unreachable: shapes are
# allocated by largest remainder, so each one still rounds to a whole row and the error
# can be as large as 1/n. 1/34 < 0.03; 1/33 is not.
SHAPE_MIX_MIN_ROWS = 34


def check(rows: list[dict[str, str]], plan: FixturePlan, groups: list[int]) -> list[str]:
    """Every way the fixture drifted from its plan. Empty means faithful.

    `groups` is the group each row belongs to, in row order - `[t.group for t in
    tickets]`. It is required rather than optional because a check that silently does
    not run is the failure this module exists to prevent.
    """
    problems: list[str] = []

    if len(rows) != plan.rows:
        problems.append(f"row count is {len(rows)}, planned {plan.rows}")

    if rows:
        filled = sum(1 for r in rows if (r.get("solutions") or "").strip())
        actual = filled / len(rows)
        if abs(actual - plan.solutions_fill) > FILL_TOLERANCE:
            problems.append(f"solutions fill is {actual:.3f}, planned {plan.solutions_fill:.3f}")

    present: dict[str, int] = {}
    shapes: dict[str, Counter] = defaultdict(Counter)
    # One entry per row, in row order, so per_row_names[i] describes rows[i] and
    # groups[i]. An unparsable row still gets its (empty) entry: skipping it would shift
    # every later row's names onto the wrong group and the cluster check below would
    # silently compare the wrong rows.
    per_row_names: list[set[str]] = []
    unparsed = 0
    for row in rows:
        records = customdata.parse_records(row.get("customData"))
        if records is None:
            unparsed += 1
            per_row_names.append(set())
            continue
        for name in {r.get("key") for r in records if isinstance(r.get("key"), str)}:
            present[name] = present.get(name, 0) + 1
        for record in records:
            name, value = record.get("key"), record.get("value")
            if isinstance(name, str) and isinstance(value, str):
                shapes[name][shape_of(value)] += 1
        per_row_names.append({r.get("key") for r in records if isinstance(r.get("key"), str)})

    if unparsed:
        problems.append(
            f"{unparsed} of {len(rows)} customData values do not round-trip through "
            f"parse_records; an empty envelope parses to [] and is not one of them"
        )

    for field in plan.custom_fields:
        actual = present.get(field.name, 0) / len(rows) if rows else 0.0
        if abs(actual - field.share) > FIELD_SHARE_TOLERANCE:
            problems.append(
                f"customData field {field.name} present in {actual:.3f} of rows, "
                f"planned {field.share:.3f}"
            )

    for field in plan.custom_fields:
        planned_rows = round(field.share * len(rows))
        if not field.shape_mix or planned_rows < SHAPE_MIX_MIN_ROWS:
            continue
        counts = shapes.get(field.name, Counter())
        total = sum(counts.values())
        if not total:
            problems.append(f"customData field {field.name} carries no values to shape")
            continue
        for shape, weight in field.shape_mix:
            actual = counts.get(shape, 0) / total
            if abs(actual - weight) > SHAPE_MIX_TOLERANCE:
                problems.append(
                    f"customData field {field.name} shape {shape} is {actual:.3f} of its "
                    f"values, planned {weight:.3f}"
                )

    if len(groups) != len(rows):
        problems.append(f"{len(groups)} group assignments for {len(rows)} rows")
    else:
        actual_sizes = sorted(Counter(groups).values(), reverse=True)
        planned_sizes = sorted(plan.group_sizes, reverse=True)
        if actual_sizes != planned_sizes:
            problems.append(
                f"group sizes drifted: largest {actual_sizes[:4]} against planned "
                f"{planned_sizes[:4]}, {len(actual_sizes)} groups against {len(planned_sizes)}"
            )

    by_year: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_year[(row.get("timestampCreated") or "")[:4]].append(row)
    for year, planned_fill in plan.fill_by_year.items():
        dated = by_year.get(year, [])
        if not dated:
            problems.append(f"no rows are dated {year}, which the plan gives fill rates")
            continue
        # A year holding 7 of 1,500 rows cannot express a rate to better than half a
        # row: 91.67% rounds to 6 of 7, 5.95 points out before anything went wrong.
        tolerance = max(FILL_BY_YEAR_TOLERANCE, 0.5 / len(dated))
        for column, rate in planned_fill.items():
            filled = sum(1 for row in dated if (row.get(column) or "").strip())
            actual_rate = filled / len(dated)
            if abs(actual_rate - rate) > tolerance:
                problems.append(
                    f"{column} fill in {year} is {actual_rate:.3f} over {len(dated)} "
                    f"rows, planned {rate:.3f}"
                )

    # Neither check below has a tolerance. They are not measurements that can drift, they
    # are structural facts: a form is filled by one action, and the cluster IS the form.
    by_block: dict[object, list[str]] = defaultdict(list)
    for index, field in enumerate(plan.custom_fields):
        by_block[block_key(field, index)].append(field.name)

    for block, names in by_block.items():
        if len(names) < 2:
            continue
        carried = [{name for name in names if name in row_names} for row_names in per_row_names]
        broken = sum(1 for held in carried if held and len(held) != len(names))
        if broken:
            problems.append(
                f"block {block} is half-filled in {broken} rows: a form of "
                f"{len(names)} fields ({', '.join(sorted(names)[:3])}...) is filled by "
                f"one action, so a row carries all of it or none"
            )
        if len(groups) == len(rows):
            largest = Counter(groups).most_common(1)[0][0]
            missing = sum(
                1 for index, group in enumerate(groups) if group == largest and not carried[index]
            )
            if missing:
                problems.append(
                    f"block {block} is absent from {missing} rows of the largest group; "
                    f"in the real corpus that cluster IS the form - 2,034 of its 2,549 "
                    f"carriers are the group"
                )

    return problems
