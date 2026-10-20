"""Release gate: the only way information leaves the sealed root.

Accepts a JSON document of numbers, booleans, nulls and lists/objects of them. Free-text
strings are refused, and object keys must be snake_case identifiers (a key can carry a value).
Errors name a JSON path and a code, never a value.
"""

from __future__ import annotations

import json
import math
import re
import sys

from .config import load_config

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_DEPTH = 8
MAX_LIST = 10_000
MAX_INT = 2**53  # integers this large carry more than a measurement: a way to smuggle text


def validate(obj, path: str = "$", depth: int = 0) -> list:
    if depth > MAX_DEPTH:
        return [f"E_DEPTH at {path}"]
    if obj is None or isinstance(obj, bool):
        return []
    if isinstance(obj, int):
        return [] if abs(obj) < MAX_INT else [f"E_INT_RANGE at {path}"]
    if isinstance(obj, float):
        return [] if math.isfinite(obj) else [f"E_NONFINITE at {path}"]
    if isinstance(obj, str):
        return [f"E_STRING at {path}"]
    errors: list = []
    if isinstance(obj, list):
        if len(obj) > MAX_LIST:
            return [f"E_LIST_LENGTH at {path}"]
        for index, item in enumerate(obj):
            errors += validate(item, f"{path}[{index}]", depth + 1)
        return errors
    if isinstance(obj, dict):
        for index, (key, value) in enumerate(obj.items()):
            if not isinstance(key, str) or not KEY_RE.match(key):
                errors.append(f"E_KEY at {path}.<key#{index}>")
                continue
            errors += validate(value, f"{path}.{key}", depth + 1)
        return errors
    return [f"E_TYPE at {path}"]


def export(cfg, name: str) -> list:
    """Validate <sealed root>/<name>.json and write it to the released dir. Returns errors."""
    if not NAME_RE.match(name):
        return ["E_NAME"]
    source = cfg.sealed_root / f"{name}.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError:
        return ["E_MISSING"]
    except (ValueError, RecursionError):
        return ["E_JSON"]
    errors = validate(data)
    if errors:
        return errors
    out_dir = cfg.released_dirs[0]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return []


def main(argv: list) -> int:
    if len(argv) != 1:
        print(
            "usage: export_aggregate.py <name>   (reads <sealed root>/<name>.json)", file=sys.stderr
        )
        return 4
    cfg = load_config(lenient=True)
    errors = export(cfg, argv[0])
    if errors:
        for error in errors:
            print(error)
        return 4
    print(f"OK released {argv[0]}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
