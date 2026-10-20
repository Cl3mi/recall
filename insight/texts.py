"""Evidence about the text that needs no model: lengths, identifier density, repetition.

The bases differ between measures, so they are stated here rather than left to be guessed:

  * lengths: `title`, `description` and `solutions` are measured on the RAW text; `problem_text`
    is the CLEANED title + description (HTML, quoted replies and signatures stripped, PII
    redacted to placeholders that themselves count as tokens).
  * identifiers: counted on the raw text AND after the cleaning pipeline, for the problem and
    the solutions alike. Both sides share one basis, and what cleaning destroys becomes a number
    (`tickets` against `tickets_after_cleaning`) instead of a silent bias. The pipeline's phone
    pattern, for one, redacts a part number such as 1234.56789.
  * repetition: `k` is the release floor, reused as the minimum cluster size. Tickets with a
    blank problem text are left out of the clustering and counted, because identical empty
    texts would otherwise form one spurious cluster.

Lengths are WHITESPACE tokens and labelled so. The e5 truncation share needs the model's own
tokenizer and belongs to stage 2; reporting a proxy under the real name would be a number that
looks measured and is not.
"""

from __future__ import annotations

from insight import measures, release
from insight.extract import Ticket
from profiler.stats import clusters, lengths
from recall.clean import pipeline
from recall.german import identifiers

# Our own closed list, taken from the extractor's patterns: kind names are never corpus text.
IDENTIFIER_KINDS = tuple(kind for kind, _ in identifiers.PATTERNS)


def _lengths(tickets: list[Ticket], problem: list[str]) -> dict:
    def quantiles(values: list[str]) -> dict[str, float]:
        return lengths.quantiles([len(v.split()) for v in values])

    return {
        "unit": "whitespace_tokens",
        "title": quantiles([t.title for t in tickets]),
        "description": quantiles([t.description for t in tickets]),
        "solutions": quantiles([t.solutions for t in tickets]),
        "problem_text": quantiles(problem),
    }


def _kinds(documents: list[str]) -> list[set[str]]:
    return [{i.kind for i in identifiers.extract(text)} for text in documents]


def _density(raw: list[str], cleaned: list[str]) -> dict:
    """Identifier density on the raw text and again after cleaning, so the loss is visible."""
    before = _kinds(raw)
    after = _kinds(cleaned)
    total = len(raw)
    by_kind = []
    for kind in IDENTIFIER_KINDS:
        n = sum(1 for kinds in before if kind in kinds)
        kept = sum(1 for kinds in after if kind in kinds)
        by_kind.append(
            {
                "kind": kind,
                "tickets": n,
                "tickets_after_cleaning": kept,
                "share": measures.ratio(n, total),
            }
        )
    return {
        "any_share": measures.ratio(sum(1 for kinds in before if kinds), total),
        "any_share_after_cleaning": measures.ratio(sum(1 for kinds in after if kinds), total),
        "by_kind": by_kind,
    }


def _repetition(problem: list[str], k: int) -> dict:
    # Sorted first. The clustering is greedy and arrival-ordered over LSH neighbours that are
    # not transitive, so on a chain of overlapping texts the cluster sizes changed with the row
    # order of the export. Sorting makes the result a function of the set of texts.
    documents = sorted(d for d in problem if d.strip())
    profile = clusters.profile(documents)
    distribution = {int(size): count for size, count in profile["size_distribution"].items()}
    in_large = sum(size * count for size, count in distribution.items() if size >= k)
    largest = max(distribution, default=0)
    return {
        "blank_problem_text": len(problem) - len(documents),
        "cluster_count": profile["cluster_count"],
        "singleton_count": profile["singleton_count"],
        "share_in_clusters_at_least_k": measures.ratio(in_large, len(documents)),
        # A group smaller than the floor is not described, not even by its share of the corpus.
        "largest_cluster_share": measures.ratio(largest, len(documents)) if largest >= k else None,
    }


def cluster_sizes(tickets: list[Ticket]) -> list[int]:
    """Per ticket, in the ORIGINAL order, the size of its near-duplicate cluster; 0 for a blank
    problem text, which is left out of the clustering exactly as in `_repetition`.

    The same clustering over the same sorted documents, so the sizes are a function of the set
    of texts and not of the row order. Identical texts have identical hashes and always share a
    cluster, so a size belongs to a text and can be looked up by it.
    """
    problem = [pipeline.clean(f"{t.title} {t.description}").text for t in tickets]
    documents = sorted(d for d in problem if d.strip())
    size_of: dict[str, int] = {}
    for members in clusters.groups(documents):
        for i in members:
            size_of[documents[i]] = len(members)
    return [size_of[d] if d.strip() else 0 for d in problem]


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    problem_raw = [f"{t.title} {t.description}" for t in tickets]
    problem = [pipeline.clean(text).text for text in problem_raw]
    solutions_raw = [t.solutions for t in tickets]
    solutions = [pipeline.clean(text).text for text in solutions_raw]
    return {
        "lengths": _lengths(tickets, problem),
        "identifiers": {
            "problem": _density(problem_raw, problem),
            "solutions": _density(solutions_raw, solutions),
        },
        "repetition": _repetition(problem, k),
    }
