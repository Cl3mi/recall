from __future__ import annotations

import re

from profiler.stats import lengths
from recall.clean import pipeline

JUNK_DONE = r"^(erledigt|fertig|ok|behoben|gelöst)\.?$"
JUNK_SEE_CALL = r"^(siehe|s\.)\s+(telefonat|telefon|anruf|mail|e-mail)\.?$"
JUNK_ONE_WORD = r"^\S{1,20}$"
JUNK_EMPTY = r"^\s*$"
JUNK_PATTERNS = [JUNK_EMPTY, JUNK_DONE, JUNK_SEE_CALL, JUNK_ONE_WORD]

CANDIDATE_SEPARATORS = ["|||", "\n---\n", ";;", "||", "\t"]
_ENTRY_PREFIX = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


def cardinality(values: list[str]) -> dict:
    """Answers PROJECT_BRIEF.md §12.1: is `solutions` one free-text field or a
    thread of attempts? Decided by separator prevalence, not by guessing."""
    non_empty = [v for v in values if v and v.strip()]
    for sep in CANDIDATE_SEPARATORS:
        hits = [v for v in non_empty if sep in v]
        if non_empty and len(hits) / len(non_empty) >= 0.10:
            per = [v.count(sep) + 1 for v in non_empty]
            return {
                "single_field": False,
                "detected_separator": sep,
                "entries_per_ticket_quantiles": lengths.quantiles(per),
            }
    numbered = [v for v in non_empty if len(_ENTRY_PREFIX.findall(v)) >= 2]
    if non_empty and len(numbered) / len(non_empty) >= 0.10:
        per = [max(1, len(_ENTRY_PREFIX.findall(v))) for v in non_empty]
        return {
            "single_field": False,
            "detected_separator": "numbered-list",
            "entries_per_ticket_quantiles": lengths.quantiles(per),
        }
    return {
        "single_field": True,
        "detected_separator": None,
        "entries_per_ticket_quantiles": lengths.quantiles([1] * len(non_empty)),
    }


def junk_taxonomy(values: list[str]) -> list[dict]:
    total = len(values) or 1
    out = []
    for pattern in JUNK_PATTERNS:
        rx = re.compile(pattern, re.IGNORECASE)
        count = sum(1 for v in values if rx.match((v or "").strip()))
        out.append({"pattern": pattern, "count": count, "share": count / total})
    return out


def profile(values: list[str]) -> dict:
    """Answers §12.2: fill rate and usable quality."""
    total = len(values) or 1
    filled = [v for v in values if v and v.strip()]
    cleaned = [pipeline.clean(v).text for v in filled]
    cleaned_nonempty = [c for c in cleaned if c.strip()]
    junk_rx = [re.compile(p, re.IGNORECASE) for p in JUNK_PATTERNS]
    usable = [c for c in cleaned_nonempty if not any(rx.match(c.strip()) for rx in junk_rx)]
    return {
        "fill_rate": len(filled) / total,
        "nonempty_after_clean_rate": len(cleaned_nonempty) / total,
        "cardinality": cardinality(values),
        "junk_taxonomy": junk_taxonomy(values),
        "usable_rate_estimate": len(usable) / total,
        "token_len_quantiles": lengths.quantiles([len(c.split()) for c in cleaned_nonempty]),
    }
