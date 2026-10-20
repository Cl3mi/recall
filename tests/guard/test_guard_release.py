import json
import os
import subprocess

from recall_guard import release

from .conftest import GUARD_DIR


def test_validate_accepts_numbers_bools_nulls_and_lists():
    data = {
        "rows": 10,
        "rate": 0.5,
        "ok": True,
        "gap": None,
        "hist": [1, 2, 3],
        "by_band": {"a": 1, "b": 2},
    }
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


def test_integers_beyond_float_precision_are_rejected():
    assert release.validate({"a": 2**53 - 1, "b": -(2**53 - 1)}) == []
    assert release.validate({"a": 2**53}) == ["E_INT_RANGE at $.a"]
    assert release.validate([-(2**53)]) == ["E_INT_RANGE at $[0]"]
    assert release.validate({"a": 10**40}) == ["E_INT_RANGE at $.a"]
    assert release.validate({"a": True}) == []  # booleans are not integers here


def test_deeply_nested_json_is_a_json_error(cfg):
    (cfg.sealed_root).mkdir(parents=True, exist_ok=True)
    (cfg.sealed_root / "deep.json").write_text("[" * 100000, encoding="utf-8")
    assert release.export(cfg, "deep") == ["E_JSON"]


def test_usage_goes_to_stderr(repo):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}
    result = subprocess.run(
        ["python3", str(GUARD_DIR / "export_aggregate.py")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 4
    assert result.stdout == ""
    assert "usage" in result.stderr


def test_cli(repo):
    sealed = repo.root / "local" / "sealed"
    sealed.mkdir(parents=True)
    (sealed / "m.json").write_text('{"n": 1}', encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.root)}
    ok = subprocess.run(
        ["python3", str(GUARD_DIR / "export_aggregate.py"), "m"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert ok.returncode == 0
    assert (repo.root / "local" / "released" / "m.json").exists()
    bad = subprocess.run(
        ["python3", str(GUARD_DIR / "export_aggregate.py"), "missing"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert bad.returncode == 4
    assert "E_MISSING" in bad.stdout
