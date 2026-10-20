from __future__ import annotations

from collections import Counter


def _is_null(value: str | None) -> bool:
    return value is None or value.strip() == ""


def joint_patterns(rows: list[dict[str, str]], columns: list[str], top_n: int = 50) -> list[dict]:
    """Missingness is correlated - no vehicleSerialNo usually means no vehicleId -
    so joint masks are reported, not per-column rates."""
    counts: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        counts[tuple(c for c in columns if _is_null(row.get(c)))] += 1
    total = len(rows) or 1
    return [
        {"columns_null": list(mask), "count": count, "share": count / total}
        for mask, count in counts.most_common(top_n)
    ]
