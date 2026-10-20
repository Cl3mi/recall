"""Spec sections 3 and 7: volume and fill over time, recurrence, and time to a status change.

A year or a month is structural, so each count is released through `release.release` with a
None field and floored. A vehicle is identified by its serial for the recurrence arithmetic, but
the serial is only ever a dict key inside `_recurrence`: the output holds numbers. A date that
does not parse is an absent date (`extract.parse_date` already returned None for it), and
every block says how many tickets it could use. Quantiles and shares stand on at least `k`
observations, else the block is zeros with `below_floor` set, because a quantile of two gaps
is those two gaps.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable

from insight import measures, release
from insight.extract import Ticket

WINDOWS = (30, 90, 365)

# What a month label looks like (`extract` writes it from a parsed date). The guard admits a month
# string only where this module emits one, and only in this shape.
MONTH = re.compile("[0-9]{4}-(0[1-9]|1[0-2])")

# What "filled" means for each column of the per-year fill table. Text must be non-blank; the
# dates are the PARSED dates, so an unparseable one is absent.
_FILLED: dict[str, Callable[[Ticket], bool]] = {
    "description": lambda t: bool(t.description.strip()),
    "solutions": lambda t: bool(t.solutions.strip()),
    "serial": lambda t: bool(t.serial),
    # `model_id`, not `model`: `model` is the name of a released STRING field, and the guard refuses
    # any non-string value under that name, which a fill share would be.
    "model_id": lambda t: bool(t.model),
    "baugruppe": lambda t: bool(t.baugruppe),
    "fehlercode": lambda t: bool(t.fehlercode),
    "hours": lambda t: t.hours is not None,
    "delivery": lambda t: t.delivery is not None,
}


def _fill_by_year(tickets: list[Ticket], kept_years: list[str]) -> list[dict]:
    by_year: dict[str, list[Ticket]] = defaultdict(list)
    for t in tickets:
        if t.created_year:
            by_year[t.created_year].append(t)
    out = []
    for year in kept_years:
        group = by_year[year]
        entry: dict = {"year": year, "tickets": len(group)}
        for name, filled in _FILLED.items():
            entry[name] = measures.ratio(sum(1 for t in group if filled(t)), len(group))
        out.append(entry)
    return out


def _recurrence(tickets: list[Ticket], k: int) -> dict:
    by_vehicle: dict[str, list] = defaultdict(list)
    usable = 0
    for t in tickets:
        if t.serial and t.created:
            by_vehicle[t.serial].append(t.created)
            usable += 1
    gaps = []
    for days in by_vehicle.values():
        days.sort()
        gaps += [(later - earlier).days for earlier, later in zip(days, days[1:], strict=False)]
    quantiles, small = measures.floored_quantiles(gaps, k)
    out = {
        "coverage": measures.coverage(usable, len(tickets)),
        "vehicles": len(by_vehicle),
        "below_floor": small,
    }
    # Everything below is about tickets WITH a previous ticket on the same vehicle; a vehicle's
    # first ticket has none, so it is in neither the numerator nor the denominator.
    enough = len(gaps) >= k
    out["tickets_with_previous"] = len(gaps) if enough else 0
    out["gap_days_quantiles"] = quantiles
    for days in WINDOWS:
        share = measures.ratio(sum(1 for g in gaps if g <= days), len(gaps)) if enough else 0.0
        out[f"repeat_within_{days}_share"] = share
    return out


def _resolution(tickets: list[Ticket], k: int) -> dict:
    days = [(t.status_changed - t.created).days for t in tickets if t.created and t.status_changed]
    quantiles, small = measures.floored_quantiles(days, k)
    return {
        "coverage": measures.coverage(len(days), len(tickets)),
        "days_to_status_change_quantiles": quantiles,
        "negative_share": measures.ratio(sum(1 for d in days if d < 0), len(days))
        if not small and days
        else 0.0,
        "below_floor": small,
    }


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    years, years_withheld = release.release(
        Counter(t.created_year for t in tickets if t.created_year), (None,), k
    )
    months, months_withheld = release.release(
        Counter(t.created_month for t in tickets if t.created_month), (None,), k
    )
    return {
        "coverage": measures.coverage(sum(1 for t in tickets if t.created_year), len(tickets)),
        "per_year": [{"year": y, "count": n} for y, n in sorted(years)],
        "per_year_withheld": years_withheld,
        "per_month": [{"month": m, "count": n} for m, n in sorted(months)],
        "per_month_withheld": months_withheld,
        "fill_by_year": _fill_by_year(tickets, sorted(y for y, _ in years)),
        "fill_by_year_withheld": years_withheld,
        "recurrence": _recurrence(tickets, k),
        "resolution": _resolution(tickets, k),
    }
