"""`gate_report.json` - the artifact, and the only thing that leaves the window.

`PROJECT_BRIEF.md` §8 calls for a signed report: "that file is the answer when the client's
DPO asks how leakage was ruled out". The operator chose a hash manifest over keys on
2026-08-27 - the report pins its inputs by SHA-256, the code commit, the image digest and the
embedder identity, so any later change to the inputs is detectable and the run is
reproducible, with no key custody on a shared box.

It carries COUNTS, THRESHOLDS AND VERDICTS ONLY. No shingle, no vector, no row. A report that
quoted the colliding shingle would carry real corpus text out of the window, which is the one
thing the airlock exists to prevent, and
`tests/unit/test_gate_report.py::test_no_check_carries_examples_or_sample_text` pins every
check's key set so adding such a field fails there rather than inside a window.
"""

from __future__ import annotations

from profiler.gate import neighbours, sweep
from profiler.gate.embedder import E5_DOCUMENT_PREFIX, MAX_TOKENS
from profiler.gate.shingles import WINDOW


def build(
    *,
    shingle_collisions: int,
    pii_hits: dict[str, int],
    roster_violations: int,
    roster_values_traced: int,
    cross_p99: float,
    baseline_p95: float,
    embedder: str,
    synthetic_sha256: str,
    real_sha256: str,
    synthetic_rows: int,
    real_rows: int,
    code_commit: str,
    image_digest: str,
) -> dict:
    checks = {
        "shingles": {
            "passed": shingle_collisions == 0,
            "synthetic_rows_sharing_a_shingle": shingle_collisions,
            "bar": 0,
        },
        "neighbours": {
            "passed": neighbours.passes(cross_p99, baseline_p95),
            "cross_p99": round(cross_p99, 6),
            "baseline_p95": round(baseline_p95, 6),
            "bar": "cross_p99 <= baseline_p95",
            # A saturated baseline makes the bar `cross_p99 <= 1.0`, which nothing can exceed,
            # so `passed: true` would be uninterpretable rather than reassuring.
            #
            # This FIRED once and was fixed: at the 99th percentile the baseline came out
            # 1.000000 on the accepted fixture, because 24% of its rows sit in deliberate
            # near-duplicate groups and 41 (2.7%) have a twin at cosine ~1.0 - more than the 1%
            # that percentile needs. `neighbours.BASELINE_PERCENTILE` is now 95, measured at
            # 0.965943, which needs 5% of rows to be twinned before it saturates. The flag
            # stays as the guard for a future fixture with more cluster mass than this one.
            "baseline_saturated": baseline_p95 >= 0.999,
        },
        "pii": {
            "passed": sum(pii_hits.values()) == 0,
            "hits": dict(pii_hits),
            # Which of §8's six pattern families actually ran. Three are implemented; plate
            # detection is absent because it matches every designation of the fixture's own
            # invented product line, and a green verdict must not read as "no PII of any kind".
            "patterns": list(sweep.PATTERNS),
            "bar": 0,
        },
        "roster": {
            "passed": roster_violations == 0,
            "violations": roster_violations,
            # How many non-blank values the check actually examined.
            #
            # Finding 13, measured 2026-09-08 and again 2026-09-14: ROSTER_COLUMN names a key
            # inside the double-encoded customData envelope, NOT one of the 38 columns, so
            # this comes out 0 on the current fixture - and `passed` is true because there was
            # nothing to trace, not because everything traced was clean. Only 13 of the 38
            # columns are filled at all and every name-bearing one (merchantName,
            # endCustomerName, lastModifiedUser) is empty, so repointing the column would not
            # change that.
            #
            # Without this number the two cases are byte-identical in the artifact, which is
            # exactly the hazard `baseline_saturated` exists for on check 2. A DPO reading
            # "roster: passed" must be able to see whether anything was looked at.
            "values_traced": roster_values_traced,
            "bar": 0,
        },
    }
    return {
        "verdict": "green" if all(check["passed"] for check in checks.values()) else "red",
        # A green gate produced with the hashing stand-in must be identifiable as such from
        # the artifact alone. Finding 1 cost two rounds to a stub nobody could see.
        "embedder_is_a_model": not embedder.startswith("hashing:"),
        "checks": checks,
        "manifest": {
            "synthetic_sha256": synthetic_sha256,
            "real_sha256": real_sha256,
            "synthetic_rows": synthetic_rows,
            "real_rows": real_rows,
            "code_commit": code_commit,
            "image_digest": image_digest,
            "embedder": embedder,
            "max_tokens": MAX_TOKENS,
            "document_prefix": E5_DOCUMENT_PREFIX,
            "shingle_window": WINDOW,
        },
    }
