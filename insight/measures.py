"""Arithmetic only. Nothing here handles a string, so nothing here can leak one."""

from __future__ import annotations

from profiler.stats import lengths


def ratio(part: int | float, whole: int | float) -> float:
    return round(part / whole, 4) if whole else 0.0


def coverage(present: int, total: int) -> dict[str, int | float]:
    return {"present": present, "total": total, "share": ratio(present, total)}


def gini(values: list[int]) -> float:
    """Concentration of a count distribution: 0 when equal, towards 1 when one holds all."""
    n = len(values)
    total = sum(values)
    if n == 0 or total == 0:
        return 0.0
    ascending = sorted(values)
    weighted = sum((i + 1) * v for i, v in enumerate(ascending))
    return round(2 * weighted / (n * total) - (n + 1) / n, 4)


def top_share(ordered_desc: list[int], n: int, total: int) -> float:
    return ratio(sum(ordered_desc[:n]), total)


# The quantile keys that are always released. `p1` and `max` are never released: each is one
# record's reading (the oldest machine, the longest wait), and a single record can single out a
# vehicle. `p999` is released only when at least 1,000 observations stand behind it, because for
# fewer it IS the maximum.
RELEASED_QUANTILES = ("p5", "p25", "p50", "p75", "p90", "p95", "p99")
P999_MIN_OBSERVATIONS = 1000


def floored_quantiles(values: list[int | float], k: int) -> tuple[dict[str, int], bool]:
    """Whole-number quantiles of `values`, or zeros when fewer than `k` values stand behind them.

    A quantile of two numbers IS those numbers, so a small group releases none. The flag says
    which of the two a reader is looking at, since the zeros alone cannot. Readings are rounded to
    whole numbers (hours, days): a decimal on a machine's hours is a fingerprint, not information.
    The keys do not depend on the group's size except for `p999` (see RELEASED_QUANTILES).
    """
    if len(values) < k:
        return {key: 0 for key in RELEASED_QUANTILES}, bool(values)
    quantiles = lengths.quantiles(values)
    out = {key: int(round(quantiles[key])) for key in RELEASED_QUANTILES}
    if len(values) >= P999_MIN_OBSERVATIONS:
        out["p999"] = int(round(quantiles["p999"]))
    return out, False
