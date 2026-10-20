"""Insight report, stage 1. Runs inside an airlock window: no network, no model, no GPU.

    python -m insight --csv export --out report.json [--serial-prefixes]

Run by a human with no AI to help, on real data, so every failure is one coded line and never a
value, and a run that does not produce a guarded report leaves NO report behind: a stale file
from an earlier run is removed first, and the report is written under a temporary name and moved
into place, so a half-written file can never look finished. `--out` may never be the input.

Exit codes: 0 ok, 2 the guard refused (profiler.safety), 3 unexpected failure (profiler.safety),
4 the arguments or the input are wrong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

from insight import cube, extract, guard, release, report
from profiler import safety
from profiler.columns import EXPECTED_COLUMNS
from profiler.stats import vocab

# Without these the report would be an all-zero artifact that looks like a result. A count of
# how many are missing is safe to print; their names are not needed and not printed.
REQUIRED_COLUMNS = (
    "title",
    "description",
    "solutions",
    "customData",
    "vehicleSerialNo",
    "vehicleModelId",
    "vehicleYear",
    "timestampCreated",
)


class _BadArguments(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's own text echoes the offending value, which may be a path or a string.
        raise _BadArguments


def _abort(code: str, message: str) -> int:
    print(f"ABORT {code} {message}", flush=True)
    return 4


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    """True if `a` and `b` are the same file under any spelling, symlink or hardlink."""
    if a.resolve() == b.resolve():
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="insight", allow_abbrev=False)
    parser.add_argument("--csv", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--min-frequency", type=int, default=release.K)
    # A floor below the release floor needs saying twice: a typo of 5 for 50 would otherwise
    # run a whole window with a weak floor and nothing but a number in the artifact to show it.
    parser.add_argument("--allow-weak-floor", action="store_true")
    # Off unless asked: vehicleSerialNo is on profiler.selfcheck.DENYLISTED_COLUMNS, and
    # releasing even a prefix is a loosening only the operator may choose.
    parser.add_argument("--serial-prefixes", action="store_true")
    # Seconds the cube's derivability measurement may spend after setup; it never stops the run,
    # and the report says how many cells it settled. 0 skips it; inf lets it run to the end.
    parser.add_argument("--cube-budget", type=float, default=cube.BUDGET)
    parser.add_argument("--code-commit", default="unknown")
    parser.add_argument("--image-digest", default="unknown")
    try:
        args = parser.parse_args(argv)
    except _BadArguments:
        return _abort("BAD_ARGUMENT", "the arguments were not understood; run with --help")
    except SystemExit as exc:  # --help
        return 0 if exc.code in (0, None) else _abort("BAD_ARGUMENT", "see --help")

    # The one irreversible mistake, refused before anything else is touched: the export cannot
    # be fetched again inside the window.
    if _same_file(args.out, args.csv):
        return _abort("BAD_ARGUMENT", "--out is the input file and would overwrite it")
    # A report left by an earlier run must not survive a run that fails: it would still claim
    # selfcheck.passed. Whatever happens next, no output exists until a guarded one is written.
    args.out.unlink(missing_ok=True)

    if not args.cube_budget >= 0:
        return _abort("BAD_ARGUMENT", "--cube-budget must be a number of seconds, 0 or more")
    if args.min_frequency < vocab.MIN_FREQUENCY_FLOOR:
        return _abort(
            "BAD_ARGUMENT",
            f"--min-frequency={args.min_frequency} is below the minimum of "
            f"{vocab.MIN_FREQUENCY_FLOOR}",
        )
    if args.min_frequency < release.K and not args.allow_weak_floor:
        return _abort(
            "BAD_ARGUMENT",
            f"--min-frequency={args.min_frequency} is below the release floor {release.K}; "
            "pass --allow-weak-floor only for a rehearsal",
        )

    # Provenance is checked BEFORE any real data is read: a value the guard would refuse at the
    # end should cost nothing, not a whole airlock window. The value is never echoed.
    for flag, value, pattern, form in (
        ("--code-commit", args.code_commit, guard.COMMIT, "7 to 40 hex characters or 'unknown'"),
        ("--image-digest", args.image_digest, guard.DIGEST, "sha256:<64 hex> or 'unknown'"),
    ):
        if not pattern.fullmatch(value):
            return _abort("BAD_ARGUMENT", f"{flag} must be {form}")

    if not args.csv.is_file():
        return _abort("MISSING_INPUT", "the input file does not exist or is not a file")
    rows = extract.read_rows(args.csv)
    if not rows:
        return _abort(
            "EMPTY_INPUT",
            "the export parsed to 0 data rows - check the transfer and the delimiter "
            "before re-running",
        )
    absent = sum(1 for column in REQUIRED_COLUMNS if column not in rows[0])
    if absent:
        return _abort(
            "WRONG_INPUT",
            f"{absent} of {len(REQUIRED_COLUMNS)} required columns are missing - "
            "wrong file or wrong delimiter",
        )
    missing = len(set(EXPECTED_COLUMNS) - set(rows[0]))

    # The filename reaches the artifact, so an export named after the client would put that
    # name in the one file an AI may read. Withheld rather than left to operator discipline.
    conforming = args.csv.name == "export.csv"
    if not conforming:
        print("NOTE source filename was not 'export.csv' and has been withheld", flush=True)
    source = {
        "filename": args.csv.name if conforming else "<non-conforming>",
        "sha256": _sha256(args.csv),
        "bytes": args.csv.stat().st_size,
        "row_count": len(rows),
    }
    built = report.build(
        rows,
        source=source,
        provenance={"code_commit": args.code_commit, "image_digest": args.image_digest},
        k=args.min_frequency,
        serial_prefixes=args.serial_prefixes,
        cube_budget=args.cube_budget,
    )

    # Written under a temporary name and moved into place, so a kill or a full disk can leave
    # a clearly partial `.tmp` file but never a truncated report that looks finished.
    data = json.dumps(built, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(args.out.name + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, args.out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    # Paths and counts only - never a field value.
    print(f"wrote {args.out} ({len(data)} bytes)")
    print(
        f"rows={source['row_count']} columns_expected_missing={missing} "
        f"selfcheck_passed={built['selfcheck']['passed']} ledger_rows={len(built['suppression'])}"
    )
    measured = built["quality"]["cube"]["measurement"]
    print(
        f"cube_newly_derivable={measured['newly_derivable']} "
        f"cube_checked={measured['checked']}/{measured['withheld_cells']}"
        + (f" cube_stopped={measured['stopped']}" if measured["stopped"] else "")
    )
    return 0


if __name__ == "__main__":
    # Never let a raw traceback reach stdout: a decode or csv error quotes the input.
    sys.exit(safety.run_scrubbed(main))
