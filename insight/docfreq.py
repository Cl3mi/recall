"""Word, pair and triple counts where the unit is the TICKET, not the occurrence.

The release floor means "at least k tickets". `profiler.stats.vocab` counts every occurrence, so
one ticket that repeats a name sixty times (a pasted mail thread, a repeated signature) cleared a
floor of 50 on its own and released the name. Counting document frequency, one per ticket per
distinct n-gram, makes the floor mean what it says. It lives here and not in `profiler.stats.vocab`
because Window A's published numbers must not change meaning.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable

from profiler.stats import vocab


def _count(texts: Iterable[str], grams: Callable[[list[str]], Iterable[str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(set(grams(vocab.tokenize(text))))
    return counts


def tokens(texts: Iterable[str]) -> Counter[str]:
    return _count(texts, lambda toks: toks)


def bigrams(texts: Iterable[str]) -> Counter[str]:
    return _count(texts, lambda toks: (f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)))


def trigrams(texts: Iterable[str]) -> Counter[str]:
    return _count(
        texts,
        lambda toks: (f"{a} {b} {c}" for a, b, c in zip(toks, toks[1:], toks[2:], strict=False)),
    )
