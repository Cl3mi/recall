# Recall guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a repo-local `PreToolUse` guard that keeps real client data and anything derived from it out of every AI context in this repo, with new logs and outputs protected automatically.

**Architecture:** A stdlib-only Python package (`tools/guard/recall_guard/`) is run by a fail-closed bash wrapper and registered in the tracked `.claude/settings.json`. It enforces an allowlist read policy (git-tracked files, released aggregates, synthetic fixtures, scratchpad, files the agent created), name and content rules, Bash command analysis, an airlock window lock and an audit log. Outputs go through `recall.sealed` into a marker-protected sealed root; only a numbers-only exporter releases aggregates.

**Tech Stack:** Python 3 stdlib only for the hook (must run on the system `python3`, not the uv env), bash, git, pytest + ruff for tests (uv env, Python 3.12).

**Spec:** `docs/superpowers/specs/2026-10-16-recall-guard-design.md`

---

## Read this first

**Deviations from the spec** (all deliberate; the final summary to the user must list them):

1. **Module layout.** The hook is a package `tools/guard/recall_guard/` with thin entry scripts. `sealed.py` lives in `src/recall/sealed.py` (not `tools/`) because only the `recall` package is installed in the sealed profiler image. The pre-commit lint runs through `guard.py --lint-staged`.
2. **Artifacts dir.** `local/artifacts/` is treated as released (agents already read aggregates there after a window), alongside `local/released/`. `profile.json`, `profile_report.md` and `eval_real.json` are therefore NOT in the name deny list (user decision, 2026-10-16).
3. **State location.** The audit log (`guard.log`) and the session ledger live inside `local/sealed/`, so they are sealed too.
4. **Lint behaviour.** On `Write`/`Edit` of in-scope Python files the lint denies (with the fix named) instead of merely warning, and a line can opt out with `# guard: ok(<reason>)`. It only examines *added* lines, so existing code is not retrofitted; pre-commit checks staged added lines only.
5. **Self-protection (added).** Agents cannot modify `tools/guard/`, the hook registration in `.claude/settings*.json`, `.githooks/`, `src/recall/sealed.py` or the airlock marker; otherwise the guard could be switched off by the thing it guards. A human sets `RECALL_GUARD_DEV=1` in the environment that launches `claude` to maintain it.
6. **Script scan.** Only untracked scripts (or scripts outside the repo) are scanned for protected paths / data-suffix text. Tracked scripts are trusted as reviewed. This keeps the sanctioned route of running pytest on tracked tests whose fixtures name data paths.
7. **Internal errors.** An unexpected exception inside the guard denies that one call (fail closed) and is logged; it does not silently allow.
8. **`guard.py --explain <path>`** (added) shows why a path is allowed or denied, for tuning.
9. **Task 8b hardening (added after an independent spec review of Tasks 1-8).** Path extraction also scans substrings inside quoted strings and `-c` code, recurses into `bash -c`, expands braces, treats implicit-cwd recursive tools and `xargs` readers as walking sealed zones, applies the closed-zone rule to `Grep` on explicit directories, resolves Artifact `files` against `root`, makes the session ledger exact-match, adds magic-byte archive sniffing and 2-column tables, widens the lint regexes, checks the airlock marker before parsing, caps audit-log paths, and checks path-like keys in generic tools.
10. **Outside-repo reads are not allowlisted** (decision by the controller, documented here): paths outside the repo are only subject to the sealed/protected/suffix/content rules, not the tracked-file allowlist, because agents legitimately read their own harness files (memory, tool results, scratchpad). A renamed export outside the repo is caught by the header fingerprint and the table heuristics, not by a deny-all rule.

**Conventions for every task:**

- The hook modules are stdlib-only and Python 3.8-compatible: every module starts with `from __future__ import annotations`; no `match`, no `X | Y` at runtime, no `Path.is_relative_to`, no `str.removeprefix`.
- Tests live in `tests/guard/` and use unique basenames `test_guard_*.py`. Run them with `uv run pytest tests/guard -q`.
- Lint with `uv run ruff check tools tests/guard src/recall/sealed.py` and `uv run ruff format --check tools tests/guard src/recall/sealed.py`; fix what it reports before each commit (line length 100).
- **Commit messages and shell commands must not contain data-suffix text** (the global `sindri-guard.py` blocks any Bash command mentioning it). Say "data suffix", never the literal extension. Test *files* may contain the literals (they are file content, not commands).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (as a second `-m`).
- The guard is registered **last** (Task 14). Until then agents may freely edit `tools/guard/`. After it, maintenance needs `RECALL_GUARD_DEV=1`.

---

## File structure

```
tools/guard/
  guard.py                  # hook entry (thin)
  run-guard.sh              # fail-closed wrapper
  airlock                   # human-run window CLI (thin)
  export_aggregate.py       # release gate CLI (thin)
  recall_guard/
    __init__.py
    config.py               # Config, load_config, constants
    names.py                # data-suffix regex, protected-string matching
    store.py                # ensure_sealed, Ledger, log_denial
    sniff.py                # content sniffing
    policy.py               # Denial, Context.check_path, messages
    bashcheck.py            # Bash tokenizer + analysis
    lint.py                 # write-side lint (+ staged mode)
    release.py              # numbers-only validation + export
    airlock.py              # window marker logic
    core.py                 # decide(), run_payload(), selfcheck(), explain(), main()
src/recall/sealed.py        # sealed_path(), sealed_logger()
.githooks/pre-commit        # runs guard.py --lint-staged
tests/guard/                # __init__.py, conftest.py, test_guard_*.py
CLAUDE.md                   # agent rules
docs/export.header.txt      # one line, supplied by the user (human step)
```

---

### Task 0: Branch and scaffolding

**Files:**
- Create: `tests/guard/__init__.py`, `tests/guard/conftest.py`, `tools/guard/recall_guard/__init__.py`

- [ ] **Step 1: Create the branch**

The spec commit lives on `feat/insight-view`; branch from it so the spec comes along.

```bash
cd <repo-root>
git switch -c feat/recall-guard
git log --oneline -1
```
Expected: `d244602 docs(guard): design spec for the recall client-data guard`

- [ ] **Step 2: Create the package and test scaffolding**

This step creates the two `__init__.py` files and nothing else. It also holds the two
versions of `tests/guard/conftest.py` used later: the **temporary** one is written in Task 1
(it only needs `load_config`), the **final** one replaces it in Task 5 (it also needs
`Context`). Do not write either conftest in this task.

`tools/guard/recall_guard/__init__.py`:

```python
"""Client-data guard for the recall repo.

Design: docs/superpowers/specs/2026-10-16-recall-guard-design.md
"""
```

`tests/guard/__init__.py`: empty file.

`tests/guard/conftest.py`:

```python
"""Shared fixtures: a throwaway git repo shaped like recall, plus guard config/context."""

import subprocess
import sys
from pathlib import Path

import pytest

GUARD_DIR = Path(__file__).resolve().parents[2] / "tools" / "guard"
sys.path.insert(0, str(GUARD_DIR))

from recall_guard.config import load_config  # noqa: E402
from recall_guard.policy import Context  # noqa: E402

HEADER = "ticket_id,created,title,description,customData"


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, rel: str, text: str = "x\n", track: bool = False) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if track:
            self.git("add", "-f", rel)
        return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    r = Repo(root)
    r.git("init", "-q")
    r.write("src/app.py", "print('hi')\n", track=True)
    r.write("README.md", "# readme\n", track=True)
    r.write("docs/export.header.txt", HEADER + "\n", track=True)
    return r


@pytest.fixture
def cfg(repo):
    return load_config(root=repo.root, env={})


@pytest.fixture
def ctx(cfg, repo):
    return Context(cfg, cwd=repo.root, session_id="sess1")
```

The conftest above is the **final** version (Task 5). It imports `recall_guard.policy`, which
does not exist before Task 5, so Tasks 1-4 use this temporary one instead:

Temporary `tests/guard/conftest.py` for Tasks 1-4 (replaced in Task 5):

```python
import subprocess
import sys
from pathlib import Path

import pytest

GUARD_DIR = Path(__file__).resolve().parents[2] / "tools" / "guard"
sys.path.insert(0, str(GUARD_DIR))

from recall_guard.config import load_config  # noqa: E402

HEADER = "ticket_id,created,title,description,customData"


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, rel: str, text: str = "x\n", track: bool = False) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if track:
            self.git("add", "-f", rel)
        return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    r = Repo(root)
    r.git("init", "-q")
    r.write("src/app.py", "print('hi')\n", track=True)
    r.write("README.md", "# readme\n", track=True)
    r.write("docs/export.header.txt", HEADER + "\n", track=True)
    return r


@pytest.fixture
def cfg(repo):
    return load_config(root=repo.root, env={})
```

(The temporary conftest imports `load_config`, created in Task 1, so it is written at the start of Task 1 Step 1.)

- [ ] **Step 3: Commit**

```bash
git add tools/guard/recall_guard/__init__.py tests/guard/__init__.py
git commit -m "chore(guard): scaffold guard package and test dir" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Config

**Files:**
- Create: `tools/guard/recall_guard/config.py`
- Create: `tests/guard/conftest.py` (temporary version above)
- Test: `tests/guard/test_guard_config.py`

- [ ] **Step 1: Write the temporary conftest and the failing test**

Write `tests/guard/conftest.py` with the **temporary version** from Task 0 Step 2.

`tests/guard/test_guard_config.py`:

```python
import json

from recall_guard.config import SEALED_MARKER, load_config

from .conftest import HEADER


def test_defaults(repo):
    root = repo.root.resolve()
    cfg = load_config(root=repo.root, env={})
    assert cfg.root == root
    assert cfg.sealed_root == root / "local" / "sealed"
    assert cfg.released_dirs == (root / "local" / "released", root / "local" / "artifacts")
    assert cfg.fixtures_dir == root / "local" / "fixtures"
    assert cfg.airlock_marker == root / "local" / "airlock.open"
    assert cfg.header_line() == HEADER
    assert root / "local" / "quarantine" in cfg.protected_dirs
    assert not cfg.dev_mode


def test_env_overrides(repo, tmp_path):
    env = {"RECALL_SEALED_ROOT": str(tmp_path / "s"), "RECALL_GUARD_DEV": "1"}
    cfg = load_config(root=repo.root, env=env)
    assert cfg.sealed_root == tmp_path / "s"
    assert tmp_path / "s" in cfg.protected_dirs
    assert cfg.dev_mode


def test_local_file_extends_allowed_and_protected(repo):
    repo.write(
        ".claude/guard.local.json",
        json.dumps({"extra_allowed": ["notes"], "extra_protected": ["/srv/other"]}),
    )
    cfg = load_config(root=repo.root, env={})
    root = repo.root.resolve()
    assert cfg.extra_allowed == (root / "notes",)
    assert cfg.protected_dirs[-1].as_posix() == "/srv/other"


def test_malformed_local_file_is_ignored(repo):
    repo.write(".claude/guard.local.json", "{not json")
    cfg = load_config(root=repo.root, env={})
    assert cfg.extra_allowed == ()


def test_missing_header_gives_none(repo):
    (repo.root / "docs" / "export.header.txt").unlink()
    assert load_config(root=repo.root, env={}).header_line() is None


def test_marker_name_is_stable():
    assert SEALED_MARKER == ".sealed"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_config.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'recall_guard.config'`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/config.py`:

```python
"""Locations, zones and per-person overrides for the recall guard."""

from __future__ import annotations

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
)


def _abs(value: str, root: Path) -> Path:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(path))


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
        try:
            with open(self.header_file, encoding="utf-8") as fh:
                line = fh.readline().strip()
        except OSError:
            return None
        return line or None

    def self_protected(self) -> tuple:
        return tuple(self.root / rel for rel in SELF_PROTECTED_RELS)


def _read_local(root: Path) -> tuple:
    try:
        data = json.loads((root / LOCAL_CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (), ()

    def paths(key: str) -> tuple:
        values = data.get(key, []) if isinstance(data, dict) else []
        return tuple(_abs(v, root) for v in values if isinstance(v, str) and v)

    return paths("extra_allowed"), paths("extra_protected")


def load_config(root: Path | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    if root is None:
        root = Path(env.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    root = Path(os.path.realpath(root))
    local = root / "local"
    extra_allowed, extra_protected = _read_local(root)
    sealed = _abs(env[SEALED_ENV], root) if env.get(SEALED_ENV) else local / "sealed"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    scratch = tuple(
        {Path("/tmp") / f"claude-{uid}", Path(tempfile.gettempdir()) / f"claude-{uid}"}
    )
    return Config(
        root=root,
        sealed_root=sealed,
        released_dirs=(local / "released", local / "artifacts"),
        fixtures_dir=local / "fixtures",
        header_file=root / HEADER_REL,
        airlock_marker=root / AIRLOCK_MARKER_REL,
        scratch_dirs=scratch,
        protected_dirs=(
            sealed,
            local / "quarantine",
            Path("/data/recall-quarantine"),
            *extra_protected,
        ),
        extra_allowed=extra_allowed,
        dev_mode=env.get(DEV_ENV) == "1",
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_config.py -q`
Expected: `6 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/config.py tests/guard
git commit -m "feat(guard): config with zones, env overrides and per-person local file" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Name rules

**Files:**
- Create: `tools/guard/recall_guard/names.py`
- Test: `tests/guard/test_guard_names.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from recall_guard.names import data_suffix, protected_string

BLOCKED = [
    "cat a/x.csv|head",
    "cat x.csv;ls",
    "wc -l <x.csv",
    "x.csv>out",
    "x.csv,y",
    "x.csv)",
    "X.CSV.gz",
    "a.tsv",
    "b.parquet",
    "c.jsonl",
    "d.xlsx",
    "d.xls",
    "e.npy",
    "e.npz",
    "f.syn",
    "g.pkl",
    "open('data.csv')",
    "cmd --out=y/z.csv --flag",
]

ALLOWED = [
    "x.csvfoo",
    "a.csv_old",
    "notes.md",
    "csv_reader.py",
    "docs/csv.md",
    "src/recall/profile.json",
    "local/artifacts/profile_report.md",
    "git status",
]


