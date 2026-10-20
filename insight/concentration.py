"""Spec section 5: where tickets come from, as numbers only.

Dealers, end customers, creators, assignees, persons and the last-modified user are personal
data or identify an organisation, so NOTHING in this module is ever released: not an id, not a
name, not a rank-ordered list that could be matched to one. An entity is counted and then only
the distribution of the counts survives. There is deliberately no call to `release.release`
here, and no string in the output; the floor does not apply because no value leaves.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from insight import measures
from insight.extract import Ticket
from profiler.stats import lengths

_GETTERS: dict[str, Callable[[Ticket], str | None]] = {
    "merchantId": lambda t: t.merchant,
    "endCustomerId": lambda t: t.end_customer,
    "userCreatedId": lambda t: t.creator,
    "userAssignedId": lambda t: t.assignee,
    "personId": lambda t: t.person,
    "lastModifiedUser": lambda t: t.last_modified,
}

COLUMNS = tuple(_GETTERS)


def _column(tickets: list[Ticket], get: Callable[[Ticket], str | None]) -> dict:
    per_entity = Counter(v for t in tickets if (v := get(t)))
    ordered = sorted(per_entity.values(), reverse=True)
    present = sum(ordered)
    return {
        "coverage": measures.coverage(present, len(tickets)),
        "distinct": len(ordered),
        "per_entity_quantiles": lengths.quantiles(ordered),
        "top1_share": measures.top_share(ordered, 1, present),
        "top5_share": measures.top_share(ordered, 5, present),
        "top10_share": measures.top_share(ordered, 10, present),
        "gini": measures.gini(ordered),
    }


def build(tickets: list[Ticket], k: int | None = None) -> dict:
    """`k` is accepted for the section interface and unused: nothing here is floored because
    nothing here is a value."""
    return {column: _column(tickets, get) for column, get in _GETTERS.items()}
