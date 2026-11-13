# Eval image for M4's GPU run on the shared box. Same pattern as infra/profiler/Dockerfile:
# `uv sync --frozen` installs the lock's cu126 torch. No weights are baked in: the shared HF cache
# is mounted read-only at /opt/hf with HF_HUB_OFFLINE=1, and the fixture is mounted read-only at
# run time. Build it ON THE BOX ONLY, from the published checkout: a workstation build context
# would carry local/ into the builder (there is no .dockerignore).
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /work
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# What `python -m recall.eval` imports: recall (src), insight.extract and profiler (the e5 embedder
# and the customData parser). Nothing else is copied.
COPY src ./src
COPY profiler ./profiler
COPY insight ./insight

# The project is not installed (its wheel lists packages this image does not carry), so the code
# is found through PYTHONPATH, as on the box's venv runs.
ENV PATH="/work/.venv/bin:$PATH" \
    PYTHONPATH="/work/src:/work" \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# A missing module, or a CPU-only torch wheel, is a build failure and not a failure in the GPU run.
RUN python -c "\
import torch, transformers; \
assert torch.version.cuda, 'torch is a CPU-only build'; \
import recall.eval, recall.rerank, recall.retrieve, insight.extract, profiler.gate.embedder; \
print('eval image ok, torch', torch.__version__, 'cuda', torch.version.cuda, \
'transformers', transformers.__version__)"

ENTRYPOINT []
