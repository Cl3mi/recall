from __future__ import annotations

import json
import pathlib

SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.json"

# The report is read on-screen inside the window; the full list is in profile.json.
REPORT_SHAPE_ROWS = 25

# How near-duplicate groups are banded in the report. The product requirement is a
# comprehensive answer listing every variant approach, so the question the reviewer needs
# answered is "how much of the corpus sits in groups at all", not "what is the biggest
# group". Only clusters at or above min_frequency are characterised by name, so these
# bands are the only view of the small groups - and the small groups are the variants.
CLUSTER_BANDS = [(1, 1, "1 (singleton)"), (2, 4, "2-4"), (5, 9, "5-9"), (10, 49, "10-49")]


def _cluster_band_rows(profile: dict) -> list[str]:
    """Counts only - no cluster is named here, so no floor is needed."""
    dist = {int(k): v for k, v in profile.get("clusters", {}).get("size_distribution", {}).items()}
    total = profile.get("source", {}).get("row_count") or 1
    rows = []
    for low, high, label in CLUSTER_BANDS:
        clusters = sum(n for size, n in dist.items() if low <= size <= high)
        tickets = sum(size * n for size, n in dist.items() if low <= size <= high)
        rows.append(f"| {label} | {clusters:,} | {tickets:,} | {tickets / total:.1%} |")
    clusters = sum(n for size, n in dist.items() if size >= 50)
    tickets = sum(size * n for size, n in dist.items() if size >= 50)
    rows.append(
        f"| 50+ (characterised below) | {clusters:,} | {tickets:,} | {tickets / total:.1%} |"
    )
    return rows


def _envelope_lines(profile: dict) -> list[str]:
    """The client's real field inventory, when customData is an EAV envelope.

    Without this the report shows the envelope's own six attribute names - group, key,
    label, value, text, type - and reads as though the corpus has six fields. The
    question this whole window exists to answer is which fields the client actually
    configured, and those are the values of the naming attribute.
    """
    env = profile.get("custom_data", {}).get("envelope", {})
    if not env.get("detected"):
        return []
    q = env.get("records_per_row_quantiles", {})
    return [
        "## customData field inventory — what the client actually records",
        "",
        f"- customData is a list of field descriptors keyed by `{env['name_attribute']}`, "
        "so the table above shows the envelope's attributes, not the schema",
        f"- {env['distinct_field_count']:,} distinct fields, "
        f"{env['fields_suppressed']:,} suppressed, "
        f"{env['fields_omitted_over_cap']:,} omitted over the cap",
        f"- descriptors per ticket: p50 {q.get('p50')}, p95 {q.get('p95')}, max {q.get('max')}",
        "",
        "| field | kind | fill | dominant value shape |",
        "|---|---|---:|---|",
        *[
            f"| `{f['name']}` | {f['kind']} | {f['fill_rate']:.0%} | "
            f"`{f['value_shapes'][0]['shape'] if f['value_shapes'] else '—'}` |"
            for f in env["fields"]
        ],
        "",
    ]


def _fill_by_year_rows(profile: dict) -> list[str]:
    """Collapse fill_by_month to a year per row, so the step is visible on one screen."""
    by_month = profile.get("temporal", {}).get("fill_by_month", {})
    years: dict[str, dict[str, list[float]]] = {}
    for column in ("description", "solutions"):
        for month, rate in by_month.get(column, {}).items():
            years.setdefault(month[:4], {}).setdefault(column, []).append(rate)
    rows = []
    for year in sorted(years):
        cols = years[year]
        desc = cols.get("description", [])
        sols = cols.get("solutions", [])
        mean = lambda v: f"{sum(v) / len(v):.0%}" if v else "—"  # noqa: E731
        rows.append(f"| {year} | {len(desc)} | {mean(desc)} | {mean(sols)} |")
    return rows or ["| — | 0 | — | — |"]


def validate(profile: dict) -> None:
    """Check the profile against schema.json before it is written.

    The artifact is the review gate for a sealed window, so shipping one that does not
    match its own schema would be discovered only when someone tried to read it - a
    whole cycle later. jsonschema's message names the offending schema path and can
    quote an offending *value*, so it is routed through the detail sink rather than
    printed: the raise carries the schema location only.
    """
    import jsonschema

    from profiler import safety

    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(profile, schema)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(p) for p in exc.absolute_path) or "profile"
        safety.detail("UNEXPECTED_FAILURE", "profiler", f"schema validation at {location}: {exc}")
        raise safety.SafetyViolation(
            "UNEXPECTED_FAILURE", "profiler", path_depth=len(exc.absolute_path)
        ) from None


def write_profile(profile: dict, out_path: pathlib.Path) -> None:
    validate(profile)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False, sort_keys=True))