@pytest.mark.parametrize("text", BLOCKED)
def test_blocked(text):
    assert data_suffix(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_allowed(text):
    assert data_suffix(text) is None


def test_returns_lowercased_match():
    assert data_suffix("X.CSV.GZ") == ".csv.gz"


def test_protected_string_variants(cfg, repo):
    root = repo.root.resolve()
    assert protected_string(f"cat {root}/local/sealed/a", cfg)
    assert protected_string("cat local/sealed/a", cfg)
    assert protected_string("ls local/quarantine", cfg)
    assert protected_string("cat /data/recall-quarantine/x", cfg)
    assert protected_string("git status", cfg) is None
    assert protected_string("cat local/artifacts/gate_report.json", cfg) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_names.py -q`
Expected: FAIL (`ModuleNotFoundError: ... names`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/names.py`:

```python
"""Name-based rules: data suffixes and protected locations, matched on raw text."""

from __future__ import annotations

import os
import re

DATA_SUFFIX_RE = re.compile(
    r"\.(csv|tsv|parquet|jsonl|xlsx|xls|xlsm|xlsb|ods|pkl|npy|npz|syn)"
    r"(\.(gz|zip|bz2|xz))?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


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
        try:
            out.append(directory.relative_to(cfg.root).as_posix())
        except ValueError:
            pass
    return out


def protected_string(text: str, cfg) -> str | None:
    for variant in protected_variants(cfg):
        if variant and variant in text:
            return variant
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_names.py -q`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/names.py tests/guard/test_guard_names.py
git commit -m "feat(guard): punctuation-aware data-suffix and protected-location matching" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Store (sealed dirs, session ledger, audit log)

**Files:**
- Create: `tools/guard/recall_guard/store.py`
- Test: `tests/guard/test_guard_store.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import time

from recall_guard.store import Ledger, ensure_sealed, log_denial


def test_ensure_sealed_marks_root_and_dir(cfg):
    target = cfg.sealed_root / "ledger"
    ensure_sealed(target, cfg)
    assert (cfg.sealed_root / ".sealed").exists()
    assert (target / ".sealed").exists()


def test_ledger_records_new_file_and_missing_parents(cfg, repo):
    ledger = Ledger(cfg, "s1")
    new = repo.root / "scratch" / "deep" / "new.py"
    ledger.record_new_file(new)
    assert ledger.contains(new)
    assert ledger.contains(repo.root / "scratch" / "deep")
    assert ledger.contains(repo.root / "scratch" / "deep" / "later.txt")  # inside agent-made dir
    assert not ledger.contains(repo.root / "other" / "x.py")


def test_ledger_ignores_existing_files(cfg, repo):
    existing = repo.write("notes/old.txt")
    ledger = Ledger(cfg, "s1")
    ledger.record_new_file(existing)
    assert not ledger.contains(existing)


def test_ledger_is_per_session(cfg, repo):
    new = repo.root / "scratch" / "a.py"
    Ledger(cfg, "s1").record_new_file(new)
    assert not Ledger(cfg, "s2").contains(new)


def test_ledger_sanitises_session_id(cfg):
    ledger = Ledger(cfg, "../../evil")
    assert ledger.path.parent == cfg.sealed_root / "ledger"


def test_ledger_cleanup_removes_old_files(cfg, repo):
    ledger = Ledger(cfg, "old")
    ledger.record_new_file(repo.root / "scratch" / "a.py")
    old = time.time() - 3 * 86400
    os.utime(ledger.path, (old, old))
    Ledger.cleanup(cfg, max_age_s=86400)
    assert not ledger.path.exists()


def test_log_denial_writes_json_line_without_payload(cfg):
    log_denial(cfg, "Bash", "suffix", "data/x.csv")
    lines = (cfg.sealed_root / "guard.log").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert entry["tool"] == "Bash"
    assert entry["rule"] == "suffix"
    assert entry["path"] == "data/x.csv"
    assert set(entry) == {"ts", "tool", "rule", "path"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_store.py -q`
Expected: FAIL (`ModuleNotFoundError: ... store`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/store.py`:

```python
"""Guard state kept inside the sealed root: session ledger and audit log."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import SEALED_MARKER

_MARKER_TEXT = "sealed: never read from an AI session\n"


def ensure_sealed(directory: Path, cfg) -> None:
    """Create directory (mode 700) and make sure it and the sealed root carry the marker."""
    for target in (cfg.sealed_root, directory):
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = target / SEALED_MARKER
        if not marker.exists():
            marker.write_text(_MARKER_TEXT, encoding="utf-8")


class Ledger:
    """Files and directories an agent created this session; those stay readable."""

    def __init__(self, cfg, session_id: str):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")[:64]
        self._cfg = cfg
        self.path = cfg.sealed_root / "ledger" / f"{safe}.json"

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [str(item) for item in data] if isinstance(data, list) else []

    def contains(self, path: Path) -> bool:
        text = str(path)
        return any(text == e or text.startswith(e.rstrip("/") + "/") for e in self._load())

    def add(self, *paths: Path) -> None:
        entries = self._load()
        changed = False
        for path in paths:
            if str(path) not in entries:
                entries.append(str(path))
                changed = True
        if changed:
            ensure_sealed(self.path.parent, self._cfg)
            self.path.write_text(json.dumps(entries), encoding="utf-8")

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


def log_denial(cfg, tool: str, rule: str, path: str) -> None:
    """Append one JSON line: timestamp, tool, rule id, normalised path. Never payload content."""
    try:
        ensure_sealed(cfg.sealed_root, cfg)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "rule": rule,
            "path": path,
        }
        with open(cfg.sealed_root / "guard.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_store.py -q`
Expected: `7 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/store.py tests/guard/test_guard_store.py
git commit -m "feat(guard): sealed-dir helper, session ledger and audit log" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Content sniffing

**Files:**
- Create: `tools/guard/recall_guard/sniff.py`
- Test: `tests/guard/test_guard_sniff.py`

- [ ] **Step 1: Write the failing test**

```python
from recall_guard.sniff import sniff

HEADER = "ticket_id,created,title,description,customData"
TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def test_header_fingerprint_catches_renamed_file(tmp_path):
    f = tmp_path / "export.txt"
    f.write_text(HEADER + "\n1,2,3,4,5\n", encoding="utf-8")
    assert sniff(f, HEADER) == "header-fingerprint"


def test_header_fingerprint_beats_code_suffix(tmp_path):
    f = tmp_path / "schema.json"
    f.write_text(f'{{"cols": "{HEADER}"}}', encoding="utf-8")
    assert sniff(f, HEADER) == "header-fingerprint"


def test_delimited_table_caught_without_header(tmp_path):
    f = tmp_path / "dump.dat"
    f.write_text(TABLE, encoding="utf-8")
    assert sniff(f, None) == "delimited-table"


def test_semicolon_and_tab_tables(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text(TABLE.replace(",", ";"), encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text(TABLE.replace(",", "\t"), encoding="utf-8")
    assert sniff(a, None) == "delimited-table"
    assert sniff(b, None) == "delimited-table"


def test_code_and_markup_are_not_tables(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(TABLE, encoding="utf-8")
    assert sniff(f, None) is None


def test_prose_and_short_files_pass(tmp_path):
    prose = tmp_path / "notes.txt"
    prose.write_text("hello world, this is fine\nsecond line\nthird line\n", encoding="utf-8")
    short = tmp_path / "short.txt"
    short.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert sniff(prose, None) is None
    assert sniff(short, None) is None


def test_archives_are_denied(tmp_path):
    f = tmp_path / "bundle.zip"
    f.write_bytes(b"PK\x03\x04 not really")
    assert sniff(f, None) == "archive"


def test_binary_without_archive_suffix_passes(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\x02" * 100)
    assert sniff(f, None) is None


def test_large_extensionless_text_is_denied(tmp_path):
    f = tmp_path / "dump"
    f.write_text("word " * 300_000, encoding="utf-8")
    assert sniff(f, None) == "large-text"
    assert sniff(f, None, large_check=False) is None


def test_missing_file_is_none(tmp_path):
    assert sniff(tmp_path / "nope", HEADER) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_sniff.py -q`
Expected: FAIL (`ModuleNotFoundError: ... sniff`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/sniff.py`:

```python
"""Content sniffing: catch client data whatever the file is called."""

from __future__ import annotations

from pathlib import Path

HEAD_BYTES = 8192
LARGE_BYTES = 1_000_000

CODE_SUFFIXES = frozenset(
    {
        ".py", ".js", ".ts", ".svelte", ".md", ".sh", ".toml", ".yaml", ".yml", ".json",
        ".html", ".css", ".sql", ".lock", ".cfg", ".ini", ".rst", ".mjs", ".cjs",
    }
)
ARCHIVE_SUFFIXES = frozenset({".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar"})
LARGE_TEXT_SUFFIXES = frozenset({"", ".txt", ".dat", ".out", ".bin"})
DELIMITERS = (",", ";", "\t", "|")


def _delimited(text: str, truncated: bool) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    if truncated and len(lines) > 1:
        lines = lines[:-1]  # the last line may be cut mid-row by the read limit
    if len(lines) < 3:
        return False
    for delimiter in DELIMITERS:
        counts = {ln.count(delimiter) for ln in lines}
        if len(counts) == 1 and next(iter(counts)) >= 2:
            return True
    return False


def sniff(path: Path, header: str | None, large_check: bool = True) -> str | None:
    """Reason this file looks like client data, or None. Never returns file content."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        return None
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if b"\0" in head:
        return None
    text = head.decode("utf-8", errors="replace")
    if header and header in text:
        return "header-fingerprint"
    if suffix in CODE_SUFFIXES:
        return None
    if _delimited(text, truncated=len(head) >= HEAD_BYTES):
        return "delimited-table"
    if large_check and size > LARGE_BYTES and suffix in LARGE_TEXT_SUFFIXES:
        return "large-text"
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_sniff.py -q`
Expected: `10 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/sniff.py tests/guard/test_guard_sniff.py
git commit -m "feat(guard): content sniffing (header fingerprint, delimited tables, archives)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Read policy (`Context.check_path`)

**Files:**
- Create: `tools/guard/recall_guard/policy.py`
- Modify: `tests/guard/conftest.py` (replace temporary version with the final one)
- Test: `tests/guard/test_guard_policy.py`

- [ ] **Step 1: Replace conftest with the final version and write the failing test**

Write `tests/guard/conftest.py` with the **final version** from Task 0 Step 2 (the one that also imports `Context` and defines the `ctx` fixture).

`tests/guard/test_guard_policy.py`:

```python
import os

import pytest
from recall_guard.config import load_config
from recall_guard.policy import Context

from .conftest import HEADER

TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def rule(ctx, path, **kw):
    denial = ctx.check_path(str(path), **kw)
    return denial.rule if denial else None


def fresh(cfg, repo):
    return Context(cfg, cwd=repo.root, session_id="sess1")


def test_tracked_file_allowed(ctx, repo):
    assert rule(ctx, repo.root / "src" / "app.py") is None


def test_untracked_file_denied(ctx, repo):
    repo.write("notes/x.txt")
    assert rule(ctx, repo.root / "notes" / "x.txt") == "untracked"


def test_git_add_intent_makes_untracked_readable(cfg, repo):
    repo.write("notes/x.txt")
    repo.git("add", "-N", "notes/x.txt")
    assert rule(fresh(cfg, repo), repo.root / "notes" / "x.txt") is None


def test_sealed_root_and_marker_dirs_denied(ctx, repo):
    repo.write("local/sealed/run1.json")
    repo.write("elsewhere/.sealed", "")
    repo.write("elsewhere/a.txt")
    assert rule(ctx, repo.root / "local" / "sealed" / "run1.json") == "sealed"
    assert rule(ctx, repo.root / "elsewhere" / "a.txt") == "sealed"


def test_sealed_denies_even_tracked_and_even_when_missing(ctx, repo):
    assert rule(ctx, repo.root / "local" / "sealed" / "not-yet.json") == "sealed"


def test_protected_quarantine_denied(ctx, repo):
    repo.write("local/quarantine/words.txt")
    assert rule(ctx, repo.root / "local" / "quarantine" / "words.txt") == "protected"
    assert rule(ctx, "/data/recall-quarantine/x") == "protected"


def test_data_suffix_denied_even_when_tracked(ctx, repo):
    repo.write("data/x.csv", track=True)
    denial = ctx.check_path(str(repo.root / "data" / "x.csv"))
    assert denial.rule == "suffix"
    assert "docs/export.header.txt" in denial.reason


def test_released_dirs_readable_without_sniff_hits(ctx, repo):
    repo.write("local/artifacts/gate_report.json", "{}\n")
    repo.write("local/artifacts/profile.json", "{}\n")
    repo.write("local/released/agg.json", "{}\n")
    for rel in ("local/artifacts/gate_report.json", "local/artifacts/profile.json",
                "local/released/agg.json"):
        assert rule(ctx, repo.root / rel) is None


def test_fixtures_dir_readable(ctx, repo):
    repo.write("local/fixtures/cache/readme.txt", "synthetic\n")
    assert rule(ctx, repo.root / "local" / "fixtures" / "cache" / "readme.txt") is None


def test_ledger_files_readable(cfg, repo):
    ctx = fresh(cfg, repo)
    new = repo.root / "scratch" / "new.py"
    ctx.ledger.record_new_file(new)
    repo.write("scratch/new.py", "x = 1\n")
    assert rule(ctx, new) is None


def test_renamed_export_with_header_is_caught_in_zones(ctx, repo):
    repo.write("local/fixtures/export.txt", HEADER + "\n1,2,3,4,5\n")
    repo.write("local/artifacts/renamed.dat", TABLE)
    assert rule(ctx, repo.root / "local" / "fixtures" / "export.txt") == "content"
    assert rule(ctx, repo.root / "local" / "artifacts" / "renamed.dat") == "content"


def test_outside_root_files_are_only_sniffed(ctx, tmp_path):
    ok = tmp_path / "notes.txt"
    ok.write_text("hello\n", encoding="utf-8")
    bad = tmp_path / "outside.txt"
    bad.write_text(TABLE, encoding="utf-8")
    assert rule(ctx, ok) is None
    assert rule(ctx, bad) == "content"


def test_nonexistent_untracked_path_is_not_denied(ctx, repo):
    assert rule(ctx, repo.root / "notes" / "future.txt") is None


def test_write_mode_skips_allowlist_but_not_sealed_or_suffix(ctx, repo):
    assert rule(ctx, repo.root / "notes" / "new.txt", write=True) is None
    assert rule(ctx, repo.root / "local" / "sealed" / "a", write=True) == "sealed"
    assert rule(ctx, repo.root / "notes" / "new.csv", write=True) == "suffix"


def test_tooling_dirs_pass(ctx, repo):
    repo.write(".venv/lib/mod.py", "x = 1\n")
    assert rule(ctx, repo.root / ".venv" / "lib" / "mod.py") is None


def test_symlink_escaping_the_repo_is_denied(ctx, repo, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.txt").write_text("hello\n", encoding="utf-8")
    os.symlink(real, repo.root / "linkdir")
    assert rule(ctx, repo.root / "linkdir" / "a.txt") == "symlink-escape"


def test_directories(ctx, repo):
    repo.write("notes/x.txt")
    repo.write("local/artifacts/g.json", "{}\n")
    assert rule(ctx, repo.root / "src") is None
    assert rule(ctx, repo.root) is None
    assert rule(ctx, repo.root / "notes") == "untracked"
    assert rule(ctx, repo.root / "local") is None  # ancestor of an allowed zone


def test_extra_allowed_from_local_file(repo):
    repo.write(".claude/guard.local.json", '{"extra_allowed": ["mynotes"]}')
    repo.write("mynotes/a.txt", "hello\n")
    cfg = load_config(root=repo.root, env={})
    assert rule(Context(cfg, cwd=repo.root), repo.root / "mynotes" / "a.txt") is None


def test_relative_paths_resolve_against_cwd(cfg, repo):
    repo.write("notes/x.txt")
    ctx = Context(cfg, cwd=repo.root / "notes", session_id="s")
    assert rule(ctx, "x.txt") == "untracked"
    assert rule(ctx, "../src/app.py") is None


@pytest.mark.parametrize("rel", ["tools/guard", "tools/guard/x.py", ".claude/settings.json"])
def test_self_protect_check(ctx, repo, rel):
    assert ctx.self_protect_check(str(repo.root / rel)).rule == "self-protect"


def test_self_protect_ignores_other_paths(ctx, repo):
    assert ctx.self_protect_check(str(repo.root / "src" / "app.py")) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_policy.py -q`
Expected: FAIL / collection error (`ModuleNotFoundError: ... policy`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/policy.py`:

```python
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
PROTECTED_MSG = "Protected client-data location. Never read, list or reference it from an AI session."
SELF_MSG = (
    "The guard, its registration and the airlock marker cannot be changed from an agent "
    "session. A human can: start claude with RECALL_GUARD_DEV=1, or edit outside the session."
)


def suffix_message(cfg: Config, suffix: str) -> str:
    return (
        f"{suffix} files hold client rows and are blocked in this repo.{header_hint(cfg)} "
        "Real data must never enter an AI context."
    )


def untracked_message() -> str:
    return (
        "Untracked or ignored file (client-data guard allowlist). Agents may read git-tracked "
        "files, local/released/, local/artifacts/, local/fixtures/, their scratchpad and files "
        "they created this session. If this is a new source or doc file of yours, "
        "`git add -N <path>` makes it readable. Code outputs and logs belong in recall.sealed; "
        "scratch work belongs in the scratchpad."
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

    def self_protect_check(self, value: str, base: Path | None = None) -> Denial | None:
        lex = self.lexical(value, base)
        if any(under(lex, p) for p in self.cfg.self_protected()):
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard -q`
Expected: all tests so far pass (config, names, store, sniff, policy)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/policy.py tests/guard
git commit -m "feat(guard): allowlist read policy with sealed, content and symlink rules" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Bash analysis

**Files:**
- Create: `tools/guard/recall_guard/bashcheck.py`
- Test: `tests/guard/test_guard_bashcheck.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from recall_guard.bashcheck import analyse, tokenize
from recall_guard.config import load_config
from recall_guard.policy import Context


def rule(ctx, command):
    denial = analyse(ctx, command)
    return denial.rule if denial else None


def test_tokenizer_splits_shell_punctuation():
    assert tokenize("cat a/x.csv|head") == ["cat", "a/x.csv", "|", "head"]
    assert tokenize("wc -l <x.csv") == ["wc", "-l", "<", "x.csv"]
    assert tokenize("a;b") == ["a", ";", "b"]
    assert tokenize("unterminated 'quote")  # falls back instead of raising


@pytest.mark.parametrize(
    "command",
    [
        "cat data/x.csv",
        "cat a/x.csv|head",
        "cat x.csv;ls",
        "wc -l <x.csv",
        "python3 -c \"open('data.csv')\"",
        "cat local/sealed/run.json",
        "ls local/quarantine",
    ],
)
def test_text_rules_deny(ctx, command):
    assert analyse(ctx, command) is not None


def test_cd_then_relative_sealed_read(ctx, repo):
    repo.write("local/sealed/run.json")
    assert rule(ctx, "cd local && cat sealed/run.json") == "sealed"


def test_untracked_read_denied_and_git_add_N_hint(ctx, repo):
    repo.write("notes/x.txt")
    assert rule(ctx, "cat notes/x.txt") == "untracked"


def test_glob_expansion_is_checked(ctx, repo):
    repo.write("notes/a.txt")
    repo.write("notes/b.txt")
    assert rule(ctx, "cat notes/*.txt") == "untracked"


def test_redirect_to_new_file_is_a_write_and_allowed(ctx):
    assert rule(ctx, "echo hi > scratch_out.log") is None


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git log --oneline -5",
        "ls src",
        "cat src/app.py",
        "grep -rn foo src docs",
        "uv run pytest -q",
        "echo $HOME",
        "git add src/app.py",
    ],
)
def test_ordinary_commands_pass(ctx, command):
    assert rule(ctx, command) is None


def test_extractors_denied(ctx):
    assert rule(ctx, "pdftotext a.pdf -") == "extractor"
    assert rule(ctx, "cd x && libreoffice --convert-to txt f") == "extractor"
    assert rule(ctx, "uv run in2csv report") == "extractor"


def test_dynamic_paths_denied_for_readers_only(ctx):
    assert rule(ctx, "cat $(git rev-parse --show-toplevel)/README.md") == "dynamic-path"
    assert rule(ctx, "cat $SOMETHING_UNSET/x") == "dynamic-path"
    assert rule(ctx, "echo $SOMETHING_UNSET") is None


def test_recursive_tools_over_a_sealed_ancestor_denied(ctx, repo):
    repo.write("local/sealed/a.json")
    assert rule(ctx, "grep -rn foo .") == "recursive-over-sealed"
    assert rule(ctx, "grep -rn foo src") is None
    assert rule(ctx, "find . -name '*.py'") is None
    assert rule(ctx, "find . -exec cat {} +") == "recursive-over-sealed"


def test_untracked_script_naming_protected_paths_denied(ctx, tmp_path):
    leak = tmp_path / "leak.py"
    leak.write_text("open('local/sealed/a')\n", encoding="utf-8")
    assert rule(ctx, f"python3 {leak}") == "script-protected"


def test_agent_created_script_with_data_suffix_denied(cfg, repo):
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    script = repo.root / "scripts" / "mk.py"
    ctx.ledger.record_new_file(script)
    repo.write("scripts/mk.py", "p = 'x.csv'\n")
    assert rule(ctx, "python3 scripts/mk.py") == "script-suffix"


def test_tracked_script_may_name_data_paths(cfg, repo):
    repo.write("tests/t.py", "p = 'x.csv'\n", track=True)
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    assert rule(ctx, "python3 -m pytest tests/t.py") is None


@pytest.mark.parametrize(
    "command", ["python3 tools/guard/airlock open", "./airlock status", "rm local/airlock.open"]
)
def test_airlock_cli_and_marker_denied(ctx, command):
    assert rule(ctx, command) == "airlock-cli"


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/a/b/ tools/guard/guard.py",
        "rm tools/guard/x",
        "echo x > .claude/settings.json",
        "git checkout -- tools/guard",
        "tee .githooks/pre-commit",
    ],
)
def test_self_protect_denies_mutation(ctx, repo, command):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, command) == "self-protect"


