# 0039. Model weights are baked into the image or mounted read-only, never fetched at run time

Status: Accepted
Date: 2026-09-07 (the baked pattern); the mounted pattern arrived later, with Window E and the M4 eval image

## Context

Sealed windows run with `--network=none`, so nothing resolves at run time, and a hub lookup that
fails inside a window with no AI available is a wasted window. Weights are large (about 2.2 GB for
e5), and shipping the sealed image is slow (tens of minutes at 3.5 GB, about an hour once CUDA torch
was added, ADR 0037). Different images have different
needs: the leakage and eval windows need e5 on every run, while the LLM and reranker weights are
bigger and shared on the box.

## Decision

Weights are never downloaded at run time. Two patterns are allowed. Sealed images that always need a
model bake it in at build time (`HF_HOME=/opt/hf`, fetched by revision) and set `HF_HUB_OFFLINE=1`
and `TRANSFORMERS_OFFLINE=1`; adapters also pass `local_files_only=True`, so an attempt to reach
out fails loudly. The build fails if the model does not load offline. Large or shared models are
mounted read-only from the box's cache with offline variables set: the vLLM server in Window E and
the M4 eval image. The embedder and reranker are pinned by revision constants next to their names
(`E5_REVISION`, `BGE_REVISION`); the LLM server is pinned by image digest plus the read-only mounted
cache, and the Qwen model name has no revision constant.

## Consequences

- A missing weight or module is a build failure, not a sealed-window failure.
- Baking makes the image large and its provenance equal to the image digest; changing a model
  requires a rebuild and a re-ship.
- Mounted weights depend on the box's cache contents and are verified on the box before a window.
- Revision pins make runs reproducible but need a deliberate bump to take a model update.
- In the profiler image, `insight`, `catalog` and `fixtures` are copied after the weights so that
  code-only changes keep the heavy layers cached; `src` and `profiler` come before them because the
  weight bake imports `profiler.gate.embedder`.

## References

- `infra/profiler/Dockerfile`, `infra/eval/Dockerfile`, `infra/eval/Dockerfile.window-c`
- `docs/superpowers/plans/2026-09-07-window-b-plan-b-sealed-embedder.md`; commit 79f9f94
- `docs/superpowers/specs/2026-10-11-insight-window-report-design.md` (planned read-only mount of
  the labelling model; stage 2, never built, so Window D is stage 1 with no model and its code baked
  in, per `2026-10-12-insight-window-d-design.md`)
