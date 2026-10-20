from __future__ import annotations

import datetime as dt
import re

_TS = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def _parse(value: str) -> dt.date | None:
    m = _TS.match(value or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def ages_in_years(timestamps: list[str]) -> list[float]:
    """Age relative to the newest row in the corpus. Feeds recency-decay
    calibration (PROJECT_BRIEF.md §14) and stays deterministic across runs."""
    dates = [d for d in (_parse(t) for t in timestamps) if d is not None]
    if not dates:
        return []
    newest = max(dates)
    return [(newest - d).days / 365.25 for d in dates]
