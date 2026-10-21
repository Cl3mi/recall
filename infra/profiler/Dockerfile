# Sealed profiler image. Everything is baked in beforehand so the airlock window
# can run with --network=none: nothing resolves at run time. `--frozen` fails loudly
# if uv.lock is stale rather than silently reaching for the network.
FROM python:3.12-slim-bookworm

# hunspell + the German dictionary: without these, vocabulary.hunspell_unrecognized_top
# comes back empty and the §7 synonym-mining input is lost for a whole cycle.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends hunspell hunspell-de-de coreutils; \
    rm -rf /var/lib/apt/lists/*; \
    hunspell -d de_DE -l </dev/null

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /work
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY profiler ./profiler
RUN uv sync --frozen --no-dev

ENV PATH="/work/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# The model weights, fetched at BUILD time because the window runs with --network=none and
# nothing resolves there. ~2.2 GB. HF_HOME is set before the fetch so the cache lands inside
# the image rather than in a layer that gets discarded.
ENV HF_HOME=/opt/hf
RUN python -c "\
from transformers import AutoModel, AutoTokenizer; \
from profiler.gate.embedder import E5_MODEL, E5_REVISION; \
AutoTokenizer.from_pretrained(E5_MODEL, revision=E5_REVISION); \
AutoModel.from_pretrained(E5_MODEL, revision=E5_REVISION); \
print('weights baked')"

# Belt and braces on --network=none. Without these, transformers may still attempt a hub
# lookup and fail with a network error INSIDE a sealed window, where there is no AI available
# to work out why. local_files_only in E5Embedder is the first guard; these are the second.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Window D's report. Copied AFTER the weights are baked on purpose: the heavy layers (torch,
# ~2.2 GB of weights) stay cached when only this code changes. It is not an installed package, so
# `python -m insight` resolves it from /work, the working directory - which is why nothing may
# be mounted over /work in a window.
COPY insight ./insight

# Proves the image works offline before a single real row is anywhere near it - and that the
# MODEL loads offline, which turns missing weights into a build failure rather than a
# sealed-window one. insight.__main__ is imported too, so a missing module is a build failure.
RUN python -c "\
import profiler.__main__, insight.__main__, recall.clean.pipeline; \
from profiler.gate.embedder import E5Embedder; \
v = E5Embedder().encode(['passage: Pumpe undicht']); \
assert v.shape[0] == 1, v.shape; \
print('sealed image ok, model loads offline, dim', v.shape[1])"

ENTRYPOINT []
