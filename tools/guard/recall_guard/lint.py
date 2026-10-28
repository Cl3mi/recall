"""Write-side lint: new code must send outputs and logs through recall.sealed."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .names import data_suffix

SCOPE_PREFIXES = ("src/", "profiler/", "insight/", "fixtures/", "catalog/")
EXEMPT = ("src/recall/sealed.py",)
PRAGMA = "# guard: ok"
HINT = (
    "Route outputs and logs through recall.sealed (sealed_path / sealed_logger) and release "
    "aggregates with tools/guard/export_aggregate.py. Add '# guard: ok(<reason>)' only for "
    "synthetic or non-client data."
)

_RULES = (
    ("open-write", re.compile(r"""\bopen\(.*,\s*['"][wax][bt+]*['"]""")),
    ("open-write", re.compile(r"""\.open\(\s*['"][wax][bt+]*['"]""")),
    ("open-write", re.compile(r"""\bopen\(.*\bmode\s*=\s*['"][wax]""")),
    ("file-handler", re.compile(r"\w*FileHandler\(")),
    ("file-handler", re.compile(r"basicConfig\([^)]*filename")),
    ("path-write", re.compile(r"\.(write_text|write_bytes)\(")),
    ("table-dump", re.compile(r"\.(to_csv|to_parquet|to_json|to_pickle)\(")),
    ("table-dump", re.compile(r"\.to_(excel|feather|sql|hdf|stata|orc)\(")),
    ("array-dump", re.compile(r"\b(np|numpy)\.(save|savez|savez_compressed|savetxt)\(")),
    ("array-dump", re.compile(r"\btofile\(")),
    ("copy-out", re.compile(r"\bshutil\.(copy|copy2|copyfile|move)\(")),
    ("serialise-dump", re.compile(r"\b(json|pickle)\.dump\(")),
    ("print-rows", re.compile(r"\bprint\(\s*(row|rows|record|records|df|ticket|tickets)\b")),
    ("print-rows", re.compile(r"\bprint\(.*\bfile\s*=")),
)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str


def in_scope(rel: str) -> bool:
    return rel.endswith(".py") and rel.startswith(SCOPE_PREFIXES) and rel not in EXEMPT


def added_lines(old: str, new: str) -> list:
    """(line number, text) of non-blank lines in new that do not appear in old."""
    seen = {line.strip() for line in old.splitlines()}
    return [
        (n, line)
        for n, line in enumerate(new.splitlines(), 1)
        if line.strip() and line.strip() not in seen
    ]


def _scan(rel: str, lines: list) -> list:
    findings = []
    for number, line in lines:
        if PRAGMA in line:
            continue
        for rule, pattern in _RULES:
            if pattern.search(line):
                findings.append(Finding(rel, number, rule, line.strip()))
                break
    return findings


def check_text(rel: str, old: str, new: str) -> list:
    if not in_scope(rel):
        return []
    return _scan(rel, added_lines(old, new))


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout
    return out.decode("utf-8", "surrogateescape")


def _added_in_diff(diff: str) -> list:
    """(line number, text) of the '+' lines of one file's zero-context diff (hunks only)."""
    lines = []
    number = 0
    in_hunk = False
    for raw in diff.split("\n"):
        match = _HUNK.match(raw)
        if match:
            number = int(match.group(1))
            in_hunk = True
        elif in_hunk and raw.startswith("+"):
            lines.append((number, raw[1:]))
            number += 1
    return lines


def check_staged(root: Path) -> list:
    """Lint the added lines of staged Python files and reject staged data files."""
    findings = []
    names = _git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").split("\0")
    for name in names:
        if not name:
            continue
        if data_suffix(name):
            findings.append(Finding(name, 0, "data-file", "data file staged for commit"))
        if in_scope(name):
            diff = _git(root, "diff", "--cached", "-U0", "--no-color", "--no-renames", "--", name)
            findings.extend(_scan(name, _added_in_diff(diff)))
    return findings
