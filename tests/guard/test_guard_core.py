import io
import json

from recall_guard import core
from recall_guard.config import load_config

TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def call(cfg, tool, tool_input, cwd=None, session="s1"):
    payload = {
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": str(cwd or cfg.root),
        "session_id": session,
    }
    return core.decide(cfg, payload)


def rule(denial):
    return denial.rule if denial else None


def test_read_tracked_ok_and_untracked_denied(cfg, repo):
    repo.write("notes/x.txt")
    assert call(cfg, "Read", {"file_path": str(repo.root / "src" / "app.py")}) is None
    assert rule(call(cfg, "Read", {"file_path": str(repo.root / "notes" / "x.txt")})) == "untracked"


def test_glob_and_grep_data_filters_denied(cfg):
    assert rule(call(cfg, "Glob", {"pattern": "**/*.csv"})) == "suffix"
    assert rule(call(cfg, "Grep", {"pattern": "x", "glob": "*.tsv"})) == "suffix"
    assert rule(call(cfg, "Grep", {"pattern": "x", "type": "csv"})) == "suffix"
    assert call(cfg, "Grep", {"pattern": "csv", "path": str(cfg.root / "src")}) is None


def test_write_new_file_records_ledger_and_is_then_readable(cfg, repo):
    target = repo.root / "scratch" / "new.py"
    assert call(cfg, "Write", {"file_path": str(target), "content": "x = 1\n"}) is None
    repo.write("scratch/new.py", "x = 1\n")
    assert call(cfg, "Read", {"file_path": str(target)}) is None
    # a different session does not inherit the ledger
    assert rule(call(cfg, "Read", {"file_path": str(target)}, session="other")) == "untracked"


def test_write_to_data_suffix_and_sealed_denied(cfg):
    assert (
        rule(call(cfg, "Write", {"file_path": str(cfg.root / "a.csv"), "content": ""})) == "suffix"
    )
    sealed = cfg.sealed_root / "x.json"
    assert rule(call(cfg, "Write", {"file_path": str(sealed), "content": ""})) == "sealed"


def test_self_protection_for_file_tools(cfg, repo):
    for tool in ("Write", "Edit", "NotebookEdit"):
        field = "notebook_path" if tool == "NotebookEdit" else "file_path"
        denial = call(cfg, tool, {field: str(repo.root / "tools" / "guard" / "guard.py")})
        assert rule(denial) == "self-protect"
    dev = load_config(root=repo.root, env={"RECALL_GUARD_DEV": "1"})
    assert (
        call(
            dev, "Write", {"file_path": str(repo.root / "tools" / "guard" / "g.py"), "content": ""}
        )
        is None
    )


def test_lint_denies_unsealed_output_in_scope_and_honours_pragma(cfg, repo):
    path = str(repo.root / "src" / "recall" / "new.py")
    bad = call(cfg, "Write", {"file_path": path, "content": 'open(p, "w")\n'})
    assert rule(bad) == "lint"
    assert "recall.sealed" in bad.reason
    ok = call(
        cfg, "Write", {"file_path": path, "content": 'open(p, "w")  # guard: ok(synthetic)\n'}
    )
    assert ok is None
    edit = call(
        cfg,
        "Edit",
        {
            "file_path": str(repo.root / "src" / "app.py"),
            "old_string": "print('hi')",
            "new_string": "logging.FileHandler(f)",
        },
    )
    assert rule(edit) == "lint"


def test_bash_is_delegated(cfg):
    assert rule(call(cfg, "Bash", {"command": "cat x.csv|head"})) == "suffix"
    assert call(cfg, "Bash", {"command": "git status"}) is None
    assert rule(call(cfg, "Monitor", {"command": "cat x.csv"})) == "suffix"


def test_airlock_marker_denies_everything(cfg, repo):
    cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
    cfg.airlock_marker.write_text("open", encoding="utf-8")
    for tool, tin in (
        ("Read", {"file_path": str(repo.root / "README.md")}),
        ("Bash", {"command": "git status"}),
        ("Skill", {}),
    ):
        assert rule(call(cfg, tool, tin)) == "airlock"


def test_airlock_marker_denies_even_unparseable_payloads(cfg):
    cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
    cfg.airlock_marker.write_text("open", encoding="utf-8")
    assert core.run_payload("not json at all", cfg)[1].rule == "airlock"
    assert core.run_payload("[1, 2]", cfg)[1].rule == "airlock"


def test_subagent_prompts_may_not_name_protected_paths(cfg):
    assert rule(call(cfg, "Agent", {"prompt": "read local/sealed/run.json"})) == "protected-ref"
    assert call(cfg, "Agent", {"prompt": "refactor src/"}) is None


