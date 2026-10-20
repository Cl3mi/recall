"""Spec section 6: how old the vehicle was when the ticket arrived.

Hours, days since delivery and warranty status at ticket time. Bucket labels are fixed literals
defined once in `BUCKETS`; each bucket count is released through `release.release` with a
structural None field, so a small bucket is withheld and counted, and the buckets come out in
the order of the literals, never in the order of their counts. A date that does not parse is
absent. Quantiles stand on at least `k` observations, else zeros with `below_floor` set.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date

from insight import measures, release
from insight.extract import Ticket

# Upper edges (exclusive) of every bucket but the last of each series.
HOUR_EDGES = (100, 500, 1000, 2000, 5000)
DAY_EDGES = (30, 90, 180, 365, 730, 1460)

BUCKETS = {
    "hours": ("0-99", "100-499", "500-999", "1000-1999", "2000-4999", "5000+"),
    "days_since_delivery": (
        "negative",
        "0-29",
        "30-89",
        "90-179",
        "180-364",
        "365-729",
        "730-1459",
        "1460+",
    ),
}
STATES = ("in", "out", "unknown")


def _index(value: float, edges: tuple[int, ...]) -> int:
    return next((i for i, edge in enumerate(edges) if value < edge), len(edges))


def _hours_label(hours: float) -> str:
    return BUCKETS["hours"][_index(hours, HOUR_EDGES)]


def _days_label(days: int) -> str:
    if days < 0:
        return BUCKETS["days_since_delivery"][0]
    return BUCKETS["days_since_delivery"][1 + _index(days, DAY_EDGES)]


def _ordered(kept: list, labels: tuple[str, ...], name: str) -> list[dict]:
    counts = dict(kept)
    return [{name: label, "count": counts[label]} for label in labels if label in counts]


def _series(
    values: list[float], label: Callable[[float], str], series: str, total: int, k: int
) -> dict:
    kept, withheld = release.release(Counter(label(v) for v in values), (None,), k)
    quantiles, small = measures.floored_quantiles(values, k)
    return {
        "coverage": measures.coverage(len(values), total),
        "quantiles": quantiles,
        "below_floor": small,
        "buckets": _ordered(kept, BUCKETS[series], "bucket"),
        "buckets_withheld": withheld,
    }


def _warranty_state(t: Ticket) -> str:
    """Both bounds and the ticket date are needed to say in or out; one bound is a guess."""
    if t.created is None or t.warranty_start is None or t.warranty_end is None:
        return "unknown"
    return "in" if t.warranty_start <= t.created <= t.warranty_end else "out"


def _warranty(tickets: list[Ticket], k: int) -> dict:
    states = [_warranty_state(t) for t in tickets]
    kept, withheld = release.release(Counter(states), (None,), k)
    return {
        "coverage": measures.coverage(sum(1 for s in states if s != "unknown"), len(tickets)),
        "states": _ordered(kept, STATES, "state"),
        "states_withheld": withheld,
    }


def _days_since(created: date, delivery: date) -> int:
    return (created - delivery).days


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    hours = [t.hours for t in tickets if t.hours is not None]
    days = [_days_since(t.created, t.delivery) for t in tickets if t.created and t.delivery]
    return {
        "hours": _series(hours, _hours_label, "hours", len(tickets), k),
        "days_since_delivery": _series(days, _days_label, "days_since_delivery", len(tickets), k),
        "warranty": _warranty(tickets, k),
    }
