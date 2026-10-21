# Recall guard — design

Date: 2026-10-16
Status: approved in brainstorming, awaiting spec review

## Goal

Keep real client data, and anything derived from it, out of every AI context
(Claude Code sessions, subagents, shell commands they issue) whenever a session
runs in this repo. The guard ships with the repo, so everyone who clones it is
protected without installing anything, and new logs and outputs are protected
automatically instead of by a hand-maintained list.

Non-goals: protecting other repos on the machine (the global `sindri-guard.py`
keeps doing that), and replacing the airlock protocol
(`docs/airlock-runbook.md`). The workstation still never holds real data; the
guard is the safety net for mistakes.

## Threat model

- An agent reads the export directly (Read, `cat`, `head`, `python -c`, a script).
- An agent reads a renamed or converted copy (`export.txt`, `.tsv`, `.gz`, `.parquet`).
- Code written or run by an agent leaks row values into a log, report, dump or error message.
- A new output file appears that nobody remembered to protect.
- A subagent, `Artifact` publish or other tool becomes a side channel.
- The guard itself fails (crash, timeout, missing file) and the call is allowed.
- Work happens during an airlock window, when no AI may assist.

## Architecture

All files are committed; per-person state is gitignored.

| Path | Purpose |
| --- | --- |
| `tools/guard/guard.py` | `PreToolUse` hook: decides allow or deny. |
| `tools/guard/run-guard.sh` | Wrapper; exits 2 (deny) if the guard crashes, times out or is missing. |
| `tools/guard/sealed.py` | `sealed_path()`, `sealed_logger()`: the only sanctioned way to write outputs. |
| `tools/guard/lint.py` | Flags code that writes files or logs outside the sealed helper. Used by the guard and by pre-commit. |
| `tools/guard/airlock` | Human-run CLI: `open`, `close`, `status`. |
| `tools/guard/export_aggregate.py` | Release gate: sealed to released, numbers only. |
| `docs/export.header.txt` | One-line header of the real export (user-provided). The schema agents may see. |
| `.claude/settings.json` | Registers the hook with matcher `.*`; adds `permissions.deny` for data suffixes; turns the sandbox on with `denyRead` for `local/sealed`, data dirs and quarantine. |
| `CLAUDE.md` (section) | Rules for agents (see "Write-side rules"). |
| `.claude/guard.local.json` (gitignored) | Per-person extra allowed paths. |
| `local/airlock.open` (gitignored) | Window marker. |
| `local/guard.log` (gitignored, sealed) | Audit log. |
| `local/sealed/`, `local/released/` | Sealed outputs and released aggregates. |

The hook is registered through `$CLAUDE_PROJECT_DIR`, so it only fires for
sessions in this repo and resolves the same way for every contributor.

## Read policy: allowlist by default

An agent may read a path only if it is one of:

1. a git-tracked file (checked with `git ls-files`, cached per call);
2. under `local/released/`;
3. under the synthetic fixtures directory;
4. under the agent's scratchpad / temp directory;
5. a file the agent created this session (recorded in a session ledger when
   `Write` or `Edit` creates it, and cleared at session end);
6. an extra path from `.claude/guard.local.json`.

Everything else is denied: untracked files, gitignored files, and every new log,
dump or output. Any directory containing a `.sealed` marker (at any depth, or in
a parent) is denied regardless of the rules above. The sealed marker wins.

Applies to `Read`, `Edit`, `Glob`, `Grep`, `LS`, `NotebookEdit`, and to path-like
tokens in `Bash`. Path-like tokens are extracted with `shlex` plus a
punctuation-aware regex, so `x.csv|head`, `x.csv;ls`, `<x.csv` and `x.csv>out`
are all seen. Globs are expanded and each match is checked.

## Name and extension rules

Denied wherever they appear, in addition to the allowlist:
`.csv .tsv .parquet .jsonl .xlsx .xls .xlsm .xlsb .ods .pkl .npy .npz .syn`,
each optionally followed by `.gz .zip .bz2 .xz`, plus `profile.json`,
`profile_report.md`, `eval_real.json`. Writing a data-suffix file from `Bash` or
`Write` is denied too; synthetic fixtures are generated through pytest, with the
path written inside a Python file, as today.

The existing rule that a command mentioning the suffix is blocked stays,
including for non-reading commands such as `window.sh push --csv`. Those remain
human-run.

## Content sniffing

