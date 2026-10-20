"""Profile the customData column: structure only, never its values.

Round 1 measured this field's length and never looked inside it, despite it being
present in nearly every row and being long. If the client records error
codes here, the identifier retrieval arm is well-founded after all - and that is
decidable from key names and value SHAPES without emitting a single value.

Nothing here emits a value. Key names are emitted only after clearing a presence floor
and the entity sweep; values contribute only counts, quantiles and shapes.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from profiler import entities
from profiler.stats import lengths
from recall.german.identifiers import shape_of

_KV_PAIR = re.compile(r"^\s*([^=;\n]{1,64})=([^;\n]*)\s*$")
_KV_SPLIT = re.compile(r"[;\n]")
_NUMERIC = re.compile(r"^\d+([.,]\d+)?$")
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")

# A key must be present in this share of ALL rows as well as clearing the absolute
# floor. The absolute floor is the main control; this guards small corpora.
PRESENCE_SHARE_FLOOR = 0.01

# Nesting deeper than this is flattened to a single value rather than recursed into.
MAX_NESTING_DEPTH = 12

# How many times a value may have been JSON-encoded. The export encodes twice; more than
# that is pathological rather than a format, and chasing it is a denial of service.
MAX_UNWRAP = 2

# Attributes that name and carry a field in an entity-attribute-value envelope.
EAV_NAME_ATTRS = ("key", "name", "field", "feld", "id")
EAV_VALUE_ATTRS = ("value", "wert", "text", "val")
EAV_MIN_SHARE = 0.5


def _flatten(obj: dict, prefix: str = "", depth: int = 0) -> dict[str, str]:
    """Nesting deeper than MAX_NESTING_DEPTH is flattened to a single value rather than
    recursed into. Unbounded recursion here raised RecursionError on pathological input,
    and a crash inside a sealed window costs the whole window."""
    out: dict[str, str] = {}
    for key, value in obj.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and depth < MAX_NESTING_DEPTH:
            out.update(_flatten(value, f"{path}.", depth + 1))
        elif isinstance(value, list):
            out[path] = " ".join(str(v) for v in value)
        elif isinstance(value, dict):
            out[path] = ""  # too deep to descend; recorded as present but not expanded
        else:
            out[path] = "" if value is None else str(value)
    return out


def _load_json(text: str) -> object | None:
    """Load JSON, unwrapping a value that was serialised more than once.

    The real export stores customData double-encoded: a JSON string whose content is a
    JSON array, so the field begins with a quote and json.loads returns str rather than a
    container. A single load therefore looks like success while yielding nothing, which
    is why round 2 parsed none of the non-empty values.

    Bounded, because chasing an arbitrarily re-encoded value is a denial of service and
    this runs inside a sealed window where nothing can be diagnosed.
    """
    for _ in range(MAX_UNWRAP + 1):
        try:
            loaded = json.loads(text)
        except (ValueError, RecursionError):
            return None
        if isinstance(loaded, str):
            text = loaded
            continue
        return loaded
    return None


def parse_records(value: str | None) -> list[dict] | None:
    """Every JSON object the value contains, unmerged. None when it is not JSON at all.

    profile() needs the objects separately: merging keeps only the last descriptor in a
    row, so a ticket carrying six fields would contribute one.
    """
    if not value or not value.strip():
        return None
    text = value.strip()
    if text[:1] not in ("{", "[", '"'):
        return None
    loaded = _load_json(text)
    if isinstance(loaded, dict):
        return [loaded]
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    return None


def detect_envelope(rows: list[list[dict]], min_share: float = EAV_MIN_SHARE) -> str | None:
    """Which attribute names the field, if these rows hold descriptors rather than records?

    The export wraps customData as a list of field descriptors - {group, key, label,
    value, text, type} - so the JSON keys are the envelope's own attribute names and the
    client's real field names are VALUES of `key`. Reporting the envelope as the schema
    answers the wrong question: it says the corpus has six fields called group, key,
    label, value, text and type, when it has however many the client configured.

    A name attribute alone is not enough - an ordinary record could have a column called
    'key' - so a value-carrying attribute must be present too.
    """
    named: Counter[str] = Counter()
    total = 0
    for records in rows:
        if not records:
            continue
        total += 1
        attrs: set[str] = set()
        for record in records:
            attrs.update(record.keys())
        if not any(a in attrs for a in EAV_VALUE_ATTRS):
            continue
        for attr in EAV_NAME_ATTRS:
            if attr in attrs:
                named[attr] += 1
                break
    if not total or not named:
        return None
    attr, count = named.most_common(1)[0]
    return attr if count / total >= min_share else None


def parse(value: str | None) -> dict[str, str] | None:
    """JSON object or array first, then key=value pairs. None when neither applies.

    Never raises: a malformed value is a count, not an exception. The offending text
    must not travel, so nothing about it is returned or logged here."""
    if not value or not value.strip():
        return None
    text = value.strip()
    if text[:1] in ("{", "[", '"'):
        loaded = _load_json(text)
        try:
            if isinstance(loaded, dict):
                return _flatten(loaded)
            if isinstance(loaded, list):
                # Merged, not indexed: the inventory wants key names, and '0.fehler'
                # would be a row number masquerading as schema. An empty array returns
                # {} rather than None - valid syntax carrying no keys is not the same as
                # a value that could not be read, and conflating them understates the
                # parse rate.
                merged: dict[str, str] = {}
                for item in loaded:
                    if isinstance(item, dict):
                        merged.update(_flatten(item))
                return merged
        except RecursionError:
            return None
        return None
    pairs: dict[str, str] = {}
    for chunk in _KV_SPLIT.split(text):
        m = _KV_PAIR.match(chunk)
        if m:
            pairs[m.group(1).strip()] = m.group(2).strip()
    return pairs or None


def detect_format(values: list[str | None]) -> str:
    """Which shape does the majority of non-empty values take?"""
    non_empty = [v for v in values if v and v.strip()]
    if not non_empty:
        return "unknown"
    # Opening character alone is not enough: the export's values open with a quote
    # because they are double-encoded, and a bare quote is not evidence of JSON. Ask
    # whether the value actually loads as a JSON container.
    json_like = sum(
        1
        for v in non_empty
        if v.strip()[:1] in ("{", "[", '"') and isinstance(_load_json(v.strip()), (dict, list))
    )
    parsed = sum(1 for v in non_empty if parse(v) is not None)
    if json_like / len(non_empty) >= 0.5:
        return "json"
    if parsed / len(non_empty) >= 0.5:
        return "key_value"
    return "unknown"


def classify(values: list[str]) -> str:
    """Which kind of data does this key hold? Rules are evaluated in order and the
    first match wins, so a key cannot be two kinds."""
    if not values:
        return "empty"
    total = len(values)
    non_empty = [v for v in values if v and v.strip()]
    if len(non_empty) / total < 0.05:
        return "empty"
    if sum(1 for v in non_empty if _NUMERIC.match(v.strip())) / len(non_empty) >= 0.90:
        return "numeric"
    id_like = sum(1 for v in non_empty if len(v) <= 32 and any(c.isdigit() for c in v))
    if id_like / len(non_empty) >= 0.70:
        return "identifier_like"
    tokens = [len(_WORD.findall(v)) for v in non_empty]
    mean_tokens = sum(tokens) / len(non_empty)
    mean_chars = sum(len(v) for v in non_empty) / max(1, sum(tokens))
    if mean_tokens >= 5 and mean_chars <= 12:
        return "prose"
    return "short_text"


# Longer than this and a character-class shape starts to fingerprint the value, because
# it preserves word lengths and punctuation positions.
MAX_SHAPED_VALUE_CHARS = 64
MAX_SHAPES_PER_KEY = 10

# custom_data.keys is rendered as a table in profile_report.md, which the operator reads
# in full inside the window. An unbounded list turns that review into skimming, and that
# review is the control the airlock rests on. Matches MAX_DIMENSION_CARDINALITY.
MAX_KEYS = 200

# A key name is schema; a long one is more likely to be data, because some systems key
# by a value. The entity sweep filters names, not lengths, so a sentence-shaped key
# passes it. Matches MAX_SHAPED_VALUE_CHARS.
MAX_KEY_NAME_CHARS = 64


# customData keys are snake_case, camelCase or dotted, so they contain no whitespace -
# and looks_like_entity splits on whitespace. Sweeping only the whole key means
# looks_like_entity('huber_sonderfeld') is False while 'huber' alone is True, so a key
# named after a person reaches the artifact. Key names are the only customData strings
# that are emitted at all, which makes this sweep the one control on them.
_KEY_PARTS = re.compile(r"[^0-9A-Za-zÄÖÜäöüß]+")


def _is_entity_named(key: str) -> bool:
    if entities.looks_like_entity(key):
        return True
    return any(part and entities.looks_like_entity(part) for part in _KEY_PARTS.split(key))


def _is_emittable(key: str) -> bool:
    """A key name is the only customData string that reaches the artifact, and the
    artifact is written with json.dumps(ensure_ascii=False) + write_text - which raises
    on a lone surrogate. Crashing at write time inside a sealed window costs the whole
    window, so an unencodable key is dropped rather than risked."""
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _describe(values: list[str], min_frequency: int) -> dict:
    """Counts, quantiles and shapes for one field's values. Shared by the plain-key and
    envelope paths so the two cannot describe the same thing differently."""
    non_empty = [v for v in values if v and v.strip()]
    kind = classify(values)
    shapeable = [v for v in non_empty if len(v) <= MAX_SHAPED_VALUE_CHARS]
    shape_counts = Counter(shape_of(v) for v in shapeable) if kind != "prose" else Counter()
    kept = [{"shape": s, "count": c} for s, c in shape_counts.most_common() if c >= min_frequency][
        :MAX_SHAPES_PER_KEY
    ]
    return {
        "present_count": len(values),
        "fill_rate": len(non_empty) / len(values) if values else 0.0,
        "kind": kind,
        "value_char_len_quantiles": lengths.quantiles([len(v) for v in non_empty]),
        "value_shapes": kept,
        "shapes_suppressed": max(0, len(shape_counts) - len(kept)),
        "long_value_count": len(non_empty) - len(shapeable),
    }


def _suppress(name: str, count: int, presence_floor: int) -> bool:
    """Same four gates a plain key name passes: floor, length, entity sweep, encodability."""
    return (
        count < presence_floor
        or len(name) > MAX_KEY_NAME_CHARS
        or _is_entity_named(name)
        or not _is_emittable(name)
    )


def _envelope_inventory(
    rows: list[list[dict]], name_attr: str, min_frequency: int, total_rows: int
) -> dict:
    """Inventory the field names an EAV envelope carries in its values.

    These names are schema, not ticket content, and they pass exactly the gates a JSON
    key name passes - presence floor, length cap, entity sweep, encodability - because
    they are the same kind of string arriving by a different route.
    """
    by_field: dict[str, list[str]] = defaultdict(list)
    for records in rows:
        for record in records:
            name = record.get(name_attr)
            if not isinstance(name, str) or not name.strip():
                continue
            attr = next((a for a in EAV_VALUE_ATTRS if a in record), None)
            raw = record.get(attr) if attr else None
            by_field[name.strip()].append("" if raw is None else str(raw))

    presence_floor = max(min_frequency, int(total_rows * PRESENCE_SHARE_FLOOR))
    fields, suppressed = [], 0
    for name, field_values in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        if _suppress(name, len(field_values), presence_floor):
            suppressed += 1
            continue
        fields.append({"name": name, **_describe(field_values, min_frequency)})

    return {
        "detected": True,
        "name_attribute": name_attr,
        "distinct_field_count": len(by_field),
        "fields_suppressed": suppressed,
        "fields_omitted_over_cap": max(0, len(fields) - MAX_KEYS),
        "fields": fields[:MAX_KEYS],
        "records_per_row_quantiles": lengths.quantiles([len(r) for r in rows if r]),
    }


def _no_envelope() -> dict:
    return {
        "detected": False,
        "name_attribute": None,
        "distinct_field_count": 0,
        "fields_suppressed": 0,
        "fields_omitted_over_cap": 0,
        "fields": [],
        "records_per_row_quantiles": lengths.quantiles([]),
    }


def profile(values: list[str | None], min_frequency: int, total_rows: int) -> dict:
    """Structure of the customData column. Emits key names, kinds, fill rates, value
    length quantiles and value shapes - never a value."""
    parsed_rows = [parse(v) for v in values]
    parsed_ok = [r for r in parsed_rows if r is not None]
    present = len([v for v in values if v and v.strip()]) or 1

    per_key: dict[str, list[str]] = defaultdict(list)
    for row in parsed_ok:
        for key, value in row.items():
            per_key[key].append(value)

    presence_floor = max(min_frequency, int(total_rows * PRESENCE_SHARE_FLOOR))
    keys_out: list[dict] = []
    suppressed = 0

    for key, key_values in sorted(per_key.items(), key=lambda kv: -len(kv[1])):
        if _suppress(key, len(key_values), presence_floor):
            suppressed += 1
            continue
        keys_out.append({"key": key, **_describe(key_values, min_frequency)})

    records_by_row = [parse_records(v) or [] for v in values]
    name_attr = detect_envelope(records_by_row)
    envelope = (
        _envelope_inventory(records_by_row, name_attr, min_frequency, total_rows)
        if name_attr
        else _no_envelope()
    )

    return {
        "envelope": envelope,
        "format": detect_format(values),
        "parse_success_rate": len(parsed_ok) / present,
        "keys_per_row_quantiles": lengths.quantiles([len(r) for r in parsed_ok]),
        "distinct_key_count": len(per_key),
        "keys_suppressed": suppressed,
        "keys_omitted_over_cap": max(0, len(keys_out) - MAX_KEYS),
        "keys": keys_out[:MAX_KEYS],
    }
