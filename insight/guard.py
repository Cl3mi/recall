"""Independent re-check of the finished report. Nothing leaves that this does not accept.

The builders already floor and sweep; this exists because a builder is only as safe as the
last person to edit it. It walks the finished dict and refuses any key that is not declared,
any string that is not accounted for, any value of a type JSON would not write as itself, and
any released value under the floor k or flagged by the sweep - calling `release.flagged`, the
same function the builders use, so the two cannot disagree about what should have been dropped -
and any released value standing at a path not declared for its field in RELEASED_AT.

It is deliberately NOT an extension of profiler.blessing, which is bound to profiler/schema.json
and to module-level path lists; changing those is a change to a safety control. For the same
reason it reuses the registered codes in profiler.safety rather than adding new ones: the guard's
own code (BELOW_FLOOR, ENTITY_LIKE, ...) goes into the local detail log beside the value.
"""

from __future__ import annotations

import math
import re

from insight import (
    concentration,
    cube,
    dimensions,
    formats,
    lifecycle,
    quality,
    release,
    timeline,
)
from insight.texts import IDENTIFIER_KINDS
from profiler import safety
from profiler.stats import lengths
from recall.german.identifiers import SHAPE_ALPHABET, SHAPE_MAX

KEYS = frozenset(
    {
        "any_share",
        "any_share_after_cleaning",
        "axes",
        "baug",
        "baugruppe",
        "baugruppe_model_year",
        "below_floor",
        "bigrams",
        "bigrams_omitted",
        "bigrams_withheld",
        "blank",
        "blank_problem_text",
        "bucket",
        "buckets",
        "buckets_withheld",
        "by_category",
        "by_category_withheld",
        "by_dimension",
        "by_field",
        "by_kind",
        "by_lifecycle",
        "by_year",
        "by_year_omitted",
        "by_year_withheld",
        "bytes",
        "cat",
        "cells",
        "checked",
        "cluster_count",
        "code_commit",
        "codes_per_ticket_quantiles",
        "complete_triple",
        "concentration",
        "count",
        "coverage",
        "covered_share",
        "cube",
        "cuts",
        "days_since_delivery",
        "days_to_status_change_quantiles",
        "default_min_words",
        "delivery",
        "description",
        "description_fill",
        "dimensions",
        "distinct",
        "distinct_casefolded",
        "duplicate_solution_share",
        "empty",
        "enabled",
        "entity_like",
        "fields",
        "filename",
        "fill",
        "fill_by_year",
        "fill_by_year_withheld",
        "formats",
        "gap_days_quantiles",
        "gates",
        "gini",
        "hours",
        "identifiers",
        "ids_per_ticket_quantiles",
        "image_digest",
        "kind",
        "largest_cluster_share",
        "length",
        "length_quantiles",
        "lengths",
        "lifecycle",
        "measurement",
        "min_frequency",
        "min_words",
        "model",
        "model_id",
        "models",
        "models_withheld",
        "month",
        "multi_code_share",
        "multi_share",
        "near_duplicate",
        "negative_share",
        "newly_derivable",
        "no_solution",
        "noise",
        "noise_reasons",
        "origin",
        "overall",
        "pairs",
        "pairs_omitted",
        "pairs_skipped",
        "pairs_withheld",
        "partner",
        "passed",
        "per_entity_quantiles",
        "per_month",
        "per_month_withheld",
        "per_year",
        "per_year_withheld",
        "phrases",
        "prefix",
        "prefixes",
        "present",
        "problem",
        "problem_text",
        "problem_text_length_median",
        "problem_text_length_p95",
        "provenance",
        "quality",
        "quantiles",
        "readiness",
        "reason",
        "recurrence",
        "repeat_rate",
        "repeat_within_30_share",
        "repeat_within_365_share",
        "repeat_within_90_share",
        "repetition",
        "resolution",
        "retrievable",
        "row_count",
        "rows",
        "schema_version",
        "section",
        "selfcheck",
        "serial",
        "serial_prefixes_enabled",
        "serial_vehicle_id",
        "serials",
        "serials_with_several_vehicle_ids",
        "sha256",
        "shape",
        "shapes",
        "share",
        "share_in_clusters_at_least_k",
        "singleton_count",
        "solution_fill",
        "solution_present",
        "solution_tokens",
        "solution_tokens_omitted",
        "solution_tokens_withheld",
        "solutions",
        "source",
        "stage",
        "state",
        "states",
        "states_withheld",
        "stopped",
        "suppression",
        "templated",
        "text",
        "tickets",
        "tickets_after_cleaning",
        "tickets_per_serial_quantiles",
        "tickets_with_both",
        "tickets_with_previous",
        "timeline",
        "title",
        "title_tokens",
        "title_tokens_omitted",
        "title_tokens_withheld",
        "titles",
        "titles_trigrams",
        "token",
        "tokens",
        "tokens_omitted",
        "tokens_withheld",
        "too_short",
        "top",
        "top10_share",
        "top1_share",
        "top5_share",
        "top_omitted",
        "top_percent_share",
        "total",
        "trigrams",
        "trigrams_omitted",
        "trigrams_withheld",
        "unit",
        "usable",
        "value",
        "values",
        "vehicle_ids_with_several_serials",
        "vehicle_years",
        "vehicle_years_withheld",
        "vehicles",
        "vocabulary",
        "warranty",
        "withheld",
        "withheld_cells",
        "year",
    }
)

