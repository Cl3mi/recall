"""Discover identifier formats instead of assuming them.

recall.german.identifiers matches patterns we wrote in advance. Round 1 reported only a
handful of identifier occurrences, which means 'those that matched our guesses'.
This histograms the character-class shape of every digit-bearing token, so a format
nobody anticipated - MOT-4711, 07.1234.556 - surfaces on its own.

Shapes are content-free by construction (see recall.german.identifiers.shape_of), and
rare shapes are dropped because that is where unusual values sit.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from recall.german.identifiers import shape_of

# Deliberately broader than the identifier patterns: a token may start with a digit
# (07.1234.556) and may carry separators that vocab.tokenize would split on.
_CANDIDATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:\-]{1,31}")

# Round 2 on the real corpus had more than twice as many shapes clear the frequency floor as
# were kept - the artifact described well under half of the formats present and read as though
# it described all of them. Shapes are content-free and already floored, so the cap is only a size bound, and
# a bound that hides more than half the answer is set wrong. Matches the 200 used for
# per_field.top_values.
DEFAULT_LIMIT = 200

# Separators that end a token are punctuation rather than format. A leading one cannot
# occur: _CANDIDATE must start with an alphanumeric.
TRAILING_NOISE = "._/:-"


def discover(
    texts_by_column: dict[str, list[str]], min_frequency: int, limit: int = DEFAULT_LIMIT
) -> dict:
    """Shape histogram over digit-bearing tokens, floored and capped.

    Returns the kept shapes plus how many frequent ones the cap dropped. Discovery is
    the section that answers 'what formats does this corpus actually use', so a silently
    truncated list would be read as the complete answer.
    """
    counts: Counter[str] = Counter()
    fields: dict[str, set[str]] = defaultdict(set)

    for column, texts in texts_by_column.items():
        for text in texts:
            for match in _CANDIDATE.finditer(text or ""):
                # Trailing separators are sentence punctuation, not part of the format.
                # Left in, 'F1247.' shapes to ADDDD. and forks the histogram: one format
                # is counted as several, and each fork can fall under min_frequency and
                # vanish. Discovery exists to find formats, so it must not split them.
                token = match.group(0).rstrip(TRAILING_NOISE)
                if not any(c.isdigit() for c in token):
                    continue
                shape = shape_of(token)
                counts[shape] += 1
                fields[shape].add(column)

    total = sum(counts.values()) or 1
    above_floor = [
        {
            "shape": shape,
            "count": count,
            "share": count / total,
            "fields": sorted(fields[shape]),
        }
        for shape, count in counts.most_common()
        if count >= min_frequency
    ]
    return {
        "shapes": above_floor[:limit],
        "omitted_over_cap": max(0, len(above_floor) - limit),
    }
