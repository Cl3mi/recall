"""Hardening round 2: Grep/Glob/LS ancestors, untracked recursion, unknown tools, header, ledger."""

import dataclasses

import pytest
from recall_guard import core
from recall_guard.bashcheck import analyse
from recall_guard.config import load_config
from recall_guard.policy import Context, has_untracked_below
from recall_guard.sniff import sniff

from .conftest import HEADER


def call(cfg, tool, tin, session="s1"):
    return core.decide(
        cfg, {"tool_name": tool, "tool_input": tin, "cwd": str(cfg.root), "session_id": session}
    )


def rule(denial):
    return denial.rule if denial else None


@pytest.fixture
def ext(repo, tmp_path):
    sealed = tmp_path / "ext_sealed"
    sealed.mkdir()
    (sealed / ".sealed").write_text("m\n", encoding="utf-8")
    return load_config(root=repo.root, env={"RECALL_SEALED_ROOT": str(sealed)})


# -- T1 ----------------------------------------------------------------------------------------


def test_grep_ls_over_ancestors_of_closed_zones_denied(ext, repo, tmp_path):
    for tool in ("Grep", "LS"):
        key = {"pattern": "x"} if tool == "Grep" else {}
        # ancestor of both the repo (local/sealed) and the external sealed root
        assert rule(call(ext, tool, {**key, "path": str(tmp_path)})) == "recursive-over-sealed"
        parent = str(tmp_path.parent)
        assert rule(call(ext, tool, {**key, "path": parent})) == "recursive-over-sealed"
    assert call(ext, "Grep", {"pattern": "x", "path": str(repo.root)}) is None
    assert call(ext, "Grep", {"pattern": "x"}) is None
    assert call(ext, "Grep", {"pattern": "x", "path": str(repo.root / "src")}) is None


def test_ancestor_of_data_quarantine_denied(cfg, repo, tmp_path):
    quarantine = tmp_path / "q" / "recall-quarantine"
    quarantine.mkdir(parents=True)
    cfg2 = dataclasses.replace(cfg, protected_dirs=(*cfg.protected_dirs, quarantine))
    denial = call(cfg2, "Grep", {"pattern": "x", "path": str(quarantine.parent)})
    assert rule(denial) == "recursive-over-sealed"
    assert rule(call(cfg2, "LS", {"path": str(quarantine.parent)})) == "recursive-over-sealed"


def test_glob_prefix_and_expanded_directories_are_checked(ext, repo, tmp_path):
    repo.write("local/raw/dump")
    assert rule(call(ext, "Glob", {"pattern": f"{tmp_path}/**/*"})) == "recursive-over-sealed"
    assert call(ext, "Glob", {"pattern": f"{repo.root}/local/**/*"}) is not None
    assert call(ext, "Glob", {"pattern": f"{ext.sealed_root}/*"}) is not None
    assert call(ext, "Glob", {"pattern": "loc*/raw/*", "path": str(repo.root)}) is not None
    assert call(ext, "Glob", {"pattern": "loc{al,x}/raw/*"}) is not None
    # legitimate globs
    assert call(ext, "Glob", {"pattern": "src/**/*.py"}) is None
    assert call(ext, "Glob", {"pattern": "**/*.py"}) is None
    assert call(ext, "Glob", {"pattern": "*.py", "path": str(repo.root / "local")}) is None


# -- R1 ----------------------------------------------------------------------------------------


def test_has_untracked_below(ctx, repo):
    assert has_untracked_below(ctx, repo.root / "src") is False
    repo.write("docs/stray.txt")
    assert has_untracked_below(ctx, repo.root / "docs") is True
    assert has_untracked_below(ctx, repo.root / "src", cap=0) is True  # cap exceeded: fail closed


def test_has_untracked_below_skips_tooling_and_zones_and_ledger(cfg, repo):
    repo.write("src/__pycache__/x.pyc")
    repo.write("local/released/ok.json")
    repo.write("src/mine.py")
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    assert has_untracked_below(ctx, repo.root / "src") is True  # mine.py is not recorded yet
    ctx.ledger.add(repo.root / "src" / "mine.py")
    assert has_untracked_below(ctx, repo.root / "src") is False
    assert has_untracked_below(ctx, repo.root / "local" / "released") is False
    assert has_untracked_below(ctx, repo.root / ".venv") is False