For any existing, non-allowlisted file touched by a call, the hook reads the
first 8 KB and denies it if:

- it contains the exact header line from `docs/export.header.txt` (any filename); or
- it has consistent delimiters (`, ; \t |`) across 3 or more lines and is not source code; or
- it is a large text file (over 1 MB) with no recognised code or markup signature.

Binary archives (`.zip`, `.gz`, `.tar`) are denied outright unless tracked.

## Bash handling

- Every path-like token is checked against the read allowlist.
- For interpreters (`python`, `python3`, `bash`, `sh`, `node`, `perl`, `ruby`,
  `source`, `.`), the script file's contents are scanned for protected paths and
  suffix strings.
- Extractor binaries (`pdftotext`, `libreoffice`, `in2csv`, `xlsx2csv`, `csvlook`,
  `qpdf`, `gs` and the sindri list) are denied.
- Chaining and substitution in a command disqualify any "sanctioned shape"
  exception.
- The OS sandbox with `denyRead` is the independent second layer: a command the
  hook misses still cannot read the sealed root or the data dirs.

## Sealed outputs and the release gate

- `sealed_path(name)` and `sealed_logger(name)` create files under
  `local/sealed/` and write a `.sealed` marker into the directory.
- `export_aggregate.py` is the only code that moves information out. It accepts a
  schema of numeric fields (counts, rates, metrics), rejects free-text strings,
  and writes to `local/released/`.
- Anything under `local/released/` is readable and may be pasted into an AI tool.

## Write-side rules

`CLAUDE.md` gets a "client data" section stating:

1. Never read, list, glob, grep or reference the real export or anything under the sealed root.
2. Logs, errors and reports never contain row values; errors carry a code and schema path only.
3. All file and log output from code that can see real rows goes through `sealed.py`.
4. New output locations are created with the sealed helper, never ad hoc.

`lint.py` runs on `Write`/`Edit` to source files and in pre-commit. It flags
`open(..., "w"|"a")`, `logging.FileHandler`, `Path.write_text/write_bytes`,
`to_csv`, `to_parquet`, `json.dump` to a file, and `print` of dataframe or row
variables in modules that import the data readers. The finding names the sealed
helper to use. It warns on `Write`/`Edit` (the agent sees the message and
corrects itself) and fails in pre-commit.

## Header sidecar

When a read of the export or a renamed copy is denied, the message points to
`docs/export.header.txt` so the agent still gets the structure. The file is
tracked and allowlisted. Its content is also the fingerprint used by content
sniffing. The guard does not lint its line count (not selected in brainstorming),
but the file name avoids the blocked suffixes.

## Airlock window lock

`tools/guard/airlock open` creates `local/airlock.open`; `close` removes it;
`status` reports. While the marker exists, every tool call is denied with
"airlock window open, no AI assistance allowed". The guard also denies any
command invoking `tools/guard/airlock`, so an agent cannot close the window.
The user runs it in a normal terminal. The marker check runs first, before any
other rule.

## Audit log

Each denial appends one JSON line to `local/guard.log`: timestamp, tool, rule
id, normalised path. Never command text beyond the rule id, never file content.
The log lives under the sealed root, so agents cannot read it; humans read it
to tune rules.

## Failure handling

- `run-guard.sh` runs the guard with a timeout and exits 2 on any non-zero
  exit other than the guard's own clean allow, on timeout, or if the guard file
  is missing.
- A `SessionStart` check verifies the guard files, the header sidecar and the
  hook registration are present, and warns loudly if not.
- Unparseable payloads that mention a protected name or suffix are denied.

## Testing

`tests/guard/` holds a table-driven suite. Payloads are JSON fixtures piped to
the hook, so running the suite never puts suffix text in a command line.

Required cases: the punctuation bypasses above; a renamed file carrying the
header; an `Artifact` publish of a data file; a new untracked log under the
repo; a sealed-marker directory; a file created this session; a crashing guard
and a missing guard (wrapper exits 2); the airlock marker blocking everything
and blocking the airlock CLI; a subagent prompt naming a protected path; a
lint finding on a new `FileHandler`; and false-positive checks for ordinary
tracked source and docs.

## Open items for the implementation plan

- Exact synthetic fixtures directory name (currently `local/fixtures/`).
- Whether `settings.local.json` entries such as `Read(//<home-dir>/**)` should
  be removed once the guard is active (deny and the hook win either way).
- Pre-commit wiring: the repo has no `core.hooksPath` set yet.
