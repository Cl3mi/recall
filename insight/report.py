"""Assemble the report, record what was withheld, and refuse to return anything the guard
does not accept."""

from __future__ import annotations

import copy

from insight import (
    concentration,
    crosstab,
    cube,
    dimensions,
    extract,
    formats,
    guard,
    lifecycle,
    origin,
    quality,
    readiness,
    release,
    texts,
    timeline,
    vocabulary,
)

SCHEMA_VERSION = "insight-1"
STAGE = "stage1-deterministic"

# Exactly these, so a caller cannot smuggle a key in or override what the build computes.
SOURCE_KEYS = frozenset({"filename", "sha256", "bytes", "row_count"})
PROVENANCE_KEYS = frozenset({"code_commit", "image_digest"})


def _suppression(node: object, path: str = "") -> list[dict]:
    """Flatten every `withheld` block into ledger rows: section, reason, distinct, rows.

    A zero is emitted as a zero. A reader must be able to tell a section that had nothing to
    withhold from one the ledger forgot, which is the lesson of checks.roster.values_traced.

    Rows are per block, so a ticket withheld from two sections (a Baugruppe is counted once in
    its distribution and again in its by-year cells) appears in both. Do not sum across sections.
    A block with only one of the two reasons is a bug in a builder and raises instead of being
    silently dropped. A bare `below_floor: bool` is not a block: it is the flag a quantile block
    carries to say its numbers were zeroed for standing on fewer than k observations.
    """
    if isinstance(node, list):
        found: list[dict] = []
        for item in node:
            found.extend(_suppression(item, path))
        return found
    if not isinstance(node, dict):
        return []
    reasons = {r for r in ("below_floor", "entity_like") if isinstance(node.get(r), dict)}
    if len(reasons) == 1:
        raise ValueError(f"the withheld block at {path} has only one of its two reasons")
    if reasons:
        return [
            {"section": path, "reason": reason, **node[reason]}
            for reason in ("below_floor", "entity_like")
        ]
    found = []
    for key, value in node.items():
        found.extend(_suppression(value, f"{path}.{key}" if path else key))
    return found


def build(
    rows: list[dict[str, str]],
    *,
    source: dict,
    provenance: dict,
    k: int = release.K,
    serial_prefixes: bool = False,
    cube_budget: float = cube.BUDGET,
) -> dict:
    # Checked and copied first. The report must not alias the caller's dicts (mutating them
    # after the guard ran would change a "guarded" report), and the caller must not be able to
    # override a value the build computes: provenance is spread FIRST, computed keys after.
    if set(source) != SOURCE_KEYS:
        raise ValueError("source must carry exactly filename, sha256, bytes and row_count")
    if set(provenance) != PROVENANCE_KEYS:
        raise ValueError("provenance must carry exactly code_commit and image_digest")
    if source["row_count"] != len(rows):
        raise ValueError("source.row_count does not match the rows")
    tickets = extract.tickets(rows)
    graded = quality.grades(tickets, k)
    origin_section = {
        "baugruppe": origin.baugruppe(tickets, k),
        "vehicles": origin.vehicles(tickets, k, serial_prefixes),
        "titles": origin.titles(tickets, k),
        "baugruppe_model_year": crosstab.baugruppe_model_year(tickets, k),
    }
    quality_section = quality.build(tickets, k, graded)
    quality_section["cube"] = cube.build(tickets, graded, quality_section["by_dimension"], k)
    quality_section["cube"]["measurement"] = cube.measure(
        tickets, quality_section, origin_section, k, cube_budget
    )
    built = {
        "schema_version": SCHEMA_VERSION,
        "source": copy.deepcopy(source),
        "provenance": {
            **copy.deepcopy(provenance),
            "stage": STAGE,
            "min_frequency": k,
            "serial_prefixes_enabled": serial_prefixes,
        },
        "origin": origin_section,
        "text": texts.build(tickets, k),
        "formats": formats.build(tickets, k),
        "timeline": timeline.build(tickets, k),
        "lifecycle": lifecycle.build(tickets, k),
        "dimensions": dimensions.build(tickets, k),
        "concentration": concentration.build(tickets, k),
        "vocabulary": vocabulary.build(tickets, k),
        "readiness": readiness.build(tickets, k),
        "quality": quality_section,
    }
    built["suppression"] = _suppression(built)
    built["selfcheck"] = {"passed": False}
    guard.assert_safe(built, k)
    built["selfcheck"] = {"passed": True}
    return built
