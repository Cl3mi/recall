"""Baugruppe x model x year, with the floor applied to each CELL.

Flooring the margins is not enough: B-10 and TX-2210 can each be common while the one cell
where they meet holds a single vehicle line's tickets. `release.release` floors the tuple.

The floor counts TICKETS here, unlike serial prefix buckets, which count vehicles. No
component of a cell is a serial, so a cell says something about a model line and a year, not
about one vehicle. Cells under the floor are withheld and tallied, never folded into an
'other' cell.
"""

from __future__ import annotations

from collections import Counter

from insight import measures, release
from insight.extract import Ticket


def baugruppe_model_year(tickets: list[Ticket], k: int = release.K) -> dict:
    """Exploded per id: a ticket carrying two Baugruppe ids counts once in the cell of each.
    `coverage` counts tickets, not the cells they were exploded into."""
    complete = [t for t in tickets if t.baugruppe and t.model and t.created_year]
    cells = Counter(
        (i, t.model, t.created_year) for t in complete for i in sorted(set(t.baugruppe))
    )
    kept, withheld = release.release(cells, ("value", "model", None), k)
    return {
        "coverage": measures.coverage(len(complete), len(tickets)),
        "cells": [{"value": b, "model": m, "year": y, "count": n} for (b, m, y), n in kept],
        "withheld": withheld,
    }
