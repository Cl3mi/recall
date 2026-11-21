# 0025. A repo-shipped, fail-closed guard hook plus a sealed output root protects client data from AI sessions

Status: Accepted
Date: 2026-10-16

## Context

Until October the protection was a hand-maintained list of denied paths, session hooks and sandbox
read-deny rules, which stop accidents but are not a boundary. The threat model: an agent reading
the export directly or through a renamed or converted copy; code written or run by an agent leaking
row values into a log or report; a new output nobody remembered to protect; a subagent or publish
tool becoming a side channel; the guard itself crashing and allowing the call; and work happening
during an airlock window when no AI may assist.

## Decision

A `PreToolUse` hook (`tools/guard`) ships with the repo and applies to every tool. Reads follow an
allowlist inside the repo: tracked files, `local/released/`, `local/artifacts/`, synthetic
fixtures, the scratchpad, files the session created itself and per-person extras from
`guard.local.json`; everything else in the repo is denied. Paths outside the repo get only the
sealed, suffix and content rules. A directory carrying a `.sealed` marker is
denied regardless of other rules. Data suffixes are denied by name, content sniffing catches
renamed copies (header fingerprint, delimited tables, archives), and Bash command text is analysed
for paths, interpreters' script contents and extractor programs; a path the guard cannot resolve
(`$VAR`, `$(...)`) is denied when a reading command is involved, while tracked scripts are trusted. A human-run `airlock open/close` marker denies every tool call during a window and denies
agents the airlock command. A write-side lint requires new outputs to go through
`recall.sealed.sealed_path` and `sealed_logger`. `run-guard.sh` exits deny on a crash, timeout or
missing file, and each denial is logged without content. The guard and its registration are
operator-maintained.

## Consequences

- New outputs and logs are protected by default instead of by a list, and the guard protects every
  contributor who clones the repo.
- The agent's workflow is constrained: it cannot build file paths from variables, must use
  `git add -N` via a human for new files it needs to read, and may not name untracked files in
  commit messages. `CLAUDE.md` documents these rules.
- The lint is single-line pattern matching and is a guard rail, not a security boundary; the real
  boundaries remain the AI-free window and an empty quarantine on the workstation (ADR 0002).
- The guard is a large piece of code (about a dozen modules, several review rounds) that must be
  kept in step with how tools evolve.
- False positives cost time, so `--explain` exists to show why a path is denied.
- Other parts of the design: a pre-commit hook (`make guard-install`, `--lint-staged`) that also
  rejects staged data files; self-protection (agents cannot edit `tools/guard`, the settings or
  `.githooks`; `RECALL_GUARD_DEV=1` is the human maintenance route); a SessionStart self-check;
  lint scope now includes `catalog/`; and `profile.json`, `profile_report.md` and `eval_real.json`
  were dropped from the name deny list by user decision on 2026-10-16.
- The spec calls the OS sandbox with `denyRead` the independent second layer, but the tracked
  `.claude/settings.json` has it disabled; whether that is deliberate is not recorded here and
  should be confirmed by the operator.

## References

- `docs/superpowers/specs/2026-10-16-recall-guard-design.md`; plan `2026-10-16-recall-guard.md`
- `tools/guard/`, `src/recall/sealed.py`, `CLAUDE.md`
- Commits d244602, 3a99722, 1142b22, f52da28, db458a4, e3700ee
