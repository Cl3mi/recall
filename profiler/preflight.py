"""Structural preflight for a real export. Reads shape, never content.

Run BEFORE opening an airlock window. A mismatched export - renamed columns, wrong
delimiter, latin-1 encoding, truncated rows - is the likeliest way to waste a full
cycle, and every one of those is detectable without looking at a single field value.

The safe-output discipline is the same as `profiler/safety.py`: the only strings this
can print are (a) column names that appear in the published 38-column contract, (b)
fixed literals, (c) character-class shapes. Everything else is a number. A field value
has no path to stdout.

One case needs care: if the file has no header, line 1 *is* a data row, so echoing it
would leak. When the first line does not recognisably match the contract, this prints
shapes only and says so loudly.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import pathlib
import sys

from profiler.columns import EXPECTED_COLUMNS

CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
# Below this share of expected columns, we do not trust line 1 to be a header and refuse
# to echo any of its fields - they might be data.
HEADER_TRUST_RATIO = 0.5


def shape_of(value: str, limit: int = 24) -> str:
    """Character classes only: A=upper, a=lower, D=digit, _=space, .=other."""
    out = []
    for ch in value[:limit]:
        if ch.isdigit():
            out.append("D")
        elif ch.isupper():
            out.append("A")
        elif ch.islower():
            out.append("a")
        elif ch.isspace():
            out.append("_")
        else:
            out.append(".")
    return "".join(out) + ("…" if len(value) > limit else "")


def sniff_delimiter(header_bytes: bytes) -> str:
    text = header_bytes.decode("utf-8", errors="replace")
    return max(CANDIDATE_DELIMITERS, key=text.count)


def scan(path: pathlib.Path) -> dict:
    """Single pass. Retains no field value - only counts and the header row."""
    size = path.stat().st_size

    with path.open("rb") as fh:
        first_line = fh.readline()
    delimiter = sniff_delimiter(first_line)

    undecodable = 0
    rows = 0
    short_rows = 0
    long_rows = 0
    header: list[str] = []

    with path.open("rb") as fh:
        raw_header = fh.readline()
        try:
            raw_header.decode("utf-8")
        except UnicodeDecodeError:
            undecodable += 1
        header = next(
            csv.reader([raw_header.decode("utf-8", errors="replace")], delimiter=delimiter),
            [],
        )
        header = [h.strip().lstrip("﻿") for h in header]

        # Count structure only. The reader's rows are never stored or returned.
        text_stream = (line.decode("utf-8", errors="replace") for line in fh)
        for record in csv.reader(text_stream, delimiter=delimiter):
            if not record:
                continue
            rows += 1
            if len(record) < len(header):
                short_rows += 1
            elif len(record) > len(header):
                long_rows += 1

    # An INCREMENTAL decoder, because a multi-byte character can straddle a chunk
    # boundary: decoding fixed-size chunks independently reports a perfectly valid
    # UTF-8 file as broken as soon as an umlaut lands on a 1 MiB edge.
    decoder = codecs.getincrementaldecoder("utf-8")()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            try:
                decoder.decode(chunk)
            except UnicodeDecodeError:
                undecodable += 1
                decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        undecodable += 1

    expected = set(EXPECTED_COLUMNS)
    matched = [c for c in header if c in expected]
    ratio = len(matched) / len(EXPECTED_COLUMNS) if EXPECTED_COLUMNS else 0.0

    return {
        "bytes": size,
        "delimiter": delimiter,
        "undecodable_chunks": undecodable,
        "rows": rows,
        "short_rows": short_rows,
        "long_rows": long_rows,
        "header_len": len(header),
        "header_trusted": ratio >= HEADER_TRUST_RATIO,
        "matched": matched,
        "missing": [c for c in EXPECTED_COLUMNS if c not in header],
        "unexpected": [c for c in header if c not in expected],
    }


def report(result: dict) -> int:
    d = {",": "','", ";": "';'", "\t": "'\\t'", "|": "'|'"}.get(result["delimiter"], "?")
    print("recall export preflight - structural only; no field value is read or printed")
    print()
    print(f"  bytes:      {result['bytes']:,}")
    print(f"  rows:       {result['rows']:,}  (data rows, excluding the header)")
    print(f"  delimiter:  {d}")
    print(
        f"  encoding:   {'utf-8 clean' if not result['undecodable_chunks'] else 'NOT valid utf-8'}"
    )
    print(f"  columns:    {result['header_len']} in the header")
    print()

    if not result["header_trusted"]:
        print("  ⚠ line 1 does not match the published column contract.")
        print("    It may not be a header at all, so its fields are NOT echoed here.")
        print("    Shapes only:")
        for s in result["unexpected"][:10]:
            print(f"      {shape_of(s)}")
        print()
        print("  VERDICT: FAIL - resolve the header before opening a window")
        return 1

    print("  column contract (PROJECT_BRIEF.md §4):")
    print(f"    matched:              {len(result['matched'])} / {len(EXPECTED_COLUMNS)}")
    print(f"    expected but MISSING: {', '.join(result['missing']) or 'none'}")
    print(f"    unexpected extras:    {', '.join(result['unexpected']) or 'none'}")
    print()
    print("  row integrity:")
    print(f"    rows with fewer fields than the header: {result['short_rows']:,}")
    print(f"    rows with more fields than the header:  {result['long_rows']:,}")
    print()

    problems = []
    if result["missing"]:
        problems.append(f"{len(result['missing'])} expected column(s) missing")
    if result["undecodable_chunks"]:
        problems.append("file is not valid utf-8")
    if result["rows"] == 0:
        problems.append("no data rows")
    if result["short_rows"] or result["long_rows"]:
        problems.append(
            f"{result['short_rows'] + result['long_rows']:,} row(s) with a field count "
            "that differs from the header"
        )

    if problems:
        print("  VERDICT: PROBLEMS FOUND")
        for p in problems:
            print(f"    - {p}")
        print()
        print("  Unexpected extras alone are tolerable - the profiler reports them.")
        print("  Missing columns, bad encoding or ragged rows should be resolved first.")
        return 1

    print("  VERDICT: matches the 38-column contract - Window A can proceed")
    print()
    print("  Reminder: rename the file to export.csv before it reaches the box.")
    print("  source.filename is emitted verbatim into profile.json, so a name that")
    print("  identifies the client would end up in the artifact an AI later reads.")
    return 0


def syntax_probe(
    path: pathlib.Path,
    column: str,
    min_frequency: int = 50,
    prefix: int = 40,
    punctuation: int = 24,
) -> int:
    """What syntax does a free-form column use? Shapes only, floored.

    An earlier round found customData present and parsed none of it: it was
    neither JSON nor key=value. We could not see why, because shape discovery matches
    [A-Za-z0-9._/:-] and so cannot represent '=', ';', '{', '<' or whitespace - the
    characters that identify a format. This looks at exactly those.

    Two views, both content-free:

    - the punctuation skeleton, every letter and digit removed. '{":,}' is JSON, '=;' is
      key=value, '<>/' is XML. It cannot carry content because it retains no character
      that could be content.
    - the prefix shape over the closed alphabet, longer than SHAPE_MAX because a format
      declares itself in the first few dozen characters.

    A longer shape would fingerprint a single value, so nothing is printed unless
    min_frequency values share it - the same frequency floor used everywhere else. On a
    16k-row corpus the surviving shapes describe the format, not any ticket.
    """
    from collections import Counter

    # This module's own shape_of, not the profiler's: preflight runs on the workstation
    # and must not depend on the package being importable. Its alphabet is closed too.
    with path.open("rb") as fh:
        delimiter = sniff_delimiter(fh.readline())

    shapes: Counter[str] = Counter()
    skeletons: Counter[str] = Counter()
    present = 0

    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if column not in (reader.fieldnames or []):
            print(f"  column {column!r} is not in this export")
            return 2
        for row in reader:
            value = (row.get(column) or "").strip()
            if not value:
                continue
            present += 1
            shapes[shape_of(value[:prefix], limit=prefix)] += 1
            skeleton = "".join(c for c in value if not c.isalnum() and not c.isspace())
            skeletons[skeleton[:punctuation]] += 1

    print(f"\n  syntax probe: {column}  ({present:,} non-empty values)")
    for title, counter, width in (
        ("punctuation skeleton (letters and digits removed)", skeletons, punctuation),
        (f"prefix shape, first {prefix} characters", shapes, prefix),
    ):
        kept = [(v, n) for v, n in counter.most_common() if n >= min_frequency]
        print(f"\n  {title}")
        print(f"    {len(counter):,} distinct, {len(kept)} at or above {min_frequency}")
        for value, n in kept[:20]:
            print(f"    {n:7,}  {value[:width]!r}")
        if not kept:
            print(f"    (none reached the floor - no shape is shared by {min_frequency} values)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="preflight",
        description="Structural check of a real export. Reads shape, never content.",
    )
    ap.add_argument("csv", type=pathlib.Path)
    ap.add_argument(
        "--syntax",
        metavar="COLUMN",
        help="probe a free-form column's syntax (shapes only, frequency-floored)",
    )
    ap.add_argument("--min-frequency", type=int, default=50)
    args = ap.parse_args(argv)
    if not args.csv.is_file():
        print(f"not a file: {args.csv}")
        return 2
    if args.syntax:
        return syntax_probe(args.csv, args.syntax, args.min_frequency)
    return report(scan(args.csv))


if __name__ == "__main__":
    sys.exit(main())
