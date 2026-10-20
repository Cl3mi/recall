"""Name-based rules: data suffixes and protected locations, matched on raw text."""

from __future__ import annotations

import contextlib
import os
import re

DATA_SUFFIX_RE = re.compile(
    r"\.(csv|tsv|parquet|jsonl|xlsx|xls|xlsm|xlsb|ods|pkl|npy|npz|syn)"
    r"(\.(gz|zip|bz2|xz))?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


# ripgrep --type names that select data files; kept beside the suffix regex they mirror
RG_DATA_TYPES = frozenset({"csv", "tsv", "parquet", "jsonl"})


def data_suffix(text: str) -> str | None:
    """First data suffix found anywhere in text (a name, a path or a whole command)."""
    match = DATA_SUFFIX_RE.search(text)
    return match.group(0).lower() if match else None


def protected_variants(cfg) -> list:
    """Every spelling of a protected directory that could appear in command text."""
    home = os.path.expanduser("~")
    out = []
    for directory in cfg.protected_dirs:
        text = str(directory)
        out.append(text)
        if text.startswith(home):
            out.append("~" + text[len(home) :])
            out.append("$HOME" + text[len(home) :])
        with contextlib.suppress(ValueError):
            out.append(directory.relative_to(cfg.root).as_posix())
    return out


def protected_string(text: str, cfg) -> str | None:
    for variant in protected_variants(cfg):
        if variant and variant in text:
            return variant
    return None
