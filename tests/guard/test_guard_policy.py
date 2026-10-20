import os

import pytest
from recall_guard.config import load_config
from recall_guard.policy import RECURSIVE_MSG, Context, walks_closed_zone

from .conftest import HEADER

TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def rule(ctx, path, **kw):
    denial = ctx.check_path(str(path), **kw)
    return denial.rule if denial else None


def fresh(cfg, repo):
    return Context(cfg, cwd=repo.root, session_id="sess1")


def test_tracked_file_allowed(ctx, repo):
    assert rule(ctx, repo.root / "src" / "app.py") is None


def test_untracked_file_denied(ctx, repo):
    repo.write("notes/x.txt")
    assert rule(ctx, repo.root / "notes" / "x.txt") == "untracked"


def test_git_add_intent_makes_untracked_readable(cfg, repo):
    repo.write("notes/x.txt")
    repo.git("add", "-N", "notes/x.txt")
    assert rule(fresh(cfg, repo), repo.root / "notes" / "x.txt") is None


def test_sibling_in_agent_made_dir_is_untracked(cfg, repo):
    agent = fresh(cfg, repo)
    agent.ledger.record_new_file(repo.root / "scratch" / "mine.py")
    repo.write("scratch/mine.py")
    repo.write("scratch/other.txt")
    assert rule(agent, repo.root / "scratch" / "mine.py") is None
    assert rule(agent, repo.root / "scratch") is None
    assert rule(agent, repo.root / "scratch" / "other.txt") == "untracked"


def test_untracked_message_does_not_instruct_agent_to_git_add():
    from recall_guard.policy import untracked_message

    text = untracked_message()
    assert "human" in text
    assert "scratchpad" in text


def test_sealed_root_and_marker_dirs_denied(ctx, repo):
    repo.write("local/sealed/run1.json")
    repo.write("elsewhere/.sealed", "")
    repo.write("elsewhere/a.txt")
    assert rule(ctx, repo.root / "local" / "sealed" / "run1.json") == "sealed"
    assert rule(ctx, repo.root / "elsewhere" / "a.txt") == "sealed"


def test_sealed_denies_even_tracked_and_even_when_missing(ctx, repo):
    assert rule(ctx, repo.root / "local" / "sealed" / "not-yet.json") == "sealed"


def test_protected_quarantine_denied(ctx, repo):
    repo.write("local/quarantine/words.txt")
    assert rule(ctx, repo.root / "local" / "quarantine" / "words.txt") == "protected"
    assert rule(ctx, "/data/recall-quarantine/x") == "protected"


def test_data_suffix_denied_even_when_tracked(ctx, repo):
    repo.write("data/x.csv", track=True)
    denial = ctx.check_path(str(repo.root / "data" / "x.csv"))
    assert denial.rule == "suffix"
    assert "docs/export.header.txt" in denial.reason


def test_released_dirs_readable_without_sniff_hits(ctx, repo):
    repo.write("local/artifacts/gate_report.json", "{}\n")
    repo.write("local/artifacts/profile.json", "{}\n")
    repo.write("local/released/agg.json", "{}\n")
    for rel in (
        "local/artifacts/gate_report.json",
        "local/artifacts/profile.json",
        "local/released/agg.json",
    ):
        assert rule(ctx, repo.root / rel) is None


def test_fixtures_dir_readable(ctx, repo):
    repo.write("local/fixtures/cache/readme.txt", "synthetic\n")
    assert rule(ctx, repo.root / "local" / "fixtures" / "cache" / "readme.txt") is None


def test_ledger_files_readable(cfg, repo):
    ctx = fresh(cfg, repo)
    new = repo.root / "scratch" / "new.py"
    ctx.ledger.record_new_file(new)
    repo.write("scratch/new.py", "x = 1\n")
    assert rule(ctx, new) is None


