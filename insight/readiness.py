"""Spec section 10: how much of the corpus a retrieval system could actually use.

Counts and shares only. No solution text is ever released: duplicate solutions are counted as
tickets, not shown, so nothing here goes through `release.release` and nothing needs a sweep.
`k` is the minimum size of a near-duplicate cluster (templated) and of a group of tickets
sharing one exact solution text (a duplicate solution), the same floor as everywhere else.
"""

from __future__ import annotations

from collections import Counter

from insight import measures, release, texts
from insight.extract import Ticket


def _count(n: int, total: int) -> dict:
    return {"tickets": n, "share": measures.ratio(n, total)}


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    total = len(tickets)
    sizes = texts.cluster_sizes(tickets)
    templated = [size >= k for size in sizes]
    has_solution = [bool(t.solutions.strip()) for t in tickets]
    shared = Counter(
        t.solutions.strip() for t, has in zip(tickets, has_solution, strict=True) if has
    )
    return {
        "total": total,
        "blank_problem_text": sum(1 for size in sizes if size == 0),
        "complete_triple": _count(
            sum(
                1
                for t, has in zip(tickets, has_solution, strict=True)
                if has and t.title.strip() and t.description.strip()
            ),
            total,
        ),
        "templated": _count(sum(templated), total),
        "solution_present": _count(sum(has_solution), total),
        "duplicate_solution_share": _count(
            sum(
                1
                for t, has in zip(tickets, has_solution, strict=True)
                if has and shared[t.solutions.strip()] >= k
            ),
            total,
        ),
        "usable": _count(
            sum(
                1
                for is_templated, has in zip(templated, has_solution, strict=True)
                if has and not is_templated
            ),
            total,
        ),
    }
