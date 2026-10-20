"""Hook decision logic and entry points."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

from . import bashcheck
from .config import HEADER_REL, ConfigError, load_config, resolve_root
from .lint import HINT, check_staged, check_text
from .names import RG_DATA_TYPES, data_suffix, protected_string
from .policy import (
    PROTECTED_MSG,
    UNTRACKED_RECURSE_MSG,
    Context,
    Denial,
    has_untracked_below,
    suffix_message,
    under,
    walks_closed_zone,
)
from .store import Ledger, log_denial

GUARD_DIR = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "guard.py",
    "run-guard.sh",
    "recall_guard/core.py",
    "recall_guard/policy.py",
    "recall_guard/bashcheck.py",
)

BASH_LIKE = frozenset({"Bash", "Monitor"})
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit", "Glob", "Grep", "LS"})
WRITERS = frozenset({"Edit", "Write", "NotebookEdit"})
PROMPT_TOOLS = frozenset({"Agent", "Task", "Workflow", "SendMessage"})
PATHISH_KEYS = (
    "file_path",
    "file_paths",
    "filePath",
    "path",
    "paths",
    "scriptPath",
    "root",
    "files",
    "from",
    "notebook_path",
)
PATHISH_SUFFIXES = ("path", "file", "dir", "directory")
PATHISH_NAMES = frozenset(
    {"source", "src", "dest", "destination", "target", "filename", "input", "output"}
)

AIRLOCK_WINDOW_MSG = (
    "Airlock window is open: no AI assistance is allowed until a human closes it "
    "(tools/guard/airlock close, run in a normal terminal)."
)


def _strings(value, depth: int = 0):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict) and depth < 3:
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif isinstance(value, (list, tuple)) and depth < 3:
        for item in value:
            yield from _strings(item, depth + 1)


def _text_rules(cfg, text) -> Denial | None:
    if not isinstance(text, str):
        return None
    suffix = data_suffix(text)
    if suffix:
        return Denial("suffix", suffix_message(cfg, suffix), suffix)
    hit = protected_string(text, cfg)
    if hit:
        return Denial("protected-ref", PROTECTED_MSG, hit)
    return None


def _lint_write(ctx: Context, tool: str, tin: dict, target: Path) -> Denial | None:
    cfg = ctx.cfg
    if not under(target, cfg.root):
        return None
    rel = target.relative_to(cfg.root).as_posix()
    if tool == "Write":
        new = tin.get("content")
        try:
            old = target.read_text(encoding="utf-8")
        except OSError:
            old = ""
    else:
        old, new = tin.get("old_string"), tin.get("new_string")
    findings = check_text(rel, str(old or ""), str(new or ""))
    if not findings:
        return None
    first = findings[0]
    return Denial(
        "lint",
        f"{first.path}:{first.line} writes output outside the sealed helper ({first.rule}). {HINT}",
        rel,
    )


def _is_repo_root(ctx: Context, path: Path) -> bool:
    return path == ctx.cfg.root or Path(os.path.realpath(path)) == ctx.cfg.root


def _walk_directory(ctx: Context, value, untracked: bool) -> Denial | None:
    """A Grep/LS rooted at a directory that is, or contains, a closed zone would walk into it.

    Applies to any existing directory that equals or is an ancestor of a closed zone (ancestors
    of the repo root and of an external sealed root included) except the repo root itself, which
    honours .gitignore. With untracked=True (Grep reads content) an explicit directory that holds
    files the agent may not read is refused too.
    """
    if not isinstance(value, str) or not value:
        return None
    lex = ctx.lexical(value)
    for cand in (lex, Path(os.path.realpath(lex))):
        if _is_repo_root(ctx, cand) or not cand.is_dir():
            continue
        denial = walks_closed_zone(ctx, cand)
        if denial:
            return denial
    scan = untracked and under(lex, ctx.cfg.root) and lex.is_dir() and not _is_repo_root(ctx, lex)
    if scan and has_untracked_below(ctx, lex):
        return Denial("recursive-over-untracked", UNTRACKED_RECURSE_MSG, ctx.display(lex))
    return None


_GLOB_CHARS = frozenset("*?[")
_MAX_GLOB_DIRS = 500


def _glob_directories(ctx: Context, pattern, base_value) -> Denial | None:
    """Walk a Glob pattern's directory components: literal prefix, expanded wildcards, `**`."""
    if not isinstance(pattern, str) or not pattern:
        return None
    base = ctx.lexical(base_value) if isinstance(base_value, str) and base_value else ctx.cwd
    expanded = os.path.expanduser(pattern)
    dirs = [Path("/")] if expanded.startswith("/") else [base]
    comps = [c for c in expanded.split("/") if c not in ("", ".")]
    for idx, comp in enumerate(comps):
        last = idx == len(comps) - 1
        if comp == "**":
            for directory in dirs:
                if not _is_repo_root(ctx, directory):
                    denial = walks_closed_zone(ctx, directory)
                    if denial:
                        return denial
            return None
        if last:
            return None
        variants = bashcheck._braces(comp)
        if variants is None:
            return Denial("brace-explosion", "A brace expression expands too far.", comp[:80])
        found = []
        for directory in dirs:
            for variant in variants:
                if _GLOB_CHARS & set(variant):
                    try:
                        entries = sorted(os.listdir(directory))
                    except OSError:
                        continue
                    found.extend(directory / e for e in entries if fnmatch.fnmatchcase(e, variant))
                else:
                    found.append(Path(os.path.normpath(directory / variant)))
        dirs = [d for d in found if d.is_dir()][:_MAX_GLOB_DIRS]
        for directory in dirs:
            denial = ctx.check_path(str(directory))
            if denial:
                return denial
    return None


