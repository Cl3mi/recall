"""Reject strings that could identify a person or company before they are emitted.

Complements the min_frequency floor rather than replacing it: the floor catches
RARE strings (identifiers), this catches COMMON ones (entity names). Neither is
sufficient alone, and neither is complete - the residue goes to human review via
vocabulary.hunspell_unrecognized_top.
"""

from __future__ import annotations

import pathlib
import re

_DATA = pathlib.Path(__file__).parent / "data" / "common_surnames.txt"

COMPANY_SUFFIXES = frozenset(
    {
        "gmbh",
        "ag",
        "kg",
        "ohg",
        "gbr",
        "gesmbh",
        "mbh",
        "eu",
        "e.u.",
        "kgaa",
        "ug",
        "se",
        "co",
        "cokg",
        "soehne",
        "sohne",
        "gebr",
        "gebrueder",
        "landtechnik",
        "baumaschinen",
        "handel",
        "handels",
        "vertrieb",
        "service",
        "maschinen",
        "agrar",
        "traktoren",
        "nachf",
        "inh",
    }
)

COMMON_SURNAMES = frozenset(
    line.strip().lower() for line in _DATA.read_text(encoding="utf-8").splitlines() if line.strip()
)

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]{2,}$")
_PHONE = re.compile(r"^\+?\d[\d\s/.-]{6,}$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$", re.IGNORECASE)
_PLATE = re.compile(r"^[A-Z]{1,2}[\s-]?\d{1,5}[A-Z]{0,3}$")
_TOKEN_SPLIT = re.compile(r"[\s/,;]+")


def looks_like_entity(value: str) -> bool:
    """True if this string may identify a person or company. Applied per token so
    that a bigram is rejected when either half fails."""
    if not value:
        return False
    raw = value.strip()
    if _EMAIL.match(raw) or _PHONE.match(raw) or _IBAN.match(raw) or _PLATE.match(raw):
        return True
    return looks_like_named_entity(value)


def looks_like_named_entity(value: str) -> bool:
    """The name half of the sweep only: company suffixes and common surnames, with
    the contact-shape heuristics (email/phone/IBAN/plate) left out.

    Split out because the plate pattern cannot distinguish a model designation
    ('TX-2210') from an Austrian licence plate - they are the same shape. Callers
    that know the value came from a product-dimension column use this instead, so a
    model designation is not mistaken for personal data. See
    profiler.selfcheck.PRODUCT_DIMENSION_COLUMNS."""
    if not value:
        return False
    raw = value.strip()
    for token in _TOKEN_SPLIT.split(raw.lower()):
        bare = token.strip(".,;:()-")
        if not bare:
            continue
        if bare in COMPANY_SUFFIXES or token.strip(",;:()") in COMPANY_SUFFIXES:
            return True
        if bare in COMMON_SURNAMES:
            return True
    return False
