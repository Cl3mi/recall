"""Hardening round 2: self-protection by effect (globs, braces, cd, redirects, symlinks)."""

import os
import shutil
import subprocess

import pytest
from recall_guard import core
from recall_guard.bashcheck import analyse
from recall_guard.config import load_config

from .test_guard_e2e import payload, run_wrapper


def rule(ctx, command):
    denial = analyse(ctx, command)
    return denial.rule if denial else None


@pytest.fixture
def guarded(repo):
    repo.write("tools/guard/guard.py", track=True)
    repo.write("tools/guard/recall_guard/core.py", track=True)
    repo.write(".claude/settings.json", "{}\n", track=True)
    repo.write(".githooks/pre-commit", "#!/bin/sh\n", track=True)
    repo.write("src/recall/sealed.py", "# s\n", track=True)
    return repo


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    (path / ".claude" / "hooks").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    return path


# -- S1/S2: bash effects ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/a/b/ tools/guard/guard.py",
        "sed -i s/a/b/ tools/gu*/guard.py",
        "sed -i s/a/b/ tools/g?ard/guard.py",
        "sed -i s/a/b/ .claude/settings.j*",
        "sed -i s/a/b/ .claude/settings{,x}.json",
        "sed -i s/a/b/ .claude/{settings,other}.json",
        "cd tools && sed -i s/a/b/ guard/guard.py",
        "cd tools/ && echo x >> guard/guard.py",
        "cd tools/guard && echo x > guard.py",
        "pushd tools; sed -i s/a/b/ guard/guard.py",
        "echo x &> tools/guard/guard.py",
        "echo x &>> tools/guard/guard.py",
        "echo x >| tools/guard/guard.py",
        "echo x >> tools/guard/guard.py",
        "echo x > tools/gu*/guard.py",
        "cat <<EOF > tools/guard/guard.py\nx\nEOF",
        "cat <<'EOF'\ntools/guard/guard.py\nEOF",
        "rsync /tmp/a tools/guard/guard.py",
        "tar xf /tmp/a.tar -C tools/guard",
        "curl -o tools/guard/guard.py http://localhost/x",
        "wget -O tools/guard/guard.py http://localhost/x",
        "unzip -o /tmp/a.zip -d tools/guard",
        "mkdir -p tools/guard/new",
        "mv tools /tmp/zz",
        "rm -rf tools",
        "rm -rf .claude",
        "cp /tmp/a .claude/settings.json",
        "touch tools/guard/new.py",
        "install /tmp/a tools/guard/guard.py",
        "ln -s /tmp/a tools/guard/guard.py",
        "dd if=/tmp/a of=tools/guard/guard.py",
        "truncate -s 0 tools/guard/guard.py",
        "patch tools/guard/guard.py x.patch",
        "sponge tools/guard/guard.py",
        "cpio -idm tools/guard",
        "python3 - <<'EOF'\nopen('tools/guard/guard.py','w').write('x')\nEOF",
        "perl -pi -e 's/a/b/' tools/guard/guard.py",
        "python3 <<EOF\nimport os; os.remove('.githooks/pre-commit')\nEOF",
        "echo x > src/recall/sealed.py",
        "echo x > .git/hooks/pre-commit",
        "cp /tmp/a .git/config",
        "rm -r .git/hooks",
    ],
)
def test_mutation_of_self_protected_paths_denied(ctx, guarded, command):
    denial = analyse(ctx, command)
    assert denial is not None, command
    assert denial.rule == "self-protect", (command, denial.rule)


@pytest.mark.parametrize(
    "command",
    [
        "cat tools/guard/guard.py",
        "cat tools/guard/guard.py 2>&1",
        "cat tools/guard/guard.py 2>/dev/null",
        "grep -n x tools/guard/guard.py 2>&1 | head",
        "git log --oneline -- tools/guard",
        "git diff -- tools/guard",
        "uv run ruff check tools/guard",
        "ls tools",
        "cp src/app.py /tmp/x",
        "cp src/app.py ./x.py",
        "mkdir -p scratch/x",
        "echo hello > scratch_out.log",
        "cat .git/config",
        "ls tools && mkdir -p scratch/x",
        "ls tools; rm scratch_x.txt",
        "find tools -name x | wc -l; touch y",
        "git commit -m 'fix tools/guard docs'",
    ],
)
def test_reading_and_unrelated_writes_stay_allowed(ctx, guarded, command):
    assert rule(ctx, command) is None


def test_self_protect_with_unbalanced_quote_fallback(ctx, guarded):
    assert rule(ctx, "echo 'x > tools/guard/guard.py") == "self-protect"


def test_home_settings_and_hooks_are_protected(ctx, guarded, home):
    assert rule(ctx, f"echo x > {home}/.claude/settings.json") == "self-protect"
    assert rule(ctx, "echo x > ~/.claude/settings.local.json") == "self-protect"
    assert rule(ctx, "cp src/app.py ~/.claude/hooks/x") == "self-protect"
    assert rule(ctx, "rm -rf ~/.claude") == "self-protect"
    assert rule(ctx, "cat ~/.claude/settings.json") is None