def test_artifact_file_path_of_untracked_page_is_denied(cfg, repo):
    page = repo.write("local/out/page.html", "<html></html>\n")
    assert rule(call(cfg, "Artifact", {"file_path": str(page)})) == "untracked"


def test_artifact_files_map_values_are_checked(cfg, repo):
    page = repo.write("local/out/page.html", "<html></html>\n")
    assert rule(call(cfg, "Artifact", {"files": {"a.js": str(page)}})) == "untracked"


def test_generic_tool_file_path_with_data_suffix_is_denied(cfg, repo):
    target = str(repo.root / "d" / ("x" + ".csv"))
    assert rule(call(cfg, "ArtifactData", {"file_path": target})) == "suffix"


def test_webfetch_url_is_an_accepted_residual(cfg):
    # ACCEPTED RESIDUAL: "url" is not a path-like key, so a URL naming a data suffix passes.
    # It cannot reach local client data; network fetches are outside this guard's scope.
    assert call(cfg, "WebFetch", {"url": "https://example.com/data.csv"}) is None


def test_grep_over_directory_holding_a_closed_zone_denied(cfg, repo):
    repo.write("local/sealed/a.json")
    repo.write("local/released/ok.txt")
    over = call(cfg, "Grep", {"pattern": "x", "path": str(repo.root / "local")})
    assert rule(over) == "recursive-over-sealed"
    zone = call(cfg, "Grep", {"pattern": "x", "path": str(repo.root / "local" / "sealed")})
    assert zone is not None
    assert call(cfg, "Grep", {"pattern": "x", "path": str(repo.root / "src")}) is None
    assert call(cfg, "Grep", {"pattern": "x", "path": str(repo.root)}) is None
    assert call(cfg, "Grep", {"pattern": "x"}) is None
    assert call(cfg, "Glob", {"pattern": "*.py", "path": str(repo.root / "local")}) is None


def test_artifact_files_resolve_against_root(cfg, repo):
    repo.write("local/sealed/out.log")
    tin = {"root": "local", "files": {"p.html": "sealed/out.log"}}
    assert call(cfg, "Artifact", tin) is not None
    tin = {"root": "local", "files": {"p.html": {"from": "sealed/out.log"}}}
    assert call(cfg, "Artifact", tin) is not None
    tin = {"root": "src", "files": {"p.html": "app.py"}}
    assert call(cfg, "Artifact", tin) is None


def test_pathish_key_names_are_checked(cfg, repo):
    note = repo.write("notes/x.txt")
    assert rule(call(cfg, "Custom", {"local_path": str(note)})) == "untracked"
    assert rule(call(cfg, "Custom", {"source": str(note)})) == "untracked"
    assert rule(call(cfg, "Custom", {"Output_Dir": str(note)})) == "untracked"
    # round 2 (T4): a non-path-ish key no longer hides an absolute path from the guard
    assert rule(call(cfg, "Custom", {"items": [str(note)]})) == "untracked"
    assert call(cfg, "Custom", {"items": ["not a path", "plain"]}) is None
    assert call(cfg, "Custom", {"source": str(repo.root / "src" / "app.py")}) is None


def test_run_payload_returns_internal_error_denial_on_bug(cfg, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(core, "decide", boom)
    tool, denial = core.run_payload(json.dumps({"tool_name": "Read", "tool_input": {}}), cfg)
    assert tool == "Read"
    assert denial.rule == "internal-error"
    assert "RuntimeError" in denial.reason


def test_run_payload_on_garbage_is_always_denied(cfg):
    assert core.run_payload("not json at all", cfg)[1].rule == "unparseable"
    assert core.run_payload("not json x.csv", cfg)[1].rule == "unparseable"
    assert core.run_payload("[1, 2]", cfg)[1].rule == "unparseable"
    assert core.run_payload('"text"', cfg)[1].rule == "unparseable"
    assert core.run_payload("", cfg)[1].rule == "unparseable"


def test_run_payload_deeply_nested_json_is_denied(cfg):
    assert core.run_payload("[" * 100000, cfg)[1].rule == "unparseable"


def test_main_denies_when_local_config_is_invalid(repo, monkeypatch, capsys):
    repo.write(".claude/guard.local.json", "{secret-ish not json")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo.root))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Read"})))
    assert core.main([]) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "[config-error]" in out["permissionDecisionReason"]
    assert "secret-ish" not in out["permissionDecisionReason"]


def test_selfcheck_command_reports_invalid_local_config(repo, monkeypatch, capsys):
    repo.write(".claude/guard.local.json", "{not json")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo.root))
    assert core.main(["--selfcheck"]) == 0
    assert "guard.local.json" in capsys.readouterr().err
