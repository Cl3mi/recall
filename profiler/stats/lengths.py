from __future__ import annotations

QUANTILE_POINTS = {
    "p1": 0.01,
    "p5": 0.05,
    "p25": 0.25,
    "p50": 0.50,
    "p75": 0.75,
    "p90": 0.90,
    "p95": 0.95,
    "p99": 0.99,
    "p999": 0.999,
}


def quantiles(values: list[int | float]) -> dict[str, float]:
    """Nearest-rank quantiles. The pathological tail is the point, so max is
    always reported alongside p999."""
    if not values:
        return {name: 0.0 for name in (*QUANTILE_POINTS, "max")}
    ordered = sorted(values)
    n = len(ordered)
    out = {}
    for name, q in QUANTILE_POINTS.items():
        idx = min(n - 1, max(0, int(round(q * (n - 1)))))
        out[name] = float(ordered[idx])
    out["max"] = float(ordered[-1])
    return out