def test_renamed_export_with_header_is_caught_in_zones(ctx, repo):
    repo.write("local/fixtures/export.txt", HEADER + "\n1,2,3,4,5\n")
    repo.write("local/artifacts/renamed.dat", TABLE)
    assert rule(ctx, repo.root / "local" / "fixtures" / "export.txt") == "content"
    assert rule(ctx, repo.root / "local" / "artifacts" / "renamed.dat") == "content"


def test_outside_root_files_are_only_sniffed(ctx, tmp_path):
    ok = tmp_path / "notes.txt"
    ok.write_text("hello\n", encoding="utf-8")
    bad = tmp_path / "outside.txt"
    bad.write_text(TABLE, encoding="utf-8")
    assert rule(ctx, ok) is None
    assert rule(ctx, bad) == "content"


def test_nonexistent_untracked_path_is_not_denied(ctx, repo):
    assert rule(ctx, repo.root / "notes" / "future.txt") is None


def test_write_mode_skips_allowlist_but_not_sealed_or_suffix(ctx, repo):
    assert rule(ctx, repo.root / "notes" / "new.txt", write=True) is None
    assert rule(ctx, repo.root / "local" / "sealed" / "a", write=True) == "sealed"
    assert rule(ctx, repo.root / "notes" / "new.csv", write=True) == "suffix"


def test_tooling_dirs_pass(ctx, repo):
    repo.write(".venv/lib/mod.py", "x = 1\n")
    assert rule(ctx, repo.root / ".venv" / "lib" / "mod.py") is None


def test_symlinked_file_pointing_outside_the_repo_is_denied(ctx, repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.txt").write_text("hello\n", encoding="utf-8")
    link = repo.root / "src" / "link.txt"
    os.symlink(outside / "note.txt", link)
    repo.git("add", "-f", "src/link.txt")  # even tracked, a link out of the repo is refused
    assert rule(ctx, link) == "symlink-escape"


def test_symlink_escaping_the_repo_is_denied(ctx, repo, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.txt").write_text("hello\n", encoding="utf-8")
    os.symlink(real, repo.root / "linkdir")
    assert rule(ctx, repo.root / "linkdir" / "a.txt") == "symlink-escape"


def test_directories(ctx, repo):
    repo.write("notes/x.txt")
    repo.write("local/artifacts/g.json", "{}\n")
    assert rule(ctx, repo.root / "src") is None
    assert rule(ctx, repo.root) is None
    assert rule(ctx, repo.root / "notes") == "untracked"
    assert rule(ctx, repo.root / "local") is None  # ancestor of an allowed zone


def test_extra_allowed_from_local_file(repo):
    repo.write(".claude/guard.local.json", '{"extra_allowed": ["mynotes"]}')
    repo.write("mynotes/a.txt", "hello\n")
    cfg = load_config(root=repo.root, env={})
    assert rule(Context(cfg, cwd=repo.root), repo.root / "mynotes" / "a.txt") is None


def test_relative_paths_resolve_against_cwd(cfg, repo):
    repo.write("notes/x.txt")
    ctx = Context(cfg, cwd=repo.root / "notes", session_id="s")
    assert rule(ctx, "x.txt") == "untracked"
    assert rule(ctx, "../src/app.py") is None


@pytest.mark.parametrize("rel", ["tools/guard", "tools/guard/x.py", ".claude/settings.json"])
def test_self_protect_check(ctx, repo, rel):
    assert ctx.self_protect_check(str(repo.root / rel)).rule == "self-protect"


def test_walks_closed_zone_covers_ancestors_and_members(ctx, repo):
    cfg = ctx.cfg
    for walked in (repo.root / "local", cfg.sealed_root, cfg.sealed_root / "sub"):
        denial = walks_closed_zone(ctx, walked)
        assert denial.rule == "recursive-over-sealed"
        assert denial.reason == RECURSIVE_MSG
    assert walks_closed_zone(ctx, repo.root / "src") is None
    assert walks_closed_zone(ctx, repo.root / "local" / "released") is None


def test_self_protect_ignores_other_paths(ctx, repo):
    assert ctx.self_protect_check(str(repo.root / "src" / "app.py")) is None
