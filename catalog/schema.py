"""What a released recipe may contain. Constants only; catalog/guard.py enforces them."""

from __future__ import annotations

import re

SCHEMA_VERSION = 1

# Hard minimums for the release floors (MIN_K equals insight.release.K; a test pins that).
MIN_K = 50
MIN_VEHICLES = 5
MIN_DEALERS = 5

MAX_PHRASE = 80
MAX_STEP = 140
MAX_TEMPLATE = 80
MIN_STEPS, MAX_STEPS = 2, 6
MIN_TEMPLATES, MAX_TEMPLATES = 3, 5
MAX_CO_OCCURS = 3

# The only angle-bracket tokens a title template may contain.
SLOTS = ("<component>", "<symptom>")
TONES = ("terse", "neutral", "verbose")
# Coarse classes of workflow note; the wording lives in dev3/personas.py, not here.
BOILERPLATE = ("callback", "closing", "warranty", "goodwill", "duplicate_ref")
# Never p1 or max: those are single tickets.
QUANTILES = ("p25", "p50", "p75")

CATALOG_KEYS = frozenset({"schema_version", "k", "min_vehicles", "min_dealers", "recipes"})
RECIPE_KEYS = frozenset(
    {
        "recipe_id",
        "support",
        "vehicles",
        "dealers",
        "component",
        "symptom",
        "cause",
        "fix_steps",
        "title_templates",
        "description_style",
        "solution_style",
        "fehlercode_shape",
        "recurrence_gap_days",
        "co_occurs_with",
    }
)
DESCRIPTION_KEYS = frozenset({"fill", "words", "tone"})
SOLUTION_KEYS = frozenset({"words", "boilerplate"})

_ANGLE = re.compile(r"<[^<>]*>")
_PUNCTUATION = frozenset(",.:;()/+-<>_")


def has_foreign_angle(text: str, slots: bool = False) -> bool:
    """True if `text` has an angle-bracket token; with `slots`, the allowed slots are ignored."""
    if slots:
        for slot in SLOTS:
            text = text.replace(slot, " ")
    return _ANGLE.search(text) is not None


def only_allowed_characters(text: str) -> bool:
    """Letters, digits, single inner plain spaces and a small punctuation set; nothing else."""
    return (
        bool(text)
        and text == text.strip(" ")
        and "  " not in text
        and all(c.isalpha() or c.isdigit() or c == " " or c in _PUNCTUATION for c in text)
    )
