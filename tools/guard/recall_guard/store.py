"""Guard state kept inside the sealed root: session ledger and audit log."""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import SEALED_MARKER

_MARKER_TEXT = "sealed: never read from an AI session\n"


def ensure_sealed(directory: Path, cfg) -> None:
    """Create directory (mode 700) and make sure it and the sealed root carry the marker."""
    for target in (cfg.sealed_root, directory):
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target == cfg.sealed_root:
            with contextlib.suppress(OSError):
                os.chmod(target, 0o700)  # mkdir's mode is masked by umask and skips parents
        marker = target / SEALED_MARKER
        if not marker.exists():
            marker.write_text(_MARKER_TEXT, encoding="utf-8")


class Ledger:
    """Files and directories an agent created this session; those stay readable."""

    def __init__(self, cfg, session_id: str):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")[:64]
        self._cfg = cfg
        self.path = cfg.sealed_root / "ledger" / f"{safe}.json"
        self._entries = None  # loaded once: the hook is one process per call

    def _load(self) -> list:
        if self._entries is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError):
                data = []
            self._entries = [str(item) for item in data] if isinstance(data, list) else []
        return self._entries

    def contains(self, path: Path) -> bool:
        return str(path) in self._load()  # exact entries only: no inheritance into directories

    def add(self, *paths: Path) -> None:
        entries = list(self._load())
        changed = False
        for path in paths:
            if str(path) not in entries:
                entries.append(str(path))
                changed = True
        if not changed:
            return
        ensure_sealed(self.path.parent, self._cfg)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(entries))
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        self._entries = entries

    def record_new_file(self, path: Path) -> None:
        """Record path and every missing parent directory. No-op if path already exists."""
        missing = []
        current = path
        while not current.exists() and current != current.parent:
            missing.append(current)
            current = current.parent
        if missing:
            self.add(*missing)

    @staticmethod
    def cleanup(cfg, max_age_s: int = 86400) -> None:
        directory = cfg.sealed_root / "ledger"
        try:
            for entry in directory.glob("*.json"):
                if time.time() - entry.stat().st_mtime > max_age_s:
                    entry.unlink()
        except OSError:
            pass


_MAX_LOG_PATH = 200


def _clean(text) -> str:
    """Cap length and replace newlines/control characters so a path cannot carry a payload."""
    text = str(text)[:_MAX_LOG_PATH]
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def log_denial(cfg, tool: str, rule: str, path: str) -> None:
    """Append one JSON line: timestamp, tool, rule id, normalised path. Never payload content."""
    try:
        ensure_sealed(cfg.sealed_root, cfg)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (py3.8)
            "tool": tool,
            "rule": rule,
            "path": _clean(path),
        }
        with open(cfg.sealed_root / "guard.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
