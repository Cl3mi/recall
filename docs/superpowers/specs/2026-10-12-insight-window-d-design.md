# Window D — running the insight report on the real export

**Status:** design approved 2026-10-12. Implements the "window" half of
`2026-10-11-insight-window-report-design.md`, for **stage 1 only** (no model, no GPU).

## Why

`python -m insight` exists and is tested on a synthetic stand-in. Real NDA-covered rows may only
be handled in a manual, AI-free window on the shared box (`docs/airlock-runbook.md`). Window D is
that window: the same sealed image, the same `window.sh` contract and review gate, a rehearsal
that fails here instead of in the window, and a runbook section written for reading with no AI.

## Decisions (taken with the operator, 2026-10-12)

| Decision | Choice |
|---|---|
| Code delivery | **Baked into the image** (`COPY insight`). The image digest pins the code, as for Windows A and B. Costs a rebuild and a re-ship of the 9.3 GB image (about an hour at the measured 2.5 MB/s). |
| Serial prefixes | **Off** (`--serial-prefixes` is not passed). `vehicleSerialNo` stays on the never-emit list. |
| Floor | `--min-frequency 50`, spelled out in the command so the rehearsal can assert it. |
| GPU | None. Claims nothing, like Window A. |

## What Window D is

- **`window.sh` window `d`.** Input `export.csv`; the only file that may cross out is
  `report.json`; shred `export.csv`, `profiler_detail.log`, `report.json.tmp`. The sealed command
  is `python -m insight --csv /q/export.csv --out /q/report.json --min-frequency 50
  --code-commit <sha> --image-digest <digest>`. `--serial-prefixes` and `--allow-weak-floor` must
  be absent from it.
- **Per-window review file.** The runbook requires the artifact to be read in full on the box
  before anything crosses. That was hard-wired to `profile_report.md`; it becomes
  `WINDOW_REVIEW`, and for D it is `report.json`.
- **`verify`** gets a Window D probe that prints counts only: rows, guard passed, floor, prefixes
  off, Baugruppe coverage, ledger rows. Coverage near 0.25 is what the profile predicts (about
  a quarter of rows carry `baugruppe`); 0.0 means the field was not found and the window was spent.
- **Dockerfile.** `COPY insight` goes AFTER the weights are baked, so the heavy layers stay cached,
  and the final build check imports `insight.__main__`, turning a missing module into a build
  failure rather than a sealed-window one.
- **`ship`** also checks `insight.__main__` imports offline on the box.
- **`rehearse-window-d.sh`** (`make window-d-rehearsal`) runs the real sealed container locally on
  the stand-in with `--network=none`. It reads the command back out of `window.sh --dry-run`
  (so it cannot rehearse a command the window does not run), carries the stale-image guard from
  finding 20 over both `insight/` and `profiler/`, asserts no planted leak reaches the report,
  that `--out` equal to the input is refused with the input unchanged, that a wrong-schema file
  aborts, that a failed run leaves no report, and that after the shred list is applied only
  `report.json` remains.
- **A unit test** (`tests/unit/test_window_d_contract.py`) pins the contract from `--dry-run`
  output without needing Docker, so a drifting command is caught in CI.

## Out of scope

Stage 2 (embeddings, clusters, labels, review step) and the HTML view. This window produces only
the deterministic report.

## What this cannot answer

Whether the real export parses the way the stand-in does. The first real run is also the first
time `insight` sees the real export's `customData`; the `verify` probe and the review gate exist so the
operator can tell immediately if `baugruppe` was not found.
