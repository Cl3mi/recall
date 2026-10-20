import json
import os
import shutil
import subprocess
import time

import pytest

from .conftest import GUARD_DIR


def run_wrapper(repo_root, payload, guard_dir=GUARD_DIR, raw=None, path=None, extra_env=None):
    """Run the real wrapper. raw replaces the JSON payload; path replaces PATH."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo_root), **(extra_env or {})}
    env.pop("RECALL_GUARD_DEV", None)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        ["bash", str(guard_dir / "run-guard.sh")],
        input=json.dumps(payload) if raw is None else raw,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def payload(repo, tool, tool_input):
    return {
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": str(repo.root),
        "session_id": "e2e",
        "hook_event_name": "PreToolUse",
    }


def test_allow_is_silent(repo):
    result = run_wrapper(
        repo.root, payload(repo, "Read", {"file_path": str(repo.root / "README.md")})
    )
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
    assert "secret-looking" not in log  # the denied command's path text is never logged
    assert "x.csv" not in log


def test_invalid_local_config_denies_through_the_wrapper(repo):
    repo.write(".claude/guard.local.json", "{not json")
    result = run_wrapper(
        repo.root, payload(repo, "Read", {"file_path": str(repo.root / "README.md")})
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "[config-error]" in out["permissionDecisionReason"]


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


def test_garbage_payload_is_denied_through_the_wrapper(repo):
    result = run_wrapper(repo.root, None, raw="this is not json")
    assert result.returncode == 0
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "[unparseable]" in out["permissionDecisionReason"]


def test_deeply_nested_payload_is_never_allowed(repo):
    result = run_wrapper(repo.root, None, raw="[" * 100000)
    if result.returncode == 0:
        out = json.loads(result.stdout)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
    else:
        assert result.returncode == 2


def _minimal_path(tmp_path, names):
    bin_dir = tmp_path / "minbin"
    bin_dir.mkdir()
    for name in names:
        (bin_dir / name).symlink_to(shutil.which(name))
    return str(bin_dir)


def test_wrapper_works_without_timeout_on_path(repo, tmp_path):
    path = _minimal_path(tmp_path, ["bash", "python3", "git", "dirname"])
    allowed = run_wrapper(
        repo.root,
        payload(repo, "Read", {"file_path": str(repo.root / "README.md")}),
        path=path,
    )
    assert allowed.returncode == 0
    assert allowed.stdout == ""
    denied = run_wrapper(repo.root, payload(repo, "Bash", {"command": "cat a/x.csv"}), path=path)
    assert denied.returncode == 0
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.skipif(shutil.which("timeout") is None, reason="coreutils timeout is not installed")
def test_wrapper_fails_closed_when_guard_hangs(repo, tmp_path):
    guard = _copy_guard(tmp_path)
    (guard / "guard.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    start = time.monotonic()
    result = run_wrapper(repo.root, payload(repo, "Read", {"file_path": "x"}), guard)
    assert result.returncode == 2
    assert time.monotonic() - start < 15
    assert "fail closed" in result.stderr


def test_wrapper_fails_closed_when_guard_missing(repo, tmp_path):
    guard = _copy_guard(tmp_path)
    (guard / "guard.py").unlink()
    result = run_wrapper(repo.root, payload(repo, "Read", {"file_path": "x"}), guard)
    assert result.returncode == 2