def test_self_protect_allows_reading_and_running(ctx, repo):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, "cat tools/guard/guard.py") is None
    assert rule(ctx, "git add tools/guard") is None
    assert rule(ctx, "uv run ruff check tools/guard") is None


def test_dev_mode_lifts_self_protection(repo):
    cfg = load_config(root=repo.root, env={"RECALL_GUARD_DEV": "1"})
    repo.write("tools/guard/guard.py", track=True)
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    assert rule(ctx, "sed -i s/a/b/ tools/guard/guard.py") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_bashcheck.py -q`
Expected: FAIL (`ModuleNotFoundError: ... bashcheck`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/bashcheck.py`:

```python
"""Analysis of Bash command text: paths, programs, scripts, self-protection."""

from __future__ import annotations

import glob
import os
import re
import shlex
from pathlib import Path

from .config import TOOLING_NAMES
from .names import data_suffix, protected_string
from .policy import (
    PROTECTED_MSG,
    SELF_MSG,
    Context,
    Denial,
    suffix_message,
    under,
)

EXTRACTORS = frozenset(
    {
        "pdftotext", "pdfimages", "pdftoppm", "pdftocairo", "pdfplumber", "mutool",
        "libreoffice", "soffice", "ssconvert", "in2csv", "xlsx2csv", "csvlook",
        "antiword", "catdoc", "tesseract", "ocrmypdf", "qpdf", "gs",
    }
)
READERS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "awk", "sed",
        "cut", "sort", "uniq", "wc", "xxd", "od", "hexdump", "strings", "bat", "tac", "nl",
        "paste", "column", "jq", "python", "python3", "perl", "ruby", "node", "cp", "mv",
        "scp", "rsync", "tar", "zip", "gzip", "gunzip", "zcat", "base64", "diff", "cmp",
        "split", "tee",
    }
)
RECURSIVE = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack", "tar", "zip", "7z",
                       "rsync", "cp", "scp"})
MUTATORS = frozenset(
    {"rm", "mv", "cp", "tee", "chmod", "chown", "ln", "truncate", "dd", "install", "patch",
     "rmdir", "shred", "touch"}
)
GIT_MUTATING = frozenset(
    {"checkout", "restore", "rm", "mv", "reset", "stash", "apply", "clean", "revert", "am"}
)
SCRIPT_RUNNERS = frozenset({"python", "python3", "bash", "sh", "zsh", "dash", "ksh", "node",
                            "perl", "ruby", "source", "."})
WRAPPERS = frozenset(
    {"uv", "run", "env", "sudo", "time", "nohup", "exec", "command", "nice", "timeout",
     "xargs", "builtin"}
)
_STARTERS = frozenset({";", "|", "&&", "||", "&", "|&", "(", "then", "do", "else", "!", "{"})
_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
_MAX_SCRIPT_BYTES = 262144
_MAX_GLOB = 500

AIRLOCK_MSG = (
    "The airlock window CLI and its marker can only be used by a human in a normal terminal."
)


def _is_punct(token: str) -> bool:
    return bool(token) and all(ch in "();<>|&" for ch in token)


def tokenize(command: str) -> list:
    """Shell-aware split that also separates ; | && < > ( ) from adjacent words."""
    text = command.replace("\n", " ; ")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # treat comments as code: stricter than the shell
        return list(lexer)
    except ValueError:
        return [t for t in re.split(r"[\s;|&<>()]+", text) if t]


def _effective(tokens: list, start: int) -> tuple:
    """(program basename, token index) at a command position, skipping wrappers and flags."""
    i = start
    while i < len(tokens):
        token = tokens[i]
        if _is_punct(token):
            return "", i
        base = os.path.basename(token)
        if (
            base in WRAPPERS
            or token.startswith("-")
            or _ASSIGN.match(token)
            or token.isdigit()
        ):
            i += 1
            continue
        return base, i
    return "", i


def _programs(tokens: list) -> list:
    found = []
    for i in range(len(tokens)):
        if i == 0 or tokens[i - 1] in _STARTERS:
            base, j = _effective(tokens, i)
            if base:
                found.append((base, j))
    return found


def _is_runner(base: str) -> bool:
    return base in SCRIPT_RUNNERS or bool(re.match(r"^python[\d.]*$", base))


def _candidates(token: str) -> list:
    if token.startswith("-") and "=" not in token:
        return []
    if "=" in token:
        return [token.split("=", 1)[1]]
    return [token]


def _expand(ctx: Context, value: str, cur: Path) -> list:
    if not value or _is_punct(value):
        return []
    if any(ch in value for ch in "*?["):
        pattern = str(ctx.lexical(value, cur))
        return sorted(glob.glob(pattern, recursive=True))[:_MAX_GLOB]
    if "/" in value or "." in value or os.path.lexists(ctx.lexical(value, cur)):
        return [value]
    return []


def _cd_args(tokens: list, prog_at: dict) -> set:
    out = set()
    for j, base in prog_at.items():
        if base in ("cd", "pushd"):
            k = j + 1
            while k < len(tokens) and tokens[k].startswith("-"):
                k += 1
            if k < len(tokens) and not _is_punct(tokens[k]):
                out.add(k)
    return out


def _sed_in_place(tokens: list, names: set) -> bool:
    return "sed" in names and any(t.startswith("-i") or t == "--in-place" for t in tokens)


def _check_self_protect(ctx: Context, tokens: list, names: set) -> Denial | None:
    protected = ctx.cfg.self_protected()
    touched = None
    for token in tokens:
        for cand in _candidates(token):
            if not cand or _is_punct(cand) or "$" in cand:
                continue
            lex = ctx.lexical(cand)
            if any(under(lex, p) for p in protected):
                touched = lex
                break
        if touched:
            break
    if touched is None:
        return None
    mutating = (
        ">" in tokens
        or ">>" in tokens
        or bool(names & MUTATORS)
        or _sed_in_place(tokens, names)
        or ("git" in names and any(t in GIT_MUTATING for t in tokens))
    )
    if mutating:
        return Denial("self-protect", SELF_MSG, ctx.display(touched))
    return None


def _check_tokens(ctx: Context, tokens: list, programs: list, names: set) -> Denial | None:
    cfg = ctx.cfg
    prog_at = {j: base for base, j in programs}
    cd_args = _cd_args(tokens, prog_at)
    recursive = bool(names & RECURSIVE) or (
        "find" in names and any(t in ("-exec", "-execdir", "-ok") for t in tokens)
    )
    closed = (cfg.sealed_root, *cfg.protected_dirs)
    cur = ctx.cwd
    dynamic = False
    for i, token in enumerate(tokens):
        for cand in _candidates(token):
            expanded = os.path.expandvars(os.path.expanduser(cand))
            if "$" in expanded or "`" in expanded:
                dynamic = True
                continue
            for path in _expand(ctx, expanded, cur):
                denial = ctx.check_path(path, base=cur)
                if denial:
                    return denial
                lex = ctx.lexical(path, cur)
                if recursive and lex.is_dir() and any(under(z, lex) for z in closed):
                    return Denial(
                        "recursive-over-sealed",
                        "This recursive command would walk into a sealed or protected "
                        "location. Scope it to a tracked directory such as src/, tests/ or docs/.",
                        ctx.display(lex),
                    )
        if i in cd_args and "$" not in token:
            cur = ctx.lexical(token, cur)
    if dynamic and names & READERS:
        return Denial(
            "dynamic-path",
            "A reader command uses a path the guard cannot resolve ($VAR or $(...)). "
            "Write the path out literally.",
        )
    return None


def _check_scripts(ctx: Context, tokens: list, names: set) -> Denial | None:
    if not any(_is_runner(b) for b in names):
        return None
    cfg = ctx.cfg
    files, _ = ctx.tracked()
    for token in tokens:
        if token.startswith("-") or _is_punct(token) or "$" in token:
            continue
        path = ctx.lexical(token)
        try:
            if not path.is_file() or path.stat().st_size > _MAX_SCRIPT_BYTES:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if TOOLING_NAMES & set(path.parts):
            continue
        inside = under(path, cfg.root)
        if inside and path.relative_to(cfg.root).as_posix() in files:
            continue  # tracked scripts are reviewed code
        hit = protected_string(body, cfg)
        if hit:
            return Denial(
                "script-protected",
                f"Script {ctx.display(path)} reaches into a protected location. "
                "Running it would pull client data into an AI context.",
                ctx.display(path),
            )
        if inside and data_suffix(body):
            return Denial(
                "script-suffix",
                f"Script {ctx.display(path)} names data files. Untracked scripts that do "
                "so cannot be run from an agent session; put the path in a tracked, "
                "reviewed file (as the integration tests do).",
                ctx.display(path),
            )
    return None


def analyse(ctx: Context, command: str) -> Denial | None:
    cfg = ctx.cfg
    hit = protected_string(command, cfg)
    if hit:
        return Denial("protected-ref", PROTECTED_MSG, hit)
    suffix = data_suffix(command)
    if suffix:
        return Denial("suffix", suffix_message(cfg, suffix), suffix)

    tokens = tokenize(command)
    programs = _programs(tokens)
    names = {base for base, _ in programs}

    extractor = names & EXTRACTORS
    if extractor:
        return Denial(
            "extractor",
            f"'{sorted(extractor)[0]}' turns documents into text and is blocked in this repo.",
            sorted(extractor)[0],
        )
    if any(os.path.basename(t) in ("airlock", "airlock.open") for t in tokens):
        return Denial("airlock-cli", AIRLOCK_MSG)
    if not cfg.dev_mode:
        denial = _check_self_protect(ctx, tokens, names)
        if denial:
            return denial
    denial = _check_tokens(ctx, tokens, programs, names)
    if denial:
        return denial
    return _check_scripts(ctx, tokens, names)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_bashcheck.py -q`
Expected: all pass. If a case fails, fix `bashcheck.py` (not the test) unless the test itself contradicts the spec.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/bashcheck.py tests/guard/test_guard_bashcheck.py
git commit -m "feat(guard): Bash analysis (token paths, globs, cd, extractors, scripts, self-protection)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Write-side lint

**Files:**
- Create: `tools/guard/recall_guard/lint.py`
- Test: `tests/guard/test_guard_lint.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from recall_guard.lint import added_lines, check_staged, check_text, in_scope


@pytest.mark.parametrize(
    "line,rule",
    [
        ('open(p, "w")', "open-write"),
        ("open(p, 'ab')", "open-write"),
        ("logging.FileHandler(f)", "file-handler"),
        ("path.write_text(x)", "path-write"),
        ("df.to_csv('a')", "table-dump"),
        ("np.save(f, a)", "array-dump"),
        ("json.dump(obj, fh)", "serialise-dump"),
        ("print(row)", "print-rows"),
    ],
)
def test_flags_output_writers(line, rule):
    findings = check_text("src/recall/mod.py", "", line + "\n")
    assert [f.rule for f in findings] == [rule]


