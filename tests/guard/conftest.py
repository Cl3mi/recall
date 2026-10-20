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
