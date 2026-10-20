import json
import os
import time

from recall_guard.store import Ledger, ensure_sealed, log_denial


def test_ensure_sealed_marks_root_and_dir(cfg):
    target = cfg.sealed_root / "ledger"
    ensure_sealed(target, cfg)
    assert (cfg.sealed_root / ".sealed").exists()
    assert (target / ".sealed").exists()


def test_ledger_records_new_file_and_missing_parents(cfg, repo):
    ledger = Ledger(cfg, "s1")
    new = repo.root / "scratch" / "deep" / "new.py"
    ledger.record_new_file(new)
    assert ledger.contains(new)
    assert ledger.contains(repo.root / "scratch" / "deep")
    # intentionally changed (Task 8b, F): entries are exact, no inheritance into the directory
    assert not ledger.contains(repo.root / "scratch" / "deep" / "later.txt")
    assert not ledger.contains(repo.root / "other" / "x.py")


def test_ledger_loads_once_and_add_updates_the_cache(cfg, repo):
    ledger = Ledger(cfg, "cache")
    first = repo.root / "scratch" / "a.py"
    ledger.record_new_file(first)
    assert ledger.contains(first)
    ledger.path.unlink()  # a re-read would now find nothing
    assert ledger.contains(first)
    second = repo.root / "scratch" / "b.py"
    ledger.add(second)
    assert ledger.contains(second) and ledger.contains(first)


def test_ledger_add_is_atomic_and_leaves_no_temp_files(cfg, repo):
    ledger = Ledger(cfg, "atomic")
    ledger.add(repo.root / "x1", repo.root / "x2")
    assert sorted(p.name for p in ledger.path.parent.iterdir() if p.name != ".sealed") == [
        "atomic.json"
    ]
    assert json.loads(ledger.path.read_text(encoding="utf-8")) == [
        str(repo.root / "x1"),
        str(repo.root / "x2"),
    ]


def test_ensure_sealed_root_is_mode_700(cfg):
    ensure_sealed(cfg.sealed_root / "ledger", cfg)
    assert (cfg.sealed_root.stat().st_mode & 0o777) == 0o700
    assert ((cfg.sealed_root / "ledger").stat().st_mode & 0o777) == 0o700


def test_ledger_ignores_existing_files(cfg, repo):
    existing = repo.write("notes/old.txt")
    ledger = Ledger(cfg, "s1")
    ledger.record_new_file(existing)
    assert not ledger.contains(existing)


def test_ledger_is_per_session(cfg, repo):
    new = repo.root / "scratch" / "a.py"
    Ledger(cfg, "s1").record_new_file(new)
    assert not Ledger(cfg, "s2").contains(new)


def test_ledger_sanitises_session_id(cfg):
    ledger = Ledger(cfg, "../../evil")
    assert ledger.path.parent == cfg.sealed_root / "ledger"


def test_ledger_cleanup_removes_old_files(cfg, repo):
    ledger = Ledger(cfg, "old")
    ledger.record_new_file(repo.root / "scratch" / "a.py")
    old = time.time() - 3 * 86400
    os.utime(ledger.path, (old, old))
    Ledger.cleanup(cfg, max_age_s=86400)
    assert not ledger.path.exists()


def test_log_denial_caps_path_and_strips_control_characters(cfg):
    log_denial(cfg, "Bash", "suffix", "a" * 5000)
    log_denial(cfg, "Bash", "suffix", "line1\nline2\x00\rend")
    lines = (cfg.sealed_root / "guard.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert len(json.loads(lines[0])["path"]) <= 200
    second = json.loads(lines[1])["path"]
    assert all(ch.isprintable() for ch in second)


def test_log_denial_writes_json_line_without_payload(cfg):
    log_denial(cfg, "Bash", "suffix", "data/x.csv")
    lines = (cfg.sealed_root / "guard.log").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert entry["tool"] == "Bash"
    assert entry["rule"] == "suffix"
    assert entry["path"] == "data/x.csv"
    assert set(entry) == {"ts", "tool", "rule", "path"}