# Column names from the published 38-column contract, taken from the section modules that key a
# dict by them. A column name is structure, not content; a VALUE of that column never is a key.
COLUMN_KEYS = frozenset({*formats.COLUMNS, *dimensions.COLUMNS, *concentration.COLUMNS})

# Keys that are structure rather than content: quantile points and "max". No digit-only key is
# admitted, four digits included, because a plant number, a PIN or a serial could then travel as
# a dict key; no section keys a dict by year (years are entries in lists).
_STRUCTURAL_KEY = re.compile("|".join([*lengths.QUANTILE_POINTS, "max"]))
# ASCII digits only: \d would accept full-width and Arabic-Indic digits.
_YEAR_VALUE = re.compile("[0-9]{4}")

# What the operator may pass for provenance. Public so the CLI can refuse a bad value BEFORE any
# real data is read, instead of discovering it when the finished report is refused.
COMMIT = re.compile("[0-9a-f]{7,40}|unknown")
DIGEST = re.compile("sha256:[0-9a-f]{64}|unknown")

# Every section path a builder may report withheld rows for. A closed set, so a new withheld
# block has to be declared here, and test_every_declared_section_is_emitted fails if one is dead.
SECTIONS = (
    "origin.baugruppe.withheld",
    "origin.baugruppe.by_year_withheld",
    "origin.baugruppe.pairs_withheld",
    "origin.baugruppe_model_year.withheld",
    "origin.titles.tokens_withheld",
    "origin.titles.bigrams_withheld",
    "origin.vehicles.models_withheld",
    "origin.vehicles.vehicle_years_withheld",
    "origin.vehicles.serials.prefixes.withheld",
    *(f"formats.{column}.withheld" for column in formats.COLUMNS),
    "timeline.per_year_withheld",
    "timeline.per_month_withheld",
    "timeline.fill_by_year_withheld",
    *(f"lifecycle.{series}.buckets_withheld" for series in lifecycle.BUCKETS),
    "lifecycle.warranty.states_withheld",
    *(
        f"dimensions.{column}.{block}"
        for column in dimensions.COLUMNS
        for block in ("withheld", "by_year_withheld")
    ),
    "dimensions.by_category_withheld",
    "vocabulary.titles_trigrams.trigrams_withheld",
    *(f"vocabulary.solutions.{kind}_withheld" for kind in ("tokens", "bigrams", "trigrams")),
    "vocabulary.by_category_withheld",
    "vocabulary.by_category.title_tokens_withheld",
    "vocabulary.by_category.solution_tokens_withheld",
    "quality.by_year_withheld",
    *(
        f"quality.by_dimension.{dimension}.{block}"
        for dimension in quality.DIMENSIONS
        for block in ("withheld", "by_year_withheld")
    ),
    *(f"quality.by_lifecycle.{series}.buckets_withheld" for series in lifecycle.BUCKETS),
    "quality.by_lifecycle.warranty.states_withheld",
    "quality.cube.cuts.withheld",
)

