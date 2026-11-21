# 0038. The shared box is used under a fair-use claim: UUID-pinned GPU, 60 GB cap, 32 threads

Status: Accepted
Date: 2026-08-04 (the fair-use script); the thread cap was decided 2026-09-11 after measurements on 2026-09-07

## Context

The brief assumed a dedicated 80 GB GPU. In reality the box has two H100 PCIe cards shared with
other users (22 users at one measurement, load average around 194 on 256 hardware threads), and a
fair-use script caps this project at 60 GB per GPU. The planning session concluded one model per
card, never tensor-parallel across the pair. Measurements showed that oversubscribing threads is slower, not
faster: 32 threads gave about 2.08 documents per second on real-length text, 128 gave 1.10, and
nothing capped threads by default.

## Decision

GPU access goes through `infra/fairuse/gpu-fairuse2.sh`: `claim` pins one index and returns its UUID,
and is itself a go/no-go gate, so the device spec is `nvidia.com/gpu=<uuid>` and cannot silently
land on another user's card after an index change. `claim` reserves nothing: it prints exports, has
no release subcommand and is per session, and it runs from the workstation over ssh. The go
thresholds include at least 60 GB free, GPU utilisation at most 85%, no foreign compute process
and low load; the script counts any other process as foreign, which caused a deferral of about five
hours on 2026-08-18. Windows that need no GPU run `check` instead, and a window holding a card it
does not use is considered unfair. Memory is sized to the cap (Window E uses 0.70 of 80 GB for the
LLM; the claim script itself prints 0.75, i.e. 60 of 81.5 GB). Plain `--device nvidia.com/gpu=`
fails under the box's Podman version, so Window C workers use the UUID-based `podman-gpu` wrapper. CPU use is capped at 32 threads by default (`--threads`, or
`RECALL_WINDOW_THREADS`), via `--cpus` plus `OMP_NUM_THREADS` and `MKL_NUM_THREADS`, clamped on the
box to its core count.

## Consequences

- The work stays a good neighbour, and runs are reproducible because thread counts are fixed.
- Capacity planning uses 60 GB, not 80 GB: model choices are bounded (ADR 0040), and the two-card
  split in the original design is a ceiling, not a plan.
- A refused claim means waiting, which can defer a window for hours.
- Timing figures from a shared box are single samples under contention and are not a calibrated
  curve.
- 32 was the best of the three values tested (8, 32, 128); the true optimum is unmeasured, and a
  quiet box may tolerate more.

## References

- `docs/superpowers/specs/2026-08-04-loesungsfinder-design.md` section 1
- `docs/STATE.md` findings 17, 19; commit 201e6f2
- `infra/fairuse/gpu-fairuse2.sh`; `infra/profiler/window.sh`
