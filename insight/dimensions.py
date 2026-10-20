"""Spec section 4: the categorical columns, and what each category looks like.

Every value is released through `release.release` with the `value` sweep, so a floored value
that reads as an entity (a company typed into a sub-status) is withheld and counted. The year
cells are floored as cells. Everything else is a count, a share or a length.

Problem text is the CLEANED title + description, as `texts` defines it, and its length is in
whitespace tokens.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from insight import measures, release
from insight.extract import Ticket
from profiler.stats import lengths
from recall.clean import pipeline

_GETTERS: dict[str, Callable[[Ticket], str | None]] = {
    "categoryId": lambda t: t.category,
    "statusId": lambda t: t.status,
    "priorityId": lambda t: t.priority,
    "subStatusString": lambda t: t.sub_status,
    "vehicleStatus": lambda t: t.vehicle_status,
    "showInProteam": lambda t: t.show_in_proteam,
    "contractTransaction": lambda t: t.contract_transaction,
}

COLUMNS = tuple(_GETTERS)


def _column(tickets: list[Ticket], get: Callable[[Ticket], str | None], k: int) -> dict:
    values = [(v, t.created_year) for t in tickets if (v := get(t))]
    counts = Counter(v for v, _ in values)
    kept, withheld = release.release(counts, "value", k)
    cells = Counter((v, year) for v, year in values if year)
    by_year, by_year_withheld = release.release(cells, ("value", None), k)
    return {
        "coverage": measures.coverage(len(values), len(tickets)),
        "distinct": len(counts),
        "values": [{"value": v, "count": n} for v, n in kept],
        "withheld": withheld,
        "by_year": [{"value": v, "year": y, "count": n} for (v, y), n in by_year],
        "by_year_withheld": by_year_withheld,
    }


def _problem_length(ticket: Ticket) -> int:
    return len(pipeline.clean(f"{ticket.title} {ticket.description}").text.split())


def _by_category(tickets: list[Ticket], k: int) -> dict:
    groups: dict[str, list[Ticket]] = {}
    for t in tickets:
        if t.category:
            groups.setdefault(t.category, []).append(t)
    kept, withheld = release.release(Counter({c: len(g) for c, g in groups.items()}), "value", k)
    entries = []
    for category, n in kept:
        group = groups[category]
        problem = lengths.quantiles([_problem_length(t) for t in group])
        entries.append(
            {
                "value": category,
                "count": n,
                "solution_fill": measures.ratio(sum(1 for t in group if t.solutions.strip()), n),
                "description_fill": measures.ratio(
                    sum(1 for t in group if t.description.strip()), n
                ),
                "problem_text_length_median": problem["p50"],
                "problem_text_length_p95": problem["p95"],
            }
        )
    return {"by_category": entries, "by_category_withheld": withheld}


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    out = {column: _column(tickets, get, k) for column, get in _GETTERS.items()}
    out.update(_by_category(tickets, k))
    return out
