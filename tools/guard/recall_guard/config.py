"""Locations, zones and per-person overrides for the recall guard."""

from __future__ import annotations

import functools
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

SEALED_MARKER = ".sealed"
LOCAL_CONFIG_REL = ".claude/guard.local.json"
AIRLOCK_MARKER_REL = "local/airlock.open"
HEADER_REL = "docs/export.header.txt"
DEV_ENV = "RECALL_GUARD_DEV"
SEALED_ENV = "RECALL_SEALED_ROOT"

# Directory names that are tooling, never client data.
TOOLING_NAMES = frozenset(
    {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}
)

# Repo-relative paths an agent may not modify: the guard and its registration.
SELF_PROTECTED_RELS = (
    "tools/guard",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/guard.local.json",
    ".githooks",
    "src/recall/sealed.py",
    AIRLOCK_MARKER_REL,
    ".git/config",  # core.hooksPath / fsmonitor / aliases run code outside any tool call
    ".git/hooks",
)
# Home-relative paths an agent may not write: the harness settings and hooks, and the user-level
# python/bin locations that would let a planted file replace the interpreter the hook runs on.
SELF_PROTECTED_HOME_RELS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/hooks",
    ".local/bin",
    ".local/lib",
)


def _abs(value: str, root: Path) -> Path:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(path))


@functools.lru_cache(maxsize=32)  # not functools.cache: that needs Python 3.9
def _header_line(path: str) -> str | None:
    """First line of the export header file. Cached: the hook is one process per call."""
    try:
        with open(path, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except (OSError, ValueError):
        return None
    return line or None


@dataclass(frozen=True)
class Config:
    root: Path
    sealed_root: Path
    released_dirs: tuple
    fixtures_dir: Path
    header_file: Path
    airlock_marker: Path
    scratch_dirs: tuple
    protected_dirs: tuple
    extra_allowed: tuple
    dev_mode: bool

    def header_line(self) -> str | None:
        return _header_line(str(self.header_file))

    def closed_zones(self) -> tuple:
        """Directories no recursive walk may enter: the sealed root and protected dirs."""
        return tuple(dict.fromkeys((self.sealed_root, *self.protected_dirs)))

    def self_protected(self) -> tuple:
        """Paths agents may read but never write (absolute; HOME is read at call time)."""
        out = [self.root / rel for rel in SELF_PROTECTED_RELS]
        home = Path(os.path.expanduser("~"))
        if home.is_absolute():
            out.extend(Path(os.path.normpath(home / rel)) for rel in SELF_PROTECTED_HOME_RELS)
        return tuple(out)


class ConfigError(Exception):
    """The per-person override file exists but is unusable. Never carries file content."""


def _read_local(root: Path) -> tuple:
    """(extra_allowed, extra_protected). A missing file is fine; an invalid one is an error."""
    path = root / LOCAL_CONFIG_REL
    if not os.path.lexists(path):
        return (), ()
    bad = f"{LOCAL_CONFIG_REL} is present but invalid"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        raise ConfigError(bad) from None
    if not isinstance(data, dict):
        raise ConfigError(bad)

    def paths(key: str) -> tuple:
        values = data.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise ConfigError(f"{LOCAL_CONFIG_REL}: '{key}' must be a list of non-empty strings")
        return tuple(_abs(v, root) for v in values)

    return paths("extra_allowed"), paths("extra_protected")


def resolve_root(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if root is None:
        root = Path(env.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return Path(os.path.realpath(root))


def load_config(root: Path | None = None, env: dict | None = None, lenient: bool = False) -> Config:
    env = os.environ if env is None else env
    root = resolve_root(root, env)
    local = root / "local"
    try:
        extra_allowed, extra_protected = _read_local(root)
    except ConfigError:
        if not lenient:
            raise
        extra_allowed, extra_protected = (), ()  # human tools (airlock, release) must still run
    sealed = _abs(env[SEALED_ENV], root) if env.get(SEALED_ENV) else local / "sealed"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    scratch: list = []
    for base in (Path("/tmp"), Path(tempfile.gettempdir())):
        candidate = base / f"claude-{uid}"
        if candidate not in scratch:
            scratch.append(candidate)
    return Config(
        root=root,
        sealed_root=sealed,
        released_dirs=(local / "released", local / "artifacts"),
        fixtures_dir=local / "fixtures",
        header_file=root / HEADER_REL,
        airlock_marker=root / AIRLOCK_MARKER_REL,
        scratch_dirs=tuple(scratch),
        protected_dirs=(
            sealed,
            local / "quarantine",
            Path("/data/recall-quarantine"),
            *extra_protected,
        ),
        extra_allowed=extra_allowed,
        dev_mode=env.get(DEV_ENV) == "1",
    )