# Where each released field may stand: the path of the entry list that carries it, matched in
# full. The sweep and the floor say whether a value may leave; this says where. Without it a
# short id in the concentration section, which is numbers only, would pass the code sweep.
RELEASED_AT = {
    "origin.baugruppe.top": {"value"},
    "origin.baugruppe.by_year": {"value"},
    "origin.baugruppe.pairs": {"value", "partner"},
    "origin.baugruppe_model_year.cells": {"value", "model"},
    "origin.titles.tokens": {"token"},
    "origin.titles.bigrams": {"token"},
    "origin.vehicles.models": {"model"},
    "origin.vehicles.serials.prefixes.buckets": {"prefix"},
    **{f"formats.{column}.shapes": {"shape"} for column in formats.COLUMNS},
    **{
        f"dimensions.{column}.{entries}": {"value"}
        for column in dimensions.COLUMNS
        for entries in ("values", "by_year")
    },
    "dimensions.by_category": {"value"},
    "vocabulary.titles_trigrams.trigrams": {"token"},
    **{f"vocabulary.solutions.{kind}": {"token"} for kind in ("tokens", "bigrams", "trigrams")},
    "vocabulary.by_category": {"value"},
    "vocabulary.by_category.title_tokens": {"token"},
    "vocabulary.by_category.solution_tokens": {"token"},
    **{
        f"quality.by_dimension.{dimension}.{entries}": {"value"}
        for dimension in quality.DIMENSIONS
        for entries in ("values", "by_year")
    },
    "quality.cube.cuts.cells": {"cat", "baug", "model"},
}

_KIND = re.compile("|".join(IDENTIFIER_KINDS))

# A shape as `shape_of` can emit it: `A` (an uppercase first letter) only as the FIRST character,
# the rest drawn from the closed alphabet, at most SHAPE_MAX in all. The guard checks this
# itself and does not trust release._shape_flagged, so a builder bug cannot widen it.
_SHAPE_TAIL = SHAPE_ALPHABET.replace("A", "")
_SHAPE = re.compile(f"[{SHAPE_ALPHABET}][{_SHAPE_TAIL}]{{0,{SHAPE_MAX - 1}}}")

# Every path that carries a `year` string: the entry lists that bucket by calendar year. A year
# is four ASCII digits and nothing else, and only here; anywhere else a four-digit string is just
# a number that looks like one.
YEARS = frozenset(
    {
        "origin.baugruppe.by_year.year",
        "origin.baugruppe_model_year.cells.year",
        "origin.vehicles.vehicle_years.year",
        "timeline.per_year.year",
        "timeline.fill_by_year.year",
        *(f"dimensions.{column}.by_year.year" for column in dimensions.COLUMNS),
        "quality.by_year.year",
        *(f"quality.by_dimension.{dimension}.by_year.year" for dimension in quality.DIMENSIONS),
    }
)


def _labels(labels: tuple[str, ...]) -> re.Pattern[str]:
    """Exactly these fixed labels, escaped: '5000+' is a label, not a pattern."""
    return re.compile("|".join(re.escape(label) for label in labels))


