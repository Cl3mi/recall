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
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": '"$CLAUDE_PROJECT_DIR"/tools/guard/run-guard.sh',
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    )
    repo.git("config", "core.hooksPath", ".githooks")
    assert core.selfcheck(cfg) == []


def test_selfcheck_accepts_registration_in_local_settings(cfg, repo):
    hook = {"hooks": [{"type": "command", "command": "tools/guard/run-guard.sh"}]}
    repo.write(".claude/settings.local.json", json.dumps({"hooks": {"PreToolUse": [hook]}}))
    assert not any("not registered" in p for p in core.selfcheck(cfg))


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
        capture_output=True,
        text=True,
        env=env,
        cwd=repo.root,
    )
    assert explain.stdout.strip() == "ALLOW"
    repo.write("src/m.py", 'open(p, "w")\n', track=True)
    lint = subprocess.run(
        ["python3", str(GUARD_DIR / "guard.py"), "--lint-staged"],
        capture_output=True,
        text=True,
        env=env,
        cwd=repo.root,
    )
    assert lint.returncode == 1
    assert "src/m.py:1: [open-write]" in lint.stdout
