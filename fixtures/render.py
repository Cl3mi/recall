"""Assemble fixture rows in exactly the shape the real export uses."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from typing import TextIO

from fixtures import values
from fixtures.plan import CustomField, block_key
from profiler.columns import EXPECTED_COLUMNS


def custom_data(fields: list[tuple[str, str]]) -> str:
    """The client's customData encoding: descriptors, serialised twice.

    json.dumps of a json.dumps, so the CSV field opens with a quote and a single
    json.loads returns a string rather than a container. Round 2 parsed 0% of 16,053
    real values because nothing rehearsed this.
    """
    records = [
        {
            "group": "Allgemein",
            "key": name,
            "label": f"Feld {name}",
            "value": value,
            "text": value,
            "type": "string",
        }
        for name, value in fields
    ]
    return json.dumps(json.dumps(records, ensure_ascii=False), ensure_ascii=False)


def _allocate(mix: list[tuple[str, float]], count: int) -> list[str]:
    """Largest-remainder allocation of `count` values over the measured shape mix.

    Each shape gets floor(weight * count), and the leftover goes to the largest
    fractional parts, so every shape lands within one row of its measured proportion on
    every seed. Sampling per row instead reproduces the mix only in expectation.
    """
    exact = [weight * count for _, weight in mix]
    counts = [int(value) for value in exact]
    leftover = count - sum(counts)
    order = sorted(range(len(mix)), key=lambda i: exact[i] - counts[i], reverse=True)
    for index in order[:leftover]:
        counts[index] += 1
    return [shape for (shape, _), n in zip(mix, counts, strict=True) for _ in range(n)]


def custom_fields_for_rows(
    fields: list[CustomField],
    rows: int,
    rng: random.Random,
    groups: list[int] | None = None,
) -> list[list[tuple[str, str]]]:
    """Which fields each ticket carries, at exactly the measured share.

    Deciding each field independently per row reproduces a share only in expectation. At
    1,500 rows the standard error on a 15.9% field is ~0.9 points against a +/-2.0 point
    acceptance tolerance, and across 26 fields that breached on 8 of 10 measured seeds -
    so the committed fixture would have depended on a lucky number. Assigning exactly
    round(share * rows) rows per field makes the share exact and seed-independent.

    Fields are assigned in plan order, so a row's descriptors keep the profile's ordering.

    The same holds for the SHAPE each value takes: shapes are allocated by largest
    remainder over the measured mix and shuffled, not drawn per row, so the mix is
    exact on any seed.

    Fields sharing a block are one form and move together - 21 real fields share
    present_count 2549, and treating them as 21 independent coincidences gave a fixture
    whose p90 was 8 descriptors against a real 21, with no row carrying a whole form. A
    multi-field block is seated on the largest near-duplicate group first, because in the
    real corpus that cluster IS the form: 2,034 of its 2,549 carriers are the group.
    Remaining fields then avoid the form's rows where their own share allows, which is
    what puts p90, p95 and p99 all at exactly 21, as measured.
    """
    per_row: list[list[tuple[str, str]]] = [[] for _ in range(rows)]
    blocks: dict[object, list[CustomField]] = defaultdict(list)
    for index, field in enumerate(fields):
        blocks[block_key(field, index)].append(field)

    # Forms first, so single fields know which rows to avoid.
    ordered = sorted(blocks.values(), key=lambda block: len(block), reverse=True)
    form_rows: set[int] = set()
    for block in ordered:
        count = round(block[0].share * rows)
        if len(block) > 1:
            indices = _seat_on_largest_group(count, rows, rng, groups)
            form_rows |= set(indices)
        else:
            free = [index for index in range(rows) if index not in form_rows]
            if count <= len(free):
                indices = rng.sample(free, count)
            else:  # commoner than the form; disjointness is a preference, the share is not
                taken = [index for index in range(rows) if index in form_rows]
                indices = free + rng.sample(taken, count - len(free))
        for field in block:
            shapes = _allocate(field.shape_mix, len(indices)) if field.shape_mix else []
            rng.shuffle(shapes)
            for offset, index in enumerate(indices):
                value = values.from_shape(shapes[offset], rng) if shapes else ""
                per_row[index].append((field.name, value))
    return per_row


def _seat_on_largest_group(
    count: int, rows: int, rng: random.Random, groups: list[int] | None
) -> list[int]:
    """The form's rows: every member of the largest near-duplicate group, then others.

    All 2,034 members of the real largest group carry the form and 515 further rows do
    too. Seating the form anywhere else reproduces its share while destroying the reason
    the cluster exists, which is the one thing the near-duplicate pipeline is built on.
    """
    seats: list[int] = []
    if groups:
        largest = Counter(groups).most_common(1)[0][0]
        seats = [index for index, group in enumerate(groups) if group == largest][:count]
    rest = [index for index in range(rows) if index not in set(seats)]
    return seats + rng.sample(rest, count - len(seats))


def row(
    index: int,
    title: str,
    description: str,
    solution: str,
    month: str,
    custom: list[tuple[str, str]],
    rng: random.Random,
) -> dict[str, str]:
    """One ticket, with every expected column present.

    Columns the profile shows as opaque identifiers are filled with opaque identifiers;
    the fixture is about structure, so a plausible-looking foreign key is enough.
    """
    day = rng.randint(1, 28)
    filled = {
        "id": str(index),
        "ticketNumber": f"TN-{100000 + index}",
        "title": title,
        "description": description,
        "solutions": solution,
        "customData": custom_data(custom),
        "timestampCreated": f"{month}-{day:02d}",
        "statusId": str(rng.choice([3, 3, 3, 3, 7])),
        "priorityId": str(rng.choice([1, 2, 2, 3])),
        "categoryId": str(rng.randint(1, 12)),
        "vehicleModelId": str(rng.randint(1, 66)),
        "vehicleYear": str(rng.randint(2008, 2025)),
        "vehicleHours": str(rng.randint(50, 12000)),
    }
    return {column: filled.get(column, "") for column in EXPECTED_COLUMNS}


def write_csv(rows: list[dict[str, str]], handle: TextIO) -> None:
    writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
