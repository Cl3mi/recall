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
