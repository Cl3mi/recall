import json
from pathlib import Path

import pytest
from recall_guard.config import SEALED_MARKER, ConfigError, load_config

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


def test_missing_local_file_means_no_extras(repo):
    cfg = load_config(root=repo.root, env={})
    assert cfg.extra_allowed == ()
    assert len(cfg.protected_dirs) == 3  # sealed, quarantine, /data/recall-quarantine


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        '{"extra_allowed": "abc"}',
        '{"extra_protected": {"a": 1}}',
        '{"extra_protected": [1]}',
        "[]",
        "",
    ],
)
def test_invalid_local_file_raises_config_error(repo, text):
    repo.write(".claude/guard.local.json", text)
    with pytest.raises(ConfigError) as err:
        load_config(root=repo.root, env={})
    assert "{not json" not in str(err.value)  # never echo file content


def test_lenient_load_ignores_invalid_local_file_for_human_tools(repo):
    repo.write(".claude/guard.local.json", "{not json")
    cfg = load_config(root=repo.root, env={}, lenient=True)
    assert cfg.extra_allowed == ()


def test_unreadable_local_path_raises_config_error(repo):
    (repo.root / ".claude" / "guard.local.json").mkdir(parents=True)
    with pytest.raises(ConfigError):
        load_config(root=repo.root, env={})


def test_header_line_is_read_once_per_process(repo):
    cfg = load_config(root=repo.root, env={})
    assert cfg.header_line() == HEADER
    (repo.root / "docs" / "export.header.txt").unlink()  # one hook call = one process
    assert cfg.header_line() == HEADER


def test_closed_zones_are_sealed_root_plus_protected_dirs_without_duplicates(repo):
    cfg = load_config(root=repo.root, env={})
    zones = cfg.closed_zones()
    assert zones[0] == cfg.sealed_root
    assert set(zones) == {cfg.sealed_root, *cfg.protected_dirs}
    assert len(set(zones)) == len(zones)


def test_scratch_dirs_are_deterministic_and_unique(repo):
    cfg = load_config(root=repo.root, env={})
    assert len(set(cfg.scratch_dirs)) == len(cfg.scratch_dirs)
    assert cfg.scratch_dirs == load_config(root=repo.root, env={}).scratch_dirs
    assert cfg.scratch_dirs[0].parent == Path("/tmp")


def test_missing_header_gives_none(repo):
    (repo.root / "docs" / "export.header.txt").unlink()
    assert load_config(root=repo.root, env={}).header_line() is None


def test_marker_name_is_stable():
    assert SEALED_MARKER == ".sealed"
