"""Generate the synthetic fixture.

    uv run python -m fixtures --profile local/artifacts/profile.json \\
        --out local/fixtures/export.csv --fake

Drop --fake and pass --base-url to use the model on the H100. Generation reads a gated
artifact and produces invented text, so it needs no airlock window - the box is used for
compute, not for data access.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from collections import defaultdict

from fixtures import generate, llm, render, verify
from fixtures.plan import FixturePlan
from fixtures.plan import plan as build_plan


def months_for_rows(fixture_plan: FixturePlan, rows: int, rng: random.Random) -> list[str]:
    """One month per ticket, in the real corpus's monthly volume.

    The old code sorted fill_by_year's keys - four-character YEARS - called them months,
    cycled them round-robin and drew the calendar month at random, so ticket volume per
    year was wrong and the per-year rates were never read at all.

    The months are shuffled because group members are contiguous in the ticket list: an
    ordered assignment would drop the whole 216-member cluster into one month and make
    its fill rate the fill rate of a single year.
    """
    weights = fixture_plan.month_weights or {
        f"{year}-{month:02d}": 1
        for year in (sorted(fixture_plan.fill_by_year) or ["2024"])
        for month in range(1, 13)
    }
    months = sorted(weights)
    total = sum(weights.values()) or 1
    exact = [rows * weights[month] / total for month in months]
    counts = [int(value) for value in exact]
    order = sorted(range(len(months)), key=lambda i: exact[i] - counts[i], reverse=True)
    for index in order[: rows - sum(counts)]:
        counts[index] += 1
    out = [month for month, n in zip(months, counts, strict=True) for _ in range(n)]
    rng.shuffle(out)
    return out


def fill_flags(
    months: list[str], fixture_plan: FixturePlan, column: str, rng: random.Random
) -> list[bool]:
    """Which rows carry `column`, at exactly its measured share of each YEAR's rows.

    Exactly, not per-row coin flips: the same lesson customData field shares already
    learned, and at 7 rows for 2020 a flip is not a rate at all.
    """
    flags = [True] * len(months)
    by_year: dict[str, list[int]] = defaultdict(list)
    for index, month in enumerate(months):
        by_year[month[:4]].append(index)
    for year, indices in by_year.items():
        rate = fixture_plan.fill_by_year.get(year, {}).get(column)
        if rate is None:
            continue
        keep = set(rng.sample(indices, round(rate * len(indices))))
        for index in indices:
            flags[index] = index in keep
    return flags


# Below this many members, a group's description is blanked as a UNIT.
#
# The generator gives every member of a group the same title and description so the group
# clusters by construction, but per-row blanking then breaks it: a blanked row's cleaned token
# set is its TITLE ALONE and cannot reach 0.7 Jaccard against title+description. Measured
# 2026-08-26 with zero exceptions - of the groups of size 2, all 14 with exactly one member
# blanked SPLIT, and all 17 with 0 or 2 blanked held together. 27 of 51 groups had a loose
# member and 24 rows ended up alone, inflating the singleton band and deflating mid.
#
# Groups of 50 or more are EXCLUDED on purpose. Forcing all 216 rows of the dominant group one
# way is a 14.4% swing, measured to push description fill-by-year out of tolerance in 2022
# (+0.1070) and 2023 (+0.1037), which makes verify refuse the fixture outright. That group's
# own split costs nothing while both halves clear 50, so the large band is exactly 0.1440.
COHESIVE_BLANK_MAX = 50


def cohere_by_group(
    flags: list[bool],
    groups: list[int],
    group_sizes: list[int],
    limit: int = COHESIVE_BLANK_MAX,
) -> list[bool]:
    """Make a small group's description blanking all-or-nothing.

    Keeps whichever way the majority of the group was already drawn, ties keeping the
    description, so the per-year rates fill_flags allocated move as little as possible while
    the group can still cluster. Applied to `description` only: `solutions` must stay per row,
    because one problem with many DIFFERENT resolutions is the entire point of a group, and
    cohering solutions would blank every variant in a group at once.
    """
    rows_by_group: dict[int, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        rows_by_group[group].append(index)
    out = list(flags)
    for group, indices in rows_by_group.items():
        size = group_sizes[group] if 0 <= group < len(group_sizes) else 1
        if not 2 <= size < limit:
            continue
        kept = sum(1 for index in indices if flags[index])
        keep_all = kept * 2 >= len(indices)
        for index in indices:
            out[index] = keep_all
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixtures")
    parser.add_argument("--profile", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--rows", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fake", action="store_true", help="no GPU; deterministic stub")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("local/fixtures/cache"))
    args = parser.parse_args(argv)

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    fixture_plan = build_plan(profile, rows=args.rows, seed=args.seed)

    inner = llm.Fake(seed=args.seed) if args.fake else llm.VLLM(args.base_url, args.model)
    client = llm.Cached(inner, args.cache, inner.identity)

    stats: dict[str, int] = {}
    tickets = generate.tickets(fixture_plan.group_sizes, client, stats)
    if stats["padded"]:
        print(
            f"WARNING padded {stats['padded']} of {len(tickets)} tickets across "
            f"{stats['groups_short']} short groups; padded tickets are byte-identical "
            f"within their group and carry no solution"
        )
    rng = random.Random(args.seed)
    months = months_for_rows(fixture_plan, len(tickets), rng)
    keep_solution = fill_flags(months, fixture_plan, "solutions", rng)
    keep_description = cohere_by_group(
        fill_flags(months, fixture_plan, "description", rng),
        [ticket.group for ticket in tickets],
        fixture_plan.group_sizes,
    )
    custom_by_row = render.custom_fields_for_rows(
        fixture_plan.custom_fields, len(tickets), rng, [ticket.group for ticket in tickets]
    )
    rows = []
    for index, ticket in enumerate(tickets):
        rows.append(
            render.row(
                index=index + 1,
                title=ticket.title,
                description=ticket.description if keep_description[index] else "",
                solution=ticket.solution if keep_solution[index] else "",
                month=months[index],
                custom=custom_by_row[index],
                rng=rng,
            )
        )

    problems = verify.check(rows, fixture_plan, [ticket.group for ticket in tickets])
    if problems:
        print("ABORT the fixture drifted from its plan:")
        for problem in problems:
            print(f"  - {problem}")
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        render.write_csv(rows, handle)
    print(f"wrote {args.out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
