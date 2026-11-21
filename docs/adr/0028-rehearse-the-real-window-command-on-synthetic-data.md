# 0028. Every window has a synthetic rehearsal that runs the real command, and guards against a stale image

Status: Accepted
Date: 2026-09-14

## Context

A failure inside a sealed window costs the window and cannot be debugged with AI help, so failures
must surface earlier. Three kinds of "green for the wrong reason" occurred. A rehearsal kept its own
copy of the window command and could drift from `window.sh`. A `--quick` rehearsal skipped the image
build and passed against an image that predated the change under test (finding 20); the first
version of the guard that detects this sorted files under different locales on host and container,
so it failed on every build. A leakage gate run on `--fake` data produced a green that meant little,
which is why rehearsals record verdicts instead of asserting them.

## Decision

Each window has a rehearsal (`make window-{a,b,c,d,e}-rehearsal`) that runs the real sealed
container on invented data with `--network=none`. It reads the command back out of
`window.sh --dry-run` instead of keeping a copy, so it cannot rehearse a command the window does
not run. In the rehearsals for windows B to E, a stale-image guard hashes the baked code directories
inside the image and compares them with the working tree (first `profiler/` only; later windows
extended it, for example Window C hashes `src/recall`, `profiler` and `insight`), with `LC_ALL=C` on
both sides, and it was verified to discriminate in both directions. Window A's rehearsal has
`--quick` but no such guard. Rehearsals assert the controls (egress fails, no quarantine mount on the LLM container,
only allowlisted files fetchable, shred list empties quarantine) and record results such as
`embedder_is_a_model` rather than asserting a verdict. A contract unit test pins the same commands
in CI without Docker.

## Consequences

- Most window defects are found on the workstation; several cycle-costing ones were found this way.
- Rehearsals need Docker, built images and time, and they run Docker where the box runs Podman, so
  Podman-specific behaviour is only proved on the box (Window C still has that gap).
- The rehearsal inherits the weakness of the stand-in data: it proves the mechanism, not the
  science (ADR 0005).
- The Window C state file records two Window D dry-run regex tests failing before Window C work
  began (the `image_digest` output splits before `unknown`).

## References

- `docs/STATE.md` findings 19, 20; commits b62353a and db2b6b9 (the stale-image guard), 2a4126b
  (the rehearsal reads the command from `--dry-run`), 7a63939 (the Window E rehearsal)
- `infra/profiler/rehearse-window-*.sh`; `tests/unit/test_window_*_contract.py`
