from __future__ import annotations

import re

from profiler import entities, safety

# No value from these columns is ever emitted, at any frequency. Only lengths,
# null rates and cardinality estimates.
DENYLISTED_COLUMNS = frozenset(
    {
        "merchantName",
        "endCustomerName",
        "contactEmail",
        "contactPhone",
        "contactPhoneTrimmed",
        "merchantPhoneNumber",
        "endCustomerPhoneNumber",
        "endCustomerNumber",
        "merchantNumber",
        "vehicleSerialNo",
        "personId",
        "lastModifiedUser",
        "userCreatedId",
        "userAssignedId",
    }
)

# Columns whose values are PRODUCT designations, not personal data. The entity
# sweep's plate heuristic (^[A-Z]{1,2}[\s-]?\d{1,5}[A-Z]{0,3}$) cannot tell
# 'TX-2210' from an Austrian licence plate - they are genuinely the same shape - so
# without this exemption the profiler refuses to emit any profile at all, which is
# what the stand-in rehearsal caught. Shape cannot separate them; column context
# can. PROJECT_BRIEF.md §4 lists vehicleModelId under "Filterable metadata" and
# NOT under PII, and these columns are dimension-capped (<=200 distinct) and
# frequency-floored, so a stray plate could not reach top_values anyway.
# The frequency floor and the surname/company checks still apply here - only the
# contact-shape heuristics are relaxed.
PRODUCT_DIMENSION_COLUMNS = frozenset({"vehicleModelId", "vehicleStatus", "subStatusString"})

_HAS_DIGITS = re.compile(r"\d")

# A location is only safe to put in a SafetyViolation if it is a plain schema path. An
# unblessed *dict key* is reported with the path it was found at, and that path can
# itself contain a corpus-derived key name (custom_data keys are corpus text). Anything
# that does not match this is replaced before it reaches the message.
_SCHEMA_PATH = re.compile(r"^[a-z_]+(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _reject(code: str, location: str, payload: str, **facts: float) -> None:
    """Record the verbatim value locally, then raise a message that cannot carry it."""
    safety.detail(code, location, payload)
    raise safety.SafetyViolation(code, location, **facts)


def assert_safe(profile: dict) -> list[str]:
    """Enforce the safety invariant. Returns warnings; raises on violation.

    Two independent checks, because they catch opposite failures: the frequency
    floor catches RARE strings (where identifiers hide) and the entity sweep
    catches COMMON ones (where company and person names hide)."""
    warnings: list[str] = []

    vocab_section = profile.get("vocabulary", {})
    min_freq = vocab_section.get("min_frequency_threshold", 0)
    for key in ("top_tokens", "top_bigrams", "hunspell_unrecognized_top"):
        for index, entry in enumerate(vocab_section.get(key, [])):
            location = f"vocabulary.{key}[{index}]"
            if entry["count"] < min_freq:
                _reject(
                    "VOCAB_BELOW_MIN_FREQ",
                    location,
                    entry["token"],
                    count=entry["count"],
                    threshold=min_freq,
                )
            if entities.looks_like_entity(entry["token"]):
                _reject("ENTITY_PATTERN_MATCH", location, entry["token"], count=entry["count"])

    for column, stats in profile.get("per_field", {}).items():
        location = f"per_field.{column}"
        if stats.get("top_values") and column in DENYLISTED_COLUMNS:
            _reject(
                "DENYLISTED_COLUMN_VALUES",
                location,
                f"{len(stats['top_values'])} values present",
                value_count=len(stats["top_values"]),
            )
        for index, entry in enumerate(stats.get("top_values", [])):
            if entry["count"] < min_freq:
                _reject(
                    "TOPVALUE_BELOW_MIN_FREQ",
                    f"{location}[{index}]",
                    entry["value"],
                    count=entry["count"],
                    threshold=min_freq,
                )
            if column in PRODUCT_DIMENSION_COLUMNS:
                # Still reject a person or company name appearing here; only the
                # contact-shape heuristics are relaxed. See PRODUCT_DIMENSION_COLUMNS.
                flagged = entities.looks_like_named_entity(entry["value"])
            else:
                flagged = entities.looks_like_entity(entry["value"])
            if flagged:
                _reject(
                    "ENTITY_PATTERN_MATCH",
                    f"{location}[{index}]",
                    entry["value"],
                    count=entry["count"],
                )

    for index, grammar in enumerate(profile.get("identifier_grammars", [])):
        shape = grammar.get("shape", "")
        if _HAS_DIGITS.search(shape):
            _reject(
                "SHAPE_CONTAINS_DIGITS",
                f"identifier_grammars[{index}]",
                shape,
                count=grammar.get("count", 0),
            )

    for section, hints in profile.get("dimension_hints", {}).items():
        for hint_index, hint in enumerate(hints):
            location = f"dimension_hints.{section}[{hint_index}]"
            # The `id` is a raw column value emitted verbatim, so it is subject to the
            # same invariant as every other emitted string: a frequency floor plus the
            # entity sweep. Checking only top_tokens left a hole through which a rare
            # dimension value (e.g. a cost-centre string carrying a surname) reached
            # profile.json - the one artifact an AI is allowed to read.
            raw_id = hint.get("id")
            if raw_id is not None and isinstance(raw_id, str) and raw_id.strip():
                count = hint.get("count", 0)
                if count < min_freq:
                    _reject(
                        "TOPVALUE_BELOW_MIN_FREQ",
                        location,
                        raw_id,
                        count=count,
                        threshold=min_freq,
                    )
                # Same exemption, same reason, as per_field.top_values above: a model
                # designation and an Austrian plate are the same shape, so a
                # product-dimension column gets the name half of the sweep only. Without
                # this, adding vehicleModelId to DIMENSION_HINT_COLUMNS makes the
                # profiler refuse every profile - the identical value is accepted in
                # per_field.top_values and rejected here.
                if section in PRODUCT_DIMENSION_COLUMNS:
                    flagged = entities.looks_like_named_entity(raw_id)
                else:
                    flagged = entities.looks_like_entity(raw_id)
                if flagged:
                    _reject("ENTITY_PATTERN_MATCH", location, raw_id, count=count)

            for token_index, token in enumerate(hint.get("top_tokens", [])):
                if entities.looks_like_entity(token):
                    _reject("ENTITY_PATTERN_MATCH", location, token, token_index=token_index)
                if _HAS_DIGITS.search(token) and len(token) > 6:
                    safety.detail("ENTITY_PATTERN_MATCH", location, token)
                    warnings.append(f"{location} holds an identifier-like token; see detail log")

    # Catch-all. Everything above protects a path someone remembered; this rejects any
    # string that is not accounted for at all, so a new section cannot ship unchecked.
    from profiler import blessing

    for location, value in blessing.unblessed(profile):
        # Same split as _reject, applied to the location as well as the payload. A path
        # here can be built from a corpus-derived dict key, and any path carrying a list
        # index fails the guard, so raising it sanitised would leave the operator with
        # location "profiler" and nowhere to look. The detail log never leaves the box
        # and already holds verbatim values, so the real path is recorded there.
        safety.detail("ENTITY_PATTERN_MATCH", location, value)
        raise safety.SafetyViolation(
            "ENTITY_PATTERN_MATCH",
            location if _SCHEMA_PATH.match(location) else "profiler",
            unblessed=1,
        )
    return warnings
