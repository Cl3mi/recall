from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,}")
DEFAULT_MIN_FREQUENCY = 50

# schema.json pins `min_frequency_threshold` at minimum 2 and every emitted token count
# at minimum 2, so anything lower produces a schema-invalid artifact. Kept beside the
# default so the two cannot drift apart.
MIN_FREQUENCY_FLOOR = 2


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN.finditer(text or "")]


def token_counts(texts: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(tokenize(text))
    return counts


def bigram_counts(texts: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        toks = tokenize(text)
        counts.update(f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False))
    return counts


def top_tokens(
    counts: Counter[str], min_frequency: int = DEFAULT_MIN_FREQUENCY, limit: int = 2000
) -> list[dict]:
    """Rare terms are where identifying information hides, so they are pruned
    before anything is written. See the safety invariant in the plan."""
    return [
        {"token": token, "count": count}
        for token, count in counts.most_common()
        if count >= min_frequency
    ][:limit]
