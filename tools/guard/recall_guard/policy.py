"""The read policy: allowlist by default, sealed and data-file rules on top."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import SEALED_MARKER, TOOLING_NAMES, Config
from .names import data_suffix
from .sniff import sniff
from .store import Ledger


@dataclass(frozen=True)
class Denial:
    rule: str
    reason: str
    path: str = ""


def under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def has_sealed_marker(path: Path) -> bool:
    """True if path, or any ancestor directory, carries the sealed marker."""
    current = path if path.is_dir() else path.parent
    while True:
        if (current / SEALED_MARKER).exists():
            return True
        if current == current.parent:
            return False
        current = current.parent


def header_hint(cfg: Config) -> str:
    if cfg.header_line() is None:
        return ""
    rel = cfg.header_file.relative_to(cfg.root).as_posix()
    return f" The export structure is in {rel} (one line, columns only)."


SEALED_MSG = (
    "Sealed output: files here may hold real-data derivatives and are never readable by "
    "agents. Only aggregates released with `python3 tools/guard/export_aggregate.py <name>` "
    "(written to local/released/) can be read."
)
PROTECTED_MSG = (
    "Protected client-data location. Never read, list or reference it from an AI session."
)
SELF_MSG = (
    "The guard, its registration and the airlock marker cannot be changed from an agent "
    "session. A human can: start claude with RECALL_GUARD_DEV=1, or edit outside the session."
)


RECURSIVE_MSG = (
    "This recursive command or search would walk into a sealed or protected location. "
    "Scope it to a tracked directory such as src/, tests/ or docs/."
)


def walks_closed_zone(ctx: Context, path: Path) -> Denial | None:
    """Deny when walking path would enter, or start inside, a sealed or protected zone."""
    if any(under(z, path) or under(path, z) for z in ctx.cfg.closed_zones()):
        return Denial("recursive-over-sealed", RECURSIVE_MSG, ctx.display(path))
    return None


UNTRACKED_RECURSE_MSG = (
    "This recursive command or search would walk over files that are not git-tracked "
    "(they may hold client data). Name tracked files, use `git grep`, or ask a human."
)


def has_untracked_below(ctx: Context, directory: Path, cap: int = 5000) -> bool:
    """True if a recursive walk of directory could reach an unreadable file.

    Bounded os.walk (symlinks are not followed, tooling directories are skipped). A file or
    symlink is fine only if tracked, in a location zone or in this session's ledger; any other
    one, or more than cap entries, answers True (fail closed). Directories outside the repo have
    no tracked set and are not judged here.
    """
    cfg = ctx.cfg
    if not under(directory, cfg.root) or TOOLING_NAMES & set(directory.parts):
        return False
    files = ctx.tracked()[0]
    seen = 0
    for top, dirs, names in os.walk(str(directory), followlinks=False):
        dirs[:] = [d for d in dirs if d not in TOOLING_NAMES]
        # symlinks to directories land in dirs but are never descended: judge them as files
        entries = list(names) + [d for d in dirs if os.path.islink(os.path.join(top, d))]
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
        for name in entries:
            seen += 1
            if seen > cap:
                return True
            lex = Path(top) / name
            if lex.relative_to(cfg.root).as_posix() in files or ctx.in_zone(lex):
                continue
            return True
    return False


def suffix_message(cfg: Config, suffix: str) -> str:
    return (
        f"{suffix} files hold client rows and are blocked in this repo.{header_hint(cfg)} "
        "Real data must never enter an AI context."
    )


def untracked_message() -> str:
    return (
        "Untracked or ignored file (client-data guard allowlist). Agents may read git-tracked "
        "files, local/released/, local/artifacts/, local/fixtures/, their scratchpad and files "
        "they created this session. A human can run `git add -N <path>` to make a new file "
        "readable. Code outputs and logs belong in recall.sealed; scratch work belongs in "
        "the scratchpad."
    )


class Context:
    """Per-call state: config, cwd, session ledger and the (lazily read) tracked-file set."""

    def __init__(self, cfg: Config, cwd=None, session_id: str = ""):
        self.cfg = cfg
        self.cwd = Path(cwd) if cwd else cfg.root
        self.ledger = Ledger(cfg, session_id)
        self._tracked = None

    # -- helpers ---------------------------------------------------------------------
    def lexical(self, value: str, base: Path | None = None) -> Path:
        path = Path(os.path.expanduser(os.path.expandvars(value)))
        if not path.is_absolute():
            path = (base or self.cwd) / path
        return Path(os.path.normpath(path))

    def display(self, path: Path) -> str:
        if under(path, self.cfg.root):
            return path.relative_to(self.cfg.root).as_posix()
        return str(path)

    def tracked(self) -> tuple:
        """(tracked file set, tracked directory set), repo-relative posix paths."""
        if self._tracked is None:
            files = set()
            try:
                out = subprocess.run(
                    ["git", "-C", str(self.cfg.root), "ls-files", "-z"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                ).stdout
                files = {p for p in out.decode("utf-8", "surrogateescape").split("\0") if p}
            except (OSError, subprocess.SubprocessError):
                pass  # no git answer: nothing is tracked, so everything is denied (fail closed)
            dirs = set()
            for rel in files:
                parent = os.path.dirname(rel)
                while parent:
                    dirs.add(parent)
                    parent = os.path.dirname(parent)
            self._tracked = (files, dirs)
        return self._tracked

    def zone_dirs(self) -> tuple:
        cfg = self.cfg
        return (*cfg.released_dirs, cfg.fixtures_dir, *cfg.extra_allowed)

    def in_zone(self, lex: Path) -> bool:
        return any(under(lex, zone) for zone in self.zone_dirs()) or self.ledger.contains(lex)

    def self_hit(self, lex: Path) -> bool:
        """True if lex, or where it really points, is under a self-protected path."""
        protected = set(self.cfg.self_protected())
        protected.update(Path(os.path.realpath(p)) for p in list(protected))
        real = Path(os.path.realpath(lex))
        via_parent = Path(os.path.realpath(lex.parent)) / lex.name
        return any(under(c, p) for c in (lex, real, via_parent) for p in protected)

    def self_protect_check(self, value: str, base: Path | None = None) -> Denial | None:
        lex = self.lexical(value, base)
        if self.self_hit(lex):
            return Denial("self-protect", SELF_MSG, self.display(lex))
        return None

    # -- the policy ------------------------------------------------------------------
    def check_path(
        self, value: str, *, write: bool = False, base: Path | None = None
    ) -> Denial | None:
        cfg = self.cfg
        lex = self.lexical(value, base)
        real = Path(os.path.realpath(lex))
        if not under(lex, cfg.root) and under(real, cfg.root):
            lex = real  # reached through a symlinked cwd: judge it by where it really is
        shown = self.display(lex)

        for candidate in (lex, real):
            if under(candidate, cfg.sealed_root) or has_sealed_marker(candidate):
                return Denial("sealed", SEALED_MSG, shown)
            if any(under(candidate, p) for p in cfg.protected_dirs):
                return Denial("protected", PROTECTED_MSG, shown)

        suffix = data_suffix(lex.name) or data_suffix(real.name)
        if suffix:
            return Denial("suffix", suffix_message(cfg, suffix), shown)

        if write or not os.path.lexists(lex) or TOOLING_NAMES & set(lex.parts):
            return None

        inside = under(lex, cfg.root)
        if inside:
            if not under(real, cfg.root):
                return Denial(
                    "symlink-escape",
                    "Symlink inside the repo points outside it; blocked so a link cannot "
                    "smuggle protected data in.",
                    shown,
                )
            files, dirs = self.tracked()
            rel = lex.relative_to(cfg.root).as_posix()
            if rel == "." or rel in files or rel in dirs:
                return None
            if not self.in_zone(lex):
                if lex.is_dir() and any(under(z, lex) for z in self.zone_dirs()):
                    return None  # an ancestor of an allowed zone (e.g. local/)
                return Denial("untracked", untracked_message(), shown)

        return self._sniff(real, shown, large_check=inside or self._in_scratch(real))

    def _in_scratch(self, path: Path) -> bool:
        return any(under(path, s) for s in self.cfg.scratch_dirs)

    def _sniff(self, real: Path, shown: str, large_check: bool) -> Denial | None:
        if not real.is_file():
            return None
        hit = sniff(real, self.cfg.header_line(), large_check=large_check)
        if not hit:
            return None
        return Denial(
            "content",
            f"Content looks like client data ({hit}); blocked whatever the file is called."
            f"{header_hint(self.cfg)}",
            shown,
        )