def test_has_untracked_below_judges_symlinks_without_following(ctx, repo, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "f").write_text("x", encoding="utf-8")
    (repo.root / "src" / "lnk").symlink_to(target)
    assert has_untracked_below(ctx, repo.root / "src") is True
    assert has_untracked_below(ctx, target) is False  # outside the repo: not judged here


@pytest.mark.parametrize(
    "command",
    [
        "grep -r SECRET docs",
        "grep -rn SECRET ./docs",
        "rg SECRET docs",
        "cp -r docs /tmp/zz_out",
        "tar cf /tmp/zz.tar docs",
        "zip -r /tmp/zz.zip docs",
        "rsync -a docs /tmp/zz_out",
        "scp -r docs host:",
        "find docs -type f -exec cat {} +",
        "find docs -print | cpio -pdm /tmp/zz_out",
        "find docs -print | pax -rw /tmp/zz_out",
        "cd docs && grep -r foo",
    ],
)
def test_recursive_programs_over_untracked_files_denied(ctx, repo, command):
    repo.write("docs/stray.txt")
    assert rule(analyse(ctx, command)) == "recursive-over-untracked"


def test_recursive_over_tracked_only_directories_allowed(ctx, repo):
    assert analyse(ctx, "grep -rn foo src docs") is None
    assert analyse(ctx, "rg foo src") is None


def test_grep_tool_over_directory_with_untracked_files(cfg, repo):
    repo.write("docs/stray.txt")
    assert rule(call(cfg, "Grep", {"pattern": "x", "path": str(repo.root / "docs")})) == (
        "recursive-over-untracked"
    )
    assert call(cfg, "Grep", {"pattern": "x", "path": str(repo.root / "src")}) is None
    assert call(cfg, "Grep", {"pattern": "x"}) is None  # repo root: ripgrep honours .gitignore


# -- T4 ----------------------------------------------------------------------------------------


def test_generic_tools_check_any_string_that_looks_like_a_path(cfg, repo):
    note = repo.write("notes/x.txt")
    for tin in (
        {"uri": f"file://{note}"},
        {"location": str(note)},
        {"pattern": str(note)},
        {"a": {"b": [str(note)]}},
        {"anything": f"file://{note}"},
    ):
        assert rule(call(cfg, "mcp__fs__read", tin)) == "untracked", tin
    assert rule(call(cfg, "WebFetch", {"url": f"file://{note}", "prompt": "x"})) == "untracked"
    ok = repo.root / "src" / "app.py"
    assert call(cfg, "mcp__fs__read", {"uri": f"file://{ok}"}) is None
    assert call(cfg, "mcp__x__y", {"name": "notes", "route": "/api/v1/users"}) is None
    assert call(cfg, "mcp__x__y", {"text": f"{note} with spaces"}) is None  # prose, not a path
    assert call(cfg, "mcp__x__y", {"text": "/" + "x" * 5000}) is None


def test_generic_tools_expand_home(cfg, repo, monkeypatch):
    monkeypatch.setenv("HOME", str(repo.root))
    repo.write("notes/x.txt")
    assert rule(call(cfg, "mcp__fs__read", {"loc": "~/notes/x.txt"})) == "untracked"


# -- E1 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first_line",
    [
        HEADER,
        HEADER.replace(",", ", "),
        HEADER.replace(",", " , "),
        ",".join(f'"{c}"' for c in HEADER.split(",")),
        ",".join(f"'{c}'" for c in HEADER.split(",")),
    ],
)
def test_header_fingerprint_survives_spacing_and_quotes(tmp_path, first_line):
    path = tmp_path / "x.txt"
    path.write_text(first_line + "\nrow\n", encoding="utf-8")
    assert sniff(path, HEADER) == "header-fingerprint"


def test_header_with_spaces_in_the_configured_line_matches_plain_text(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text(HEADER + "\nrow\n", encoding="utf-8")
    assert sniff(path, HEADER.replace(",", ", ")) == "header-fingerprint"
    other = tmp_path / "y.txt"
    other.write_text("hello world\n", encoding="utf-8")
    assert sniff(other, HEADER) is None


# -- P1 ----------------------------------------------------------------------------------------


def test_ledger_never_records_closed_zone_writes(cfg, repo):
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    sealed = cfg.sealed_root / "new" / "out.log"
    quarantine = repo.root / "local" / "quarantine" / "q.txt"
    for target in (sealed, quarantine):
        assert call(cfg, "Write", {"file_path": str(target), "content": "x"}) is not None
        assert not ctx.ledger.contains(target)
        assert not ctx.ledger.contains(target.parent)
