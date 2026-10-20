"""Corpus profiler. Runs inside an airlock window: no network, no DB, no GPU.

    python -m profiler --csv export.csv --out profile.json

Emits profile.json (safe to read) and profile_report.md (review artifact).
Refuses to write anything if the safety selfcheck fails.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import sys
from collections import Counter, defaultdict

from profiler import emit, entities, safety, selfcheck
from profiler.columns import (
    DIMENSION_COLUMNS,
    DIMENSION_HINT_COLUMNS,
    EXPECTED_COLUMNS,
    MAX_DIMENSION_CARDINALITY,
    TEXT_COLUMNS,
)
from profiler.stats import (
    clusters,
    customdata,
    hunspell,
    lengths,
    nullmask,
    shapes,
    solutions,
    temporal,
    vocab,
)
from recall.clean import pipeline
from recall.german import identifiers


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _drop_entities(entries: list[dict], location: str, warnings: list[str]) -> list[dict]:
    """Remove token entries that the entity sweep flags, recording how many.

    The verbatim tokens are NOT written anywhere - not even to the detail log - since
    dropping them is the normal path, not an incident. The count is a number, so it is
    safe to carry in the artifact.
    """
    kept = [e for e in entries if not entities.looks_like_entity(e["token"])]
    dropped = len(entries) - len(kept)
    if dropped:
        warnings.append(f"{location}: dropped {dropped} entity-matching token(s)")
    return kept


def _fill_by_month(rows: list[dict], column: str) -> dict[str, float]:
    """Non-empty rate per month. A flat line means a workflow reality; a step at a date
    means a system change, and recent data may be better than the corpus average."""
    seen: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        month = (row.get("timestampCreated") or "")[:7]
        if len(month) == 7:
            seen[month].append(1 if (row.get(column) or "").strip() else 0)
    return {m: sum(v) / len(v) for m, v in sorted(seen.items())}


def build_profile(
    csv_path: pathlib.Path, min_frequency: int, hunspell_dict: str | None = None
) -> dict:
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    columns_found = list(rows[0].keys()) if rows else []

    per_field: dict[str, dict] = {}
    for column in columns_found:
        # Keep the raw values: csv.DictReader yields None for a column missing from a
        # SHORT row, and collapsing that to "" up front made null_count dead code -
        # a structurally truncated export then looked merely sparsely filled.
        raw_values = [r.get(column) for r in rows]
        values = [(v or "") for v in raw_values]
        stats = {
            "present_count": sum(1 for v in values if v.strip()),
            "null_count": sum(1 for v in raw_values if v is None),
            "empty_string_count": sum(1 for v in values if v == ""),
            "distinct_count_estimate": len({v for v in values if v.strip()}),
            "char_len_quantiles": lengths.quantiles([len(v) for v in values]),
            "token_len_quantiles": lengths.quantiles([len(v.split()) for v in values]),
        }
        if column in TEXT_COLUMNS:
            cleaned = [pipeline.clean(v) for v in values]
            n = len(values) or 1
            stats.update(
                cleaned_char_len_quantiles=lengths.quantiles([len(c.text) for c in cleaned]),
                cleaned_token_len_quantiles=lengths.quantiles(
                    [len(c.text.split()) for c in cleaned]
                ),
                html_rate=sum(c.report.had_html for c in cleaned) / n,
                quoted_chain_rate=sum(c.report.had_quoted_chain for c in cleaned) / n,
                signature_rate=sum(c.report.had_signature for c in cleaned) / n,
                diag_dump_rate=sum(c.report.had_diag_dump for c in cleaned) / n,
                all_caps_rate=sum(c.report.is_all_caps for c in cleaned) / n,
                no_punctuation_rate=sum(c.report.has_no_punctuation for c in cleaned) / n,
            )
        if column in DIMENSION_COLUMNS and column not in selfcheck.DENYLISTED_COLUMNS:
            counts = Counter(v for v in values if v.strip())
            if len(counts) <= MAX_DIMENSION_CARDINALITY:
                stats["top_values"] = [
                    {"value": v, "count": c} for v, c in counts.most_common() if c >= min_frequency
                ]
        per_field[column] = stats

    problem_texts = [
        pipeline.clean(f"{r.get('title') or ''} {r.get('description') or ''}").text for r in rows
    ]
    token_counts = vocab.token_counts(problem_texts)

    custom_data_values = [r.get("customData") for r in rows]
    custom_data = customdata.profile(custom_data_values, min_frequency, len(rows))
    discovered_shapes = shapes.discover(
        {
            "title": [(r.get("title") or "") for r in rows],
            "description": [(r.get("description") or "") for r in rows],
            "solutions": [(r.get("solutions") or "") for r in rows],
            "customData": [(v or "") for v in custom_data_values],
        },
        min_frequency,
    )

    cluster_profile = clusters.profile(problem_texts)
    cluster_profile["largest"], cluster_profile["clusters_omitted"] = clusters.characterise(
        problem_texts, min_frequency, entities.looks_like_entity
    )

    all_identifiers = [i.value for text in problem_texts for i in identifiers.extract(text)]
    models = [(r.get("vehicleModelId") or "").strip() for r in rows]
    families = {identifiers.model_family(m) for m in models if m} - {None}
    per_family: dict[str, set[str]] = defaultdict(set)
    for m in models:
        fam = identifiers.model_family(m) if m else None
        if fam:
            per_family[fam].add(m)

    build_warnings: list[str] = []

    dimension_hints: dict[str, list[dict]] = {}
    for column in DIMENSION_HINT_COLUMNS:
        if column not in columns_found:
            continue
        grouped: dict[str, list[str]] = defaultdict(list)
        for row, text in zip(rows, problem_texts, strict=False):
            key = (row.get(column) or "").strip()
            if key:
                grouped[key].append(text)
        hints = []
        # `id` is a raw column value emitted verbatim, so it needs the same frequency
        # floor and cardinality cap as per_field.top_values. Without them a rare
        # dimension value - a cost-centre string carrying a surname, say - reached
        # profile.json unfloored. A dimension with fewer than min_frequency tickets is
        # useless as a category proxy anyway, which is what these hints are for.
        ordered = sorted(grouped.items(), key=lambda kv: -len(kv[1]))
        dropped_rare = sum(1 for _, texts in ordered if len(texts) < min_frequency)
        kept = [(k, t) for k, t in ordered if len(t) >= min_frequency][:MAX_DIMENSION_CARDINALITY]
        if dropped_rare:
            build_warnings.append(
                f"dimension_hints.{column}: dropped {dropped_rare} value(s) below "
                f"min_frequency={min_frequency}"
            )
        if len(ordered) > MAX_DIMENSION_CARDINALITY:
            build_warnings.append(
                f"dimension_hints.{column}: {len(ordered)} distinct values exceeds the "
                f"cardinality cap of {MAX_DIMENSION_CARDINALITY}; truncated"
            )
        for key, texts in kept:
            counts = vocab.token_counts(texts)
            hints.append(
                {
                    "id": key,
                    "count": len(texts),
                    "top_tokens": [t["token"] for t in vocab.top_tokens(counts, min_frequency, 15)],
                }
            )
        dimension_hints[column] = hints

    created = [(r.get("timestampCreated") or "")[:7] for r in rows]

    # source.filename reached the artifact verbatim, so an export named after the client
    # would put that name in the one file an AI is allowed to read. The runbook asks for
    # a rename; this stops that being a matter of discipline.
    if csv_path.name == "export.csv":
        filename = csv_path.name
    else:
        filename = "<non-conforming>"
        build_warnings.append(
            "source.filename was not 'export.csv' and has been withheld; "
            "rename the export before the next window"
        )

    profile = {
        "schema_version": "2",
        "source": {
            "filename": filename,
            "sha256": _sha256(csv_path),
            "bytes": csv_path.stat().st_size,
            "row_count": len(rows),
            "encoding_detected": "utf-8",
            "delimiter": ",",
            "columns_found": columns_found,
            "columns_expected_missing": [c for c in EXPECTED_COLUMNS if c not in columns_found],
            "columns_unexpected": [c for c in columns_found if c not in EXPECTED_COLUMNS],
        },
        "per_field": per_field,
        "null_mask_patterns": nullmask.joint_patterns(rows, columns_found),
        "identifier_grammars": identifiers.infer_grammars(all_identifiers),
        "custom_data": custom_data,
        "discovered_identifier_shapes": discovered_shapes["shapes"],
        "discovered_identifier_shapes_omitted": discovered_shapes["omitted_over_cap"],
        "model_designations": {
            "grammar": sorted({identifiers.shape_of(m) for m in models if m}),
            "inferred_family_rule": "uppercase prefix + first two digits (e.g. TX-2240 -> TX-22)",
            "family_count": len(families),
            "models_per_family_quantiles": lengths.quantiles([len(v) for v in per_family.values()]),
        },
        "dimension_hints": dimension_hints,
        "temporal": {
            "created_per_month": dict(Counter(c for c in created if len(c) == 7)),
            "age_years_quantiles": lengths.quantiles(
                temporal.ages_in_years([(r.get("timestampCreated") or "") for r in rows])
            ),
            "fill_by_month": {
                column: _fill_by_month(rows, column) for column in ("description", "solutions")
            },
        },
        "solutions": solutions.profile([(r.get("solutions") or "") for r in rows]),
        "clusters": cluster_profile,
        "vocabulary": {
            "total_tokens": sum(token_counts.values()),
            "distinct_tokens": len(token_counts),
            "min_frequency_threshold": min_frequency,
            # Filtered, not left for selfcheck to abort on. A frequent dealer or
            # person name in description text clears the frequency floor easily -
            # "Huber" in 200 tickets is unremarkable in this corpus - and selfcheck's
            # response is to refuse the whole artifact. That turns an expected corpus
            # property into a wasted airlock cycle. Dropping the token keeps the
            # invariant (no entity value is emitted) and keeps the run alive; selfcheck
            # remains the backstop for anything this misses.
            "top_tokens": _drop_entities(
                vocab.top_tokens(token_counts, min_frequency),
                "vocabulary.top_tokens",
                build_warnings,
            ),
            # Bigrams are the highest-risk emission: a company name as a bigram is a
            # complete identification, so both halves must clear the entity sweep.
            "top_bigrams": _drop_entities(
                vocab.top_tokens(vocab.bigram_counts(problem_texts), min_frequency, 500),
                "vocabulary.top_bigrams",
                build_warnings,
            ),
            "hunspell_unrecognized_top": _drop_entities(
                hunspell.unrecognized(token_counts, min_frequency, dict_path=hunspell_dict),
                "vocabulary.hunspell_unrecognized_top",
                build_warnings,
            ),
        },
        "multi_fault_estimate": {
            "heuristic": "distinct error_code identifiers per ticket >= 2",
            "rate": (
                sum(
                    1
                    for text in problem_texts
                    if len({i.value for i in identifiers.extract(text) if i.kind == "error_code"})
                    >= 2
                )
                / (len(problem_texts) or 1)
            ),
        },
        "selfcheck": {"passed": False, "checks": [], "warnings": []},
    }

    warnings = build_warnings + selfcheck.assert_safe(profile)
    profile["selfcheck"] = {
        "passed": True,
        "checks": [
            "min_frequency pruning",
            "denylisted-column values",
            "identifier shapes carry no literal digits",
            "dimension-hint ids and token shapes",
            "entity sweep over emitted tokens",
        ],
        "warnings": warnings,
    }
    return profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="profiler")
    ap.add_argument("--csv", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--min-frequency", type=int, default=vocab.DEFAULT_MIN_FREQUENCY)
    ap.add_argument(
        "--hunspell-dict",
        default="de_DE",
        help="hunspell dictionary name for unrecognised-token mining; "
        "pass empty to skip if the binary is unavailable",
    )
    args = ap.parse_args(argv)

    # schema.json requires min_frequency_threshold >= 2, so a lower value would emit a
    # schema-invalid artifact - and in a window the artifact IS the review gate.
    if args.min_frequency < vocab.MIN_FREQUENCY_FLOOR:
        print(
            f"ABORT BAD_ARGUMENT --min-frequency={args.min_frequency} is below the "
            f"schema minimum of {vocab.MIN_FREQUENCY_FLOOR}",
            flush=True,
        )
        return 4

    profile = build_profile(args.csv, args.min_frequency, args.hunspell_dict or None)

    # A zero-row profile is a truncated or mis-transferred export, not a result. Without
    # this it prints `rows=0 selfcheck_passed=True`, which satisfies the runbook's
    # "confirm selfcheck_passed=True" check and looks like success.
    if profile["source"]["row_count"] == 0:
        print(
            "ABORT EMPTY_INPUT the CSV parsed to 0 data rows - check the transfer "
            "and the delimiter before re-running",
            flush=True,
        )
        return 4

    emit.write_profile(profile, args.out)
    emit.write_report(profile, args.out.with_name("profile_report.md"))
    # Paths and counts only - never a field value.
    print(
        f"wrote {args.out} ({args.out.stat().st_size} bytes) "
        f"and {args.out.with_name('profile_report.md')}"
    )
    print(
        f"rows={profile['source']['row_count']} "
        f"columns={len(profile['source']['columns_found'])} "
        f"selfcheck_passed={profile['selfcheck']['passed']} "
        f"warnings={len(profile['selfcheck']['warnings'])}"
    )
    return 0


if __name__ == "__main__":
    # Never let a raw traceback reach stdout: UnicodeDecodeError and csv.Error
    # quote the offending input.
    sys.exit(safety.run_scrubbed(main))
