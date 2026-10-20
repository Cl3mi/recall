import pytest
from recall_guard.lint import added_lines, check_staged, check_text, in_scope


@pytest.mark.parametrize(
    "line,rule",
    [
        ('open(p, "w")', "open-write"),
        ("open(p, 'ab')", "open-write"),
        ("logging.FileHandler(f)", "file-handler"),
        ("path.write_text(x)", "path-write"),
        ("df.to_csv('a')", "table-dump"),
        ("np.save(f, a)", "array-dump"),
        ("json.dump(obj, fh)", "serialise-dump"),
        ("print(row)", "print-rows"),
        ("h = RotatingFileHandler(f)", "file-handler"),
        ("logging.basicConfig(level=1, filename=f)", "file-handler"),
        ('open(os.path.join(a, b), "w")', "open-write"),
        ('p.open("w")', "open-write"),
        ("p.open('wb')", "open-write"),
    ],
)
def test_flags_output_writers(line, rule):
    findings = check_text("src/recall/mod.py", "", line + "\n")
    assert [f.rule for f in findings] == [rule]


@pytest.mark.parametrize(
    "line",
    [
        'open(p, "r")',
        'p.open("r")',
        "x = json.dumps(a)",
        'print("hello")',
        'open(p, "w")  # guard: ok(synthetic fixture)',
        "from recall.sealed import sealed_logger",
    ],
)
def test_passes_safe_lines(line):
    assert check_text("src/recall/mod.py", "", line + "\n") == []


def test_only_added_lines_count():
    old = 'open(p, "w")\nx = 1\n'
    new = 'open(p, "w")\nx = 2\n'
    assert check_text("src/recall/mod.py", old, new) == []
    assert [n for n, _ in added_lines(old, new)] == [2]


def test_scope():
    assert in_scope("src/recall/mod.py")
    assert in_scope("profiler/x.py")
    assert in_scope("insight/x.py")
    assert in_scope("fixtures/generate.py")
    assert not in_scope("tests/unit/test_x.py")
    assert not in_scope("tools/guard/x.py")
    assert not in_scope("src/recall/sealed.py")
    assert not in_scope("src/recall/notes.md")
    assert check_text("tests/unit/test_x.py", "", 'open(p, "w")\n') == []


def test_finding_carries_location(repo):
    f = check_text("src/recall/mod.py", "", "a = 1\nopen(p, 'w')\n")[0]
    assert (f.path, f.line, f.rule) == ("src/recall/mod.py", 2, "open-write")


def test_check_staged_flags_added_lines_and_data_files(repo):
    repo.write("src/m.py", 'open(p, "w")\n', track=True)
    repo.write("data/x.csv", "a\n", track=True)
    findings = check_staged(repo.root)
    assert {(f.path, f.rule) for f in findings} == {
        ("src/m.py", "open-write"),
        ("data/x.csv", "data-file"),
    }


def test_check_staged_clean_repo(repo):
    assert check_staged(repo.root) == []


def test_check_staged_flags_file_with_spaces(repo):
    repo.write("src/my file.py", 'open(p, "w")\n', track=True)
    findings = check_staged(repo.root)
    assert [(f.path, f.line, f.rule) for f in findings] == [("src/my file.py", 1, "open-write")]


def test_check_staged_flags_non_ascii_name(repo):
    repo.write("src/münchen.py", "x = 1\nopen(p, 'w')\n", track=True)
    findings = check_staged(repo.root)
    assert [(f.path, f.line, f.rule) for f in findings] == [("src/münchen.py", 2, "open-write")]


def test_check_staged_flags_rename_onto_data_suffix(repo):
    repo.write("data/plain.txt", "a\n", track=True)
    repo.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    repo.git("mv", "data/plain.txt", "data/renamed" + ".csv")
    findings = check_staged(repo.root)
    assert {(f.path, f.rule) for f in findings} == {("data/renamed.csv", "data-file")}


@pytest.mark.parametrize(
    "line,rule",
    [
        ('open(p, mode="w")', "open-write"),
        ("open(p, mode='ab')", "open-write"),
        ("df.to_excel('a')", "table-dump"),
        ("df.to_feather(f)", "table-dump"),
        ("df.to_sql('t', con)", "table-dump"),
        ("df.to_hdf(f, 'k')", "table-dump"),
        ("df.to_stata(f)", "table-dump"),
        ("df.to_orc(f)", "table-dump"),
        ("arr.tofile(f)", "array-dump"),
        ("shutil.copy(a, b)", "copy-out"),
        ("shutil.copy2(a, b)", "copy-out"),
        ("shutil.copyfile(a, b)", "copy-out"),
        ("shutil.move(a, b)", "copy-out"),
        ("print(x, file=fh)", "print-rows"),
    ],
)
def test_flags_extra_output_writers(line, rule):
    findings = check_text("src/recall/mod.py", "", line + "\n")
    assert [f.rule for f in findings] == [rule]


@pytest.mark.parametrize(
    "line",
    [
        'open(p, mode="r")',
        "df.to_string()",
        "shutil.rmtree(d)",
        "shutil.copytree_x(a)",
        "print(x, flush=True)",
        "arr.tolist()",
    ],
)
def test_extra_rules_negatives(line):
    assert check_text("src/recall/mod.py", "", line + "\n") == []
