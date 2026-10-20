"""Hardening round 2: line continuation, git policy, dynamic paths, bare words."""

import pytest
from recall_guard import bashcheck
from recall_guard.bashcheck import analyse, tokenize


def rule(ctx, command):
    denial = analyse(ctx, command)
    return denial.rule if denial else None


# -- L1: backslash-newline and IFS ----------------------------------------------------------


def test_backslash_newline_is_joined_before_analysis(ctx, repo):
    repo.write("notes.txt")
    repo.write("local/sealed/out.log")
    assert rule(ctx, "cat note\\\ns.txt") == "untracked"
    assert rule(ctx, "cat local/seal\\\ned/out.log") == "protected-ref"
    assert rule(ctx, "cat a/x.c\\\nsv") == "suffix"


def test_ifs_is_a_space(ctx, repo):
    repo.write("notes")
    assert rule(ctx, "cat${IFS}notes") == "untracked"
    assert rule(ctx, "cat$IFS notes") == "untracked"
    assert rule(ctx, "echo${IFS}hello") is None


# -- G1/G2: git policy -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git update-index --add notes",
        "git stash push -u",
        "git -C . stash",
        "git apply x.patch",
        "git hash-object -w notes",
        "git fast-import",
        "git diff --no-index /dev/null notes",
        "git grep --no-index -e SECRET",
        "git log --no-index",
        "git show --no-index x",
        "git grep --untracked -e SECRET",
        "git grep --include-untracked -e SECRET",
        "git config core.hooksPath /dev/null",
        "git config --local core.hooksPath ''",
        "git config core.HOOKSpath x",
        "git config --unset core.hooksPath",
        "git -c core.hooksPath=x status",
        "git --git-dir=local/x status",
    ],
)
def test_git_policy_denies(ctx, repo, command):
    repo.write("notes")
    assert rule(ctx, command) == "git-policy"


def test_git_via_xargs_is_denied(ctx, repo):
    repo.write("notes")
    assert rule(ctx, "echo notes | xargs git diff --no-index /dev/null") is not None
    assert rule(ctx, "echo . | xargs git add") == "git-add"
    assert rule(ctx, "git ls-files -o | xargs cat") == "dynamic-path"
    assert rule(ctx, "git ls-files | xargs cat") is None


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git log --oneline -5",
        "git diff",
        "git diff --cached --stat",
        "git grep foo",
        "git commit -am msg",
        "git commit -a -m msg",
        "git ls-files -o",
        "git -C . status",
        "git -c user.name=x status",
        "git config user.name",
        "git add src/app.py",
        "git add -v src/app.py",
        "git add -- src/app.py README.md",
        "git add --dry-run src/app.py",
        "git add",
    ],
)
def test_git_policy_allows_ordinary_commands(ctx, repo, command):
    assert rule(ctx, command) is None


@pytest.mark.parametrize(
    "command",
    [
        "git add -A",
        "git add --all",
        "git add .",
        "git add src",
        "git add src/",
        "git add -f src/app.py",
        "git add --force src/app.py",
        "git add -fA",
        "git add -u",
        "git add --update",
        "git add -N src/app.py",
        "git add --intent-to-add src/app.py",
        "git add -p src/app.py",
        "git add --patch src/app.py",
        "git add -i",
        "git add --interactive",
        "git add -e",
        "git add --edit",
        "git add 'src/*.py'",
        "git add src/*.py",
        "git add $X",
        "git add $(ls)",
        "git add missing.py",
        "git add src/app.py .",
        "git add --pathspec-from-file=list",
        "git add -- src",
    ],
)
def test_git_add_denied_unless_explicit_files(ctx, repo, command):
    repo.write("src/other.py", track=True)
    assert rule(ctx, command) == "git-add"


def test_git_add_of_untracked_file_denied_but_session_file_allowed(cfg, repo):
    from recall_guard.policy import Context

    ctx = Context(cfg, cwd=repo.root, session_id="s1")
    repo.write("other/new.py")
    assert rule(ctx, "git add other/new.py") is not None
    ctx.ledger.record_new_file(repo.root / "scratch" / "mine.py")
    repo.write("scratch/mine.py")
    assert rule(ctx, "git add scratch/mine.py") is None


def test_git_add_follows_cd_and_dash_C(ctx, repo):
    repo.write("docs/stray.txt")
    repo.write("stray.txt", track=True)
    assert rule(ctx, "cd docs && git add stray.txt") is not None
    assert rule(ctx, "git -C docs add stray.txt") is not None
    assert rule(ctx, "git add stray.txt") is None


def test_git_add_with_dynamic_cwd_denied(ctx, repo):
    assert rule(ctx, "cd $SOMEWHERE && git add src/app.py") == "git-add"


