import os
import shutil
import subprocess

from .conftest import GUARD_DIR

HOOK = GUARD_DIR.parents[1] / ".githooks" / "pre-commit"


def test_precommit_without_python3_fails_with_a_clear_message(repo, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    result = subprocess.run(
        ["/bin/sh", str(HOOK)],
        capture_output=True,
        text=True,
        cwd=repo.root,
        env={"PATH": str(bin_dir)},
    )
    assert result.returncode == 1
    assert "python3" in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1


def test_precommit_blocks_unsealed_output_and_passes_clean_commits(repo):
    hooks = repo.root / ".githooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "pre-commit")
    (repo.root / "tools").mkdir()
    shutil.copytree(
        GUARD_DIR, repo.root / "tools" / "guard", ignore=shutil.ignore_patterns("__pycache__")
    )
    repo.git("config", "core.hooksPath", ".githooks")
    repo.git("config", "user.email", "t@example.com")
    repo.git("config", "user.name", "t")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}

    repo.write("src/ok.py", "x = 1\n", track=True)
    ok = subprocess.run(
        ["git", "-C", str(repo.root), "commit", "-m", "clean"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert ok.returncode == 0, ok.stderr + ok.stdout

    repo.write("src/leak.py", 'open(p, "w")\n', track=True)
    bad = subprocess.run(
        ["git", "-C", str(repo.root), "commit", "-m", "leaky"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert bad.returncode != 0
    # git forwards a hook's stdout to stderr, so accept either stream
    assert "src/leak.py:1: [open-write]" in bad.stdout + bad.stderr
