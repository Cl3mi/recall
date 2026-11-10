"""Closed-allowlist check of a finished catalog. Nothing is released that this refuses.

Returns lines `CODE path`. A line never contains a value or a key name from the file under
test: a key or a value may itself be what leaked, and the log must not repeat it.
"""

from __future__ import annotations

import re

from catalog import schema, scrub
from recall.german.identifiers import SHAPE_ALPHABET, SHAPE_MAX

_SHAPE = re.compile(f"[{SHAPE_ALPHABET}]{{1,{SHAPE_MAX}}}")
_ID = re.compile(r"R\d{3,4}")


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _keys(out: list[str], path: str, value: object, allowed: frozenset[str]) -> bool:
    if not isinstance(value, dict):
        out.append(f"WRONG_TYPE {path}")
        return False
    if set(value) != allowed:
        out.append(f"UNKNOWN_KEY {path}")
        return False
    return True


def _text(out: list[str], path: str, value: object, limit: int, slots: bool = False) -> None:
    if not isinstance(value, str) or not value.strip():
        out.append(f"WRONG_TYPE {path}")
        return
    if len(value) > limit:
        out.append(f"TOO_LONG {path}")
    probe = value
    if slots:
        for slot in schema.SLOTS:
            probe = probe.replace(slot, " ")
    if (
        schema.has_foreign_angle(value, slots)
        or not schema.only_allowed_characters(value)
        or not scrub.is_clean(probe)
    ):
        out.append(f"NOT_CLEAN {path}")


def _texts(out, path, value, low, high, limit, slots=False) -> None:
    if not isinstance(value, list):
        out.append(f"WRONG_TYPE {path}")
        return
    if not low <= len(value) <= high:
        out.append(f"WRONG_COUNT {path}")
    for i, item in enumerate(value):
        _text(out, f"{path}[{i}]", item, limit, slots)


def _quantiles(out: list[str], path: str, value: object) -> None:
    if not isinstance(value, dict) or set(value) != set(schema.QUANTILES):
        out.append(f"WRONG_TYPE {path}")
        return
    numbers = []
    for name in schema.QUANTILES:
        if not _whole(value[name]):
            out.append(f"NOT_WHOLE {path}.{name}")
        else:
            numbers.append(value[name])
    if len(numbers) == len(schema.QUANTILES) and numbers != sorted(numbers):
        out.append(f"NOT_MONOTONE {path}")


def _recipe(out, path, recipe, floors, ids) -> None:
    if not _keys(out, path, recipe, schema.RECIPE_KEYS):
        return
    if not isinstance(recipe["recipe_id"], str) or not _ID.fullmatch(recipe["recipe_id"]):
        out.append(f"BAD_ID {path}.recipe_id")
    for field, floor in zip(("support", "vehicles", "dealers"), floors, strict=True):
        value = recipe[field]
        if not _whole(value):
            out.append(f"NOT_WHOLE {path}.{field}")
        elif value < floor:
            out.append(f"BELOW_FLOOR {path}.{field}")
    for field in ("component", "symptom", "cause"):
        _text(out, f"{path}.{field}", recipe[field], schema.MAX_PHRASE)
    _texts(
        out,
        f"{path}.fix_steps",
        recipe["fix_steps"],
        schema.MIN_STEPS,
        schema.MAX_STEPS,
        schema.MAX_STEP,
    )
    _texts(
        out,
        f"{path}.title_templates",
        recipe["title_templates"],
        schema.MIN_TEMPLATES,
        schema.MAX_TEMPLATES,
        schema.MAX_TEMPLATE,
        slots=True,
    )

    style = recipe["description_style"]
    if _keys(out, f"{path}.description_style", style, schema.DESCRIPTION_KEYS):
        fill = style["fill"]
        if not isinstance(fill, (int, float)) or isinstance(fill, bool) or not 0 <= fill <= 1:
            out.append(f"BAD_VALUE {path}.description_style.fill")
        elif round(fill, 2) != fill:
            out.append(f"NOT_WHOLE {path}.description_style.fill")
        _quantiles(out, f"{path}.description_style.words", style["words"])
        if style["tone"] not in schema.TONES:
            out.append(f"BAD_VALUE {path}.description_style.tone")

    solution = recipe["solution_style"]
    if _keys(out, f"{path}.solution_style", solution, schema.SOLUTION_KEYS):
        _quantiles(out, f"{path}.solution_style.words", solution["words"])
        boiler = solution["boilerplate"]
        if not isinstance(boiler, list) or any(b not in schema.BOILERPLATE for b in boiler):
            out.append(f"BAD_VALUE {path}.solution_style.boilerplate")

    shape = recipe["fehlercode_shape"]
    if shape is not None and not (isinstance(shape, str) and _SHAPE.fullmatch(shape)):
        out.append(f"BAD_SHAPE {path}.fehlercode_shape")
    if recipe["recurrence_gap_days"] is not None:
        _quantiles(out, f"{path}.recurrence_gap_days", recipe["recurrence_gap_days"])
    refs = recipe["co_occurs_with"]
    if not isinstance(refs, list) or len(refs) > schema.MAX_CO_OCCURS:
        out.append(f"WRONG_COUNT {path}.co_occurs_with")
    elif any(
        not isinstance(ref, str) or ref not in ids or ref == recipe["recipe_id"] for ref in refs
    ):
        out.append(f"BAD_REF {path}.co_occurs_with")


def _exact_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def problems(
    catalog: object,
    *,
    k: int,
    min_vehicles: int,
    min_dealers: int,
    allow_weak: bool = False,
) -> list[str]:
    out: list[str] = []
    if not _keys(out, "$", catalog, schema.CATALOG_KEYS):
        return out
    version = catalog["schema_version"]
    if not _exact_int(version) or version != schema.SCHEMA_VERSION:
        out.append("BAD_VALUE $.schema_version")
    floors = (
        ("k", k, schema.MIN_K),
        ("min_vehicles", min_vehicles, schema.MIN_VEHICLES),
        ("min_dealers", min_dealers, schema.MIN_DEALERS),
    )
    for name, floor, minimum in floors:
        if not _exact_int(floor):
            out.append(f"WRONG_TYPE $.{name}")
        elif not _exact_int(catalog[name]) or catalog[name] != floor:
            out.append(f"FLOOR_MISMATCH $.{name}")
        elif floor < minimum and not allow_weak:
            out.append(f"FLOOR_TOO_LOW $.{name}")
    recipes = catalog["recipes"]
    if not isinstance(recipes, list) or not recipes:
        out.append("WRONG_TYPE $.recipes")
        return out
    seen: set[str] = set()
    for i, recipe in enumerate(recipes):
        identifier = recipe.get("recipe_id") if isinstance(recipe, dict) else None
        if isinstance(identifier, str):
            if identifier in seen:
                out.append(f"DUPLICATE_ID $.recipes[{i}]")
            seen.add(identifier)
    known = set(seen)
    for i, recipe in enumerate(recipes):
        _recipe(out, f"$.recipes[{i}]", recipe, (k, min_vehicles, min_dealers), known)
    return out
