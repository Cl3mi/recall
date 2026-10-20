import pytest
from recall_guard import bashcheck, policy
from recall_guard.bashcheck import analyse, tokenize
from recall_guard.config import load_config
from recall_guard.policy import Context


def rule(ctx, command):
    denial = analyse(ctx, command)
    return denial.rule if denial else None


def test_tokenizer_splits_shell_punctuation():
    assert tokenize("cat a/x.csv|head") == ["cat", "a/x.csv", "|", "head"]
    assert tokenize("wc -l <x.csv") == ["wc", "-l", "<", "x.csv"]
    assert tokenize("a;b") == ["a", ";", "b"]
    assert tokenize("unterminated 'quote")  # falls back instead of raising


@pytest.mark.parametrize(
    "command,expected",
    [
        ("cat data/x.csv", "suffix"),
        ("cat a/x.csv|head", "suffix"),
        ("cat x.csv;ls", "suffix"),
        ("wc -l <x.csv", "suffix"),
        ("python3 -c \"open('data.csv')\"", "suffix"),
        ("cat local/sealed/run.json", "protected-ref"),
        ("ls local/quarantine", "protected-ref"),
    ],
)
def test_text_rules_deny(ctx, command, expected):
    assert rule(ctx, command) == expected


def test_cd_then_relative_sealed_read(ctx, repo):
    repo.write("local/sealed/run.json")
    assert rule(ctx, "cd local && cat sealed/run.json") == "sealed"


def test_untracked_read_denied_and_git_add_N_hint(ctx, repo):
    repo.write("notes/x.txt")
    assert rule(ctx, "cat notes/x.txt") == "untracked"


def test_glob_expansion_is_checked(ctx, repo):
    repo.write("notes/a.txt")
    repo.write("notes/b.txt")
    assert rule(ctx, "cat notes/*.txt") == "untracked"


def test_runner_without_existing_script_makes_no_git_call(ctx, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("git ls-files must not run when no script file exists")

    monkeypatch.setattr(policy.subprocess, "run", forbidden)
    assert rule(ctx, "python3 no_such_script_zz.py") is None
    assert rule(ctx, "python3 -m pytest") is None
    assert rule(ctx, "bash -c 'echo hi'") is None


def test_glob_over_the_cap_is_denied_not_truncated(ctx, repo, monkeypatch):
    for n in range(5):
        repo.write(f"src/g{n}.py", track=True)
    assert rule(ctx, "cat src/g*.py") is None  # under the default cap
    monkeypatch.setattr(bashcheck, "_MAX_GLOB", 3)
    assert rule(ctx, "cat src/g*.py") == "glob-too-large"


def test_glob_cap_stops_an_unbounded_walk(ctx, repo, monkeypatch):
    monkeypatch.setattr(bashcheck, "_MAX_GLOB", 2)
    seen = []

    def endless(pattern, recursive=False):
        for n in range(10**9):
            seen.append(n)
            yield f"/nonexistent/{n}"

    monkeypatch.setattr(bashcheck.glob, "iglob", endless)
    assert rule(ctx, "cat src/**/*.py") == "glob-too-large"
    assert len(seen) <= 5


def test_redirect_to_new_file_is_a_write_and_allowed(ctx):
    assert rule(ctx, "echo hi > scratch_out.log") is None


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git log --oneline -5",
        "ls src",
        "cat src/app.py",
        "grep -rn foo src docs",
        "uv run pytest -q",
        "echo $HOME",
        "git add src/app.py",
    ],
)
def test_ordinary_commands_pass(ctx, command):
    assert rule(ctx, command) is None


def test_extractors_denied(ctx):
    assert rule(ctx, "pdftotext a.pdf -") == "extractor"
    assert rule(ctx, "cd x && libreoffice --convert-to txt f") == "extractor"
    assert rule(ctx, "uv run in2csv report") == "extractor"


def test_dynamic_paths_denied_for_readers_only(ctx):
    assert rule(ctx, "cat $(git rev-parse --show-toplevel)/README.md") == "dynamic-path"
    assert rule(ctx, "cat $SOMETHING_UNSET/x") == "dynamic-path"
    assert rule(ctx, "echo $SOMETHING_UNSET") is None


def test_recursive_tools_over_a_sealed_ancestor_denied(ctx, repo):
    repo.write("local/sealed/a.json")
    assert rule(ctx, "grep -rn foo .") == "recursive-over-sealed"
    assert rule(ctx, "grep -rn foo src") is None
    assert rule(ctx, "find . -name '*.py'") is None
    assert rule(ctx, "find . -exec cat {} +") == "recursive-over-sealed"


def test_untracked_script_naming_protected_paths_denied(ctx, tmp_path):
    leak = tmp_path / "leak.py"
    leak.write_text("open('local/sealed/a')\n", encoding="utf-8")
    assert rule(ctx, f"python3 {leak}") == "script-protected"


def test_agent_created_script_with_data_suffix_denied(cfg, repo):
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    script = repo.root / "scripts" / "mk.py"
    ctx.ledger.record_new_file(script)
    repo.write("scripts/mk.py", "p = 'x.csv'\n")
    assert rule(ctx, "python3 scripts/mk.py") == "script-suffix"


def test_tracked_script_may_name_data_paths(cfg, repo):
    repo.write("tests/t.py", "p = 'x.csv'\n", track=True)
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    assert rule(ctx, "python3 -m pytest tests/t.py") is None


