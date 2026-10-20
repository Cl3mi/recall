"""Who produced the vectors, and a deterministic stand-in for tests.

The real model is `intfloat/multilingual-e5-large` (operator decision, 2026-08-27), shared
with M3's pgvector index so the gate's cosine bound applies to the vectors M3 actually
stores. Its integration is a later plan; nothing here imports torch, so the whole gate is
testable in CI on a machine with no model and no GPU.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

# Both corpora are DOCUMENTS for this gate, so both get e5's passage prefix. Mixing
# `query: ` and `passage: ` across the two sides would silently shift every cosine in the
# report, and the report is the artifact a DPO reads.
E5_DOCUMENT_PREFIX = "passage: "

# e5-large truncates at 512 tokens. The limit is stated here, applied identically to both
# corpora, and recorded in the report: truncating the real side harder than the synthetic
# side would bias every neighbour distance in the fixture's favour.
MAX_TOKENS = 512


class Embedder(Protocol):
    """Anything that turns documents into unit-norm row vectors."""

    identity: str

    def encode(self, documents: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    """A deterministic, dependency-free embedder for tests.

    Not a model and not pretending to be one: it hashes character trigrams into a fixed number
    of buckets and normalises. That is enough to exercise every arithmetic path in the
    neighbour check - identical text gives cosine 1.0, unrelated text gives something small -
    without torch, a GPU, or a download.

    Its identity begins with `hashing:` precisely so a gate report produced with it can never
    be mistaken for one produced by the real model.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim
        self.identity = f"hashing:trigram:dim={dim}"

    def encode(self, documents: list[str]) -> np.ndarray:
        vectors = np.zeros((len(documents), self._dim), dtype=np.float64)
        for row, document in enumerate(documents):
            text = (document or "").lower()
            for start in range(max(len(text) - 2, 1)):
                trigram = text[start : start + 3]
                digest = hashlib.sha256(trigram.encode("utf-8")).digest()
                vectors[row, int.from_bytes(digest[:4], "big") % self._dim] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vectors / norms


# The operator's choice on 2026-08-27, shared with M3's pgvector index so the gate's cosine
# bound applies to the vectors M3 actually stores. Pinned by revision: the manifest exists to
# make a run reproducible, and "multilingual-e5-large" without a revision is a claim about
# whatever the hub served that day.
E5_MODEL = "intfloat/multilingual-e5-large"
E5_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"


class E5Embedder:
    """`intfloat/multilingual-e5-large` on CPU, offline.

    Loads from the local cache only. The airlock window runs with `--network=none`, so a hub
    lookup there fails inside a sealed window with no AI available to debug it - the weights are
    baked into the image at build time and `local_files_only=True` makes an attempt to reach out
    a loud failure here rather than a mystery there.

    GPU when one is present, CPU otherwise (operator, 2026-09-11, reversing the 2026-09-07
    CPU-only decision once the CPU cost was measured at ~2.2 h per window). The fallback is
    not a nicety and must not be removed: the sealed image's own build-time self-check runs
    with NO GPU attached, the test suite has to keep passing on a CPU-only machine, and a
    window that found no GPU must still produce a verdict rather than crash somewhere nobody
    can read the error.

    The device is deliberately NOT part of `identity`, which names the weights. That is only
    defensible because the two agree numerically, which
    `test_the_device_does_not_change_the_vectors` pins - if they ever diverge, the gate's
    calibrated threshold (finding 18) would mean something different depending on where it
    ran, and identity would have to carry the device.

    Pooling is a MASKED MEAN over the last hidden state, which is what this model family
    requires. CLS pooling would produce plausible-looking but degraded vectors, and a gate that
    is green for the wrong reason is the failure mode this whole project keeps hitting.
    """

    def __init__(
        self, model: str = E5_MODEL, revision: str = E5_REVISION, device: str | None = None
    ) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        # Overridable so a test can force CPU and compare the two.
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._tokenizer = AutoTokenizer.from_pretrained(
            model, revision=revision, local_files_only=True
        )
        self._model = (
            AutoModel.from_pretrained(model, revision=revision, local_files_only=True)
            .eval()
            .to(self.device)
        )
        self.identity = f"e5:{model}@{revision}"

    def encode(self, documents: list[str], batch_size: int = 16) -> np.ndarray:
        torch = self._torch
        out: list[np.ndarray] = []
        for start in range(0, len(documents), batch_size):
            batch = [d or "" for d in documents[start : start + batch_size]]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=MAX_TOKENS,
                return_tensors="pt",
            )
            # Inputs must follow the weights, or torch raises on a device mismatch. Done here
            # rather than in the tokenizer call so the CPU path allocates nothing extra.
            encoded = {name: tensor.to(self.device) for name, tensor in encoded.items()}
            with torch.no_grad():
                hidden = self._model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.cpu().numpy().astype(np.float64))
        return np.vstack(out) if out else np.zeros((0, 1))
