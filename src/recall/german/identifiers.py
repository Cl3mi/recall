from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("error_code", re.compile(r"\b[A-Z]{1,3}\d{3,5}\b")),
    ("model_designation", re.compile(r"\b[A-Z]{2,3}-\d{2,4}[A-Z]?\b")),
    ("part_number", re.compile(r"\b\d{3,4}[.\-/]\d{3,5}(?:[.\-/]\d{1,4})?\b")),
    ("serial_number", re.compile(r"\b[A-Z]{2}\d{5,10}\b")),
]

# A shape may contain nothing but these characters, which is what makes it
# structurally incapable of carrying a corpus value. A later task will pin the same
# alphabet in profiler/schema.json and re-check it in profiler/selfcheck.py.
SHAPE_SEPARATORS = "-./:"
# Built with '-' trailing so the alphabet can be dropped straight into a regex
# character class ('[...]') without it being read as a range operator - '-' is only
# safe there as the first or last character of the class, or escaped.
SHAPE_ALPHABET = "ALaD_" + SHAPE_SEPARATORS.replace("-", "") + "#-"
SHAPE_MAX = 16

# shape_of and _shape_to_regex must agree: the profiler emits the shape, M2 generates
# synthetic identifiers from the regex, and a regex that does not match its own source
# value yields wrongly-shaped fixtures. Classifying with str.is*() on one side and re
# classes on the other makes that agreement a coincidence - str.isdigit() is true for
# '²' while re's \d (category Nd) is not, and 'm²' is ordinary in a machinery corpus.
# Both sides therefore read the same compiled matchers.
_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[^\W\d_]")
_SPACE = re.compile(r"\s")


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    start: int
    end: int


def extract(text: str | None) -> list[Identifier]:
    """Longest-match-wins so a model designation is not also read as an error code."""
    if not text:
        return []
    claimed: list[Identifier] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < c.end and c.start < m.end() for c in claimed):
                continue
            claimed.append(Identifier(kind, m.group(0), m.start(), m.end()))
    return sorted(claimed, key=lambda i: i.start)


def shape_of(value: str, limit: int = SHAPE_MAX) -> str:
    """Structure without content: A=first uppercase, L=later uppercase, a=lowercase,
    D=digit, _=whitespace, -./: kept because they distinguish identifier formats,
    # everything else.

    'F1247' -> 'ADDDD' keeps the leading-letter/four-digit structure while discarding
    every digit, so shapes are safe to emit from the profiler. Capped at `limit`
    characters: a longer shape starts to fingerprint the value it came from."""
    out = []
    for i, ch in enumerate(value[:limit]):
        if _DIGIT.match(ch):
            out.append("D")
        elif _LETTER.match(ch):
            out.append("A" if i == 0 and ch.isupper() else "L" if ch.isupper() else "a")
        elif _SPACE.match(ch):
            out.append("_")
        elif ch in SHAPE_SEPARATORS:
            out.append(ch)
        else:
            out.append("#")
    return "".join(out)


def infer_grammars(values: list[str]) -> list[dict]:
    counts: Counter[tuple[str, str, bool]] = Counter()
    for v in values:
        kinds = {i.kind for i in extract(v)} or {"other"}
        truncated = len(v) > SHAPE_MAX
        counts[(next(iter(kinds)), shape_of(v), truncated)] += 1
    total = sum(counts.values()) or 1
    return [
        {
            "kind": kind,
            "shape": shape,
            "regex": _shape_to_regex(shape, truncated),
            "count": count,
            "share": count / total,
        }
        for (kind, shape, truncated), count in counts.most_common()
    ]


def _shape_to_regex(shape: str, truncated: bool = False) -> str:
    # Read from the same matchers shape_of classifies with (_DIGIT/_LETTER/_SPACE
    # above), so the regex cannot drift from the classification that produced the
    # shape it describes.
    mapping = {
        "A": _LETTER.pattern,
        "L": _LETTER.pattern,
        "a": _LETTER.pattern,
        "D": _DIGIT.pattern,
        "_": _SPACE.pattern,
        "#": ".",
    }
    body = "".join(mapping.get(c, re.escape(c)) for c in shape)
    # A truncated shape describes only a prefix, so it must not claim the value ends here.
    return "^" + body + ("" if truncated else "$")


_FAMILY = re.compile(r"^([A-Z]{2,3})-?(\d{2})")


def model_family(designation: str) -> str | None:
    """Proxy for the client's missing model hierarchy: prefix plus the first two
    digits. 'TX-2240' and 'TX-2210' share family 'TX-22'."""
    m = _FAMILY.match(designation.strip().upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None