# The only strings the report writes itself, blessed by PATH and constrained by SHAPE (matched
# with fullmatch, so a trailing newline does not pass), so the same text appearing anywhere else
# is still refused.
LITERALS = {
    "schema_version": re.compile("insight-[0-9]{1,3}"),
    "source.filename": re.compile("export\\.csv|<non-conforming>"),
    "source.sha256": re.compile("[0-9a-f]{64}"),
    "provenance.stage": re.compile("stage1-deterministic"),
    "provenance.code_commit": COMMIT,
    "provenance.image_digest": DIGEST,
    "suppression.section": re.compile("|".join(re.escape(s) for s in SECTIONS)),
    "suppression.reason": re.compile("below_floor|entity_like"),
    "text.lengths.unit": re.compile("whitespace_tokens"),
    "text.identifiers.problem.by_kind.kind": _KIND,
    "text.identifiers.solutions.by_kind.kind": _KIND,
    **{
        f"lifecycle.{series}.buckets.bucket": _labels(buckets)
        for series, buckets in lifecycle.BUCKETS.items()
    },
    "lifecycle.warranty.states.state": _labels(lifecycle.STATES),
    **{
        f"quality.by_lifecycle.{series}.buckets.bucket": _labels(buckets)
        for series, buckets in lifecycle.BUCKETS.items()
    },
    "quality.by_lifecycle.warranty.states.state": _labels(lifecycle.STATES),
    "timeline.per_month.month": timeline.MONTH,
    "quality.cube.gates": re.compile(re.escape(cube.GATE_ORDER)),
    "quality.cube.cuts.axes": _labels(cube.CUT_NAMES),
    "quality.cube.cuts.cells.gates": re.compile(f"[01]{{{len(cube.GATES)}}}"),
    "quality.cube.measurement.stopped": re.compile("budget|solver"),
}

# What a finished report may hold. A tuple, a set, bytes or any object is refused: json.dumps
# writes a tuple as a list, so one would reach the file without ever having been examined.
_LEAVES = (str, int, float, bool, type(None))

_Found = list[tuple[str, str, str]]


def _literal_ok(path: str, value: str) -> bool:
    pattern = LITERALS.get(path)
    if pattern is not None:
        return bool(pattern.fullmatch(value))
    return path in YEARS and bool(_YEAR_VALUE.fullmatch(value))


def _scan(node: object, path: str, k: int, found: _Found) -> None:
    if isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                # No list of bare strings is declared anywhere in a report: entries are dicts,
                # so a string here is unaccounted for whatever it says.
                found.append((path, "UNACCOUNTED_STRING", item))
            else:
                _scan(item, path, k, found)
        return
    if not isinstance(node, dict):
        if not isinstance(node, _LEAVES):
            found.append((path or "<root>", "UNACCOUNTED_TYPE", type(node).__name__))
        elif isinstance(node, float) and not math.isfinite(node):
            # NaN and inf pass every other check and then break json.dumps(allow_nan=False), which
            # would spend a sealed window on a crash.
            found.append((path or "<root>", "NON_FINITE", repr(node)))
        return
    released = [f for f in sorted(release.RELEASED_FIELDS) if isinstance(node.get(f), str)]
    # A released field holds a string. An int, a float, a bool, None or a list in its place would
    # be an id travelling as a number, and is refused without being looked into.
    wrong_type = {f for f in release.RELEASED_FIELDS if f in node and not isinstance(node[f], str)}
    for field in sorted(wrong_type):
        found.append((path, "UNACCOUNTED_TYPE", type(node[field]).__name__))
    count = node.get("count")
    for field in released:
        value = node[field]
        if field not in RELEASED_AT.get(path, ()):
            found.append((path, "UNACCOUNTED_STRING", value))
        elif not isinstance(count, int) or isinstance(count, bool):
            found.append((path, "MISSING_COUNT", value))
        elif count < k:
            found.append((path, "BELOW_FLOOR", value))
        elif release.flagged(field, value) or (field == "shape" and not _SHAPE.fullmatch(value)):
            found.append((path, "ENTITY_LIKE", value))
    for key, value in node.items():
        if not isinstance(key, str):
            found.append((path or "<root>", "UNDECLARED_KEY", repr(key)))
            continue
        known = key in KEYS or key in COLUMN_KEYS or bool(_STRUCTURAL_KEY.fullmatch(key))
        if not known:
            found.append((path or "<root>", "UNDECLARED_KEY", key))
        # An undeclared key is corpus text, so it never becomes part of a location.
        child = (f"{path}.{key}" if path else key) if known else path
        if key in wrong_type:
            continue  # already refused above, and not scanned as if it were content
        if isinstance(value, str):
            if key not in released and not _literal_ok(child, value):
                found.append((child, "UNACCOUNTED_STRING", value))
        else:
            _scan(value, child, k, found)