@pytest.mark.parametrize(
    "line",
    [
        'open(p, "r")',
        "x = json.dumps(a)",
        'print("hello")',
        'open(p, "w")  # guard: ok(synthetic fixture)',
        "from recall.sealed import sealed_logger",
    ],
)
def test_passes_safe_lines(line):
    assert check_text("src/recall/mod.py", "", line + "\n") == []


def test_only_added_lines_count():
    old = 'open(p, "w")\nx = 1\n'
    new = 'open(p, "w")\nx = 2\n'
    assert check_text("src/recall/mod.py", old, new) == []
    assert [n for n, _ in added_lines(old, new)] == [2]


def test_scope():
    assert in_scope("src/recall/mod.py")
    assert in_scope("profiler/x.py")
    assert in_scope("insight/x.py")
    assert in_scope("fixtures/generate.py")
    assert not in_scope("tests/unit/test_x.py")
    assert not in_scope("tools/guard/x.py")
    assert not in_scope("src/recall/sealed.py")
    assert not in_scope("src/recall/notes.md")
    assert check_text("tests/unit/test_x.py", "", 'open(p, "w")\n') == []


def test_finding_carries_location(repo):
    f = check_text("src/recall/mod.py", "", "a = 1\nopen(p, 'w')\n")[0]
    assert (f.path, f.line, f.rule) == ("src/recall/mod.py", 2, "open-write")


def test_check_staged_flags_added_lines_and_data_files(repo):
    repo.write("src/m.py", 'open(p, "w")\n', track=True)
    repo.write("data/x.csv", "a\n", track=True)
    findings = check_staged(repo.root)
    assert {(f.path, f.rule) for f in findings} == {
        ("src/m.py", "open-write"),
        ("data/x.csv", "data-file"),
    }


def test_check_staged_clean_repo(repo):
    assert check_staged(repo.root) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_lint.py -q`
Expected: FAIL (`ModuleNotFoundError: ... lint`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/lint.py`:

```python
"""Write-side lint: new code must send outputs and logs through recall.sealed."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .names import data_suffix

SCOPE_PREFIXES = ("src/", "profiler/", "insight/", "fixtures/")
EXEMPT = ("src/recall/sealed.py",)
PRAGMA = "# guard: ok"
HINT = (
    "Route outputs and logs through recall.sealed (sealed_path / sealed_logger) and release "
    "aggregates with tools/guard/export_aggregate.py. Add '# guard: ok(<reason>)' only for "
    "synthetic or non-client data."
)

_RULES = (
    ("open-write", re.compile(r"""\bopen\([^)]*['"][wax][bt+]*['"]""")),
    ("file-handler", re.compile(r"\bFileHandler\(")),
    ("path-write", re.compile(r"\.(write_text|write_bytes)\(")),
    ("table-dump", re.compile(r"\.(to_csv|to_parquet|to_json|to_pickle)\(")),
    ("array-dump", re.compile(r"\b(np|numpy)\.(save|savez|savez_compressed|savetxt)\(")),
    ("serialise-dump", re.compile(r"\b(json|pickle)\.dump\(")),
    ("print-rows", re.compile(r"\bprint\(\s*(row|rows|record|records|df|ticket|tickets)\b")),
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
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def check_staged(root: Path) -> list:
    """Lint the added lines of staged Python files and reject staged data files."""
    findings = []
    for name in _git(root, "diff", "--cached", "--name-only", "--diff-filter=AM", "-z").split("\0"):
        if name and data_suffix(name):
            findings.append(Finding(name, 0, "data-file", "data file staged for commit"))

    current = None
    number = 0
    added: dict = {}
    diff = _git(root, "diff", "--cached", "--unified=0", "--no-color", "--diff-filter=AM")
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else None
            if current:
                added.setdefault(current, [])
            continue
        match = _HUNK.match(raw)
        if match:
            number = int(match.group(1))
            continue
        if raw.startswith("+") and current:
            added[current].append((number, raw[1:]))
            number += 1
    for rel, lines in added.items():
        if in_scope(rel):
            findings.extend(_scan(rel, lines))
    return findings
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard/test_guard_lint.py -q`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard/recall_guard/lint.py tests/guard/test_guard_lint.py
git commit -m "feat(guard): write-side lint for outputs and logs outside the sealed helper" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Core dispatch, entry scripts and fail-closed wrapper

**Files:**
- Create: `tools/guard/recall_guard/core.py`, `tools/guard/guard.py`, `tools/guard/run-guard.sh`
- Test: `tests/guard/test_guard_core.py`, `tests/guard/test_guard_e2e.py`

- [ ] **Step 1: Write the failing tests**

`tests/guard/test_guard_core.py`:

```python
import json

import pytest
from recall_guard import core
from recall_guard.config import load_config

TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def call(cfg, tool, tool_input, cwd=None, session="s1"):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or cfg.root),
               "session_id": session}
    return core.decide(cfg, payload)


def rule(denial):
    return denial.rule if denial else None


def test_read_tracked_ok_and_untracked_denied(cfg, repo):
    repo.write("notes/x.txt")
    assert call(cfg, "Read", {"file_path": str(repo.root / "src" / "app.py")}) is None
    assert rule(call(cfg, "Read", {"file_path": str(repo.root / "notes" / "x.txt")})) == "untracked"


def test_glob_and_grep_data_filters_denied(cfg):
    assert rule(call(cfg, "Glob", {"pattern": "**/*.csv"})) == "suffix"
    assert rule(call(cfg, "Grep", {"pattern": "x", "glob": "*.tsv"})) == "suffix"
    assert rule(call(cfg, "Grep", {"pattern": "x", "type": "csv"})) == "suffix"
    assert call(cfg, "Grep", {"pattern": "csv", "path": str(cfg.root / "src")}) is None


def test_write_new_file_records_ledger_and_is_then_readable(cfg, repo):
    target = repo.root / "scratch" / "new.py"
    assert call(cfg, "Write", {"file_path": str(target), "content": "x = 1\n"}) is None
    repo.write("scratch/new.py", "x = 1\n")
    assert call(cfg, "Read", {"file_path": str(target)}) is None
    # a different session does not inherit the ledger
    assert rule(call(cfg, "Read", {"file_path": str(target)}, session="other")) == "untracked"


def test_write_to_data_suffix_and_sealed_denied(cfg):
    assert rule(call(cfg, "Write", {"file_path": str(cfg.root / "a.csv"), "content": ""})) == "suffix"
    sealed = cfg.sealed_root / "x.json"
    assert rule(call(cfg, "Write", {"file_path": str(sealed), "content": ""})) == "sealed"


def test_self_protection_for_file_tools(cfg, repo):
    for tool in ("Write", "Edit", "NotebookEdit"):
        field = "notebook_path" if tool == "NotebookEdit" else "file_path"
        denial = call(cfg, tool, {field: str(repo.root / "tools" / "guard" / "guard.py")})
        assert rule(denial) == "self-protect"
    dev = load_config(root=repo.root, env={"RECALL_GUARD_DEV": "1"})
    assert call(dev, "Write", {"file_path": str(repo.root / "tools" / "guard" / "g.py"),
                               "content": ""}) is None


def test_lint_denies_unsealed_output_in_scope_and_honours_pragma(cfg, repo):
    path = str(repo.root / "src" / "recall" / "new.py")
    bad = call(cfg, "Write", {"file_path": path, "content": 'open(p, "w")\n'})
    assert rule(bad) == "lint"
    assert "recall.sealed" in bad.reason
    ok = call(cfg, "Write", {"file_path": path,
                             "content": 'open(p, "w")  # guard: ok(synthetic)\n'})
    assert ok is None
    edit = call(cfg, "Edit", {"file_path": str(repo.root / "src" / "app.py"),
                              "old_string": "print('hi')",
                              "new_string": "logging.FileHandler(f)"})
    assert rule(edit) == "lint"


def test_bash_is_delegated(cfg):
    assert rule(call(cfg, "Bash", {"command": "cat x.csv|head"})) == "suffix"
    assert call(cfg, "Bash", {"command": "git status"}) is None
    assert rule(call(cfg, "Monitor", {"command": "cat x.csv"})) == "suffix"


def test_airlock_marker_denies_everything(cfg, repo):
    cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
    cfg.airlock_marker.write_text("open", encoding="utf-8")
    for tool, tin in (("Read", {"file_path": str(repo.root / "README.md")}),
                      ("Bash", {"command": "git status"}),
                      ("Skill", {})):
        assert rule(call(cfg, tool, tin)) == "airlock"


def test_subagent_prompts_may_not_name_protected_paths(cfg):
    assert rule(call(cfg, "Agent", {"prompt": "read local/sealed/run.json"})) == "protected-ref"
    assert call(cfg, "Agent", {"prompt": "refactor src/"}) is None


def test_artifact_and_generic_path_fields(cfg, repo):
    page = repo.write("local/out/page.html", "<html></html>\n")
    assert rule(call(cfg, "Artifact", {"file_path": str(page)})) == "untracked"
    assert rule(call(cfg, "ArtifactData", {"file_path": str(repo.root / "d" / "x.csv")})) == "suffix"
    assert rule(call(cfg, "Artifact", {"files": {"a.js": str(page)}})) == "untracked"
    assert call(cfg, "WebFetch", {"url": "https://example.com/data.csv"}) is None


def test_run_payload_returns_internal_error_denial_on_bug(cfg, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(core, "decide", boom)
    tool, denial = core.run_payload(json.dumps({"tool_name": "Read", "tool_input": {}}), cfg)
    assert tool == "Read"
    assert denial.rule == "internal-error"
    assert "RuntimeError" in denial.reason


def test_run_payload_on_garbage_denies_only_when_it_mentions_data(cfg):
    assert core.run_payload("not json at all", cfg)[1] is None
    assert core.run_payload("not json x.csv", cfg)[1].rule == "unparseable"
```

`tests/guard/test_guard_e2e.py`:

```python
import json
import os
import shutil
import subprocess

from .conftest import GUARD_DIR


def run_wrapper(repo_root, payload, guard_dir=GUARD_DIR):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo_root)}
    env.pop("RECALL_GUARD_DEV", None)
    return subprocess.run(
        ["bash", str(guard_dir / "run-guard.sh")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def payload(repo, tool, tool_input):
    return {"tool_name": tool, "tool_input": tool_input, "cwd": str(repo.root),
            "session_id": "e2e", "hook_event_name": "PreToolUse"}


def test_allow_is_silent(repo):
    result = run_wrapper(repo.root, payload(repo, "Read", {"file_path": str(repo.root / "README.md")}))
    assert result.returncode == 0
    assert result.stdout == ""


def test_deny_emits_hook_json(repo):
    result = run_wrapper(repo.root, payload(repo, "Bash", {"command": "cat a/x.csv|head"}))
    assert result.returncode == 0
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "recall guard [suffix]" in out["permissionDecisionReason"]
    assert "docs/export.header.txt" in out["permissionDecisionReason"]


def test_denial_is_audited_without_payload(repo):
    run_wrapper(repo.root, payload(repo, "Bash", {"command": "cat secret-looking/x.csv"}))
    log = (repo.root / "local" / "sealed" / "guard.log").read_text(encoding="utf-8")
    entry = json.loads(log.splitlines()[0])
    assert entry["rule"] == "suffix"
    assert "cat" not in log


def _copy_guard(tmp_path):
    dest = tmp_path / "g"
    shutil.copytree(GUARD_DIR, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def test_wrapper_fails_closed_when_guard_crashes(repo, tmp_path):
    guard = _copy_guard(tmp_path)
    (guard / "guard.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    result = run_wrapper(repo.root, payload(repo, "Read", {"file_path": "x"}), guard)
    assert result.returncode == 2
    assert "fail closed" in result.stderr


def test_wrapper_fails_closed_when_guard_missing(repo, tmp_path):
    guard = _copy_guard(tmp_path)
    (guard / "guard.py").unlink()
    result = run_wrapper(repo.root, payload(repo, "Read", {"file_path": "x"}), guard)
    assert result.returncode == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_core.py tests/guard/test_guard_e2e.py -q`
