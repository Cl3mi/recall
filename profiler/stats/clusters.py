from __future__ import annotations

import math
from collections import Counter

from datasketch import MinHash, MinHashLSH

from profiler.stats import lengths, vocab


def _minhash(text: str, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for token in set(vocab.tokenize(text)):
        m.update(token.encode())
    return m


def groups(docs: list[str], threshold: float = 0.7, num_perm: int = 128) -> list[set[int]]:
    """The greedy near-duplicate groups, as sets of indexes into `docs`, in arrival order."""
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    hashes = {}
    for i, doc in enumerate(docs):
        h = _minhash(doc, num_perm)
        hashes[i] = h
        lsh.insert(str(i), h)

    seen: set[int] = set()
    found: list[set[int]] = []
    for i in range(len(docs)):
        if i in seen:
            continue
        members = {int(k) for k in lsh.query(hashes[i])} | {i}
        members -= seen
        seen |= members
        found.append(members)
    return found


def profile(docs: list[str], threshold: float = 0.7, num_perm: int = 128) -> dict:
    """Near-duplicate cluster-size distribution. This is the piece people skip and
    the piece that makes the synthetic corpus useful: two tickets from the same
    cluster are relevant to each other, which is a free gold label."""
    sizes = [len(g) for g in groups(docs, threshold, num_perm)]

    dist = Counter(sizes)
    return {
        "method": f"minhash-lsh(num_perm={num_perm}) over cleaned title+description",
        "threshold": threshold,
        "cluster_count": len(sizes),
        "singleton_count": dist.get(1, 0),
        "size_distribution": {str(k): v for k, v in sorted(dist.items())},
        "size_quantiles": lengths.quantiles(sizes),
        "zipf_alpha_estimate": _zipf_alpha(sizes),
    }


def _zipf_alpha(sizes: list[int]) -> float | None:
    """Hill estimator on cluster sizes >= 2. Reported so the generator can match
    the real long tail rather than producing uniform cluster sizes."""
    tail = sorted((s for s in sizes if s >= 2), reverse=True)
    if len(tail) < 5:
        return None

    xmin = tail[-1]
    if not xmin:
        return None
    # The estimator is undefined when the tail has no spread above xmin: every term
    # is log(1) = 0 and the denominator collapses. That is not exotic - a corpus
    # whose clusters are all the same size hits it, and so does the stand-in CSV.
    denominator = sum(math.log(s / xmin) for s in tail if s > xmin)
    return len(tail) / denominator if denominator > 0 else None


MAX_CHARACTERISED = 20


def characterise(
    docs: list[str], min_frequency: int, is_entity, threshold: float = 0.7, num_perm: int = 128
) -> tuple[list[dict], int]:
    """Top tokens of the largest near-duplicate clusters, so a dominant group can be
    identified. Clusters below min_frequency members are not characterised: a
    three-ticket cluster's top tokens is a summary of three tickets."""
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    hashes = {}
    for i, doc in enumerate(docs):
        h = _minhash(doc, num_perm)
        hashes[i] = h
        lsh.insert(str(i), h)

    seen: set[int] = set()
    groups: list[set[int]] = []
    for i in range(len(docs)):
        if i in seen:
            continue
        members = ({int(k) for k in lsh.query(hashes[i])} | {i}) - seen
        seen |= members
        groups.append(members)

    big = sorted((g for g in groups if len(g) >= min_frequency), key=len, reverse=True)
    total = len(docs) or 1
    out = []
    for group in big[:MAX_CHARACTERISED]:
        counts = vocab.token_counts([docs[i] for i in group])
        out.append(
            {
                "size": len(group),
                "share": len(group) / total,
                "top_tokens": [
                    t["token"]
                    for t in vocab.top_tokens(counts, min_frequency, 15)
                    if not is_entity(t["token"])
                ],
            }
        )
    return out, max(0, len(big) - MAX_CHARACTERISED)
