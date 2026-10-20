"""Spec section 9: what the titles and the solutions are made of.

Tokens, bigrams and trigrams only, each floored and swept as a `token` (which includes the
first-name list), after the same cleaning `origin.titles` applies. A solution is never released
as text: the longest thing that leaves is three words, and only if at least k tickets share it.
`by_category` floors the (category, token) CELL, so a word that is common overall but rare inside
one category does not appear under it, and a category itself must clear the floor.
"""

from __future__ import annotations

from collections import Counter

from insight import docfreq, measures, release
from insight.extract import Ticket
from recall.clean import pipeline

MAX_LISTED = 100
MAX_PER_CATEGORY = 30


def _listed(counts: Counter, k: int, limit: int = MAX_LISTED) -> tuple[list[dict], dict, int]:
    kept, withheld = release.release(counts, "token", k)
    return (
        [{"token": t, "count": n} for t, n in kept[:limit]],
        withheld,
        max(0, len(kept) - limit),
    )


def _ngrams(cleaned: list[str], k: int, kinds: dict) -> dict:
    out: dict = {}
    for name, count in kinds.items():
        listed, withheld, omitted = _listed(count(cleaned), k)
        out[name] = listed
        out[f"{name}_withheld"] = withheld
        out[f"{name}_omitted"] = omitted
    return out


def _sum_withheld(blocks: list[dict]) -> dict:
    total = {
        "below_floor": {"distinct": 0, "rows": 0},
        "entity_like": {"distinct": 0, "rows": 0},
    }
    for block in blocks:
        for reason, tally in block.items():
            for key, n in tally.items():
                total[reason][key] += n
    return total


def _by_category(groups: dict[str, list[tuple[str, str]]], k: int) -> dict:
    kept, below = release.release(Counter({c: len(g) for c, g in groups.items()}), "value", k)
    entries = []
    for category, n in kept:
        titles = docfreq.tokens([title for title, _ in groups[category]])
        solutions = docfreq.tokens([solution for _, solution in groups[category]])
        title_tokens, title_withheld, title_omitted = _listed(titles, k, MAX_PER_CATEGORY)
        sol_tokens, sol_withheld, sol_omitted = _listed(solutions, k, MAX_PER_CATEGORY)
        entries.append(
            {
                "value": category,
                "count": n,
                "title_tokens": title_tokens,
                "title_tokens_withheld": title_withheld,
                "title_tokens_omitted": title_omitted,
                "solution_tokens": sol_tokens,
                "solution_tokens_withheld": sol_withheld,
                "solution_tokens_omitted": sol_omitted,
            }
        )
    return {"by_category": entries, "by_category_withheld": below}


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    titles = [pipeline.clean(t.title).text for t in tickets]
    solutions = [pipeline.clean(t.solutions).text for t in tickets]
    groups: dict[str, list[tuple[str, str]]] = {}
    for t, title, solution in zip(tickets, titles, solutions, strict=True):
        if t.category:
            groups.setdefault(t.category, []).append((title, solution))
    out = {
        "titles_trigrams": _ngrams(titles, k, {"trigrams": docfreq.trigrams}),
        "solutions": {
            "fill": measures.ratio(sum(1 for t in tickets if t.solutions.strip()), len(tickets)),
            **_ngrams(
                solutions,
                k,
                {
                    "tokens": docfreq.tokens,
                    "bigrams": docfreq.bigrams,
                    "trigrams": docfreq.trigrams,
                },
            ),
        },
    }
    out.update(_by_category(groups, k))
    return out