Expected: FAIL (`ModuleNotFoundError`/missing `core`, missing `run-guard.sh`)

- [ ] **Step 3: Implement `core.py`**

`tools/guard/recall_guard/core.py`:

```python
"""Hook decision logic and entry points."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import bashcheck
from .config import HEADER_REL, load_config
from .lint import HINT, check_staged, check_text
from .names import data_suffix, protected_string
from .policy import PROTECTED_MSG, Context, Denial, suffix_message, under
from .store import Ledger, log_denial

GUARD_DIR = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "guard.py",
    "run-guard.sh",
    "recall_guard/core.py",
    "recall_guard/policy.py",
    "recall_guard/bashcheck.py",
)

BASH_LIKE = frozenset({"Bash", "Monitor"})
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit", "Glob", "Grep", "LS"})
WRITERS = frozenset({"Edit", "Write", "NotebookEdit"})
PROMPT_TOOLS = frozenset({"Agent", "Task", "Workflow", "SendMessage"})
PATHISH_KEYS = (
    "file_path", "file_paths", "filePath", "path", "paths", "scriptPath", "root", "files",
    "from", "notebook_path",
)
RG_DATA_TYPES = frozenset({"csv", "tsv", "parquet", "jsonl"})

AIRLOCK_WINDOW_MSG = (
    "Airlock window is open: no AI assistance is allowed until a human closes it "
    "(tools/guard/airlock close, run in a normal terminal)."
)


def _strings(value, depth: int = 0):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict) and depth < 3:
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif isinstance(value, (list, tuple)) and depth < 3:
        for item in value:
            yield from _strings(item, depth + 1)


def _text_rules(cfg, text) -> Denial | None:
    if not isinstance(text, str):
        return None
    suffix = data_suffix(text)
    if suffix:
        return Denial("suffix", suffix_message(cfg, suffix), suffix)
    hit = protected_string(text, cfg)
    if hit:
        return Denial("protected-ref", PROTECTED_MSG, hit)
    return None


def _lint_write(ctx: Context, tool: str, tin: dict, target: Path) -> Denial | None:
    cfg = ctx.cfg
    if not under(target, cfg.root):
        return None
    rel = target.relative_to(cfg.root).as_posix()
    if tool == "Write":
        new = tin.get("content")
        try:
            old = target.read_text(encoding="utf-8")
        except OSError:
            old = ""
    else:
        old, new = tin.get("old_string"), tin.get("new_string")
    findings = check_text(rel, str(old or ""), str(new or ""))
    if not findings:
        return None
    first = findings[0]
    return Denial(
        "lint",
        f"{first.path}:{first.line} writes output outside the sealed helper "
        f"({first.rule}). {HINT}",
        rel,
    )


def _file_tool(ctx: Context, tool: str, tin: dict) -> Denial | None:
    cfg = ctx.cfg
    writer = tool in WRITERS
    target = None
    for field in ("file_path", "notebook_path", "path"):
        value = tin.get(field)
        if not isinstance(value, str) or not value:
            continue
        if writer and not cfg.dev_mode:
            denial = ctx.self_protect_check(value)
            if denial:
                return denial
        denial = ctx.check_path(value, write=writer)
        if denial:
            return denial
        if writer and field != "path":
            target = ctx.lexical(value)

    if tool == "Glob":
        denial = _text_rules(cfg, tin.get("pattern"))
        if denial:
            return denial
    if tool == "Grep":
        denial = _text_rules(cfg, tin.get("glob"))
        if denial:
            return denial
        if str(tin.get("type") or "").lower() in RG_DATA_TYPES:
            return Denial("suffix", suffix_message(cfg, "data-type search"), "type")

    if target is not None:
        if tool in ("Write", "Edit"):
            denial = _lint_write(ctx, tool, tin, target)
            if denial:
                return denial
        ctx.ledger.record_new_file(target)
    return None


def _generic(ctx: Context, tin: dict) -> Denial | None:
    for key in PATHISH_KEYS:
        for text in _strings(tin.get(key)):
            if text and len(text) < 4096 and "\n" not in text:
                denial = ctx.check_path(text)
                if denial:
                    return denial
    return None


def decide(cfg, payload: dict) -> Denial | None:
    tool = payload.get("tool_name", "") or ""
    tin = payload.get("tool_input")
    if not isinstance(tin, dict):
        tin = {}
    if cfg.airlock_marker.exists():
        return Denial("airlock", AIRLOCK_WINDOW_MSG)
    ctx = Context(cfg, payload.get("cwd"), str(payload.get("session_id") or ""))
    if tool in BASH_LIKE:
        return bashcheck.analyse(ctx, str(tin.get("command") or ""))
    if tool in FILE_TOOLS:
        return _file_tool(ctx, tool, tin)
    if tool in PROMPT_TOOLS:
        hit = protected_string(json.dumps(tin), cfg)
        if hit:
            return Denial(
                "protected-ref",
                "Subagent and workflow prompts must not name protected locations: they are "
                "AI readers too.",
                hit,
            )
    return _generic(ctx, tin)


def run_payload(raw: str, cfg) -> tuple:
    """(tool name, Denial or None). Never raises: a guard bug denies the call."""
    try:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except ValueError:
        if data_suffix(raw) or protected_string(raw, cfg):
            return "", Denial(
                "unparseable",
                "The guard could not parse this call and it mentions protected data.",
            )
        return "", None
    tool = str(payload.get("tool_name", ""))
    try:
        return tool, decide(cfg, payload)
    except Exception as exc:  # fail closed on a guard bug, for this call only
        return tool, Denial(
            "internal-error",
            f"The guard failed on this call ({type(exc).__name__}). Denied to fail safe; a "
            "human can run `python3 tools/guard/guard.py --selfcheck` and check the audit log.",
        )


def emit_deny(denial: Denial) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"recall guard [{denial.rule}]: {denial.reason}",
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def main(argv: list) -> int:
    cfg = load_config()
    if "--selfcheck" in argv:
        return cmd_selfcheck(cfg)
    if "--explain" in argv:
        return cmd_explain(cfg, argv)
    if "--lint-staged" in argv:
        return cmd_lint_staged(cfg)
    tool, denial = run_payload(sys.stdin.read(), cfg)
    if denial:
        log_denial(cfg, tool, denial.rule, denial.path)
        emit_deny(denial)
    return 0


# Placeholders replaced in Task 9.
def cmd_selfcheck(cfg) -> int:
    return 0


def cmd_explain(cfg, argv: list) -> int:
    return 0


def cmd_lint_staged(cfg) -> int:
    return 0


__all__ = ["decide", "run_payload", "emit_deny", "main", "Ledger", "HEADER_REL", "check_staged",
           "subprocess", "GUARD_DIR", "REQUIRED_FILES"]
```

(The `__all__` and placeholder block exist only so Task 8 is self-contained; Task 9 replaces the placeholders and drops the unused imports. Do not leave them.)

- [ ] **Step 4: Implement the entry scripts**

`tools/guard/guard.py`:

```python
#!/usr/bin/env python3
"""PreToolUse hook entry for the recall client-data guard (stdlib only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall_guard.core import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

`tools/guard/run-guard.sh`:

```bash
#!/usr/bin/env bash
# Fail-closed wrapper around guard.py: a crash, a timeout or a missing file denies the call
# (exit 2) instead of silently allowing it.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="$here/guard.py"

fail() {
    echo "recall guard: $1 - denying (fail closed). A human can run: python3 tools/guard/guard.py --selfcheck" >&2
    exit 2
}

[ -f "$guard" ] || fail "guard.py missing"
command -v python3 >/dev/null 2>&1 || fail "python3 missing"

runner=()
command -v timeout >/dev/null 2>&1 && runner=(timeout 8)

out="$(${runner[@]+"${runner[@]}"} python3 "$guard" "$@")"
rc=$?
[ "$rc" -eq 0 ] || fail "guard exited with status $rc"
[ -z "$out" ] || printf '%s\n' "$out"
exit 0
```

```bash
chmod +x tools/guard/run-guard.sh tools/guard/guard.py
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/guard -q`
Expected: all pass. The e2e tests shell out to `bash tools/guard/run-guard.sh` with the system `python3`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard tests/guard
git commit -m "feat(guard): hook dispatch for all tools, entry script and fail-closed wrapper" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Self-check, `--explain` and `--lint-staged`

**Files:**
- Modify: `tools/guard/recall_guard/core.py` (replace the placeholder block and the trailing `__all__`)
- Test: `tests/guard/test_guard_selfcheck.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import subprocess

from recall_guard import core

from .conftest import GUARD_DIR


def test_selfcheck_reports_missing_registration_and_hookspath(cfg):
    problems = core.selfcheck(cfg)
    assert any("not registered" in p for p in problems)
    assert any("core.hooksPath" in p for p in problems)