@pytest.mark.parametrize(
    "command", ["python3 tools/guard/airlock open", "./airlock status", "rm local/airlock.open"]
)
def test_airlock_cli_and_marker_denied(ctx, command):
    assert rule(ctx, command) == "airlock-cli"


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/a/b/ tools/guard/guard.py",
        "rm tools/guard/x",
        "echo x > .claude/settings.json",
        "git checkout -- tools/guard",
        "tee .githooks/pre-commit",
    ],
)
def test_self_protect_denies_mutation(ctx, repo, command):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, command) == "self-protect"


def test_self_protect_allows_reading_and_running(ctx, repo):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, "cat tools/guard/guard.py") is None
    # round 2: a directory argument is no longer stageable by an agent (rule git-add)
    assert rule(ctx, "git add tools/guard") == "git-add"
    assert rule(ctx, "git add tools/guard/guard.py") is None
    assert rule(ctx, "uv run ruff check tools/guard") is None


def test_paths_hidden_in_quoted_strings_and_code_are_checked(ctx, repo):
    repo.write("notes/x.txt")
    assert rule(ctx, "python3 -c \"print(open('notes/x.txt').read())\"") == "untracked"
    assert rule(ctx, 'echo "see notes/x.txt for details"') == "untracked"
    assert rule(ctx, "echo e.g. something, i.e. nothing") is None
    assert rule(ctx, 'echo "tracked src/app.py is fine."') is None


def test_file_url_is_unwrapped(ctx, repo):
    path = repo.write("notes/x.txt")
    assert rule(ctx, f"curl file://{path}") == "untracked"
    assert rule(ctx, f"curl 'file://{path}'") == "untracked"


def test_shell_dash_c_is_analysed_recursively(ctx, repo):
    repo.write("tools/guard/guard.py", track=True)
    repo.write("notes/x")
    assert rule(ctx, "bash -c 'rm tools/guard/guard.py'") == "self-protect"
    assert rule(ctx, 'sh -c "cat notes/x"') == "untracked"
    assert rule(ctx, "zsh -lc 'rm tools/guard/guard.py'") == "self-protect"
    assert rule(ctx, "bash -c \"bash -c 'rm tools/guard/guard.py'\"") == "self-protect"
    assert rule(ctx, "bash -c 'echo hello'") is None


def test_interpreter_code_naming_self_protected_path_denied(ctx, repo):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, "python3 -c \"open('tools/guard/guard.py','w')\"") == "self-protect"
    assert rule(ctx, "perl -e 'unlink q(tools/guard/guard.py)'") == "self-protect"
    assert rule(ctx, "node -e \"fs.rmSync('.githooks/pre-commit')\"") == "self-protect"
    assert rule(ctx, 'python3 -c "print(1)"') is None


@pytest.mark.parametrize(
    "command",
    [
        "ed tools/guard/guard.py",
        "perl -pi -e s/a/b/ tools/guard/guard.py",
        "perl -i.bak -pe s/a/b/ tools/guard/guard.py",
        "awk -i inplace 1 tools/guard/guard.py",
    ],
)
def test_more_in_place_mutators_denied(ctx, repo, command):
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, command) == "self-protect"


def test_brace_expansion_is_checked(ctx, repo):
    repo.write("notes/x")
    repo.write("notes/y")
    # a data suffix only appears after expansion; built here, never typed into a shell command
    assert rule(ctx, "cat real.c{s,}v") == "suffix"
    assert rule(ctx, "cat notes/{x,z}") == "untracked"
    assert rule(ctx, "cat src/{app.py,}") is None


def test_brace_explosion_denied(ctx):
    assert rule(ctx, "cat {a,b,c}{a,b,c}{a,b,c}{a,b,c}") == "brace-explosion"
    assert rule(ctx, "cat {a,b}{a,b}") is None


def test_recursive_without_path_walks_cwd(ctx, cfg, repo):
    repo.write("local/sealed/a.json")
    assert rule(ctx, "grep -rn foo") == "recursive-over-sealed"
    assert rule(ctx, "grep -r src") == "recursive-over-sealed"  # first argument is the pattern
    assert rule(ctx, "find -exec cat {} +") == "recursive-over-sealed"
    assert rule(ctx, "cd local && grep -r foo") == "recursive-over-sealed"
    assert rule(ctx, "find -name x") is None
    assert rule(ctx, "grep -rn foo src") is None
    assert rule(ctx, "grep -r -e foo src") is None
    assert rule(ctx, "cd src && grep -r foo") is None


def test_rg_and_ag_without_path_allowed_only_at_repo_root(ctx, repo):
    repo.write("local/sealed/a.json")
    assert rule(ctx, "rg foo") is None
    assert rule(ctx, "ag foo") is None
    assert rule(ctx, "cd local && rg foo") == "recursive-over-sealed"


def test_xargs_with_reader_denied_unless_git_ls_files(ctx):
    assert rule(ctx, "ls src | xargs cat") == "dynamic-path"
    assert rule(ctx, "find src | xargs -0 grep foo") == "dynamic-path"
    assert rule(ctx, "git ls-files | xargs cat") is None
    assert rule(ctx, "echo a | xargs echo") is None


def test_denial_path_never_holds_the_whole_command(ctx, repo):
    repo.write("notes/x.txt")
    denial = analyse(ctx, "python3 -c \"print(open('notes/x.txt').read())\"")
    assert denial.path == "notes/x.txt"


def test_dev_mode_lifts_self_protection(repo):
    cfg = load_config(root=repo.root, env={"RECALL_GUARD_DEV": "1"})
    repo.write("tools/guard/guard.py", track=True)
    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    assert rule(ctx, "sed -i s/a/b/ tools/guard/guard.py") is None