def write_report(profile: dict, out_path: pathlib.Path) -> None:
    """Human-readable companion. This is what gets reviewed line by line before
    anything derived from it leaves the box."""
    src = profile["source"]
    sol = profile["solutions"]
    structure = (
        "single free-text field"
        if sol["cardinality"]["single_field"]
        else "MULTI-ENTRY, separator " + repr(sol["cardinality"]["detected_separator"])
    )
    lines = [
        "# Corpus profile report",
        "",
        f"- source: `{src['filename']}` ({src['bytes']:,} bytes, sha256 `{src['sha256'][:16]}…`)",
        f"- rows: {src['row_count']:,}",
        f"- columns found: {len(src['columns_found'])}",
        f"- expected but missing: {src['columns_expected_missing'] or 'none'}",
        f"- unexpected extras: {src['columns_unexpected'] or 'none'}",
        "",
        "## solutions — the load-bearing field (§12.1, §12.2)",
        "",
        f"- fill rate: **{sol['fill_rate']:.1%}**",
        f"- non-empty after cleaning: **{sol['nonempty_after_clean_rate']:.1%}**",
        f"- usable (non-junk) estimate: **{sol['usable_rate_estimate']:.1%}**",
        f"- structure: {structure}",
        "",
        "### junk taxonomy",
        "",
        "| pattern | count | share |",
        "|---|---:|---:|",
        *[
            f"| `{t['pattern']}` | {t['count']:,} | {t['share']:.1%} |"
            for t in sol["junk_taxonomy"]
        ],
        "",
        "## near-duplicate clusters",
        "",
        f"- clusters: {profile['clusters']['cluster_count']:,}",
        f"- singletons: {profile['clusters']['singleton_count']:,}",
        f"- Zipf α estimate: {profile['clusters'].get('zipf_alpha_estimate')}",
        "",
        "## customData — structure of the least understood field",
        "",
        f"- format: **{profile['custom_data']['format']}** "
        f"(parsed {profile['custom_data']['parse_success_rate']:.1%} of non-empty rows)",
        f"- distinct keys: {profile['custom_data']['distinct_key_count']:,}, "
        f"suppressed: {profile['custom_data']['keys_suppressed']:,}, "
        f"omitted over the cap: {profile['custom_data']['keys_omitted_over_cap']:,}",
        "",
        "| key | kind | fill | dominant value shape |",
        "|---|---|---:|---|",
        *[
            f"| `{k['key']}` | {k['kind']} | {k['fill_rate']:.0%} | "
            f"`{k['value_shapes'][0]['shape'] if k['value_shapes'] else '—'}` |"
            for k in profile["custom_data"]["keys"]
        ],
        "",
        *_envelope_lines(profile),
        "## discovered identifier shapes",
        "",
        f"- {len(profile['discovered_identifier_shapes']):,} shapes cleared the frequency "
        f"floor; {profile['discovered_identifier_shapes_omitted']:,} further shapes cleared "
        "it but were dropped by the cap",
        "",
        "| shape | count | share | fields |",
        "|---|---:|---:|---|",
        *[
            f"| `{s['shape']}` | {s['count']:,} | {s['share']:.1%} | "
            f"{', '.join(s.get('fields', []))} |"
            for s in profile["discovered_identifier_shapes"][:REPORT_SHAPE_ROWS]
        ],
        # The operator reads this report to decide whether the identifier arm is worth
        # building. A table silently showing 15 of 50 reads as "these are the formats",
        # so say what is not on screen.
        *(
            [
                "",
                f"_Showing the {REPORT_SHAPE_ROWS} most frequent of "
                f"{len(profile['discovered_identifier_shapes']):,} in profile.json._",
            ]
            if len(profile["discovered_identifier_shapes"]) > REPORT_SHAPE_ROWS
            else []
        ),
        "",
        "## near-duplicate groups — how much of the corpus has variants",
        "",
        "| group size | groups | tickets | share |",
        "|---|---:|---:|---:|",
        *_cluster_band_rows(profile),
        "",
        "A ticket in a group of 2-49 has near-identical siblings that are not summarised "
        "anywhere else in this report. Those siblings are variant approaches to the same "
        "fault, so they are the answer, not redundancy to collapse.",
        "",
        "## largest clusters",
        "",
        *[
            f"- {c['size']:,} members ({c['share']:.1%}): {', '.join(c['top_tokens'][:8])}"
            for c in profile["clusters"].get("largest", [])
        ],
        "",
        "## fill by year — is the corpus uniform, or did the workflow change?",
        "",
        # Per year, not per month: 65 month rows is a wall nobody reads, and the thing
        # worth seeing is the step. A flat column means a workflow reality that will not
        # improve; a step at a date means recent data is better than the corpus average
        # and corpus selection is a real lever.
        "| year | months | description | solutions |",
        "|---|---:|---:|---:|",
        *_fill_by_year_rows(profile),
        "",
        "## selfcheck",
        "",
        f"- passed: **{profile['selfcheck']['passed']}**",
        *[f"- warning: {w}" for w in profile["selfcheck"].get("warnings", [])],
    ]
    out_path.write_text("\n".join(lines) + "\n")
