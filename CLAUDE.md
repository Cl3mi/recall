# recall — notes for AI agents

## Client data (hard rules, enforced by tools/guard)

1. Never read, list, glob, grep or name the real ticket export, any data file (`.csv`,
   `.tsv`, `.parquet`, `.jsonl`, `.xlsx`, `.npy` and friends) or anything under `local/sealed/`
   or `local/quarantine/`. The guard denies these; do not look for a way around it.
2. The export's structure is in `docs/export.header.txt` (one line, columns only). Read that
   when you need the schema.
3. Logs, errors and reports never contain row values. Errors carry a code and a schema path
   only.
4. All file and log output from code that can see real rows goes through `recall.sealed`
   (`sealed_path`, `sealed_logger`). New output locations are created with that helper, never
   ad hoc. The guard's lint will refuse a bare `open(..., "w")`, `FileHandler`, `to_csv`
   and similar in `src/`, `profiler/`, `insight/` and `fixtures/`; use `# guard: ok(<reason>)`
   only for synthetic or non-client data. The lint is a best-effort guard-rail (single-line
   patterns; multi-line calls can escape) and is not a security boundary.
5. Aggregates (counts, rates, metrics — numbers only) leave the sealed root through
   `python3 tools/guard/export_aggregate.py <name>`, which writes to `local/released/`.
   Only released aggregates and `local/artifacts/` may be read.
6. You may read git-tracked files, `local/released/`, `local/artifacts/`, `local/fixtures/`,
   your scratchpad and files you created this session with the Write tool (exact paths only;
   a new file next to them is not readable). Any other new file: ask the human to
   `git add -N <path>` (you cannot run it yourself), or keep scratch in the scratchpad.
   You may `git add` only explicit files you can already read (no directories, `.`, globs,
   `-A`, `-f`, `-u`, `-N`); everything else is for a human.
7. The guard also scans quoted strings and `-c` code for paths. In commands that read files,
   write every path out literally. Never build one with `$VAR` or `$(...)`. That includes
   commit messages: use a plain `git commit -m "..."`, not `-m "$(cat <<EOF ...)"`, and
   keep message words from naming untracked files in the working directory.
8. The guard, its registration and the airlock marker are not yours to change. If the guard is
   wrong, tell the human; they can maintain it with `RECALL_GUARD_DEV=1`.
9. While the airlock window is open every tool call is denied. That is expected.

To see why a path is allowed or denied: `python3 tools/guard/guard.py --explain <path>`.
