import pytest
from recall_guard.names import data_suffix, protected_string

BLOCKED = [
    "cat a/x.csv|head",
    "cat x.csv;ls",
    "wc -l <x.csv",
    "x.csv>out",
    "x.csv,y",
    "x.csv)",
    "X.CSV.gz",
    "a.tsv",
    "b.parquet",
    "c.jsonl",
    "d.xlsx",
    "d.xls",
    "e.npy",
    "e.npz",
    "f.syn",
    "g.pkl",
    "open('data.csv')",
    "cmd --out=y/z.csv --flag",
]

ALLOWED = [
    "x.csvfoo",
    "a.csv_old",
    "notes.md",
    "csv_reader.py",
    "docs/csv.md",
    "src/recall/profile.json",
    "local/artifacts/profile_report.md",
    "git status",
]


@pytest.mark.parametrize("text", BLOCKED)
def test_blocked(text):
    assert data_suffix(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_allowed(text):
    assert data_suffix(text) is None


def test_returns_lowercased_match():
    assert data_suffix("X.CSV.GZ") == ".csv.gz"


def test_protected_string_variants(cfg, repo):
    root = repo.root.resolve()
    assert protected_string(f"cat {root}/local/sealed/a", cfg)
    assert protected_string("cat local/sealed/a", cfg)
    assert protected_string("ls local/quarantine", cfg)
    assert protected_string("cat /data/recall-quarantine/x", cfg)
    assert protected_string("git status", cfg) is None
    assert protected_string("cat local/artifacts/gate_report.json", cfg) is None