def _dicts_at(node: object, target: str, path: str = "") -> list[dict]:
    """Every dict that `_scan` would visit at `target`, whatever shape carries it there. `_scan`
    builds a path from dict keys only, so a list (or a list of lists) adds nothing to it; a check
    that walked only the builder's own shape would miss a reshaped report that `_scan` still
    reaches at the same path (review finding on b07bf50)."""
    if isinstance(node, list):
        return [d for item in node for d in _dicts_at(item, target, path)]
    if not isinstance(node, dict):
        return []
    if path == target:
        return [node]
    found = []
    for key, value in node.items():
        if not isinstance(key, str):
            continue
        child = f"{path}.{key}" if path else key
        if target == child or target.startswith(child + "."):
            found.extend(_dicts_at(value, target, child))
    return found


def _cube_found(report: dict, k: int) -> _Found:
    """A cube cell names only values listed in `quality.by_dimension` (or a sentinel), and exactly
    the axes of its cut. The floor and the sweep are `_scan`'s. This keeps the report consistent
    with itself: a value must stand, floored and swept, in the quality section's own lists."""
    allowed = {
        axis: {
            e["value"]
            for e in _dicts_at(report, f"quality.by_dimension.{source}.values")
            if isinstance(e.get("value"), str)
        }
        | set(cube.SENTINELS)
        for axis, source in cube.SOURCES.items()
    }
    found: _Found = []
    path = "quality.cube.cuts.cells"
    for cell in _dicts_at(report, path):
        # A cell of the gates-only cut has no released field, so `_scan` does not floor it.
        if not any(isinstance(cell.get(f), str) for f in release.RELEASED_FIELDS):
            count = cell.get("count")
            if not isinstance(count, int) or isinstance(count, bool):
                found.append((path, "MISSING_COUNT", "gates"))
            elif count < k:
                found.append((path, "BELOW_FLOOR", "gates"))
        for axis, values in allowed.items():
            if isinstance(cell.get(axis), str) and cell[axis] not in values:
                found.append((path, "UNRELEASED_VALUE", cell[axis]))
    for cut in _dicts_at(report, "quality.cube.cuts"):
        named = set(cut["axes"].split("+")) if isinstance(cut.get("axes"), str) else set()
        for cell in _dicts_at(cut.get("cells"), ""):
            carried = [axis for axis in cube.AXES if axis in cell]
            if set(carried) != named:
                found.append((path, "CUT_MISMATCH", "+".join(carried)))
    return found


def _found(report: object, k: int) -> _Found:
    if not isinstance(report, dict):
        return [("<root>", "UNACCOUNTED_TYPE", type(report).__name__)]
    found: _Found = []
    _scan(report, "", k, found)
    found.extend(_cube_found(report, k))
    return sorted(found, key=lambda item: (item[0], item[1]))


def unaccounted(report: object, k: int = release.K) -> list[tuple[str, str]]:
    """(path, reason) for everything refused, in a stable order. Never the value."""
    return [(path, code) for path, code, _ in _found(report, k)]


def _safety_code(code: str) -> str:
    return "TOPVALUE_BELOW_MIN_FREQ" if code == "BELOW_FLOOR" else "ENTITY_PATTERN_MATCH"


def _violation(code: str, location: str, offenders: int) -> safety.SafetyViolation:
    try:
        return safety.SafetyViolation(code, location, offenders=offenders)
    except ValueError:
        # The location was not a plain schema path, so it may carry corpus text.
        return safety.SafetyViolation(code, "insight", offenders=offenders)


def assert_safe(report: object, k: int = release.K) -> None:
    """Raise SafetyViolation if anything is refused. Verbatim values go to the local log only.

    The raised code does not depend on traversal order: anything that is not merely a
    below-floor value outranks one that is, and the location is the first in sorted order.
    """
    found = _found(report, k)
    if not found:
        return
    for path, code, value in found:
        safety.detail(_safety_code(code), path, f"{code}: {value}")
    serious = [item for item in found if item[1] != "BELOW_FLOOR"]
    path, code, _ = (serious or found)[0]
    raise _violation(_safety_code(code), path, len(found))
