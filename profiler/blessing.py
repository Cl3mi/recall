"""Whole-artifact catch-all: no string leaves without an explicit reason to.

Every per-section check in selfcheck.py protects a path someone remembered to protect.
dimension_hints[].id was emitted verbatim, with neither a frequency floor nor an entity
sweep, precisely because nobody thought to add one. This walks the finished artifact and
rejects any string that is not accounted for, so a new section has to declare how its
strings are protected rather than being trusted by default.

What it does not do is re-check a path that has been explicitly exempted below. Those
paths carry their own floor and entity sweep in selfcheck, and the exemption is what
lets this run as a hard abort instead of a warning. So this catches the *unanticipated*
string - a new field, a new section - which is the shape the dimension_hints bug had.
Adding a path to either list below is a deliberate act that moves the protection
elsewhere; it is not a way to quiet a failure.
"""

from __future__ import annotations

import re

from profiler.columns import EXPECTED_COLUMNS
from recall.german.identifiers import SHAPE_ALPHABET, SHAPE_MAX

# Both the alphabet and the cap come from the constants shape_of actually uses. A
# transcribed 16 here would silently start rejecting real shapes the day SHAPE_MAX moves.
_SHAPE = re.compile(f"^[{re.escape(SHAPE_ALPHABET)}]{{1,{SHAPE_MAX}}}$")
_STRUCTURAL_KEY = re.compile(r"^p\d+$|^max$|^\d{4}-\d{2}$|^\d+$")

# Strings we wrote ourselves. Blessed by PATH, never by value, so the same text
# appearing somewhere unexpected is still rejected.
LITERAL_PATHS = frozenset(
    {
        "schema_version",
        "source.encoding_detected",
        "source.delimiter",
        "source.sha256",
        "source.filename",
        "clusters.method",
        "model_designations.inferred_family_rule",
        "multi_fault_estimate.heuristic",
        "solutions.junk_taxonomy.pattern",
        "solutions.cardinality.detected_separator",
        "identifier_grammars.kind",
        "identifier_grammars.regex",
        "custom_data.format",
        "custom_data.keys.kind",
        # Drawn from EAV_NAME_ATTRS and the kind enum - our own literals, not the corpus.
        "custom_data.envelope.name_attribute",
        "custom_data.envelope.fields.kind",
        "selfcheck.checks",
        "selfcheck.warnings",
    }
)

# Values at these paths cleared a frequency floor and the entity sweep when they were
# built, and selfcheck re-checks them section by section.
FLOORED_PATHS = frozenset(
    {
        "per_field.top_values.value",
        "dimension_hints.id",
        "custom_data.keys.key",
        # Field names carried in an EAV envelope's values. Schema rather than content,
        # and they pass the same four gates a JSON key name passes - presence floor,
        # length cap, entity sweep, encodability - because they are the same kind of
        # string arriving by a different route.
        "custom_data.envelope.fields.name",
    }
)


def _declared_keys(schema: dict) -> set[str]:
    found: set[str] = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.get("properties", {}).items():
            found.add(key)
            walk(value)
        for nested in ("additionalProperties", "items"):
            walk(node.get(nested))
        for definition in node.get("$defs", {}).values():
            walk(definition)

    walk(schema)
    return found


def generic_path(path: str, columns: set[str]) -> str:
    """Collapse a concrete path to the one the exemption lists are written in.

    per_field and dimension_hints are dicts keyed by column name, so a real path looks
    like per_field.categoryId.top_values.0.value. Stripping only the list indices leaves
    the column in place, and the declared exemption per_field.top_values.value then never
    matches anything - it reads as deliberate protection while doing nothing at all. Two
    entries were dead exactly that way when this was checked against the round-1 artifact.

    A column name is collapsed only in the middle of a path. First segment, because
    'solutions' is both a column and a top-level section; last segment, because 'id' is
    also a column name and stripping it would collapse dimension_hints.id to
    dimension_hints.
    """
    parts = path.split(".")
    last = len(parts) - 1
    return ".".join(
        part
        for i, part in enumerate(parts)
        if not part.isdigit() and (i == 0 or i == last or part not in columns)
    )


def _collect_floored(profile: dict) -> set[str]:
    """Every string that some floored, entity-swept list already vouches for."""
    blessed: set[str] = set()
    for key in ("top_tokens", "top_bigrams", "hunspell_unrecognized_top"):
        for entry in profile.get("vocabulary", {}).get(key, []):
            blessed.add(entry["token"])
    for stats in profile.get("per_field", {}).values():
        for entry in stats.get("top_values", []):
            blessed.add(entry["value"])
    for hints in profile.get("dimension_hints", {}).values():
        for hint in hints:
            blessed.add(str(hint.get("id")))
            blessed.update(hint.get("top_tokens", []))
    for cluster in profile.get("clusters", {}).get("largest", []):
        blessed.update(cluster.get("top_tokens", []))
    for entry in profile.get("custom_data", {}).get("keys", []):
        blessed.add(entry["key"])
    for entry in profile.get("custom_data", {}).get("envelope", {}).get("fields", []):
        blessed.add(entry["name"])
    return blessed


def unblessed(profile: dict, schema: dict | None = None) -> list[tuple[str, str]]:
    """Return (schema path, offending string) for everything unaccounted for."""
    if schema is None:
        import json
        import pathlib

        schema = json.loads(
            (pathlib.Path(__file__).parent / "schema.json").read_text(encoding="utf-8")
        )

    declared = _declared_keys(schema)
    columns = set(EXPECTED_COLUMNS) | set(profile.get("source", {}).get("columns_found", []))
    floored = _collect_floored(profile)
    custom_keys = {e["key"] for e in profile.get("custom_data", {}).get("keys", [])}
    found: list[tuple[str, str]] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if not (
                    key in declared
                    or key in columns
                    or _STRUCTURAL_KEY.match(key)
                    or key in custom_keys
                ):
                    found.append((path or "<root>", key))
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}.{index}")
        elif isinstance(node, str):
            base = generic_path(path, columns)
            if base in LITERAL_PATHS or base in FLOORED_PATHS:
                return
            if node in columns or _SHAPE.match(node) or node in floored:
                return
            found.append((base, node))

    walk(profile, "")
    return found
