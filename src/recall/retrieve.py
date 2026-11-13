"""Hybrid retrieval: a dense arm (e5 over pgvector), a lexical arm (de_tech full text) and
reciprocal rank fusion of the two.

The lexical query is an OR of the query's words: plainto_tsquery ANDs every term and a pasted
ticket has dozens, so almost nothing would match and the arm would go silently empty (M3 spec,
section 2). This module never names the label table: whatever defines relevance must be
invisible to the retriever, or the metric is circular.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date

from recall import index
from recall.clean import pipeline

RRF_K = 60
ARMS = ("dense", "lexical")
POOL = 100
MAX_TERMS = 64
DOC_TEXTS = ("problem", "problem_solution")  # what a reranker reads of a candidate
_WORD = re.compile(r"[a-z0-9äöüß_]+")


@dataclass(frozen=True)
class Hit:
    doc_id: str
    score: float
    ranks: dict[str, int] = field(
        default_factory=dict
    )  # arm -> 1-based rank, only arms that found it
    rerank: float | None = None  # the reranker's score, when one ran


def fuse(
    arms: dict[str, list[str]],
    *,
    limit: int | None = None,
    weights: dict[str, float] | None = None,
) -> list[Hit]:
    """Fuse ranked id lists: score = sum over arms of weight / (RRF_K + rank), weight 1.0 unless
    `weights` names the arm.

    Ties go to the better best rank, then to the id, so the order never depends on the order of
    `arms`. An id repeated inside one arm counts once, at its first rank.
    """
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for arm, ids in arms.items():
        seen: set[str] = set()
        for position, doc_id in enumerate(ids, 1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + (weights or {}).get(arm, 1.0) / (
                RRF_K + position
            )
            ranks.setdefault(doc_id, {})[arm] = position
    ordered = sorted(scores, key=lambda d: (-scores[d], min(ranks[d].values()), d))
    hits = [Hit(d, scores[d], dict(sorted(ranks[d].items()))) for d in ordered]
    return hits if limit is None else hits[:limit]


def or_query(text: str | None) -> str:
    """`a | b | c` over the distinct lowercase words of `text`, at most MAX_TERMS.

    Only letters, digits and underscore survive, so nothing in the text can act as a tsquery
    operator."""
    words = dict.fromkeys(_WORD.findall((text or "").casefold()))
    return " | ".join(list(words)[:MAX_TERMS])


def clean_query(text: str) -> str:
    """The query as the index sees its own text (index/query symmetry)."""
    return pipeline.clean(text).text


_TEXTS = "select ticket_id, problem_text, solution_text from ticket where ticket_id = any(%(ids)s)"


def fetch_texts(conn, ids: list[str]) -> dict[str, tuple[str, str]]:
    """{ticket id: (problem text, solution text)} for the given ids, in one query."""
    rows = conn.execute(_TEXTS, {"ids": list(ids)}).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def rerank(
    reranker,
    query: str,
    hits: list[Hit],
    texts: dict[str, tuple[str, str]],
    *,
    doc_text: str,
) -> list[Hit]:
    """`hits` reordered by the reranker's score alone, ties kept in fused order.

    `query` must already be cleaned. `doc_text` picks what the reranker reads of a candidate: the
    problem, or the problem and the solution (an empty solution is sent as None)."""
    if doc_text not in DOC_TEXTS:
        raise ValueError(f"unknown doc_text {doc_text!r}")
    candidates = [
        (
            texts[h.doc_id][0],
            (texts[h.doc_id][1] or None) if doc_text == "problem_solution" else None,
        )
        for h in hits
    ]
    scores = reranker.score(query, candidates)
    order = sorted(range(len(hits)), key=lambda i: (-scores[i], i))
    return [replace(hits[i], rerank=float(scores[i])) for i in order]


_FILTER = (
    "(%(exclude)s::text is null or ticket_id <> %(exclude)s) "
    "and (%(before)s::date is null or created < %(before)s)"
)
_DENSE = (
    "select ticket_id from ticket where " + _FILTER + " "
    "order by problem_vec <=> %(vec)s::vector, ticket_id limit %(pool)s"
)
_LEXICAL = (
    "select ticket_id from ticket, to_tsquery('de_tech'::regconfig, %(query)s) q "
    "where problem_tsv @@ q and " + _FILTER + " "
    "order by ts_rank_cd(problem_tsv, q) desc, ticket_id limit %(pool)s"
)


def search(
    conn,
    embedder,
    text: str,
    *,
    k: int = 10,
    pool: int = POOL,
    arms: tuple[str, ...] = ARMS,
    exclude_id: str | None = None,
    before: date | None = None,
    prefix: str = index.QUERY,
    weights: dict[str, float] | None = None,
    reranker=None,
    depth: int | None = None,
    doc_text: str = "problem",
) -> list[Hit]:
    """The top k fused hits for text, each carrying its per-arm ranks.

    The query is cleaned exactly like the indexed text (index/query symmetry). exclude_id keeps
    an indexed ticket from finding itself when it is the query; before keeps only candidates
    created before that date, so the future cannot leak into the past. prefix is the e5 prefix
    of the query embedding (the stored vectors use "passage: "). weights scales an arm's RRF
    contribution (see fuse). With a reranker, the fused top `depth` are reordered by its score
    alone (see rerank) and the top k of that order are returned; without one the result is the
    fused top k.
    """
    unknown = [arm for arm in arms if arm not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm {unknown[0]!r}")
    if reranker is not None and (depth is None or depth < k):
        raise ValueError(f"a reranker needs a depth of at least k={k}, got {depth}")
    if doc_text not in DOC_TEXTS:
        raise ValueError(f"unknown doc_text {doc_text!r}")
    cleaned = clean_query(text)
    found: dict[str, list[str]] = {}
    params = {"exclude": exclude_id, "before": before, "pool": pool}
    if "dense" in arms and cleaned.strip():
        vector = index.vector_literal(embedder.encode([prefix + cleaned])[0])
        rows = conn.execute(_DENSE, {**params, "vec": vector}).fetchall()
        found["dense"] = [r[0] for r in rows]
    if "lexical" in arms:
        query = or_query(cleaned)
        if query:
            rows = conn.execute(_LEXICAL, {**params, "query": query}).fetchall()
            found["lexical"] = [r[0] for r in rows]
    if reranker is None:
        return fuse(found, limit=k, weights=weights)
    hits = fuse(found, limit=depth, weights=weights)
    texts = fetch_texts(conn, [h.doc_id for h in hits])
    return rerank(reranker, cleaned, hits, texts, doc_text=doc_text)[:k]
