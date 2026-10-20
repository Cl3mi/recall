"""Checks 3 and 4: is the SYNTHETIC corpus clean on its own terms?

Neither check reads the real corpus. They are in the window because the operator ruled on
2026-08-27 that all four checks emit one report, which is the artifact a DPO reads.

Patterns are reused from `profiler/entities.py` wherever it has one. A second set of regexes
here would drift from the first, and two disagreeing definitions of "looks like a phone
number" is worse than one.

WHAT THIS SWEEP DOES NOT COVER, stated because a report saying "pii: passed" must not be read
as "no PII of any kind". `PROJECT_BRIEF.md` §8 asks for "German name patterns, phone numbers,
emails, addresses, IBANs, plate numbers". This covers three of those six - see `PATTERNS`.

- **Plate numbers are deliberately absent.** `entities._PLATE` unanchored is
  `[A-Z]{1,2}[\\s-]?\\d{1,5}[A-Z]{0,3}`, and measured, it matches `TX-2200`, `LR-2200` and
  `VG-2210` - every designation of the fixture's own invented product line, which appears in
  essentially every row. Adding it naively would flag the whole corpus. Doing it properly
  means letting check 4's roster allowlist the invented line first, which is a design decision
  rather than a pattern.
- **German surnames are absent.** `entities.COMMON_SURNAMES` holds 60 entries and is built for
  classifying a whole field value, not for scanning free text where `bauer`, `braun` and
  `berger` are also ordinary German words. Matching them in prose needs a false-positive
  measurement nobody has taken.
- **Addresses are absent.** No pattern exists anywhere in the repo yet.

Those three are a real gap, not an oversight, and `PATTERNS` is exported so the report can name
what actually ran instead of implying full §8 coverage.
"""

from __future__ import annotations

import re
from collections import Counter

from profiler import entities

# Exactly which patterns this sweep applies. The report prints these, so a reader can see the
# coverage rather than infer it from a green verdict.
PATTERNS = ("email", "phone", "iban")

# Free text needs SEARCH semantics; entities.py's own patterns are anchored because it
# classifies whole field values. Same expression, rebuilt unanchored, so the two cannot
# disagree about what an email is.
_EMAIL = re.compile(entities._EMAIL.pattern.strip("^$"))
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

# Phones need more care than a digit run, and this was measured rather than assumed. A first
# draft, `(?<!\d)\+?\d[\d\s/.-]{8,}\d(?!\d)`, matched 03.04.2024, 01.01.2020, 89.88.3403 and
# "4711 / 0815" - four false positives in seven ordinary ticket strings. DD.DD.DDDD is a very
# common free-text shape, so that pattern would have fired on ordinary rows and the gate would
# have been relaxed rather than trusted.
#
# Two changes. Dates are REMOVED from the text first: a date is not a phone number, and
# deleting the confusing shape beats out-regexing it - it also handles two adjacent dates,
# which any lookaround approach still joins into one long run. Then a candidate must carry at
# least MIN_PHONE_DIGITS actual digits, because German numbers include an area or country code
# and run 10-13, while a DD.DD.DDDD date has 8 and "4711 / 0815" has 8.
#
# Measured on this form: 0 missed phones in 5 real shapes, 0 false positives in 10 ordinary
# strings.
_GERMAN_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_PHONE_RUN = re.compile(r"\+?\d[\d\s/().-]{6,}\d")
MIN_PHONE_DIGITS = 10


def _looks_like_phone(text: str) -> bool:
    without_dates = _GERMAN_DATE.sub(" ", text or "")
    return any(
        sum(character.isdigit() for character in match.group(0)) >= MIN_PHONE_DIGITS
        for match in _PHONE_RUN.finditer(without_dates)
    )


def pii_hits(documents: list[str]) -> dict[str, int]:
    """How many documents match each pattern in `PATTERNS`. Counts only.

    Documents, not occurrences: one row with three emails is one row to investigate.
    """
    counts: Counter[str] = Counter(dict.fromkeys(PATTERNS, 0))
    for document in documents:
        text = document or ""
        if _EMAIL.search(text):
            counts["email"] += 1
        if _IBAN.search(text):
            counts["iban"] += 1
        if _looks_like_phone(text):
            counts["phone"] += 1
    return dict(counts)


def roster_violations(values: list[str | None], roster: frozenset[str]) -> int:
    """How many non-blank values are not in the fictional roster.

    Blank is the common case rather than an error: 25 of the fixture's 38 columns render as
    empty strings, recorded in docs/STATE.md.
    """
    return sum(
        1 for value in values if (value or "").strip() and (value or "").strip() not in roster
    )
