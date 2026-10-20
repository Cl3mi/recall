"""Check 2: is any synthetic document unusually close to a real one?

The bar is not a constant. An absolute cosine is uninterpretable - 0.90 may be alarming or
unremarkable depending on the model and the domain - so the synthetic-vs-real tail is compared
against a synthetic-vs-synthetic baseline measured in the SAME window with the SAME embedder.
If synthetic-to-real is no closer than synthetic-to-synthetic, no real document sits unusually
close to anything we generated.

The two are read at DIFFERENT quantiles - CROSS_PERCENTILE and BASELINE_PERCENTILE - and that
asymmetry is deliberate and measured. See those constants.

No vectors leave this module's caller. `docs/airlock-runbook.md`: real-corpus embeddings are
not retained between windows, because the embedding model is public and inversion attacks
reconstruct substantial portions of short texts. Every public function returns a float.
"""

from __future__ import annotations

import numpy as np

from profiler.gate.embedder import E5_DOCUMENT_PREFIX, Embedder

# Rows per matrix multiplication. A real corpus of tens of thousands of documents against 1,500
# synthetic ones is tens of millions of cosines - trivial as arithmetic, a few hundred MB as one
# float64 matrix. Chunking keeps the peak flat on a box that is shared.
CHUNK = 256

# The two quantiles are DIFFERENT, deliberately, and each is chosen for its own job.
#
# CROSS is the tail: a leak shows up as a handful of synthetic rows sitting unusually close to
# real ones, so the 99th percentile is what has to be watched.
#
# BASELINE cannot use the 99th, because the fixture is BUILT to contain near-duplicate
# clusters. Measured on the accepted 1,500-row fixture: 360 rows (24.0%) sit in deliberate
# groups and 41 (2.7%) have a twin at cosine ~1.0, which is more than the 1% the 99th
# percentile needs, so the baseline came out 1.000000 - making the bar `cross <= 1.0`, which
# nothing can exceed. Recorded as finding 12 in docs/STATE.md.
#
# 95 rather than 90, 75 or 50, chosen by measurement rather than by eye. The bar must sit above
# a CLEAN comparison or the gate false-alarms on a fixture that is fine, and gets relaxed the
# first time it does. Round 3 is the only parked fixture genuinely independent of the current
# one - 0.1% byte-identical document overlap, against 71-87% for rounds 4-6, which were built
# from the same cached model responses - and round 7 against round 3 scores cross_p99 0.898644.
# Against that:
#
#     p99  1.000000  saturated, the check cannot fail
#     p95  0.965943  above 0.898644 - usable, and the highest that is not saturated
#     p90  0.942546  above 0.898644 - usable but tighter for no gain
#     p75  0.852062  BELOW 0.898644 - would fail a clean fixture
#     p50  0.751427  BELOW 0.898644 - would fail a clean fixture
#
# Round 3 shares this generator's themes and subsystem vocabulary, so it is MORE similar to
# round 7 than real data should be to either: 0.898644 is a conservative bound and the real
# headroom is larger. `report.baseline_saturated` still fires if p95 itself ever saturates,
# which needs only 5% of rows to have an identical twin against the 2.7% measured today.
CROSS_PERCENTILE = 99
BASELINE_PERCENTILE = 95


def _encode(documents: list[str], model: Embedder) -> np.ndarray:
    return model.encode([E5_DOCUMENT_PREFIX + (document or "") for document in documents])


def _nearest(left: np.ndarray, right: np.ndarray, exclude_diagonal: bool) -> np.ndarray:
    """Each left row's highest cosine against any right row."""
    best = np.full(left.shape[0], -1.0)
    for start in range(0, left.shape[0], CHUNK):
        stop = min(start + CHUNK, left.shape[0])
        block = left[start:stop] @ right.T
        if exclude_diagonal:
            for offset in range(stop - start):
                block[offset, start + offset] = -1.0
        best[start:stop] = block.max(axis=1)
    return best


def self_baseline(documents: list[str], model: Embedder) -> float:
    """BASELINE_PERCENTILE nearest-neighbour cosine WITHIN one corpus, excluding each document
    itself.

    TWO independent guards against the same failure, both of which were needed.

    The diagonal exclusion is the first. Without it every document's nearest neighbour is
    itself at cosine 1.0, so the baseline is 1.0 for any corpus whatsoever, `passes(cross, 1.0)`
    is true for every possible input, and the gate reports green unconditionally while
    appearing to do arithmetic. Measured rather than reasoned: the diagonal-included version was
    written first and `test_a_document_is_not_its_own_nearest_neighbour` failed at
    1.0000000000000004.

    BASELINE_PERCENTILE is the second, and it was needed because excluding the diagonal was not
    enough - the fixture's own deliberate near-duplicate groups saturated the 99th percentile
    anyway. See that constant for the measurements behind 95.
    """
    if len(documents) < 2:
        return 0.0
    vectors = _encode(documents, model)
    nearest = _nearest(vectors, vectors, exclude_diagonal=True)
    return float(np.percentile(nearest, BASELINE_PERCENTILE))


def cross_p99(synthetic: list[str], real: list[str], model: Embedder) -> float:
    """CROSS_PERCENTILE of each synthetic document's nearest cosine against the real corpus.

    Stays at the 99th: a leak surfaces as a handful of synthetic rows sitting unusually close
    to real ones, so the tail is the thing to watch.
    """
    if not synthetic or not real:
        return 0.0
    nearest = _nearest(_encode(synthetic, model), _encode(real, model), exclude_diagonal=False)
    return float(np.percentile(nearest, CROSS_PERCENTILE))


def passes(cross_p99: float, baseline_p95: float) -> bool:
    """At or below the baseline passes. No slack: a margin above it is a tolerance nobody
    calibrated, and this project's rule is to fix the generator rather than the tolerance.

    The two arguments are deliberately different quantiles - the cross tail against an
    uncontaminated estimate of intra-synthetic closeness. The names say which, so nobody has to
    infer it.
    """
    return cross_p99 <= baseline_p95
