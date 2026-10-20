"""The one sanctioned place for outputs that may hold real-data derivatives.

Anything written here lands under a sealed root that carries a marker file; the client-data
guard denies agents every path under (or next to) a marker. Code that can see real rows must
create its logs and outputs through this module, never ad hoc. Release aggregates with
tools/guard/export_aggregate.py.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Mirrored by tools/guard/recall_guard/config.py; a test keeps the two equal.
SEALED_MARKER = ".sealed"
MARKER_TEXT = "sealed: never read from an AI session\n"


def sealed_root() -> Path:
    """RECALL_SEALED_ROOT, or <repo>/local/sealed. Same resolution as the guard's config:
    ~ is expanded, a relative value is taken against the repo root, the result is normalised.
    Absolute values (the sealed image sets one; there is no repo there) are left as they are."""
    repo_root = Path(__file__).resolve().parents[2]
    override = os.environ.get("RECALL_SEALED_ROOT")
    if not override:
        return repo_root / "local" / "sealed"
    path = Path(os.path.expanduser(override))
    if not path.is_absolute():
        path = repo_root / path
    return Path(os.path.normpath(path))


def _mark(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / SEALED_MARKER
    if not marker.exists():
        marker.write_text(MARKER_TEXT, encoding="utf-8")


def sealed_path(name: str) -> Path:
    """Path for a new sealed output, creating (and marking) its directories."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("sealed names must be relative and stay inside the sealed root")
    root = sealed_root()
    _mark(root)
    target = root / relative
    _mark(target.parent)
    return target


def sealed_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """A logger that writes only to <sealed root>/<name>.log. Log codes and paths, never values."""
    logger = logging.getLogger(f"recall.sealed.{name}")
    if not any(getattr(h, "_recall_sealed", False) for h in logger.handlers):
        handler = logging.FileHandler(  # guard: ok(the sealed helper itself)
            sealed_path(f"{name}.log"), encoding="utf-8"
        )
        handler._recall_sealed = True
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