def _file_tool(ctx: Context, tool: str, tin: dict) -> Denial | None:
    cfg = ctx.cfg
    writer = tool in WRITERS
    target = None
    for field in ("file_path", "notebook_path", "path"):
        value = tin.get(field)
        if not isinstance(value, str) or not value:
            continue
        if writer and not cfg.dev_mode:
            denial = ctx.self_protect_check(value)
            if denial:
                return denial
        denial = ctx.check_path(value, write=writer)
        if denial:
            return denial
        if writer and field != "path":
            target = ctx.lexical(value)

    if tool == "Glob":
        denial = _text_rules(cfg, tin.get("pattern"))
        if denial:
            return denial
        denial = _glob_directories(ctx, tin.get("pattern"), tin.get("path"))
        if denial:
            return denial
    if tool == "LS":
        denial = _walk_directory(ctx, tin.get("path"), untracked=False)
        if denial:
            return denial
    if tool == "Grep":
        denial = _text_rules(cfg, tin.get("glob"))
        if denial:
            return denial
        denial = _walk_directory(ctx, tin.get("path"), untracked=True)
        if denial:
            return denial
        if str(tin.get("type") or "").lower() in RG_DATA_TYPES:
            return Denial("suffix", suffix_message(cfg, "data-type search"), "type")

    if target is not None:
        if tool in ("Write", "Edit"):
            denial = _lint_write(ctx, tool, tin, target)
            if denial:
                return denial
        ctx.ledger.record_new_file(target)
    return None


def _pathish(key) -> bool:
    if not isinstance(key, str):
        return False
    if key in PATHISH_KEYS:
        return True
    low = key.lower()
    return low in PATHISH_NAMES or low.endswith(PATHISH_SUFFIXES)


def _generic(ctx: Context, tin: dict) -> Denial | None:
    base = None
    root = tin.get("root")
    if isinstance(root, str) and root and "\n" not in root:
        base = ctx.lexical(root)
    for key, value in tin.items():
        if not _pathish(key):
            continue
        for text in _strings(value):
            if text and len(text) < 4096 and "\n" not in text:
                use = base if key == "files" else None
                denial = ctx.check_path(text, base=use)
                if denial:
                    return denial
    # any other string, under any key, that is shaped like a path or a file:// URL
    for text in _strings(tin):
        if (
            0 < len(text) < 4096
            and text.startswith(("file://", "~", "/"))
            and not any(ch.isspace() for ch in text)
        ):
            denial = ctx.check_path(text[7:] if text.startswith("file://") else text)
            if denial:
                return denial
    return None


def decide(cfg, payload: dict) -> Denial | None:
    tool = payload.get("tool_name", "") or ""
    tin = payload.get("tool_input")
    if not isinstance(tin, dict):
        tin = {}
    if cfg.airlock_marker.exists():
        return Denial("airlock", AIRLOCK_WINDOW_MSG)
    ctx = Context(cfg, payload.get("cwd"), str(payload.get("session_id") or ""))
    if tool in BASH_LIKE:
        return bashcheck.analyse(ctx, str(tin.get("command") or ""))
    if tool in FILE_TOOLS:
        return _file_tool(ctx, tool, tin)
    if tool in PROMPT_TOOLS:
        hit = protected_string(json.dumps(tin), cfg)
        if hit:
            return Denial(
                "protected-ref",
                "Subagent and workflow prompts must not name protected locations: they are "
                "AI readers too.",
                hit,
            )
    return _generic(ctx, tin)