def test_script_body_naming_self_protected_path_denied_when_untracked(ctx, guarded):
    guarded.write("scripts/tracked.py", "p = 'tools/guard/guard.py'\n", track=True)

    def agent_file(rel, text):  # a file the agent created this session: readable, but unreviewed
        ctx.ledger.record_new_file(guarded.root / rel)
        guarded.write(rel, text)

    agent_file("scratch/evil.py", "open('tools/guard/guard.py', 'w').write('x')\n")
    assert rule(ctx, "python3 scratch/evil.py") == "script-self-protect"
    agent_file("scratch/evil.sh", "echo x > .claude/settings.json\n")
    assert rule(ctx, "bash scratch/evil.sh") == "script-self-protect"
    agent_file("scratch/ok.py", "print(1)\n")
    assert rule(ctx, "python3 scratch/ok.py") is None
    assert rule(ctx, "python3 scripts/tracked.py") is None


def test_dev_mode_lifts_all_of_it(guarded):
    from recall_guard.policy import Context

    dev = load_config(root=guarded.root, env={"RECALL_GUARD_DEV": "1"})
    dctx = Context(dev, cwd=guarded.root, session_id="s")
    assert rule(dctx, "sed -i s/a/b/ tools/gu*/guard.py") is None


# -- S3: symlinks, Write/Edit/NotebookEdit ------------------------------------------------------


def call(cfg, tool, tin):
    return core.decide(
        cfg, {"tool_name": tool, "tool_input": tin, "cwd": str(cfg.root), "session_id": "s1"}
    )


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_write_through_symlinks_to_protected_paths_denied(cfg, guarded, tmp_path, tool):
    field = "notebook_path" if tool == "NotebookEdit" else "file_path"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "gl").symlink_to(guarded.root / "tools" / "guard" / "guard.py")
    (outside / "gdir").symlink_to(guarded.root / "tools" / "guard")
    (guarded.root / "src" / "linkdir").symlink_to(guarded.root / "tools" / "guard")
    for target in (
        outside / "gl",
        outside / "gdir" / "newfile.py",
        guarded.root / "src" / "linkdir" / "guard.py",
        guarded.root / "src" / "linkdir" / "brand_new.py",
    ):
        denial = call(cfg, tool, {field: str(target), "content": "x"})
        assert denial is not None and denial.rule == "self-protect", target


def test_write_to_dangling_symlink_into_protected_dir_denied(cfg, guarded, tmp_path):
    link = tmp_path / "dangling"
    link.symlink_to(guarded.root / "tools" / "guard" / "does_not_exist.py")
    denial = call(cfg, "Write", {"file_path": str(link), "content": "x"})
    assert denial is not None and denial.rule == "self-protect"


def test_write_to_ordinary_file_still_allowed(cfg, guarded, tmp_path):
    assert call(cfg, "Write", {"file_path": str(tmp_path / "ok.txt"), "content": "x"}) is None


# -- S4: hook-process hijack -------------------------------------------------------------------


def test_write_to_git_config_hooks_and_home_settings_denied(cfg, guarded, home):
    for target in (
        guarded.root / ".git" / "config",
        guarded.root / ".git" / "hooks" / "pre-commit",
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        home / ".claude" / "hooks" / "x.sh",
        home / ".local" / "bin" / "python3",
        home / ".local" / "lib" / "python3.14" / "site-packages" / "usercustomize.py",
    ):
        for tool in ("Write", "Edit"):
            denial = call(cfg, tool, {"file_path": str(target), "content": "x"})
            assert denial is not None and denial.rule == "self-protect", (tool, target)


def test_reads_of_git_config_and_home_settings_stay_allowed(cfg, guarded, home):
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert call(cfg, "Read", {"file_path": str(guarded.root / ".git" / "config")}) is None
    assert call(cfg, "Read", {"file_path": str(home / ".claude" / "settings.json")}) is None


def test_self_protected_set_contents(cfg, home):
    names = {str(p) for p in cfg.self_protected()}
    for expected in (
        cfg.root / ".git" / "config",
        cfg.root / ".git" / "hooks",
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        home / ".claude" / "hooks",
    ):
        assert str(expected) in names


def _run_env(repo, tmp_path, extra_env, path=None):
    return run_wrapper(
        repo.root,
        payload(repo, "Read", {"file_path": str(repo.root / "notes.txt")}),
        path=path,
        extra_env=extra_env,
    )


@pytest.mark.skipif(not os.access("/usr/bin/python3", os.X_OK), reason="needs /usr/bin/python3")
def test_wrapper_ignores_user_site_and_pythonpath_and_path_shadowing(repo, tmp_path):
    repo.write("notes.txt", "secret-ish\n")
    version = subprocess.run(
        ["/usr/bin/python3", "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    base = tmp_path / "userbase"
    site = base / "lib" / f"python{version}" / "site-packages"
    site.mkdir(parents=True)
    (site / "usercustomize.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "json.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake / "python3").chmod(0o755)
    for extra, path in (
        ({"PYTHONUSERBASE": str(base)}, None),
        ({"PYTHONPATH": str(evil)}, None),
        ({}, f"{fake}:{os.environ['PATH']}"),
    ):
        result = _run_env(repo, tmp_path, extra, path)
        assert result.returncode == 0
        assert '"permissionDecision": "deny"' in result.stdout, (extra, path, result.stdout)


def test_wrapper_script_uses_isolated_python():
    from .conftest import GUARD_DIR

    text = (GUARD_DIR / "run-guard.sh").read_text(encoding="utf-8")
    assert " -I " in text
    assert "/usr/bin/python3" in text
    assert shutil.which("bash")