def test_selfcheck_is_clean_when_everything_is_in_place(cfg, repo):
    repo.write(
        ".claude/settings.json",
        json.dumps({"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [
            {"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/tools/guard/run-guard.sh'}]}]}}),
    )
    repo.git("config", "core.hooksPath", ".githooks")
    assert core.selfcheck(cfg) == []


def test_selfcheck_flags_missing_header_and_open_window(cfg, repo):
    (repo.root / "docs" / "export.header.txt").unlink()
    cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
    cfg.airlock_marker.write_text("open", encoding="utf-8")
    problems = core.selfcheck(cfg)
    assert any("export.header.txt" in p for p in problems)
    assert any("airlock window is open" in p for p in problems)


def test_explain_text(cfg, repo):
    repo.write("notes/x.txt")
    assert core.explain(cfg, str(repo.root / "src" / "app.py"), cwd=repo.root) == "ALLOW"
    out = core.explain(cfg, str(repo.root / "notes" / "x.txt"), cwd=repo.root)
    assert out.startswith("DENY [untracked]")


def test_cli_explain_and_lint_staged(repo):
    env = {"CLAUDE_PROJECT_DIR": str(repo.root), "PATH": "/usr/bin:/bin"}
    explain = subprocess.run(
        ["python3", str(GUARD_DIR / "guard.py"), "--explain", "src/app.py"],
        capture_output=True, text=True, env=env, cwd=repo.root,
    )
    assert explain.stdout.strip() == "ALLOW"
    repo.write("src/m.py", 'open(p, "w")\n', track=True)
    lint = subprocess.run(
        ["python3", str(GUARD_DIR / "guard.py"), "--lint-staged"],
        capture_output=True, text=True, env=env, cwd=repo.root,
    )
    assert lint.returncode == 1
    assert "src/m.py:1: [open-write]" in lint.stdout
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_selfcheck.py -q`
Expected: FAIL (`core` has no `selfcheck`/`explain` with these signatures)

- [ ] **Step 3: Implement**

In `core.py`, delete the `# Placeholders replaced in Task 9.` block (the three stub functions) and the trailing `__all__`, then add:

```python
def selfcheck(cfg) -> list:
    """Human-readable problems with the guard installation (empty list = healthy)."""
    problems = []
    for rel in REQUIRED_FILES:
        if not (GUARD_DIR / rel).exists():
            problems.append(f"guard file missing: tools/guard/{rel}")
    try:
        settings = json.loads((cfg.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    registered = "run-guard.sh" in json.dumps(settings.get("hooks", {}).get("PreToolUse", []))
    if not registered:
        problems.append("hook not registered in .claude/settings.json (PreToolUse)")
    if cfg.header_line() is None:
        problems.append(
            f"{HEADER_REL} missing or empty: agents have no export schema to read instead"
        )
    hooks_path = subprocess.run(
        ["git", "-C", str(cfg.root), "config", "core.hooksPath"], capture_output=True, text=True
    ).stdout.strip()
    if hooks_path != ".githooks":
        problems.append("core.hooksPath is not .githooks: run `make guard-install`")
    if cfg.airlock_marker.exists():
        problems.append("airlock window is open: every tool call will be denied")
    Ledger.cleanup(cfg)
    return problems


def explain(cfg, path: str, cwd=None) -> str:
    denial = Context(cfg, cwd=cwd, session_id="explain").check_path(path)
    return "ALLOW" if denial is None else f"DENY [{denial.rule}] {denial.reason}"


def cmd_selfcheck(cfg) -> int:
    problems = selfcheck(cfg)
    if problems:
        text = "recall guard self-check found problems:\n- " + "\n- ".join(problems)
        json.dump(
            {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
            sys.stdout,
        )
        sys.stdout.write("\n")
        print(text, file=sys.stderr)
    return 0


def cmd_explain(cfg, argv: list) -> int:
    index = argv.index("--explain")
    if index + 1 >= len(argv):
        print("usage: guard.py --explain <path>", file=sys.stderr)
        return 2
    print(explain(cfg, argv[index + 1], cwd=Path.cwd()))
    return 0


def cmd_lint_staged(cfg) -> int:
    findings = check_staged(cfg.root)
    for f in findings:
        print(f"{f.path}:{f.line}: [{f.rule}] {f.text}")
    if findings:
        print(HINT, file=sys.stderr)
    return 1 if findings else 0
```

Remove now-unused imports if ruff reports them (`Ledger` stays — `selfcheck` uses it).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard -q`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard tests/guard
git commit -m "feat(guard): selfcheck, explain and staged-lint commands" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Airlock window CLI

**Files:**
- Create: `tools/guard/recall_guard/airlock.py`, `tools/guard/airlock`
- Test: `tests/guard/test_guard_airlock.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import subprocess

from recall_guard import airlock

from .conftest import GUARD_DIR


def test_open_close_status(cfg, capsys):
    assert not airlock.is_open(cfg)
    assert airlock.main(["open"], cfg) == 0
    assert airlock.is_open(cfg)
    assert airlock.main(["status"], cfg) == 0
    assert "OPEN" in capsys.readouterr().out
    assert airlock.main(["close"], cfg) == 0
    assert not airlock.is_open(cfg)
    airlock.main(["status"], cfg)
    assert "closed" in capsys.readouterr().out


def test_close_when_already_closed_is_fine(cfg):
    assert airlock.main(["close"], cfg) == 0


def test_bad_usage(cfg):
    assert airlock.main([], cfg) == 2
    assert airlock.main(["explode"], cfg) == 2


def test_cli_script_toggles_marker(repo):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}
    run = lambda arg: subprocess.run(  # noqa: E731
        ["python3", str(GUARD_DIR / "airlock"), arg], capture_output=True, text=True, env=env
    )
    assert run("open").returncode == 0
    assert (repo.root / "local" / "airlock.open").exists()
    assert run("close").returncode == 0
    assert not (repo.root / "local" / "airlock.open").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_airlock.py -q`
Expected: FAIL (`ModuleNotFoundError: ... airlock`)

- [ ] **Step 3: Implement**

`tools/guard/recall_guard/airlock.py`:

```python
"""Airlock window marker: while it exists, the guard denies every tool call."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import load_config

USAGE = "usage: airlock open|close|status"


def is_open(cfg) -> bool:
    return cfg.airlock_marker.exists()


def main(argv: list, cfg=None) -> int:
    cfg = cfg or load_config()
    command = argv[0] if argv else ""
    if command == "open":
        cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cfg.airlock_marker.write_text(f"opened {stamp}\n", encoding="utf-8")
        print("airlock window OPEN: all AI tool calls in this repo are denied until you close it")
        return 0
    if command == "close":
        cfg.airlock_marker.unlink(missing_ok=True)
        print("airlock window closed: AI tool calls are allowed again")
        return 0
    if command == "status":
        print("airlock window OPEN" if is_open(cfg) else "airlock window closed")
        return 0
    print(USAGE)
    return 2
```

`tools/guard/airlock`:

```python
#!/usr/bin/env python3
"""Open or close the airlock window. Run it yourself in a normal terminal."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall_guard.airlock import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```bash
chmod +x tools/guard/airlock
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard -q`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add tools/guard tests/guard
git commit -m "feat(guard): airlock window CLI and marker" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Sealed helper and release gate

**Files:**
- Create: `src/recall/sealed.py`, `tools/guard/recall_guard/release.py`, `tools/guard/export_aggregate.py`
- Test: `tests/guard/test_guard_sealed.py`, `tests/guard/test_guard_release.py`

- [ ] **Step 1: Write the failing tests**

`tests/guard/test_guard_sealed.py`:

```python
import logging

import pytest
from recall import sealed
from recall_guard.config import SEALED_MARKER


def test_marker_name_matches_the_guard():
    assert sealed.SEALED_MARKER == SEALED_MARKER


def test_sealed_path_creates_marked_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_SEALED_ROOT", str(tmp_path / "sealed"))
    path = sealed.sealed_path("run1/report.json")
    assert path == tmp_path / "sealed" / "run1" / "report.json"
    assert (tmp_path / "sealed" / SEALED_MARKER).exists()
    assert (tmp_path / "sealed" / "run1" / SEALED_MARKER).exists()


@pytest.mark.parametrize("name", ["../escape", "/abs/path", ""])
def test_sealed_path_rejects_escapes(tmp_path, monkeypatch, name):
    monkeypatch.setenv("RECALL_SEALED_ROOT", str(tmp_path / "sealed"))
    with pytest.raises(ValueError):
        sealed.sealed_path(name)


def test_sealed_logger_writes_into_sealed_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_SEALED_ROOT", str(tmp_path / "sealed"))
    log = sealed.sealed_logger("profiler-detail")
    log.info("E_SCHEMA at $.a.b")
    for handler in log.handlers:
        handler.flush()
    text = (tmp_path / "sealed" / "profiler-detail.log").read_text(encoding="utf-8")
    assert "E_SCHEMA at $.a.b" in text
    assert log.propagate is False
    assert len(sealed.sealed_logger("profiler-detail").handlers) == 1  # no duplicate handlers
    logging.getLogger("recall.sealed.profiler-detail").handlers.clear()
```

`tests/guard/test_guard_release.py`:

```python
import json
import subprocess
import os

import pytest
from recall_guard import release

from .conftest import GUARD_DIR


def test_validate_accepts_numbers_bools_nulls_and_lists():
    data = {"rows": 10, "rate": 0.5, "ok": True, "gap": None, "hist": [1, 2, 3],
            "by_band": {"a": 1, "b": 2}}
    assert release.validate(data) == []


def test_validate_rejects_strings_without_echoing_them():
    errors = release.validate({"note": "Mueller GmbH ticket 4711"})
    assert errors == ["E_STRING at $.note"]
    assert "Mueller" not in " ".join(errors)


def test_validate_rejects_value_like_keys_without_echoing_them():
    errors = release.validate({"hist": {"Mueller GmbH": 3}})
    assert errors == ["E_KEY at $.hist.<key#0>"]


def test_validate_rejects_nonfinite_and_depth_and_length():
    assert release.validate({"x": float("nan")}) == ["E_NONFINITE at $.x"]
    deep = cur = {}
    for _ in range(10):
        cur["a"] = {}
        cur = cur["a"]
    assert any(e.startswith("E_DEPTH") for e in release.validate(deep))
    assert release.validate({"xs": [0] * 10_001}) == ["E_LIST_LENGTH at $.xs"]


def test_export_moves_sealed_json_to_released(cfg):
    cfg.sealed_root.mkdir(parents=True)
    (cfg.sealed_root / "gate_run_12.json").write_text('{"rows": 3}', encoding="utf-8")
    assert release.export(cfg, "gate_run_12") == []
    out = cfg.released_dirs[0] / "gate_run_12.json"
    assert json.loads(out.read_text(encoding="utf-8")) == {"rows": 3}


def test_export_refuses_bad_name_missing_and_invalid(cfg):
    cfg.sealed_root.mkdir(parents=True)
    assert release.export(cfg, "../x") == ["E_NAME"]
    assert release.export(cfg, "nope") == ["E_MISSING"]
    (cfg.sealed_root / "bad.json").write_text("{", encoding="utf-8")
    assert release.export(cfg, "bad") == ["E_JSON"]
    (cfg.sealed_root / "txt.json").write_text('{"a": "b"}', encoding="utf-8")
    assert release.export(cfg, "txt") == ["E_STRING at $.a"]
    assert not (cfg.released_dirs[0] / "txt.json").exists()


def test_cli(repo):
    sealed = repo.root / "local" / "sealed"
    sealed.mkdir(parents=True)
    (sealed / "m.json").write_text('{"n": 1}', encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}
    ok = subprocess.run(["python3", str(GUARD_DIR / "export_aggregate.py"), "m"],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0
    assert (repo.root / "local" / "released" / "m.json").exists()
    bad = subprocess.run(["python3", str(GUARD_DIR / "export_aggregate.py"), "missing"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode == 4
    assert "E_MISSING" in bad.stdout
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_sealed.py tests/guard/test_guard_release.py -q`
Expected: FAIL (`ModuleNotFoundError: recall.sealed` / `release`)

- [ ] **Step 3: Implement the sealed helper**

`src/recall/sealed.py`:

```python
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


def sealed_root() -> Path:
    override = os.environ.get("RECALL_SEALED_ROOT")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / "local" / "sealed"


def _mark(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / SEALED_MARKER
    if not marker.exists():
        marker.write_text("sealed: never read from an AI session\n", encoding="utf-8")


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
```

- [ ] **Step 4: Implement the release gate**

`tools/guard/recall_guard/release.py`:

```python
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


def validate(obj, path: str = "$", depth: int = 0) -> list:
    if depth > MAX_DEPTH:
        return [f"E_DEPTH at {path}"]
    if obj is None or isinstance(obj, (bool, int)):
        return []
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
    except ValueError:
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
        print("usage: export_aggregate.py <name>   (reads <sealed root>/<name>.json)")
        return 4
    cfg = load_config()
    errors = export(cfg, argv[0])
    if errors:
        for error in errors:
            print(error)
        return 4
    print(f"OK released {argv[0]}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`tools/guard/export_aggregate.py`:

```python
#!/usr/bin/env python3
"""Release an aggregate (numbers only) from the sealed root into local/released/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall_guard.release import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```bash
chmod +x tools/guard/export_aggregate.py
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/guard -q`
Expected: all pass

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tools tests/guard src/recall/sealed.py && uv run ruff format tools tests/guard src/recall/sealed.py
git add src/recall/sealed.py tools/guard tests/guard
git commit -m "feat(guard): recall.sealed output helper and numbers-only release gate" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Pre-commit hook and Makefile targets

**Files:**
- Create: `.githooks/pre-commit`
- Modify: `Makefile` (the `.PHONY` line, plus two appended targets)
- Test: `tests/guard/test_guard_precommit.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import shutil
import subprocess

from .conftest import GUARD_DIR

HOOK = GUARD_DIR.parents[1] / ".githooks" / "pre-commit"


def test_precommit_blocks_unsealed_output_and_passes_clean_commits(repo):
    hooks = repo.root / ".githooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "pre-commit")
    (repo.root / "tools").mkdir()
    shutil.copytree(GUARD_DIR, repo.root / "tools" / "guard",
                    ignore=shutil.ignore_patterns("__pycache__"))
    repo.git("config", "core.hooksPath", ".githooks")
    repo.git("config", "user.email", "t@example.com")
    repo.git("config", "user.name", "t")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}

    repo.write("src/ok.py", "x = 1\n", track=True)
    ok = subprocess.run(["git", "-C", str(repo.root), "commit", "-m", "clean"],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr + ok.stdout

    repo.write("src/leak.py", 'open(p, "w")\n', track=True)
    bad = subprocess.run(["git", "-C", str(repo.root), "commit", "-m", "leaky"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode != 0
    # git forwards a hook's stdout to stderr, so accept either stream
    assert "src/leak.py:1: [open-write]" in bad.stdout + bad.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/guard/test_guard_precommit.py -q`
Expected: FAIL (`FileNotFoundError` on `.githooks/pre-commit`)

- [ ] **Step 3: Implement**

`.githooks/pre-commit`:

```sh
#!/usr/bin/env sh
# Rejects staged data files and new code that writes outputs or logs outside recall.sealed.
# Enable once per clone with: make guard-install
root="$(git rev-parse --show-toplevel)"
exec python3 "$root/tools/guard/guard.py" --lint-staged
```

```bash
chmod +x .githooks/pre-commit
```

Edit `Makefile`: change the `.PHONY` line to

```
.PHONY: db-up db-down db-reset migrate test lint local-dirs check-clean window-a-rehearsal window-b-rehearsal window-d-rehearsal guard-install guard-test
```

and append the targets (tabs matter):

```bash
printf '\nguard-install:\n\tgit config core.hooksPath .githooks\n\nguard-test:\n\tuv run pytest tests/guard\n' >> Makefile
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/guard -q && make -n guard-install guard-test`
Expected: tests pass; `make -n` prints the two recipes.

- [ ] **Step 5: Commit**

```bash
uv run ruff check tools tests/guard && uv run ruff format tools tests/guard
git add .githooks Makefile tests/guard
git commit -m "feat(guard): pre-commit lint hook and make guard-install/guard-test" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Docs, agent rules and gitignore

**Files:**
- Create: `CLAUDE.md` (if it already exists, append the section instead)
- Modify: `.gitignore`, `docs/airlock-runbook.md`
- Human step: `docs/export.header.txt`

- [ ] **Step 1: Agent rules**

Check first: `ls CLAUDE.md`. If absent, create it with the content below; if present, append everything from `## Client data` onward.

```markdown
# recall — notes for AI agents

## Client data (hard rules, enforced by tools/guard)

1. Never read, list, glob, grep or name the real ticket export, any data file (`.csv`,
   `.tsv`, `.parquet`, `.jsonl`, `.xlsx`, `.npy` and friends) or anything under `local/sealed/`
   or `local/quarantine/`. The guard denies these; do not look for a way around it.
2. The export's structure is in `docs/export.header.txt` (one line, columns only). Read that
   when you need the schema.
3. Logs, errors and reports never contain row values. Errors carry a code and a schema path
   only.
4. All file and log output from code that can see real rows goes through `recall.sealed`
   (`sealed_path`, `sealed_logger`). New output locations are created with that helper, never
   ad hoc. The guard's lint will refuse a bare `open(..., "w")`, `FileHandler`, `to_csv`
   and similar in `src/`, `profiler/`, `insight/` and `fixtures/`; use `# guard: ok(<reason>)`
   only for synthetic or non-client data.
5. Aggregates (counts, rates, metrics — numbers only) leave the sealed root through
   `python3 tools/guard/export_aggregate.py <name>`, which writes to `local/released/`.
   Only released aggregates and `local/artifacts/` may be read.
6. You may read git-tracked files, `local/released/`, `local/artifacts/`, `local/fixtures/`,
   your scratchpad and files you created this session. A new file of yours that is not
   readable yet: `git add -N <path>`.
7. The guard, its registration and the airlock marker are not yours to change. If the guard is
   wrong, tell the human; they can maintain it with `RECALL_GUARD_DEV=1`.
8. While the airlock window is open every tool call is denied. That is expected.

To see why a path is allowed or denied: `python3 tools/guard/guard.py --explain <path>`.
```

- [ ] **Step 2: Gitignore**

Append to `.gitignore`:

```
# Per-person guard settings (extra allowed / protected paths)
.claude/guard.local.json
```

(`local/` is already ignored, which covers `local/sealed/`, `local/released/` and the airlock marker.)

- [ ] **Step 3: Runbook**

Open `docs/airlock-runbook.md`. In **Phase 0**, add this checklist item before the first existing item:

```markdown
- [ ] `make guard-install` once per clone, then `tools/guard/airlock status` shows
      "closed". **Open the window yourself, in a normal terminal, when the real CSV lands on
      the box: `tools/guard/airlock open`.** While it is open the guard denies every AI tool
      call in this repo. Close it only after the real CSV is deleted and verified gone:
      `tools/guard/airlock close`.
```

Also, in the paragraph that explains what an AI later reads, add one sentence: "Aggregates move from the sealed root to `local/released/` through `tools/guard/export_aggregate.py`, which refuses anything but numbers."

- [ ] **Step 4: Human step — the header file (do NOT delegate to an agent)**

The user creates `docs/export.header.txt` themselves: a single line, the first line of the real export, nothing else. Then:

```bash
git add docs/export.header.txt
```

Until it exists, denial messages simply omit the pointer and `--selfcheck` reports it.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .gitignore docs/airlock-runbook.md
git commit -m "docs(guard): agent rules, airlock window steps and local settings ignore" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Register the guard, harden settings, verify

**Files:**
- Modify: `.claude/settings.json`

This is deliberately last. Once the registration is live (next session), agents can no longer edit `tools/guard/` or `.claude/settings*.json`.

- [ ] **Step 1: Full test and lint run**

```bash
uv run pytest tests/guard -q
uv run ruff check tools tests/guard src/recall/sealed.py
uv run ruff format --check tools tests/guard src/recall/sealed.py
uv run pytest -q
```
Expected: everything green. If the full suite shows failures unrelated to the guard, report them but do not fix them here.

- [ ] **Step 2: Dry-run the policy against real paths**

```bash
python3 tools/guard/guard.py --explain src/recall/sealed.py
python3 tools/guard/guard.py --explain local/artifacts/gate_report.overnight.json
python3 tools/guard/guard.py --explain local/artifacts/overnight-window-b.log
python3 tools/guard/guard.py --explain local/artifacts/profile_report.md
python3 tools/guard/guard.py --explain local/fixtures/cache
python3 tools/guard/guard.py --explain local/sealed
```
Expected: the first five `ALLOW`, the last `DENY [sealed]`. A `DENY [content]` on an existing released artifact (for example a comma-delimited log) is a false positive: tell the user, who can either move that file or add it to `.claude/guard.local.json` under `extra_allowed`.

- [ ] **Step 3: Register the hook and add the static rules**

Replace `.claude/settings.json` with the existing content plus the new keys (keep every existing entry):

```json
{
  "permissions": {
    "deny": [
      "Read(./local/quarantine/**)",
      "Read(//data/recall-quarantine/**)",
      "Read(//<path-to-export-dir>/**)",
      "Read(**/*.syn)",
      "Read(**/*.csv)",
      "Read(**/*.tsv)",
      "Read(**/*.parquet)",
      "Read(**/*.jsonl)",
      "Read(./local/sealed/**)",
      "Bash(cat ./local/quarantine/*)",
      "Bash(head ./local/quarantine/*)",
      "Bash(tail ./local/quarantine/*)",
      "Bash(less ./local/quarantine/*)",
      "Bash(grep * ./local/quarantine/*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/tools/guard/run-guard.sh",
            "timeout": 10,
            "statusMessage": "recall guard"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/tools/guard/run-guard.sh --selfcheck",
            "timeout": 10
          }
        ]
      }
    ]
  },
  "sandbox": {
    "enabled": false,
    "filesystem": {
      "denyRead": [
        "./local/quarantine",
        "./local/sealed",
        "/data/recall-quarantine",
        "<path-to-export-dir>"
      ],
      "denyWrite": [
        "./tools/guard",
        "./.claude/settings.json",
        "./.githooks"
      ],
      "allowWrite": [
        "~/.cache/uv"
      ]
    },
    "network": {
      "allowLocalBinding": true,
      "allowAllUnixSockets": true,
      "allowedDomains": [
        "localhost",
        "127.0.0.1"
      ]
    }
  }
}
```

`sandbox.enabled` stays `false` in this commit; Step 5 turns it on after verification.

- [ ] **Step 4: Commit the registration**

```bash
git add .claude/settings.json
git commit -m "feat(guard): register the recall guard hook and add static deny rules" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Human verification checkpoint (the user runs these; an agent cannot)**

Start a **fresh** Claude Code session in this repo, with `make guard-install` run once. Check:

1. The SessionStart self-check prints nothing (or tells you exactly what is missing).
2. Ask the agent to read `local/artifacts/gate_report.overnight.json` → allowed.
3. Ask it to `cat` any data-suffix file, to glob for them, and to read something under `local/sealed/` → each denied with a pointer to `docs/export.header.txt` or the sealed message.
4. Ask it to create `scratch/x.py`, then read it back → allowed; ask it to read an untracked file you made yourself → denied, with the `git add -N` hint.
5. Ask it to add a bare `open(p, "w")` to a file under `src/` → denied with the `recall.sealed` hint.
6. Ask it to edit `tools/guard/guard.py` → denied (self-protect).
7. In a normal terminal: `tools/guard/airlock open`; any tool call in the session is now denied; `tools/guard/airlock close` restores it.
8. Check `local/sealed/guard.log` (read it yourself) shows one line per denial and no command text.
9. Turn the sandbox on: set `"enabled": true` in `.claude/settings.json` (start `claude` with `RECALL_GUARD_DEV=1` or edit the file in your own editor). Then run `make test lint` and `infra/profiler/window.sh status` inside a session. If ssh, uv, docker or podman break, add them under `sandbox.excludedCommands` (check the Claude Code sandbox docs for the exact key) rather than disabling the sandbox, and re-test. Confirm the `denyWrite` key is accepted (the session should not warn about an unknown setting).

If any of 1-8 fails, stop and report; do not weaken a rule to make a check pass.

- [ ] **Step 6: Record the result**

Append a short entry to `docs/STATE.md` (what the guard enforces, the five-line summary of the rules, and the `RECALL_GUARD_DEV=1` maintenance route), then:

```bash
git add docs/STATE.md
git commit -m "docs(state): record the recall guard and how to maintain it" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage**

| Spec section | Task |
| --- | --- |
| Architecture / files | 0-12 (layout under "File structure") |
| Read policy (allowlist, ledger, sealed marker, Bash tokens) | 3, 5, 6 |
| Name and extension rules | 2, 5, 8 (Glob/Grep filters) |
| Content sniffing | 4, 5 |
| Bash handling (tokens, scripts, extractors, sandbox) | 6, 14 |
| Sealed outputs, release gate | 11 |
| Write-side rules (CLAUDE.md, lint, pre-commit, data-suffix writes) | 7, 8, 12, 13 |
| Header sidecar | 5 (hint in messages), 13 (human step), 9 (selfcheck) |
| Airlock window lock | 8 (check first in `decide`), 10, 6 (CLI denial) |
| Audit log | 3, 8 |
| Failure handling (wrapper, SessionStart check, unparseable) | 8, 9 |
| Testing (bypass cases, fail-closed, false positives) | tests in every task |
| Open items (fixtures dir, local allows, pre-commit wiring) | fixtures = `local/fixtures`; broad allows left (deny wins); `make guard-install` + selfcheck warning |

**Placeholder scan:** none; the only transitional code is the labelled placeholder block in Task 8, replaced in Task 9 Step 3.

**Type consistency:** `Denial(rule, reason, path)`, `Context.check_path(value, write=, base=)`, `Context.self_protect_check`, `Context.lexical(value, base)`, `Ledger.record_new_file/contains/add/cleanup`, `ensure_sealed(directory, cfg)`, `log_denial(cfg, tool, rule, path)`, `sniff(path, header, large_check=)`, `analyse(ctx, command)`, `check_text(rel, old, new)`, `check_staged(root)`, `release.validate/export`, `core.decide/run_payload/selfcheck/explain` are used with the same names and signatures across tasks.

**Known limits (documented, not fixed):** Grep/Glob on a directory that contains sealed zones relies on ripgrep honouring `.gitignore` plus the `permissions.deny` and `denyRead` rules; dynamic file access in code run through an interpreter is only caught by the sandbox; the `sandbox.excludedCommands` and `denyWrite` keys must be confirmed against the installed Claude Code version in Task 14 Step 5.
