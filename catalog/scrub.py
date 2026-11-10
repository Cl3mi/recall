"""Remove what could identify a person, a vehicle, a part or a dealer from a recipe phrase.

Deliberately blunt: it also removes harmless things such as a thread size like `M12`. A recipe
that loses a word is still a recipe; one that keeps an identifier is a leak.
"""

from __future__ import annotations

import re

from insight import names
from profiler import entities

_PATTERNS = (
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"\S+@\S+"),
    re.compile(r"\+?\d[\d\s/().-]{5,}\d"),
    re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?"),
    re.compile(r"\b[A-Za-z]{0,3}\d[\w-]*\d\b"),
    re.compile(r"\d{4,}"),
)
_EDGE = ".,;:()[]\"'!?"


def normalise(text: str) -> str:
    return " ".join(text.split())


def _is_name(word: str) -> bool:
    bare = word.strip(_EDGE)
    return bool(bare) and (
        names.contains_first_name(bare)
        or names.contains_surname(bare)
        or entities.looks_like_named_entity(bare)
    )


def scrub(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(" ", text)
    return " ".join(word for word in text.split() if not _is_name(word))


def is_clean(text: str) -> bool:
    return scrub(text) == normalise(text)
