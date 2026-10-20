"""Analysis of Bash command text: paths, programs, scripts, git, self-protection."""

from __future__ import annotations

import glob
import itertools
import os
import re
import shlex
from pathlib import Path

from .config import TOOLING_NAMES
from .names import data_suffix, protected_string
from .policy import (
    PROTECTED_MSG,
    SELF_MSG,
    UNTRACKED_RECURSE_MSG,
    Context,
    Denial,
    has_untracked_below,
    suffix_message,
    under,
    walks_closed_zone,
)

EXTRACTORS = frozenset(
    {
        "pdftotext",
        "pdfimages",
        "pdftoppm",
        "pdftocairo",
        "pdfplumber",
        "mutool",
        "libreoffice",
        "soffice",
        "ssconvert",
        "in2csv",
        "xlsx2csv",
        "csvlook",
        "antiword",
        "catdoc",
        "tesseract",
        "ocrmypdf",
        "qpdf",
        "gs",
    }
)
READERS = frozenset(
    {
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "awk",
        "sed",
        "cut",
        "sort",
        "uniq",
        "wc",
        "xxd",
        "od",
        "hexdump",
        "strings",
        "bat",
        "tac",
        "nl",
        "paste",
        "column",
        "jq",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
        "cp",
        "mv",
        "scp",
        "rsync",
        "tar",
        "zip",
        "gzip",
        "gunzip",
        "zcat",
        "base64",
        "diff",
        "cmp",
        "split",
        "tee",
    }
)
RECURSIVE = frozenset(
    {
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ag",
        "ack",
        "tar",
        "zip",
        "7z",
        "rsync",
        "cp",
        "scp",
        "cpio",
        "pax",
        "bsdtar",
    }
)
MUTATORS = frozenset(
    {
        "rm",
        "mv",
        "cp",
        "tee",
        "chmod",
        "chown",
        "ln",
        "truncate",
        "dd",
        "install",
        "patch",
        "rmdir",
        "shred",
        "touch",
        "ed",
        "rsync",
        "tar",
        "unzip",
        "curl",
        "wget",
        "mkdir",
        "sponge",
        "cpio",
        "pax",
        "bsdtar",
    }
)
DESTRUCTIVE = frozenset({"rm", "mv", "rmdir", "shred"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
MAX_DEPTH = 3
_MAX_BRACE = 64
_MAX_PIECES = 200
_PATHLIKE = re.compile(r"[A-Za-z0-9_.~+\-]*[/.][A-Za-z0-9_./~+\-]*")
_WORD = re.compile(r"[A-Za-z0-9_.+\-]+")
_BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")
_PATTERN_FIRST = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack"})
# `git ls-files` is the one blessed xargs source; the -o/--others forms list untracked files
_GIT_LS_FILES = re.compile(r"\bgit\s+ls-files\b(?![^|;&]*\s(-[A-Za-z]*o|--others|--other))")
_PATTERN_FLAG = re.compile(r"^-[A-Za-z]*[ef]$")
GIT_MUTATING = frozenset(
    {
        "checkout",
        "restore",
        "rm",
        "mv",
        "reset",
        "stash",
        "apply",
        "clean",
        "revert",
        "am",
        "merge",
        "rebase",
        "pull",
        "switch",
        "cherry-pick",
        "checkout-index",
        "read-tree",
        "sparse-checkout",
    }
)
SCRIPT_RUNNERS = frozenset(
    {"python", "python3", "bash", "sh", "zsh", "dash", "ksh", "node", "perl", "ruby", "source", "."}
)
# Every program name the guard has an opinion about. `names` is an over-approximation: a
# command-position program, plus any token (or word inside a dynamic token) that is one of these.
KNOWN = READERS | MUTATORS | RECURSIVE | EXTRACTORS | SCRIPT_RUNNERS | {"git", "eval", "find"}
# Programs that may take $VAR / $(...) / backtick arguments: they cannot print file content
# (echo and friends), only list names (ls), or run reviewed repo code (git after its policy,
# make, pytest, ruff, uv). Everything else with an unresolved argument is denied (dynamic-path).
# Shell keywords are listed because they surface as command-position words.
SAFE_DYNAMIC = frozenset(
    {
        "echo",
        "printf",
        "cd",
        "pushd",
        "popd",
        "ls",
        "mkdir",
        "pwd",
        "export",
        "unset",
        "test",
        "[",
        "[[",
        "true",
        "false",
        "sleep",
        "date",
        "which",
        "git",
        "uv",
        "make",
        "pytest",
        "ruff",
        "for",
        "done",
        "fi",
        "esac",
        "case",
        "select",
        "function",
        "read",
        "set",
    }
)
WRAPPERS = frozenset(
    {
        "uv",
        "run",
        "env",
        "sudo",
        "time",
        "nohup",
        "exec",
        "command",
        "nice",
        "timeout",
        "xargs",
        "builtin",
        "ionice",
        "setsid",
        "stdbuf",
    }
)
# Options of each wrapper that consume the next token as their value.
_WRAPPER_VALUE_OPTS = {
    "sudo": frozenset(
        {"-u", "-g", "-D", "-C", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group"}
    ),
    "env": frozenset({"-u", "-C", "-S", "--unset", "--chdir"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-k", "-s", "--kill-after", "--signal"}),
    "xargs": frozenset({"-n", "-I", "-L", "-P", "-d", "-s", "-E", "-a"}),
    "ionice": frozenset({"-c", "-n", "-p", "-t"}),
    "time": frozenset({"-f", "-o"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
}
_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
_KEYWORDS = frozenset({"if", "while", "until", "elif", "then", "do", "else", "!", "{", "}"})
_STARTERS = frozenset({";", "|", "&&", "||", "&", "|&", "(", *_KEYWORDS})
_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
_PYTHON = re.compile(r"^python[\d.]*$")
_FIND_EXEC = frozenset({"-exec", "-execdir", "-ok"})
_MAX_SCRIPT_BYTES = 262144
_MAX_GLOB = 500
# `$` followed by one of these starts an expansion; a bare `$` (e.g. a regex anchor) does not.
_DYNAMIC = re.compile(r"\$[A-Za-z_0-9{(@*#?!$'\"-]|`")
_HOME_VAR = re.compile(r"\$(HOME\b|\{HOME\})")

AIRLOCK_MSG = (
    "The airlock window CLI and its marker can only be used by a human in a normal terminal."
)
GIT_POLICY_MSG = (
    "This git form can print or stage untracked files, or change what git executes. Use plain "
    "git status/diff/log/show/grep, or ask a human."
)
GIT_ADD_MSG = (
    "Agents may only stage explicit files they can already read (tracked, or created this "
    "session): no directories, `.`, globs, $VARS, -A, -f, -u, -N, -p, -i or -e. A human runs "
    "`git add -N <path>` or `git add -A`."
)
DYNAMIC_MSG = (
    "A command uses a path the guard cannot resolve ($VAR, $(...) or backticks) and is not "
    "one of the programs known to be safe with such arguments. Write the path out literally."
)
_GIT_ADD_LONG_OK = frozenset(
    {"--verbose", "--dry-run", "--ignore-errors", "--ignore-missing", "--chmod"}
)
_GIT_DENY_SUBS = frozenset({"update-index", "stash", "apply", "hash-object", "fast-import"})
_GIT_CONFIG_RISKY = (
    "hookspath",
    "hooks",
    "fsmonitor",
    "alias",
    "sshcommand",
    "pager",
    "editor",
    "askpass",
    "program",
    "external",
    "textconv",
    "helper",
    "include",
    "filter",
    "tool",
    "cmd",
)


def _is_punct(token: str) -> bool:
    return bool(token) and all(ch in "();<>|&" for ch in token)


def _tokenize(command: str) -> tuple:
    """(tokens, ok). ok is False when the shell-aware lexer failed and a crude split was used."""
    text = command.replace("\n", " ; ")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # treat comments as code: stricter than the shell
        return list(lexer), True
    except ValueError:
        return [t for t in re.split(r"[\s;|&<>()]+", text) if t], False


def tokenize(command: str) -> list:
    """Shell-aware split that also separates ; | && < > ( ) from adjacent words."""
    return _tokenize(command)[0]


def _skip_wrapper_option(tokens: list, i: int, wrapper: str) -> int:
    """Index after the option at i (and its value, if this wrapper's option takes one)."""
    token = tokens[i]
    i += 1
    takes_value = token in _WRAPPER_VALUE_OPTS.get(wrapper, ())
    if takes_value and i < len(tokens) and not _is_punct(tokens[i]):
        i += 1
    return i


def _effective(tokens: list, start: int) -> tuple:
    """(program basename, token index) at a command position, skipping wrappers and flags."""
    i = start
    wrapper = ""
    while i < len(tokens):
        token = tokens[i]
        if _is_punct(token):
            return "", i
        bare = token.lstrip("`")
        base = os.path.basename(bare)
        if not bare or token in _KEYWORDS:
            i += 1
            continue
        if base in WRAPPERS:
            wrapper = base
            i += 1
            continue
        if token.startswith("-"):
            i = _skip_wrapper_option(tokens, i, wrapper)
            continue
        if _ASSIGN.match(bare) or token.isdigit() or (wrapper and _DURATION.match(token)):
            i += 1
            continue
        return base, i
    return "", i


def _programs(tokens: list) -> list:
    found = []
    for i in range(len(tokens)):
        if i == 0 or tokens[i - 1] in _STARTERS or tokens[i].startswith("`"):
            base, j = _effective(tokens, i)
            if base and (base, j) not in found:
                found.append((base, j))
    return found


def _is_dynamic(tokens: list, i: int) -> bool:
    token = tokens[i]
    if _DYNAMIC.search(_HOME_VAR.sub("", token)):
        return True
    return token == "$" and i + 1 < len(tokens) and tokens[i + 1] in ("(", "((")


def _all_names(tokens: list, programs: list) -> set:
    """Over-approximation of the programs a command may run (see KNOWN)."""
    names = {base for base, _ in programs}
    for i, token in enumerate(tokens):
        if _is_punct(token):
            continue
        base = os.path.basename(token.lstrip("`").rstrip("`"))
        if base in KNOWN:
            names.add(base)
        if _is_dynamic(tokens, i) or "`" in token:
            names.update(w for w in re.findall(r"[A-Za-z_]+", token) if w in KNOWN)
    return names


def _is_pytest_module(tokens: list, j: int) -> bool:
    return tokens[j + 1 : j + 3] == ["-m", "pytest"]


def _unsafe_for_dynamic(tokens: list, programs: list, names: set) -> set:
    """Names that are not safe with unresolved arguments (python -m pytest counts as pytest)."""
    unsafe = {n for n in names if n not in SAFE_DYNAMIC}
    pythons = [i for i, t in enumerate(tokens) if _PYTHON.match(os.path.basename(t))]
    pytest_forms = {
        j for base, j in programs if _PYTHON.match(base) and _is_pytest_module(tokens, j)
    }
    if pythons and all(i in pytest_forms for i in pythons):
        unsafe = {n for n in unsafe if not _PYTHON.match(n)}
    return unsafe


def _is_runner(base: str) -> bool:
    return base in SCRIPT_RUNNERS or bool(_PYTHON.match(base))


def _candidates(token: str) -> list:
    if token.startswith("-") and "=" not in token:
        return []
    if "=" in token:
        return [token.split("=", 1)[1]]
    return [token]


class GlobTooLarge(Exception):
    """A glob matched more paths than the guard will check (a truncated list is unsafe)."""


def _expand(ctx: Context, value: str, cur: Path) -> list:
    if not value or _is_punct(value):
        return []
    if any(ch in value for ch in "*?["):
        pattern = str(ctx.lexical(value, cur))
        # islice stops an unbounded `**` walk at the cap; one extra item proves overflow
        found = list(itertools.islice(glob.iglob(pattern, recursive=True), _MAX_GLOB + 1))
        if len(found) > _MAX_GLOB:
            raise GlobTooLarge(value)
        return sorted(found)
    if "/" in value or "." in value or os.path.lexists(ctx.lexical(value, cur)):
        return [value]
    return []


def _in_place(tokens: list, names: set) -> bool:
    flags = [t for t in tokens if t.startswith("-")]
    if "sed" in names and any(t.startswith("-i") or t == "--in-place" for t in flags):
        return True
    if "perl" in names and any(re.match(r"^-[A-Za-z]*i", t) for t in flags):
        return True
    return "awk" in names and any(t == "-i" or t.startswith("-i=") for t in flags)


def _pieces(token: str) -> list:
    """Path-like substrings and bare words of a token (prose, -c code, URLs), file:// stripped.

    Bare words are returned unfiltered; the caller keeps only those that exist on disk.
    """
    text = token.replace("file://", "")
    out = []
    for match in _PATHLIKE.findall(text):
        variants = [match]
        trimmed = match.rstrip(".")
        if trimmed != match and ("/" in trimmed or "." in trimmed):
            variants.append(trimmed)
        for piece in variants:
            if piece and piece not in out:
                out.append(piece)
        if len(out) >= _MAX_PIECES:
            return out
    for word in _WORD.findall(text):
        if word and len(word) <= 255 and word not in out:
            out.append(word)
        if len(out) >= _MAX_PIECES:
            break
    return out


def _braces(token: str):
    """Brace-expanded variants of a token, or None if the expansion would be too large."""
    if any(ch.isspace() for ch in token) or "{" not in token:
        return [token]
    out = [token]
    while True:
        grown = []
        changed = False
        for item in out:
            match = _BRACE.search(item)
            if match:
                changed = True
                for alt in match.group(1).split(","):
                    grown.append(item[: match.start()] + alt + item[match.end() :])
            else:
                grown.append(item)
        out = grown
        if len(out) > _MAX_BRACE:
            return None
        if not changed:
            return out


def _code_strings(tokens: list, programs: list) -> list:
    """(kind, code) for every `-c`/`-e` style inline program; kind is 'shell' or 'interp'."""
    found = []
    for base, j in programs:
        if base == "eval":
            args = _segment_args(tokens, j)
            if args:
                found.append(("shell", " ".join(args)))
            continue
        if base in SHELLS:
            kind, flag = "shell", re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
        elif _PYTHON.match(base):
            kind, flag = "interp", re.compile(r"^-[A-Za-z]*c$")
        elif base in ("perl", "ruby"):
            kind, flag = "interp", re.compile(r"^-[A-Za-z]*[eE]$")
        elif base == "node":
            kind, flag = "interp", re.compile(r"^(-[A-Za-z]*[ep]|--eval|--print)$")
        else:
            continue
        k = j + 1
        while k < len(tokens) and not _is_punct(tokens[k]):
            if flag.match(tokens[k]) and k + 1 < len(tokens) and not _is_punct(tokens[k + 1]):
                found.append((kind, tokens[k + 1]))
                k += 1
            k += 1
    return found


def _under_protected(ctx: Context, text: str) -> Path | None:
    cands = _candidates(text) + _pieces(text)
    for cand in cands:
        if not cand or _is_punct(cand) or "$" in cand:
            continue
        lex = ctx.lexical(cand)
        if ctx.self_hit(lex):
            return lex
    return None


def _self_mention(ctx: Context, text: str) -> str | None:
    """A spelling of a self-protected path found verbatim in text (heredocs, script bodies)."""
    cfg = ctx.cfg
    home = os.path.expanduser("~")
    for path in cfg.self_protected():
        forms = {str(path)}
        if under(path, cfg.root):
            forms.add(path.relative_to(cfg.root).as_posix())
        elif home.startswith("/") and str(path).startswith(home + "/"):
            forms.add("~" + str(path)[len(home) :])
            forms.add("$HOME" + str(path)[len(home) :])
        for form in forms:
            if form in text:
                return form
    return None


def _touches_self_protected(ctx: Context, lex: Path, role: str, is_whole: bool) -> bool:
    """lex is, is inside, or (as a destination or a deletion) contains a self-protected path.

    role is "doomed" (operand of rm/mv/rmdir/shred), "dest" (last operand or -C/-d value of a
    mutating program) or "" (anything else: reading an ancestor directory is fine).
    """
    if ctx.self_hit(lex):
        return True
    cfg = ctx.cfg
    if (
        not is_whole
        or not role
        or not any(under(p, lex) and p != lex for p in cfg.self_protected())
    ):
        return False  # only a whole argument can be the directory being deleted or filled
    # lex is an ancestor of a protected path: deleting or moving it takes the guard with it, and
    # extracting or copying into it can overwrite the guard.
    if role == "doomed":
        return True
    if lex == cfg.root:
        return False
    home = Path(os.path.expanduser("~"))
    return under(lex, cfg.root) or (home.is_absolute() and lex != home and under(lex, home))


_DEST_OPTS = frozenset(
    {"-C", "-d", "-t", "-D", "--directory", "--target-directory", "--to-directory"}
)


def _roles(tokens: list, programs: list) -> dict:
    """Token index -> "doomed" or "dest" for operands of deleting / mutating programs."""
    out: dict = {}
    for base, j in programs:
        if base not in MUTATORS:
            continue
        last = None
        k = j + 1
        while k < len(tokens) and not _is_punct(tokens[k]) and tokens[k] not in _STARTERS:
            if tokens[k] in _DEST_OPTS and k + 1 < len(tokens):
                out.setdefault(k + 1, "dest")
            elif not tokens[k].startswith("-"):
                last = k
                if base in DESTRUCTIVE:
                    out[k] = "doomed"
            k += 1
        if last is not None:
            out.setdefault(last, "dest")
    return out


def _extracts_into_cwd(base: str, args: list) -> bool:
    """tar/unzip/cpio/patch run with no destination option write wherever the archive says."""
    if any(a in _DEST_OPTS or a.startswith(("--directory=", "-C")) for a in args):
        return False
    if base in ("tar", "bsdtar"):
        first = args[0] if args else ""
        return bool(
            re.match(r"^-?[A-Za-z]*x[A-Za-z]*$", first)
            or any(a in ("--extract", "--get") or re.match(r"^-[A-Za-z]*x", a) for a in args)
        )
    if base == "cpio":
        return any(a in ("--extract",) or re.match(r"^-[A-Za-z]*i", a) for a in args)
    return base in ("unzip", "patch")


def _mutating(command: str, tokens: list, names: set, lexed_ok: bool) -> bool:
    """Broad: a redirect or heredoc, a mutating program, an in-place edit or a mutating git."""
    for k, token in enumerate(tokens):
        if not _is_punct(token):
            continue
        following = tokens[k + 1] if k + 1 < len(tokens) else ""
        if ">" in token:
            if token == ">&" and (following.isdigit() or following == "-"):
                continue  # fd duplication such as 2>&1
            if following == "/dev/null":
                continue
            return True
        if "<<" in token:
            return True
    if not lexed_ok and (">" in command or "<<" in command):
        return True  # crude split lost the operators: judge by the raw text
    if names & MUTATORS or _in_place(tokens, names):
        return True
    return "git" in names and any(t in GIT_MUTATING for t in tokens)


def _check_inline_code(ctx: Context, tokens: list, programs: list, depth: int) -> Denial | None:
    """Recurse into `sh -c` / eval strings; deny interpreter code naming a self-protected path."""
    for kind, code in _code_strings(tokens, programs):
        if kind == "shell":
            if depth < MAX_DEPTH:
                denial = analyse(ctx, code, depth + 1)
                if denial:
                    return denial
        elif not ctx.cfg.dev_mode:
            touched = _under_protected(ctx, code)
            if touched:
                return Denial("self-protect", SELF_MSG, ctx.display(touched))
    return None


def _segment_args(tokens: list, j: int) -> list:
    out = []
    for token in tokens[j + 1 :]:
        if _is_punct(token) or token in _STARTERS:
            break
        out.append(token)
    return out


def _exists(ctx: Context, value: str, cur: Path) -> bool:
    if "$" in value or "`" in value:
        return True  # unresolvable: the dynamic-path rule decides
    expanded = os.path.expandvars(os.path.expanduser(value))
    if any(ch in expanded for ch in "*?["):
        return next(glob.iglob(str(ctx.lexical(expanded, cur))), None) is not None
    return os.path.lexists(ctx.lexical(expanded, cur))


def _untracked_walk(ctx: Context, directory: Path) -> Denial | None:
    if has_untracked_below(ctx, directory):
        return Denial("recursive-over-untracked", UNTRACKED_RECURSE_MSG, ctx.display(directory))
    return None


def _implicit_cwd(ctx: Context, tokens: list, j: int, base: str, cur: Path) -> Denial | None:
    """A recursive program given no existing path argument walks the current directory."""
    args = _segment_args(tokens, j)
    if base == "find" and not _FIND_EXEC.intersection(args):
        return None
    candidates = [a for a in args if not a.startswith("-")]
    if (
        base in _PATTERN_FIRST
        and base != "find"
        and not any(_PATTERN_FLAG.match(a) or a.startswith(("--regexp", "--file")) for a in args)
    ):
        candidates = candidates[1:]  # the first operand is the pattern, not a path
    if any(_exists(ctx, a, cur) for a in candidates):
        return None
    if base in ("rg", "ag") and Path(os.path.realpath(cur)) == ctx.cfg.root:
        return None  # honours .gitignore from the repo root (documented residual)
    return walks_closed_zone(ctx, cur) or _untracked_walk(ctx, cur)


def _scan_value(
    ctx: Context,
    cand: str,
    cur: Path,
    names: set,
    touched: list,
    *,
    whole: bool,
    recursive: bool,
    role: str = "",
) -> Denial | None:
    """Policy check of one candidate path string; records the first self-protected touch."""
    expanded = os.path.expandvars(os.path.expanduser(cand))
    if "$" in expanded or "`" in expanded:
        return None  # dynamic: the dynamic-path rule decides
    try:
        paths = _expand(ctx, expanded, cur)
    except GlobTooLarge:
        return Denial(
            "glob-too-large",
            "A wildcard matches too many paths for the guard to check each one. Narrow "
            "it to a tracked directory such as src/, tests/ or docs/.",
            cand[:80],
        )
    for path in paths:
        lex = ctx.lexical(path, cur)
        if not touched and _touches_self_protected(ctx, lex, role, whole):
            touched.append(lex)
        denial = ctx.check_path(path, base=cur)
        if denial:
            return denial
        if whole and recursive and lex.is_dir():
            denial = walks_closed_zone(ctx, lex) or _untracked_walk(ctx, lex)
            if denial:
                return denial
    return None


# -- git -------------------------------------------------------------------------------------


def _long_opt(arg: str, full: str, minlen: int) -> bool:
    """arg is --full or an unambiguous-looking abbreviation of it (git accepts both)."""
    name = arg.split("=", 1)[0]
    return len(name) >= minlen and name.startswith("--") and full.startswith(name)


def _git_add(ctx: Context, rest: list, cur: Path | None, via_xargs: bool) -> Denial | None:
    def deny(shown: str = "") -> Denial:
        return Denial("git-add", GIT_ADD_MSG, shown[:80])

    if via_xargs:
        return deny()  # xargs supplies the pathspecs at run time
    files = []
    after_dashes = False
    for arg in rest:
        if not after_dashes and arg == "--":
            after_dashes = True
        elif not after_dashes and arg.startswith("--"):
            if arg.split("=", 1)[0] not in _GIT_ADD_LONG_OK:
                return deny(arg)
        elif not after_dashes and arg.startswith("-") and arg != "-":
            if not set(arg[1:]) <= {"v", "n"}:
                return deny(arg)
        else:
            files.append(arg)
    for arg in files:
        if cur is None or any(ch in arg for ch in "*?[{$`~:") or arg in (".", ".."):
            return deny(arg)
        path = ctx.lexical(arg, cur)
        if not path.is_file() or ctx.check_path(arg, base=cur):
            return deny(arg)
    return None


def _check_git(ctx: Context, tokens: list, j: int, cur: Path | None, via_xargs: bool):
    """Policy for one `git` invocation (the program at token index j)."""
    args = _segment_args(tokens, j)
    sub = ""
    k = 0
    workdir = cur
    while k < len(args):
        arg = args[k]
        if arg in ("-C", "-c"):
            value = args[k + 1] if k + 1 < len(args) else ""
            if arg == "-C":
                workdir = (
                    ctx.lexical(value, workdir) if workdir and value and "$" not in value else None
                )
            elif any(risky in value.lower() for risky in _GIT_CONFIG_RISKY):
                return Denial("git-policy", GIT_POLICY_MSG, "-c")
            k += 2
        elif arg.startswith("-c") and not arg.startswith("--") and len(arg) > 2:
            if any(risky in arg.lower() for risky in _GIT_CONFIG_RISKY):
                return Denial("git-policy", GIT_POLICY_MSG, "-c")
            k += 1
        elif arg.startswith(("--git-dir", "--work-tree", "--exec-path", "--super-prefix")):
            return Denial("git-policy", GIT_POLICY_MSG, arg.split("=", 1)[0])
        elif arg.startswith("-"):
            k += 1
        else:
            sub = arg
            break
    rest = args[k + 1 :]
    for arg in args:
        if _long_opt(arg, "--no-index", 6) or _long_opt(arg, "--untracked", 5):
            return Denial("git-policy", GIT_POLICY_MSG, arg[:40])
        if _long_opt(arg, "--include-untracked", 6):
            return Denial("git-policy", GIT_POLICY_MSG, arg[:40])
    if sub in _GIT_DENY_SUBS:
        return Denial("git-policy", GIT_POLICY_MSG, sub)
    if sub == "config" and any(r in a.lower() for a in rest for r in _GIT_CONFIG_RISKY):
        return Denial("git-policy", GIT_POLICY_MSG, "config")
    if sub == "add":
        return _git_add(ctx, rest, workdir, via_xargs)
    return None


# -- the token pass ----------------------------------------------------------------------------


def _check_tokens(
    ctx: Context, tokens: list, programs: list, names: set, skip_dynamic: set
) -> tuple:
    """(Denial or None, first self-protected path touched or None, dynamic argument seen)."""
    prog_at = {j: base for base, j in programs}
    recursive = bool(names & RECURSIVE) or (
        "find" in names and bool(_FIND_EXEC.intersection(tokens))
    )
    via_xargs = "xargs" in {os.path.basename(t) for t in tokens}
    roles = _roles(tokens, programs)
    cur = ctx.cwd
    cwd_known = True
    touched: list = []
    dynamic = False
    denial = None
    cd_next = -1
    for i, token in enumerate(tokens):
        base = prog_at.get(i)
        if token not in skip_dynamic and _is_dynamic(tokens, i):
            dynamic = True
        if base in ("cd", "pushd", "popd"):
            k = i + 1
            while k < len(tokens) and tokens[k].startswith("-"):
                k += 1
            if base != "popd" and k < len(tokens) and not _is_punct(tokens[k]):
                cd_next = k
            else:
                cwd_known = False  # bare cd, cd - and popd go somewhere the guard cannot see
        if (
            base in ("tar", "bsdtar", "unzip", "cpio", "patch")
            and not touched
            and _extracts_into_cwd(base, _segment_args(tokens, i))
            and (ctx.self_hit(cur) or any(under(p, cur) for p in ctx.cfg.self_protected()))
        ):
            touched.append(cur)  # an archive can name tools/guard/... without us seeing it
        if denial:
            continue  # keep scanning only for dynamic arguments and self-protected touches
        if base and (base in RECURSIVE or base == "find"):
            denial = _implicit_cwd(ctx, tokens, i, base, cur)
            if denial:
                continue
        if base == "git":
            denial = _check_git(ctx, tokens, i, cur if cwd_known else None, via_xargs)
            if denial:
                continue
        variants = _braces(token)
        if variants is None:
            denial = Denial(
                "brace-explosion",
                "A brace expression expands to too many words for the guard to check.",
                token[:80],
            )
            continue
        for variant in variants:
            if variant != token:
                suffix = data_suffix(variant)
                if suffix:
                    denial = Denial("suffix", suffix_message(ctx.cfg, suffix), suffix)
                    break
            whole = _candidates(variant)
            for cand in whole:
                denial = _scan_value(
                    ctx,
                    cand,
                    cur,
                    names,
                    touched,
                    whole=True,
                    recursive=recursive,
                    role=roles.get(i, ""),
                )
                if denial:
                    break
            if denial:
                break
            for piece in _pieces(variant):
                if piece in whole:
                    continue
                denial = _scan_value(
                    ctx, piece, cur, names, touched, whole=False, recursive=recursive
                )
                if denial:
                    break
            if denial:
                break
        if i == cd_next:
            if _is_dynamic(tokens, i):
                cwd_known = False
            else:
                cur = ctx.lexical(token, cur)
    return denial, (touched[0] if touched else None), dynamic


def _check_scripts(ctx: Context, tokens: list, names: set) -> Denial | None:
    if not any(_is_runner(b) for b in names):
        return None
    cfg = ctx.cfg
    for token in tokens:
        if token.startswith("-") or _is_punct(token) or "$" in token:
            continue
        path = ctx.lexical(token)
        try:
            if not path.is_file() or path.stat().st_size > _MAX_SCRIPT_BYTES:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if TOOLING_NAMES & set(path.parts):
            continue
        inside = under(path, cfg.root)
        if inside and path.relative_to(cfg.root).as_posix() in ctx.tracked()[0]:
            continue  # tracked scripts are reviewed code (git is asked only now, lazily)
        hit = protected_string(body, cfg)
        if hit:
            return Denial(
                "script-protected",
                f"Script {ctx.display(path)} reaches into a protected location. "
                "Running it would pull client data into an AI context.",
                ctx.display(path),
            )
        if not cfg.dev_mode and _self_mention(ctx, body):
            return Denial(
                "script-self-protect",
                f"Script {ctx.display(path)} names the guard or its registration. " + SELF_MSG,
                ctx.display(path),
            )
        if inside and data_suffix(body):
            return Denial(
                "script-suffix",
                f"Script {ctx.display(path)} names data files. Untracked scripts that do "
                "so cannot be run from an agent session; put the path in a tracked, "
                "reviewed file (as the integration tests do).",
                ctx.display(path),
            )
    return None


def _normalise(command: str) -> str:
    """What bash will see: line continuations joined, $IFS spelled as a space."""
    command = command.replace("\\\r\n", "").replace("\\\n", "")
    return re.sub(r"\$\{IFS\}|\$IFS(?![A-Za-z0-9_])", " ", command)


def analyse(ctx: Context, command: str, depth: int = 0) -> Denial | None:
    cfg = ctx.cfg
    command = _normalise(command)
    hit = protected_string(command, cfg)
    if hit:
        return Denial("protected-ref", PROTECTED_MSG, hit)
    suffix = data_suffix(command)
    if suffix:
        return Denial("suffix", suffix_message(cfg, suffix), suffix)

    tokens, lexed_ok = _tokenize(command)
    programs = _programs(tokens)
    names = _all_names(tokens, programs)

    extractor = names & EXTRACTORS
    if extractor:
        return Denial(
            "extractor",
            f"'{sorted(extractor)[0]}' turns documents into text and is blocked in this repo.",
            sorted(extractor)[0],
        )
    if any(os.path.basename(t) in ("airlock", "airlock.open") for t in tokens):
        return Denial("airlock-cli", AIRLOCK_MSG)
    uses_xargs = "xargs" in {os.path.basename(t) for t in tokens}
    if uses_xargs and names & READERS and not _GIT_LS_FILES.search(command):
        return Denial(
            "dynamic-path",
            "xargs feeds a reader paths the guard cannot see. Pass explicit paths, or "
            "pipe `git ls-files` into it.",
        )
    if not cfg.dev_mode and "<<" in command:
        mention = _self_mention(ctx, command[command.index("<<") :])
        if mention:
            return Denial("self-protect", SELF_MSG, mention)
    denial = _check_inline_code(ctx, tokens, programs, depth)
    if denial:
        return denial
    skip = {code for kind, code in _code_strings(tokens, programs) if kind == "shell"}
    denial, touched, dynamic = _check_tokens(ctx, tokens, programs, names, skip)
    if touched is not None and not cfg.dev_mode and _mutating(command, tokens, names, lexed_ok):
        return Denial("self-protect", SELF_MSG, ctx.display(touched))
    if denial:
        return denial
    if dynamic and _unsafe_for_dynamic(tokens, programs, names):
        return Denial("dynamic-path", DYNAMIC_MSG)
    return _check_scripts(ctx, tokens, names)
