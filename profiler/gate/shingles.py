"""Content-bearing 8-token shingles, and whether two corpora share one.

The bar is ZERO shared shingles, not a tolerance. From the approved design: a threshold here
is something we would later be tempted to relax, and a single hit is worth investigating
rather than excusing.

Nothing in this module may return a shingle or a document to a caller that will print it. A
set of 8-token shingles is a membership oracle over the real corpus and must not exist
off-box - see docs/airlock-runbook.md. The public functions therefore return COUNTS.
"""

from __future__ import annotations

import pathlib

from profiler.stats import vocab
from recall.clean import pipeline

_DATA = pathlib.Path(__file__).parent.parent / "data" / "german_stopwords.txt"


def _load_stopwords() -> frozenset[str]:
    lines = _DATA.read_text(encoding="utf-8").splitlines()
    return frozenset(
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    )


STOPWORDS = _load_stopwords()

# Eight content words. Long enough that a shared run is real evidence rather than German
# idiom, which PROJECT_BRIEF section 8 fixes at 8 tokens.
WINDOW = 8


def _content_tokens(document: str) -> list[str]:
    """Cleaned, lower-cased, stopword-free tokens.

    Uses the project's own cleaner and tokenizer rather than a local split, for the same
    reason the fixture generator does: a check that tokenises differently from the rest of the
    system is checking something the rest of the system does not see.
    """
    cleaned = pipeline.clean(document or "").text
    return [token for token in vocab.tokenize(cleaned) if token not in STOPWORDS]


def shingles_of(document: str) -> frozenset[tuple[str, ...]]:
    """Every contiguous run of WINDOW content tokens. Empty when the document is too short."""
    tokens = _content_tokens(document)
    if len(tokens) < WINDOW:
        return frozenset()
    return frozenset(
        tuple(tokens[start : start + WINDOW]) for start in range(len(tokens) - WINDOW + 1)
    )


def collisions(synthetic: list[str], real: list[str]) -> int:
    """How many SYNTHETIC documents share at least one content-bearing shingle with any real
    document.

    Counts documents rather than shingles because a document is what an investigation acts
    on: one row sharing three shingles is one row to look at. Returns an int and nothing else -
    the real corpus's shingle set is built here, used here, and dropped here.
    """
    real_shingles: set[tuple[str, ...]] = set()
    for document in real:
        real_shingles |= shingles_of(document)
    return sum(1 for document in synthetic if shingles_of(document) & real_shingles)
