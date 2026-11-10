# dev3/verify.py
"""Every way the generated fixture drifted from its plan. Empty means faithful.

Lines are `CODE detail` with a row index or a vehicle name, never row text. No code path here
raises on a malformed row or label: malformed input becomes a finding.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from catalog import scrub
from dev3.profiles import Profile
from dev3.rows import IDENTITY_COLUMNS
from profiler.columns import EXPECTED_COLUMNS

TEXT_COLUMNS = ("title", "description", "solutions")
MIN_SOLUTION_FILL = 0.8
CHRONIC_TOP3 = 0.6
BROAD_MAX_SHARE = 0.25
BROAD_MIN_RECIPES = 6
EVOLVING_MAIN_SHARE = 0.2


def _cell(row: object, column: str) -> str:
    """A cell as text; a malformed row or value reads as empty and never raises."""
    value = row.get(column) if isinstance(row, dict) else None
    return value if isinstance(value, str) else ""


def _row_id(row: object) -> int | None:
    try:
        return int(_cell(row, "id"))
    except ValueError:
        return None


def _get(label: object, key: str) -> object:
    return label.get(key) if isinstance(label, dict) else None


def _bad_followup(i: int, label: object, labels: list[dict], id_index: dict[int, int]) -> bool:
    """True unless the follow-up link is absent or names an earlier row of the same vehicle
    and recipe (and the vehicle-local number agrees with the global id)."""
    target_id = _get(label, "followup_of_id")
    if target_id is None:
        return _get(label, "followup_of") is not None
    j = id_index.get(target_id) if isinstance(target_id, int) else None
    if j is None or j >= i:
        return True
    target = labels[j]
    return not (
        _get(target, "vehicle") == _get(label, "vehicle")
        and _get(target, "recipe_id") == _get(label, "recipe_id")
        and _get(target, "number") == _get(label, "followup_of")
    )


def _row_problems(
    i: int, row: object, label: object, profile: Profile | None, labels: list[dict], ids: dict
) -> list[str]:
    found: list[str] = []
    if (
        profile is None
        or _get(label, "vehicle") != profile.name
        or _get(label, "id") != _row_id(row)
    ):
        found.append(f"LABEL_MISMATCH row {i}")
    described = bool(_cell(row, "description").strip())
    if described == (_get(label, "persona") == "title_only"):
        found.append(f"PERSONA_TEXT row {i}")
    if _bad_followup(i, label, labels, ids):
        found.append(f"BAD_FOLLOWUP row {i}")
    if any(_cell(row, c) for c in IDENTITY_COLUMNS):
        found.append(f"IDENTITY_FILLED row {i}")
    if not _cell(row, "title").strip():
        found.append(f"BLANK_TITLE row {i}")
    found += [f"NOT_CLEAN row {i} {c}" for c in TEXT_COLUMNS if not scrub.is_clean(_cell(row, c))]
    try:
        created = date.fromisoformat(_cell(row, "timestampCreated"))
    except ValueError:
        found.append(f"OUT_OF_WINDOW row {i}")
    else:
        if profile and not profile.start <= created <= profile.end:
            found.append(f"OUT_OF_WINDOW row {i}")
    return found


def _shape_ok(profile: Profile, mine: list, recipes: list[dict]) -> bool:
    counts = Counter(_get(lab, "recipe_id") for lab in mine)
    total = len(mine) or 1
    linked = any(_get(lab, "followup_of") for lab in mine)
    if profile.kind == "chronic":
        top3 = sum(n for _, n in counts.most_common(3))
        return top3 / total >= CHRONIC_TOP3 and linked
    if profile.kind == "broad":
        return (
            len(counts) >= min(len(recipes), BROAD_MIN_RECIPES)
            and max(counts.values(), default=0) / total <= BROAD_MAX_SHARE
        )
    if profile.kind == "evolving":
        mains = [r for r, n in counts.items() if n / total >= EVOLVING_MAIN_SHARE]
        return len(mains) >= 2 and linked
    return True


def check(
    rows: list[dict[str, str]],
    labels: list[dict],
    profiles: tuple[Profile, ...],
    recipes: list[dict],
) -> list[str]:
    problems: list[str] = []
    if len(rows) != len(labels):
        return ["COUNT rows and labels differ"]
    columns = set(EXPECTED_COLUMNS)
    problems += [
        f"COLUMNS row {i}"
        for i, r in enumerate(rows)
        if not isinstance(r, dict) or set(r) != columns
    ]

    expected = {p.serial: p.tickets for p in profiles}
    if dict(Counter(_cell(r, "vehicleSerialNo") for r in rows)) != expected:
        problems.append("SERIAL_COUNTS tickets per serial differ from the profiles")

    numbers = Counter(_cell(r, "ticketNumber") for r in rows)
    problems += [
        f"DUPLICATE_NUMBER row {i}"
        for i, r in enumerate(rows)
        if numbers[_cell(r, "ticketNumber")] > 1
    ]

    by_serial = {p.serial: p for p in profiles}
    id_index: dict[int, int] = {}
    for i, label in enumerate(labels):
        label_id = _get(label, "id")
        if isinstance(label_id, int):
            id_index.setdefault(label_id, i)
    for i, (row, label) in enumerate(zip(rows, labels, strict=True)):
        profile = by_serial.get(_cell(row, "vehicleSerialNo"))
        problems += _row_problems(i, row, label, profile, labels, id_index)

    filled = sum(1 for r in rows if _cell(r, "solutions").strip())
    if rows and filled / len(rows) < MIN_SOLUTION_FILL:
        problems.append("SOLUTION_FILL below the minimum")

    for profile in profiles:
        mine = [lab for lab in labels if _get(lab, "vehicle") == profile.name]
        if not _shape_ok(profile, mine, recipes):
            problems.append(f"PROFILE_SHAPE {profile.name} does not show its intended pattern")
    return problems