def run_payload(raw: str, cfg) -> tuple:
    """(tool name, Denial or None). Never raises: a guard bug denies the call."""
    if cfg.airlock_marker.exists():
        return "", Denial("airlock", AIRLOCK_WINDOW_MSG)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (ValueError, RecursionError):
        return "", Denial(
            "unparseable",
            "The guard could not parse this call (expected a JSON object). Denied to fail safe.",
        )
    tool = str(payload.get("tool_name", ""))
    try:
        return tool, decide(cfg, payload)
    except Exception as exc:  # fail closed on a guard bug, for this call only
        return tool, Denial(
            "internal-error",
            f"The guard failed on this call ({type(exc).__name__}). Denied to fail safe; a "
            "human can run `python3 tools/guard/guard.py --selfcheck` and check the audit log.",
        )


def emit_deny(denial: Denial) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"recall guard [{denial.rule}]: {denial.reason}",
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


CONFIG_ERROR_FIX = (
    "Fix or delete .claude/guard.local.json (a JSON object whose 'extra_allowed' and "
    "'extra_protected' are lists of path strings); every call is denied until then."
)


def _main_without_config(argv: list, message: str) -> int:
    """The override file is unusable: deny hook calls, report the rest, never crash."""
    text = f"{message}. {CONFIG_ERROR_FIX}"
    if "--selfcheck" in argv:
        return _report_problems([text])
    if "--explain" in argv:
        print(f"DENY [config-error] {text}")
        return 2
    if "--lint-staged" in argv:
        return cmd_lint_staged(resolve_root())
    emit_deny(Denial("config-error", text))
    return 0


def main(argv: list) -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        return _main_without_config(argv, str(exc))
    if "--selfcheck" in argv:
        return cmd_selfcheck(cfg)
    if "--explain" in argv:
        return cmd_explain(cfg, argv)
    if "--lint-staged" in argv:
        return cmd_lint_staged(cfg.root)
    tool, denial = run_payload(sys.stdin.read(), cfg)
    if denial:
        emit_deny(denial)  # first: logging must never be able to suppress the reason
        sys.stdout.flush()
        log_denial(cfg, tool, denial.rule, denial.path)
    return 0


def _registered(root: Path) -> bool:
    for name in ("settings.json", "settings.local.json"):
        try:
            settings = json.loads((root / ".claude" / name).read_text(encoding="utf-8"))
            hooks = settings.get("hooks", {}).get("PreToolUse", [])
        except (OSError, ValueError, AttributeError, RecursionError):
            continue
        if "run-guard.sh" in json.dumps(hooks):
            return True
    return False


def selfcheck(cfg) -> list:
    """Human-readable problems with the guard installation (empty list = healthy)."""
    problems = []
    for rel in REQUIRED_FILES:
        if not (GUARD_DIR / rel).exists():
            problems.append(f"guard file missing: tools/guard/{rel}")
    if not _registered(cfg.root):
        problems.append("hook not registered in .claude/settings.json (PreToolUse)")
    if cfg.header_line() is None:
        problems.append(
            f"{HEADER_REL} missing or empty: agents have no export schema to read instead"
        )
    hooks_path = subprocess.run(
        ["git", "-C", str(cfg.root), "config", "--local", "core.hooksPath"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if hooks_path != ".githooks":
        problems.append("core.hooksPath is not .githooks: run `make guard-install`")
    if cfg.airlock_marker.exists():
        problems.append("airlock window is open: every tool call will be denied")
    return problems


def explain(cfg, path: str, cwd=None) -> str:
    denial = Context(cfg, cwd=cwd, session_id="explain").check_path(path)
    return "ALLOW" if denial is None else f"DENY [{denial.rule}] {denial.reason}"


def cmd_selfcheck(cfg) -> int:
    Ledger.cleanup(cfg)
    return _report_problems(selfcheck(cfg))


def _report_problems(problems: list) -> int:
    if problems:
        text = "recall guard self-check found problems:\n- " + "\n- ".join(problems)
        json.dump(
            {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
            sys.stdout,
        )
        sys.stdout.write("\n")
        print(text, file=sys.stderr)
    return 0


def cmd_explain(cfg, argv: list) -> int:
    index = argv.index("--explain")
    if index + 1 >= len(argv):
        print("usage: guard.py --explain <path>", file=sys.stderr)
        return 2
    print(explain(cfg, argv[index + 1], cwd=Path.cwd()))
    return 0


def cmd_lint_staged(root: Path) -> int:
    findings = check_staged(root)
    for f in findings:
        print(f"{f.path}:{f.line}: [{f.rule}] {f.text}")
    if findings:
        print(HINT, file=sys.stderr)
    return 1 if findings else 0
