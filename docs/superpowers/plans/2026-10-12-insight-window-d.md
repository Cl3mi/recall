# Insight Window D Implementation Plan

> Executed inline by the controller, not by subagents: shell, Dockerfile and runbook changes
> whose real verification is running the sealed container, not reviewing code. Each task ends
> with a command whose output proves it.

**Goal:** the operator can run `python -m insight` on the real export in a sealed, AI-free window
with one wrapper command, after a local rehearsal has proved the same image and command.

**Spec:** `docs/superpowers/specs/2026-10-12-insight-window-d-design.md`.

## File map

| File | Change |
|---|---|
| `tests/unit/test_window_d_contract.py` | new: pins window d's contract from `window.sh --dry-run` |
| `infra/profiler/window.sh` | window `d`; `WINDOW_REVIEW`; per-window `verify`; `ship` checks `insight` |
| `infra/profiler/Dockerfile` | `COPY insight` after the weights; build-time import check |
| `infra/profiler/rehearse-window-d.sh` | new rehearsal; `Makefile` target `window-d-rehearsal` |
| `docs/airlock-runbook.md` | new "Window D" section; exit code 4 |
| `docs/STATE.md` | what is ready, what is the operator's |

## Task 1: Pin the contract (test first)

- [ ] Write `tests/unit/test_window_d_contract.py`: run `infra/profiler/window.sh --window d run
  --dry-run`, `fetch --dry-run` and `clean --dry-run` through `subprocess` and assert: the command
  starts `python -m insight` and carries `--csv /q/export.csv`, `--out /q/report.json`,
  `--min-frequency 50`, `--code-commit` and `--image-digest`; it does NOT carry
  `--serial-prefixes` or `--allow-weak-floor`; `fetch` names exactly one artifact, `report.json`;
  `clean` lists `export.csv`, `profiler_detail.log` and `report.json.tmp`; windows a, b and c keep
  their own review files. Also `--window e` is refused.
- [ ] Run it: expect failure (`unknown window 'd'`).

## Task 2: window.sh

- [ ] Add `WINDOW_REVIEW` to every window's contract (`a`: `profile_report.md`, `b`:
  `gate_report.json`, `c`: `eval_real.json`) and add window `d`.
- [ ] Use `WINDOW_REVIEW` in `cmd_fetch`'s prompt and `cmd_all`'s hint instead of the hard-coded
  `profile_report.md`.
- [ ] `cmd_verify`: window `d` gets the report probe; other windows keep today's probe.
- [ ] `cmd_ship`: the offline-import check also imports `insight.__main__`.
- [ ] `--help` and the unknown-window message list `a|b|c|d`.
- [ ] Run Task 1's test: expect pass. Run `bash -n infra/profiler/window.sh`.

## Task 3: Dockerfile

- [ ] `COPY insight ./insight` after the `HF_HUB_OFFLINE` block, and extend the final check to
  import `insight.__main__`.

## Task 4: Rehearsal

- [ ] `infra/profiler/rehearse-window-d.sh`, following `rehearse-window-b.sh`'s structure:
  Phase 0 (insight tests, lint, image build unless `--quick`, offline import, stale-image guard,
  German dictionary), stand-in, drift check, the sealed run, report assertions, failure paths,
  teardown, workstation hygiene, verdict. No `uv`. `make window-d-rehearsal`.
- [ ] `bash -n`; then run it for real (builds the image, runs the container offline).

## Task 5: Runbook and state

- [ ] "Window D" section in `docs/airlock-runbook.md`; exit code `4` added to "What the exit codes
  mean".
- [ ] `docs/STATE.md`: what is ready and exactly what is left for the operator.

## Done when

`pytest` (the new contract test plus everything else) is green, `ruff` is clean, `bash -n` passes
on both scripts, and the rehearsal prints `0 failed` against a freshly built image. Shipping the
image to the box and running the window are the operator's.
