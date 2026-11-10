# dev3/__main__.py
"""Generate the three-vehicle dev fixture from a released catalog.

    python -m dev3 --catalog local/released/catalog.json --out-dir local/fixtures/dev3 --fake

Drop --fake and pass --base-url to use the model on the H100. It reads only the catalog (which
passed catalog.guard) and writes invented text, so it needs no airlock window.

Exit codes: 0 ok, 2 the catalog was refused, 3 the fixture drifted from its plan.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import sys

from catalog import guard
from dev3 import planner, profiles, rows, verify, writer
from fixtures import llm

MIN_K, MIN_VEHICLES, MIN_DEALERS = 50, 5, 5
OUTPUTS = ("tickets.csv", "labels.jsonl")


def _refusals(catalog: object) -> list[str]:
    if not isinstance(catalog, dict):
        return ["WRONG_TYPE $"]
    floors = {name: catalog.get(name) for name in ("k", "min_vehicles", "min_dealers")}
    if not all(isinstance(v, int) for v in floors.values()):
        return ["WRONG_TYPE $ floors"]
    found = guard.problems(catalog, **floors)
    if floors["k"] < MIN_K or floors["min_vehicles"] < MIN_VEHICLES:
        found.append("FLOOR_TOO_WEAK $.k or $.min_vehicles")
    if floors["min_dealers"] < MIN_DEALERS:
        found.append("FLOOR_TOO_WEAK $.min_dealers")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dev3")
    parser.add_argument("--catalog", type=pathlib.Path, required=True)
    parser.add_argument("--out-dir", type=pathlib.Path, default=pathlib.Path("local/fixtures/dev3"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fake", action="store_true", help="no GPU; deterministic stub")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    args = parser.parse_args(argv)

    for name in OUTPUTS:  # a failed run must not leave an older fixture looking current
        (args.out_dir / name).unlink(missing_ok=True)

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    refused = _refusals(catalog)
    if refused:
        for line in refused:
            print(f"REFUSED {line}")
        return 2
    recipes = catalog["recipes"]
    by_id = {r["recipe_id"]: r for r in recipes}

    inner = writer.EchoClient() if args.fake else llm.VLLM(args.base_url, args.model)
    client = llm.Cached(inner, args.out_dir / "cache", inner.identity)

    rng = random.Random(args.seed)
    out_rows: list[dict[str, str]] = []
    out_labels: list[dict] = []
    for profile in profiles.PROFILES:
        try:
            plan = planner.plan(profile, recipes, args.seed)
        except planner.PlanError as error:
            print(f"REFUSED {error}")
            return 2
        first = len(out_rows) + 1
        id_of_number = {planned.number: first + k for k, planned in enumerate(plan)}
        for planned in plan:
            recipe = by_id[planned.recipe_id]
            text = writer.write(client, recipe, planned)
            index = len(out_rows) + 1
            out_rows.append(rows.row(index, profile, recipe, planned, text, rng))
            out_labels.append(rows.label(index, profile, planned, id_of_number))

    problems = verify.check(out_rows, out_labels, profiles.PROFILES, recipes)
    if problems:
        print("ABORT the fixture drifted from its plan:")
        for line in problems:
            print(f"  - {line}")
        return 3

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "tickets.csv").open(  # guard: ok(synthetic fixture)
        "w", newline="", encoding="utf-8"
    ) as handle:
        table = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        table.writeheader()
        table.writerows(out_rows)
    (args.out_dir / "labels.jsonl").write_text(  # guard: ok(synthetic fixture)
        "".join(json.dumps(label, ensure_ascii=False) + "\n" for label in out_labels),
        encoding="utf-8",
    )
    print(f"wrote {args.out_dir} ({len(out_rows)} rows, {len(profiles.PROFILES)} vehicles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
