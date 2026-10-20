"""Spec section 1: where tickets come from.

Every value released here goes through `release.release`; everything else is a count or a
ratio. A serial never appears: per-serial behaviour is reported as quantiles, and the only
serial-derived strings are the opt-in prefix buckets, which never release more than half of any
serial and are floored on distinct vehicles, not tickets.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter

from insight import docfreq, measures, release
from insight.extract import Ticket
from profiler.stats import lengths
from recall.clean import pipeline

MAX_LISTED = 100
# Pairs grow with the square of a ticket's ids; a ticket with more forms none and is counted.
MAX_PAIR_IDS = 10
PREFIX_MIN_COVERED = 0.9


def _id_order(value: str) -> tuple:
    """Numeric ids as numbers ('5' before '12'), then everything else as text. Compared by
    length and then text, so no id is converted to int and none can be too long to convert."""
    if value.isascii() and value.isdigit():
        return (0, len(value), value)
    return (1, 0, value)


def baugruppe(tickets: list[Ticket], k: int = release.K) -> dict:
    """A ticket's Baugruppe is a LIST of ids. Each id counts the tickets carrying it, once per
    ticket however often the list repeats it, so counts are id-ticket assignments: they sum to
    more than the tickets when a ticket carries two ids. The ledger rows are assignments too.

    `coverage` counts tickets with at least one id and `empty` tickets whose list is present but
    empty; a ticket with neither has no Baugruppe field at all. `pairs` are unordered (the
    smaller id first) and floored as cells, like every other cross-tab; a ticket with more than
    MAX_PAIR_IDS ids forms none and is counted in `pairs_skipped`. The released lists are capped
    at MAX_LISTED and say how many entries they omit; an omitted entry was released, not
    withheld, so it is not in the ledger.
    """
    carried = [(t, sorted(set(t.baugruppe), key=_id_order)) for t in tickets]
    carried = [(t, ids) for t, ids in carried if ids]
    counts = Counter(i for _, ids in carried for i in ids)
    assignments = sum(counts.values())
    top, withheld = release.release(counts, "value", k)
    cells = Counter((i, t.created_year) for t, ids in carried if t.created_year for i in ids)
    by_year, by_year_withheld = release.release(cells, ("value", None), k)
    pairable = [ids for _, ids in carried if len(ids) <= MAX_PAIR_IDS]
    pair_counts = Counter(pair for ids in pairable for pair in itertools.combinations(ids, 2))
    pairs, pairs_withheld = release.release(pair_counts, ("value", "partner"), k)
    per_ticket = [len(ids) for _, ids in carried]
    ordered = sorted(counts.values(), reverse=True)
    return {
        "coverage": measures.coverage(len(carried), len(tickets)),
        "empty": measures.coverage(sum(1 for t in tickets if t.baugruppe_empty), len(tickets)),
        "ids_per_ticket_quantiles": lengths.quantiles(per_ticket),
        "multi_share": measures.ratio(sum(1 for n in per_ticket if n >= 2), len(carried)),
        "distinct": len(counts),
        # Case variants ('b-10' and 'B-10') are counted as written. How many collapse under
        # case-folding is a data-quality fact in its own right, so both numbers are reported.
        "distinct_casefolded": len({v.casefold() for v in counts}),
        "top": [{"value": v, "count": n} for v, n in top[:MAX_LISTED]],
        "top_omitted": max(0, len(top) - MAX_LISTED),
        "withheld": withheld,
        "pairs": [{"value": a, "partner": b, "count": n} for (a, b), n in pairs[:MAX_LISTED]],
        "pairs_omitted": max(0, len(pairs) - MAX_LISTED),
        "pairs_skipped": len(carried) - len(pairable),
        "pairs_withheld": pairs_withheld,
        "concentration": {
            "top1_share": measures.top_share(ordered, 1, assignments),
            "top5_share": measures.top_share(ordered, 5, assignments),
            "top10_share": measures.top_share(ordered, 10, assignments),
            "gini": measures.gini(ordered),
        },
        "by_year": [{"value": v, "year": y, "count": n} for (v, y), n in by_year[:MAX_LISTED]],
        "by_year_omitted": max(0, len(by_year) - MAX_LISTED),
        "by_year_withheld": by_year_withheld,
    }


def prefixes(serials: list[str], k: int = release.K, max_len: int = release.MAX_PREFIX) -> dict:
    """Serial prefix buckets, each shared by at least k DISTINCT vehicles.

    The floor counts vehicles, not tickets. Counted per ticket, one vehicle with k tickets
    formed a bucket on its own and released half of a denylisted serial. A bucket's `count` is
    therefore a number of vehicles, and `withheld` rows are vehicles too.

    The length is the longest whose floored buckets still cover 90% of the vehicles. A serial
    takes part only at lengths up to half its OWN length, so no serial ever releases more than
    half of itself; a serial too short for the chosen length is left out and counted in
    `too_short`, instead of one stray short serial capping the length for everyone.
    """
    distinct = sorted(set(serials))
    total = len(distinct)
    chosen = 0
    for length in range(1, max_len + 1):
        counts = Counter(s[:length] for s in distinct if len(s) // 2 >= length)
        # Chosen on the floor alone. The entity sweep is not monotone in length - 'SE' is a
        # company suffix while 'SER' is not - so letting it steer the search would end it at
        # the first short prefix that happens to be a dictionary word, and a real window would
        # return a one-character bucket. The sweep still applies, at the chosen length below.
        floored = sum(n for n in counts.values() if n >= k)
        if not total or floored / total < PREFIX_MIN_COVERED:
            break
        chosen = length
    if chosen == 0:
        return {
            "enabled": True,
            "length": 0,
            "covered_share": 0.0,
            "too_short": 0,
            "buckets": [],
            "withheld": {
                "below_floor": {"distinct": total, "rows": total},
                "entity_like": {"distinct": 0, "rows": 0},
            },
        }
    eligible = [s for s in distinct if len(s) // 2 >= chosen]
    kept, withheld = release.release(Counter(s[:chosen] for s in eligible), "prefix", k)
    covered = sum(n for _, n in kept)
    return {
        "enabled": True,
        "length": chosen,
        "covered_share": measures.ratio(covered, total),
        "too_short": total - len(eligible),
        "buckets": [{"prefix": p, "count": n} for p, n in kept],
        "withheld": withheld,
    }


def vehicles(tickets: list[Ticket], k: int = release.K, serial_prefixes: bool = False) -> dict:
    serials = [t.serial for t in tickets if t.serial]
    per_serial = sorted(Counter(serials).values(), reverse=True)
    top_n = max(1, math.ceil(len(per_serial) * 0.01)) if per_serial else 0
    models, models_withheld = release.release(
        Counter(t.model for t in tickets if t.model), "model", k
    )
    years, years_withheld = release.release(
        Counter(t.vehicle_year for t in tickets if t.vehicle_year), (None,), k
    )
    return {
        "serials": {
            "coverage": measures.coverage(len(serials), len(tickets)),
            "distinct": len(per_serial),
            "tickets_per_serial_quantiles": lengths.quantiles(per_serial),
            "repeat_rate": measures.ratio(sum(n for n in per_serial if n >= 2), len(serials)),
            "top_percent_share": measures.ratio(sum(per_serial[:top_n]), len(serials)),
            "prefixes": prefixes(serials, k) if serial_prefixes else {"enabled": False},
        },
        "models": [{"model": m, "count": n} for m, n in models],
        "models_withheld": models_withheld,
        "vehicle_years": [{"year": y, "count": n} for y, n in years],
        "vehicle_years_withheld": years_withheld,
    }


def titles(tickets: list[Ticket], k: int = release.K) -> dict:
    """Floored tokens and bigrams only. A title is prose, and prose is never shaped."""
    cleaned = [pipeline.clean(t.title).text for t in tickets]
    tokens, tokens_withheld = release.release(docfreq.tokens(cleaned), "token", k)
    bigrams, bigrams_withheld = release.release(docfreq.bigrams(cleaned), "token", k)
    return {
        "fill": measures.ratio(sum(1 for t in tickets if t.title.strip()), len(tickets)),
        "tokens": [{"token": t, "count": n} for t, n in tokens[:MAX_LISTED]],
        "tokens_withheld": tokens_withheld,
        "tokens_omitted": max(0, len(tokens) - MAX_LISTED),
        "bigrams": [{"token": t, "count": n} for t, n in bigrams[:MAX_LISTED]],
        "bigrams_withheld": bigrams_withheld,
        "bigrams_omitted": max(0, len(bigrams) - MAX_LISTED),
    }
