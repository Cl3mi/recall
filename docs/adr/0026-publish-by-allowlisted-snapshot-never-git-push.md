# 0026. The repository is published as an allowlisted, denylist-scanned snapshot, never by `git push`

Status: Accepted
Date: 2026-10-20

## Context

The planning session's data-handling rules said there is no git remote. Later the work needed to be
shared through a private GitHub repository. But local history holds NDA-sensitive material (a
client name, real-corpus figures, host details) from earlier sessions, so pushing history would
publish it.

## Decision

`make publish` (`tools/publish/publish.sh`) exports `git archive HEAD` of only the paths in
`tools/publish/allowlist.txt` into a temporary tree, scans it against a local, gitignored denylist
of forbidden strings (the script refuses to run without one), and pushes the result as one new
commit on the remote main. History never leaves the machine. The only remote the repo accepts is
the publish remote (overridable with `PUBLISH_REMOTE`); a test refuses any other. The script also
aborts on uncommitted changes in published paths, on any data-file extension in the snapshot, and
on a denylisted string in a file name. Documents that were published were scrubbed of client
data first, and the tracked copy of `docs/STATE.md` carries coarse figures while exact numbers live
under `local/`.

## Consequences

- The remote has a flat history of snapshots, so authorship, bisecting and review there are poor.
- New directories are not published until they are added to the allowlist (dev3 and the catalog
  modules it imports were added in a separate commit). Only four catalog modules are allowlisted
  (`__init__`, `guard`, `scrub`, `schema`); the rest of `catalog/` is deliberately unpublished,
  which is why the box builds Window C from a dedicated Dockerfile. `docs/adr/` and
  `docs/ARCHITECTURE.md` are not in the allowlist yet.
- No rejected alternative (such as rewriting history) is recorded in the sources.
- Protection depends on the denylist being maintained; a string nobody listed is not caught.
- It amends the earlier "no git remote" rule rather than replacing the data rule: no data of any
  kind is in git, and the remote carries only scrubbed, allowlisted code and docs.

## References

- `tools/publish/publish.sh`, `tools/publish/allowlist.txt`
- Commits 8912698, 3144639, f6b6433, e98b0c1, 2144995
- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 1 (data handling rules)
