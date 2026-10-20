import logging
from pathlib import Path

import pytest
from recall_guard import store
from recall_guard.config import SEALED_MARKER, load_config

from recall import sealed


def test_marker_name_matches_the_guard():
    assert sealed.SEALED_MARKER == SEALED_MARKER


def test_marker_text_matches_the_guard():
    assert sealed.MARKER_TEXT == store._MARKER_TEXT


@pytest.mark.parametrize("override", ["local/other-sealed", "./x/../y/sealed", "~/sealed-home"])
def test_relative_override_resolves_the_same_in_guard_and_helper(monkeypatch, override):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("RECALL_SEALED_ROOT", override)
    guard_view = load_config(root=repo_root, env={"RECALL_SEALED_ROOT": override}).sealed_root
    assert sealed.sealed_root() == guard_view
    if not override.startswith("~"):
        assert guard_view.is_absolute()
        assert repo_root in guard_view.parents


def test_absolute_override_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_SEALED_ROOT", str(tmp_path / "abs"))
    assert sealed.sealed_root() == tmp_path / "abs"


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