# -- D1/D2: dynamic paths, inverted rule ----------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "install $PWD/notes /tmp/c",
        "install $PWD/loc*/seal*/out.log /tmp/c",
        "dd if=$PWD/notes of=/tmp/d",
        "timeout 5s cat $(pwd)/notes",
        "timeout -k 5 10 cat $(pwd)/notes",
        "env -u X cat $(pwd)/notes",
        "sudo -u root cat $PWD/notes",
        "nice -n 5 cat $PWD/notes",
        "if cat $(pwd)/notes; then :; fi",
        "while cat $(pwd)/notes; do break; done",
        "until cat $(pwd)/notes; do break; done",
        "echo `cat $PWD/notes`",
        "echo $(cat $PWD/notes)",
        'echo "$(cat $PWD/notes)"',
        "cat $'local/sea\\x6ced/out.log'",
        "install $'local/sea\\x6ced/out.log' /tmp/c",
        "cat $(echo notes)",
        "$EDITOR notes",
        "cat $SOMETHING_UNSET/x",
        "cat $(git rev-parse --show-toplevel)/README.md",
        "ls src | xargs cat",
        "if true; then cat $PWD/x; fi",
        "echo x; { cat $PWD/x; }",
        "! cat $PWD/x",
        "eval cat $PWD/x",
        "python3 $PWD/x.py",
        "uv run python3 $SCRIPT",
    ],
)
def test_dynamic_path_denied_unless_all_programs_safe(ctx, repo, command):
    repo.write("notes")
    assert rule(ctx, command) in ("dynamic-path", "untracked", "git-policy")
    assert rule(ctx, command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "echo $HOME",
        "echo $SOMETHING_UNSET",
        'echo "cost $5 and $(date)"',
        "printf '%s\\n' $X",
        "ls $SOMEWHERE",
        "cd $SOMEWHERE && ls",
        "mkdir -p $TMPDIR/x",
        "export FOO=$(pwd)",
        "unset FOO",
        "test -f $X",
        "[ -f $X ]",
        "sleep $N",
        "date +%s$X",
        "which $TOOL",
        "git status $X",
        "git log --oneline -n $N",
        "uv run pytest $ARGS",
        "pytest -k $EXPR",
        "python3 -m pytest $ARGS",
        "make $TARGET",
        "ruff check $PATHS",
        "for f in $(ls src); do echo $f; done",
        "bash -c 'echo $HOME'",
        "grep 'foo$' src/app.py",
    ],
)
def test_dynamic_arguments_allowed_for_safe_programs(ctx, repo, command):
    assert rule(ctx, command) is None


def test_names_over_approximate_hidden_programs(ctx, repo):
    tokens = tokenize("timeout 5s cat x")
    assert ("cat", 2) in bashcheck._programs(tokens)
    for command, expected in [
        ("timeout 5s cat x", "cat"),
        ("env -u X cat x", "cat"),
        ("sudo -u root cat x", "cat"),
        ("nice -n 5 cat x", "cat"),
        ("timeout -k 5 10 cat x", "cat"),
        ("if cat x; then :; fi", "cat"),
        ("while cat x; do :; done", "cat"),
        ("until cat x; do :; done", "cat"),
        ("! cat x", "cat"),
        ("{ cat x; }", "cat"),
        ("echo `cat x`", "cat"),
        ("echo done; elif cat x", "cat"),
    ]:
        progs = {base for base, _ in bashcheck._programs(tokenize(command))}
        assert expected in progs, command


def test_names_union_known_tokens_and_words_in_dynamic_tokens():
    tokens = tokenize('x=1 echo "$(cat /dev/null)" arg/sed')
    names = bashcheck._all_names(tokens, bashcheck._programs(tokens))
    assert {"echo", "cat", "sed"} <= names


def test_wrapper_options_do_not_hide_the_program():
    for command in (
        "nohup -- cat x",
        "xargs -n 1 cat",
        "xargs -I {} cat {}",
        "sudo -n cat x",
        "time -p cat x",
        "env -i cat x",
        "command -v cat",
    ):
        progs = {base for base, _ in bashcheck._programs(tokenize(command))}
        assert "cat" in progs, command


def test_eval_is_analysed_like_bash_c(ctx, repo):
    repo.write("notes")
    assert rule(ctx, "eval 'cat notes'") == "untracked"
    assert rule(ctx, "eval cat notes") == "untracked"
    assert rule(ctx, "eval echo hello") is None
    repo.write("tools/guard/guard.py", track=True)
    assert rule(ctx, "eval 'rm tools/guard/guard.py'") == "self-protect"


# -- B1: bare words ---------------------------------------------------------------------------


def test_bare_words_naming_existing_files_are_checked(ctx, repo):
    repo.write("notes")
    assert rule(ctx, "python3 -c \"print(open('notes').read())\"") == "untracked"
    assert rule(ctx, "awk 'BEGIN{while((getline l < \"notes\")>0) print l}'") == "untracked"
    assert rule(ctx, "echo see notes now") == "untracked"
    assert rule(ctx, "echo see README now") is None
    assert rule(ctx, "echo see nothing-here now") is None
    assert rule(ctx, "python3 -c \"print(open('README.md').read())\"") is None
