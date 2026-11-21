# 0037. The sealed images carry CUDA torch and the embedder uses the GPU when present

Status: Accepted
Date: 2026-09-11

## Context

On 2026-09-07 the operator ruled CPU only for the sealed image: no `--device`, no CUDA torch, an
overnight run acceptable. The plan treated the gate's cost as unmeasured at that point. Once
measured, embedding cost about 2.2 hours of CPU per window at box load (about 20,000 encodes; 1.07
hours on an idle box), and the same work took minutes on an H100. The reversal on 2026-09-11 also
had to answer a driver question: the box's driver (550.163.01) is older than CUDA 12.6's toolkit
requirement. Before the reversal the operator had asked for GPU 0, and the request was declined
because the image's torch was CPU-only and a device torch cannot address would have run on the CPU
while appearing accelerated.

## Decision

Reverse the CPU-only ruling. `pyproject.toml` pins torch to the `cu126` index (explicit, so other
packages stay on PyPI); cu126 is forced rather than preferred, being the only index carrying torch
2.14.0. PyTorch's cu12x wheels bundle their runtime and need only driver 525.60.13 or newer, which
a real run on the box confirmed. `E5Embedder` uses CUDA when present and falls back to CPU; the
fallback must not be removed because the image's build-time self-check and the CI tests run with no
GPU. Windows claim a GPU per window (ADR 0038); a window that does not need one (A, D) claims
none. The device is not part of the embedder identity because vectors agree across devices
(`test_the_device_does_not_change_the_vectors`: vectors within 1e-4, gate cosines within 1e-5).
The CUDA image is mandatory for Window B.

## Consequences

- The window's embedding cost fell from hours to minutes (an honest 19x on the idle box once
  contention is separated out; the first comparison of 46x conflated the card with a busy box).
- The sealed image grew from about 3.5 GB to about 9.3 GB, so `window.sh ship` went from tens of
  minutes to about an hour at the measured link speed. On a modest consumer card the same change was
  measured at 5.7x end to end.
- Verdicts do not depend on where a window runs, shown by identical gate numbers to six decimals
  on CPU and GPU.
- CDI GPU injection depends on box configuration; a stale spec after a reboot breaks every GPU
  container until an admin regenerates it (see ADR 0032).
- A CPU-only fallback for the reranker was deliberately not carried over (ADR 0019).

## References

- `docs/STATE.md` ("The four decisions" and the measured results); commit 877fc98
- `pyproject.toml` (cu126 index comment); `infra/profiler/Dockerfile`
- ADR 0009, 0038
