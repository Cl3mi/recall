"""One definition of "may this value leave", shared by the builders and the guard.

The M2 renderer and verifier read the same `block_key` for the same reason: a guard with its
own idea of what a builder should have dropped would bless exactly what the builder got
wrong. Builders call `release()`; the guard calls `flagged()`; neither has a private copy.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Hashable, Sequence

from insight import names
from profiler import entities
from profiler.stats import vocab
from recall.german.identifiers import SHAPE_ALPHABET, SHAPE_MAX

# The profiler's own floor, not a copy: a value that is rare in Window A is rare here.
K = vocab.DEFAULT_MIN_FREQUENCY

# A serial prefix never exceeds this, whatever the serials look like.
MAX_PREFIX = 8

# A code field value longer than this that also carries a digit reads as an identifier (a VIN
# or a serial typed into a free-ish field). Product and assembly codes ('B-10', 'TX-2210') are
# far shorter. A false positive only withholds, and the withheld rows are counted.
MAX_CODE_LENGTH = 16

# A token part carrying a digit and longer than this reads as an identifier (a serial, a part
# number). profiler.selfcheck only WARNS on that shape for dimension-hint tokens; here it is a
# withhold, because a new gate should not be more permissive than the one beside it.
IDENTIFIER_LIKE_LENGTH = 6

# The longest released token is a trigram. Anything longer is a phrase, and a phrase that clears
# the floor is a sentence many tickets share: a template or a whole solution, never vocabulary.
MAX_TOKEN_WORDS = 3

# A code field value is an id, a short code or a status word. More than this many words is a
# phrase, whether or not it has a digit, and a phrase is not a code.
MAX_CODE_WORDS = 4

# A shape is built from this closed alphabet and nothing else, so it cannot carry a value. The
# alphabet keeps '-' last, which is what lets it sit inside a character class unescaped.
_SHAPE = re.compile(f"[{SHAPE_ALPHABET}]{{1,{SHAPE_MAX}}}")


def _word_count(value: str) -> int:
    """Words as a reader counts them: whitespace, hyphens, slashes and dots all separate. The
    tokenizer keeps hyphens, so `pumpe-wurde-am-montag-getauscht` is one token and five words."""
    return sum(1 for part in names._PARTS.split(value) if part)


def _code_flagged(value: str) -> bool:
    """Every check `looks_like_entity` makes EXCEPT the licence-plate shape.

    Measured: the plate pattern matches product and assembly codes ('B-10', 'B-20', 'TX-2210',
    'LR-45', 'SN2000') because they genuinely have a plate's shape, while the e-mail, phone and
    IBAN patterns match none of them. A code field therefore keeps the three contact checks and
    the name checks and relaxes only the plate. profiler.selfcheck.PRODUCT_DIMENSION_COLUMNS
    documents the same relaxation for vehicleModelId, vehicleStatus and subStatusString.
    Baugruppe is NOT in that set; the reasoning is applied to it here on purpose, and more
    narrowly than "name half only", which would also have dropped the contact checks.
    """
    raw = value.strip()
    if len(raw) > MAX_CODE_LENGTH and any(c.isdigit() for c in raw):
        return True
    # A status or sub-status can name the person it is assigned to ('zugewiesen an Stefan'), and a
    # long phrase with no digit is a sentence. Neither is a code.
    if _word_count(raw) > MAX_CODE_WORDS:
        return True
    if names.contains_first_name(raw) or names.contains_surname(raw):
        return True
    contact = (entities._EMAIL, entities._PHONE, entities._IBAN)
    if any(pattern.match(raw) for pattern in contact):
        return True
    return entities.looks_like_named_entity(value)


def _prefix_flagged(value: str) -> bool:
    return len(value) > MAX_PREFIX or _code_flagged(value)


def _shape_flagged(value: str) -> bool:
    """Anything that is not a shape. No entity sweep: a shape is structurally incapable of
    carrying a value, so the floor is the only other control it needs."""
    return not _SHAPE.fullmatch(value)


def _token_flagged(value: str) -> bool:
    parts = value.split()
    identifier_like = any(
        len(part) > IDENTIFIER_LIKE_LENGTH and any(c.isdigit() for c in part) for part in parts
    )
    return (
        _word_count(value) > MAX_TOKEN_WORDS
        or identifier_like
        or names.contains_first_name(value)
        or names.contains_surname(value)
        or entities.looks_like_entity(value)
    )


# The sweep each released field gets. Free-text tokens get the full sweep, the first-name list
# and the identifier-like rule; code fields (Baugruppe and its pair partner, model, serial
# prefix) get everything but the plate shape, for the reason given on `_code_flagged`; shapes
# get the closed alphabet.
_SWEEPS = {
    "token": _token_flagged,
    "value": _code_flagged,
    "partner": _code_flagged,
    "model": _code_flagged,
    "prefix": _prefix_flagged,
    "shape": _shape_flagged,
}

RELEASED_FIELDS = frozenset(_SWEEPS)


def flagged(field: str, value: str) -> bool:
    """True when `value` must not be released under `field`."""
    return _SWEEPS[field](value)


def _empty() -> dict[str, int]:
    return {"distinct": 0, "rows": 0}


def _parts(key: Hashable, names: tuple[str | None, ...]) -> tuple:
    """The key's components, after checking the key against `names`.

    Done for EVERY key before the floor test: a structure error that only raised for keys
    clearing the floor would hide on a small or synthetic corpus and surface in the real
    window. Messages name fields, counts and types only, never a value.
    """
    parts = key if isinstance(key, tuple) else (key,)
    if len(parts) != len(names):
        raise ValueError(
            f"a key has {len(parts)} component(s) but {len(names)} field(s) were named"
        )
    for name, part in zip(names, parts, strict=True):
        if name is None:
            continue
        if name not in _SWEEPS:
            raise KeyError(f"unknown released field {name!r}")
        if not isinstance(part, str):
            raise TypeError(f"released field {name!r} needs str values, got {type(part).__name__}")
    return parts


def release(
    counts: Counter, fields: str | Sequence[str | None], k: int = K
) -> tuple[list[tuple[Hashable, int]], dict[str, dict[str, int]]]:
    """Split `counts` into what may be released and a tally of what may not.

    A key may be one value or a tuple (a cross-tab cell). The floor applies to the key's
    count, so a cell is floored as a cell. `fields` names the sweep for each component, with
    None marking a structural component (a year) that is not swept.

    Returns (kept, withheld). `withheld` holds numbers only, so it is safe to emit: a reader
    can tell a section that was empty from one whose contents were suppressed.
    """
    names = (fields,) if isinstance(fields, str) else tuple(fields)
    kept: list[tuple[Hashable, int]] = []
    below = _empty()
    swept = _empty()
    # Ordered by count, then by key. most_common() leaves ties in arrival order, which would
    # make every section's output depend on the order of the rows in the export.
    for key, n in sorted(counts.items(), key=lambda item: (-item[1], repr(item[0]))):
        parts = _parts(key, names)
        if n < k:
            below["distinct"] += 1
            below["rows"] += n
            continue
        if any(f is not None and flagged(f, p) for f, p in zip(names, parts, strict=True)):
            swept["distinct"] += 1
            swept["rows"] += n
            continue
        kept.append((key, n))
    return kept, {"below_floor": below, "entity_like": swept}
