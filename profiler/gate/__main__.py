"""The gate CLI. `window.sh`'s Window B command block will invoke this - a later plan.

`--embedder hashing` is the default ON PURPOSE. The real model
(`intfloat/multilingual-e5-large`) needs torch in the sealed image and ~2 GB of weights baked
in for `--network=none` to hold, which is a later plan. Until then the gate must still be
runnable end to end, so a bug is found in CI rather than inside a sealed window - the most
expensive place to find one. `report.embedder_is_a_model` makes the choice visible in the
artifact, so a stub-produced green cannot be mistaken for a real one.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import subprocess
import sys

from profiler.gate import neighbours, report, shingles, sweep
from profiler.gate.embedder import HashingEmbedder

# The free-text columns, joined into one document per row. Identical on both sides: including a
# column on one side only would make every cosine and every shingle in the report
# incomparable, which is the kind of asymmetry that flatters the fixture.
TEXT_COLUMNS = ("title", "description", "solutions")

# Which column check 4 traces against the fictional roster. `ansprechpartner` is the contact
# name; it is the single most important PII constraint M2 inherits.
ROSTER_COLUMN = "ansprechpartner"


def _rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _documents(rows: list[dict[str, str]]) -> list[str]:
    return [" ".join((row.get(column) or "") for column in TEXT_COLUMNS).strip() for row in rows]


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        # No git inside the sealed image. The operator passes --code-commit there, and the
        # manifest says "unknown" rather than silently claiming a commit it cannot see.
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="profiler.gate")
    parser.add_argument("--synthetic", type=pathlib.Path, required=True)
    parser.add_argument("--real", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--embedder", choices=["hashing", "e5"], default="hashing")
    # Overridable so the operator can pin a different revision in the window without a code
    # change. Defaults to the pinned one; a mismatch shows up in the manifest either way.
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--roster", type=pathlib.Path, default=None)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--image-digest", default="unknown")
    args = parser.parse_args(argv)

    synthetic_rows = _rows(args.synthetic)
    real_rows = _rows(args.real)
    synthetic_docs = _documents(synthetic_rows)
    real_docs = _documents(real_rows)

    if args.embedder == "e5":
        from profiler.gate.embedder import E5_REVISION, E5Embedder

        model = E5Embedder(revision=args.model_revision or E5_REVISION)
    else:
        model = HashingEmbedder()
    roster = (
        frozenset(
            line.strip()
            for line in args.roster.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if args.roster
        else frozenset()
    )

    # Pulled out so the report can say how many values the check actually looked at. Finding
    # 13: ROSTER_COLUMN is absent from the 38-column contract, so this is a list of None and
    # the count is 0 - which the report now states rather than hiding behind a green.
    roster_values = [row.get(ROSTER_COLUMN) for row in synthetic_rows]
    roster_values_traced = sum(1 for value in roster_values if (value or "").strip())

    built = report.build(
        shingle_collisions=shingles.collisions(synthetic_docs, real_docs),
        pii_hits=sweep.pii_hits(synthetic_docs),
        # Without a roster there is nothing to trace against, and reporting 0 violations would
        # claim a check that did not run. The operator passes --roster in the window.
        roster_violations=(sweep.roster_violations(roster_values, roster) if roster else 0),
        roster_values_traced=roster_values_traced if roster else 0,
        cross_p99=neighbours.cross_p99(synthetic_docs, real_docs, model),
        baseline_p95=neighbours.self_baseline(synthetic_docs, model),
        embedder=model.identity,
        synthetic_sha256=_sha256(args.synthetic),
        real_sha256=_sha256(args.real),
        synthetic_rows=len(synthetic_rows),
        real_rows=len(real_rows),
        code_commit=args.code_commit or _commit(),
        image_digest=args.image_digest,
    )

    # Written BEFORE the exit code is decided: a refusing gate must leave the evidence behind,
    # because the report is what an investigation reads.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(built, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"gate verdict: {built['verdict']}  (embedder: {built['manifest']['embedder']})")
    for name, check in built["checks"].items():
        print(f"  {name:<11} {'pass' if check['passed'] else 'FAIL'}")
    if not built["embedder_is_a_model"]:
        print("  NOTE: produced with the hashing stand-in, not a model - not a leakage verdict")
    return 0 if built["verdict"] == "green" else 3


if __name__ == "__main__":
    sys.exit(main())
