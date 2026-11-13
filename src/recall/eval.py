"""Retrieval metrics, identical for the synthetic and the real corpus.

recall@k divides by min(k, |relevant|), so a member of a 216-ticket group is not capped at
10/215 and read as failure. Scores are macro-averaged per problem group, so one large group
cannot dominate by contributing hundreds of near-identical queries. Aggregates only: nothing
here carries a ticket id or text out.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from insight import extract
from recall import index, retrieve

QUERY_PREFIX = index.QUERY
CAVEAT = (
    "Scores on a synthetic corpus are evidence that the code is correct, not evidence of "
    "retrieval quality on real tickets: stand-in text is far more regular than real text."
)
VARIANTS = {
    "dense_passage": {"arms": ("dense",), "prefix": index.PASSAGE},
    "dense_query": {"arms": ("dense",), "prefix": QUERY_PREFIX},
    "lexical": {"arms": ("lexical",)},
    "fused": {"prefix": index.PASSAGE},  # baseline: dense with passage: plus lexical
    "fused_query": {"prefix": QUERY_PREFIX},  # dense with query: plus lexical
    # One weight only: lexical is unusually regular on invented text, so do not tune several.
    "fused_dense2": {"prefix": QUERY_PREFIX, "weights": {"dense": 2.0}},
}
# What a ticket is asked with. A technician rarely pastes a whole indexed ticket: "title" is the
# first line only, "head" the first HEAD_WORDS words, a short search phrase.
QUERY_MODES = ("full", "title", "head")
HEAD_WORDS = 8
# The deepest list there is: two arms of POOL fuse into at most 2 * POOL ids, so recall at this
# depth is recall over the union of both pools, the ceiling of any rerank over them.
ALL_DEPTH = 2 * retrieve.POOL
RERANK_BASE = "fused_query"  # the fused list a reranker reorders, and the variant it must beat


def parse_depths(text: str) -> tuple[int | str, ...]:
    """`10,50,all` as (10, 50, "all"); a depth is a positive integer or `all`."""
    depths: list[int | str] = []
    for part in text.split(","):
        if part == "all":
            depths.append("all")
        elif part.isdigit() and int(part) > 0:
            depths.append(int(part))
        else:
            raise ValueError(f"not a depth: {part!r}")
    return tuple(depths)


def _depth(depth: int | str) -> int:
    return ALL_DEPTH if depth == "all" else int(depth)


def query_text(mode: str, text: str) -> str:
    """The query for a ticket whose indexed problem text is `text` (title, then description)."""
    if mode == "full":
        return text
    if mode == "title":
        return text.split("\n", 1)[0].strip()
    if mode == "head":
        return " ".join(text.split()[:HEAD_WORDS])
    raise ValueError(f"unknown query mode {mode!r}")


@dataclass(frozen=True)
class QueryMetrics:
    recall: float
    rr: float
    ndcg: float


def query_metrics(ranked: list[str], relevant: set[str], k: int = 10) -> QueryMetrics:
    """Metrics of one ranked id list against its relevant set (which must not be empty)."""
    top = ranked[:k]
    gains = [1.0 if doc in relevant else 0.0 for doc in top]
    hits = sum(gains)
    first = next((i for i, g in enumerate(gains, 1) if g), None)
    dcg = sum(g / math.log2(i + 1) for i, g in enumerate(gains, 1))
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return QueryMetrics(
        recall=hits / min(k, len(relevant)),
        rr=1 / first if first else 0.0,
        ndcg=dcg / ideal if ideal else 0.0,
    )


def score(
    rankings: dict[str, list[str]],
    relevant: dict[str, set[str]],
    group: dict[str, str],
    k: int = 10,
    per_group: bool = False,
) -> dict:
    """Macro-averaged recall@k, MRR and nDCG@k. A query with no relevant document is counted
    in `n_unscored` and otherwise ignored; with nothing scorable the metrics are None.

    `per_group` adds the same three numbers for every group under "groups". It is for synthetic
    corpora only: a group key on real data is a fehlercode, which must not leave the sealed root."""
    by_group: dict[str, list[QueryMetrics]] = defaultdict(list)
    unscored = 0
    for query, ranked in rankings.items():
        wanted = relevant.get(query, set())
        if not wanted:
            unscored += 1
            continue
        by_group[group[query]].append(query_metrics(ranked, wanted, k))

    def mean(ms: list[QueryMetrics], pick) -> float:
        return sum(pick(m) for m in ms) / len(ms)

    def macro(pick) -> float | None:
        if not by_group:
            return None
        return sum(mean(ms, pick) for ms in by_group.values()) / len(by_group)

    result = {
        "k": k,
        "n_queries": sum(len(ms) for ms in by_group.values()),
        "n_unscored": unscored,
        "n_groups": len(by_group),
        f"recall_at_{k}": macro(lambda m: m.recall),
        "mrr": macro(lambda m: m.rr),
        f"ndcg_at_{k}": macro(lambda m: m.ndcg),
    }
    if per_group:
        result["groups"] = {
            name: {
                "n_queries": len(ms),
                f"recall_at_{k}": mean(ms, lambda m: m.recall),
                "mrr": mean(ms, lambda m: m.rr),
                f"ndcg_at_{k}": mean(ms, lambda m: m.ndcg),
            }
            for name, ms in sorted(by_group.items())
        }
    return result


def add_depths(
    entry: dict,
    rankings: dict[str, list[str]],
    relevant: dict[str, set[str]],
    group: dict[str, str],
    depths: tuple[int | str, ...],
    per_group: bool = False,
) -> dict:
    """Add macro recall at each depth to a `score` entry (and to its groups when per_group), keyed
    by the depth as written. MRR and nDCG stay at the entry's own k."""
    for depth in depths:
        n = _depth(depth)
        scored = score(rankings, relevant, group, n, per_group)
        entry.setdefault("recall_at_depth", {})[str(depth)] = scored[f"recall_at_{n}"]
        if per_group:
            for name, metrics in scored["groups"].items():
                at = entry["groups"][name].setdefault("recall_at_depth", {})
                at[str(depth)] = metrics[f"recall_at_{n}"]
    return entry


def _reranked(conn, rerankers, depth, found, asked, relevant, group, k, per_group) -> dict:
    """One scored entry per reranker and candidate text, from the base variant's hits: nothing
    is retrieved again. Rerank time per query is reported as p50 and p95 seconds."""
    texts: dict[str, tuple[str, str]] = {}
    for hits in found.values():
        texts.update(retrieve.fetch_texts(conn, [h.doc_id for h in hits[:depth]]))
    cells = {}
    for name, reranker in rerankers.items():
        for doc_text in retrieve.DOC_TEXTS:
            rankings, seconds = {}, []
            for ticket_id, hits in found.items():
                start = time.perf_counter()
                ordered = retrieve.rerank(
                    reranker,
                    retrieve.clean_query(asked[ticket_id]),
                    hits[:depth],
                    texts,
                    doc_text=doc_text,
                )
                seconds.append(time.perf_counter() - start)
                rankings[ticket_id] = [h.doc_id for h in ordered]
            entry = score(rankings, relevant, group, k, per_group)
            entry["rerank_seconds"] = {
                "p50": float(np.percentile(seconds, 50)) if seconds else 0.0,
                "p95": float(np.percentile(seconds, 95)) if seconds else 0.0,
            }
            cells[f"rr_{name}_{doc_text}"] = entry
    return cells


def run_synthetic(
    conn,
    embedder,
    k: int = 10,
    per_group: bool = False,
    depths: tuple[int | str, ...] = (),
    rerankers: dict | None = None,
    depth: int | None = None,
) -> dict:
    """Score the indexed corpus against its labels: every ticket whose group has at least two
    members is a query, the rest of its group is relevant, and the ticket itself is excluded.
    `depths` adds recall at those list depths ("all" = both pools) under "recall_at_depth".
    With `rerankers` ({name: Reranker}) and a `depth`, each reranks the fused_query top depth
    with each candidate text, as cells `rr_<name>_<text>`.

    Dense (both e5 prefixes), lexical and fused are scored separately, so the report shows
    whether hybrid retrieval earns its complexity. Aggregates only."""
    rows = conn.execute(
        "select t.ticket_id, t.problem_text, t.created, t.vehicle_serial, l.problem_key "
        "from ticket t join eval_label l using (ticket_id) order by t.ticket_id"
    ).fetchall()
    members: dict[str, set[str]] = defaultdict(set)
    for ticket_id, _text, _created, _serial, key in rows:
        if key is not None:
            members[key].add(ticket_id)
    queries = [r for r in rows if r[4] is not None and len(members[r[4]]) >= 2]
    relevant = {r[0]: members[r[4]] - {r[0]} for r in queries}
    group = {r[0]: r[4] for r in queries}

    if rerankers and (depth is None or depth < k):
        raise ValueError(f"rerankers need a depth of at least k={k}, got {depth}")
    deep = max([k, depth or 0, *(_depth(d) for d in depths)])
    modes = {}
    for mode in QUERY_MODES:
        modes[mode] = {}
        asked = {ticket_id: query_text(mode, text) for ticket_id, text, *_ in queries}
        base: dict[str, list] = {}
        for name, options in VARIANTS.items():
            found = {
                ticket_id: retrieve.search(
                    conn, embedder, asked[ticket_id], k=deep, exclude_id=ticket_id, **options
                )
                for ticket_id in asked
            }
            if name == RERANK_BASE:
                base = found
            rankings = {t: [hit.doc_id for hit in hits] for t, hits in found.items()}
            entry = score(rankings, relevant, group, k, per_group)
            if depths:
                add_depths(entry, rankings, relevant, group, depths, per_group)
            modes[mode][name] = entry
        if rerankers:
            modes[mode].update(
                _reranked(conn, rerankers, depth, base, asked, relevant, group, k, per_group)
            )

    earlier = {r[0]: (r[2], r[3]) for r in rows}
    with_history = sum(
        any(
            earlier[other][1] == serial and earlier[other][0] < created
            for other in relevant[ticket_id]
            if serial and created and earlier[other][0]
        )
        for ticket_id, _text, created, serial, _key in queries
    )
    report = {
        "k": k,
        "embedder": embedder.identity,
        "caveat": CAVEAT,
        "n_tickets": len(rows),
        "n_singleton_tickets": sum(len(m) == 1 for m in members.values()),
        "same_serial_relevant_share": with_history / len(queries) if queries else 0.0,
        "modes": modes,
    }
    if rerankers:
        report["rerank"] = {
            "depth": depth,
            "base": RERANK_BASE,
            "models": {name: r.identity for name, r in rerankers.items()},
            "device": {name: r.device for name, r in rerankers.items()},
        }
    return report


def load_labels(path: pathlib.Path) -> dict[str, str]:
    """A label file (one JSON object per line, as dev3 writes it) as {ticket id: recipe id}.

    A bad line is refused by its number and never quoted."""
    labels: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                raise ValueError(f"line {number}: not JSON") from None
            ticket = item.get("id") if isinstance(item, dict) else None
            recipe = item.get("recipe_id") if isinstance(item, dict) else None
            if not isinstance(ticket, int) or not isinstance(recipe, str) or not recipe:
                raise ValueError(f"line {number}: needs an integer id and a recipe_id")
            if str(ticket) in labels:
                raise ValueError(f"line {number}: repeated id")
            labels[str(ticket)] = recipe
    return labels


def main(argv: list[str] | None = None) -> int:
    """Index a corpus and print the synthetic report (aggregates only) as JSON.

    python -m recall.eval --corpus <export file> --labels <label file> [--embedder hashing|e5]
    """
    import psycopg

    from profiler.gate.embedder import E5Embedder, HashingEmbedder
    from recall import rerank
    from recall.config import settings
    from recall.db import migrate

    parser = argparse.ArgumentParser(prog="recall.eval")
    parser.add_argument("--corpus", type=pathlib.Path, required=True)
    parser.add_argument("--labels", type=pathlib.Path, required=True)
    parser.add_argument("--embedder", choices=("hashing", "e5"), default="hashing")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--per-group",
        action="store_true",
        help="synthetic labels only: on real data a group key is a fehlercode",
    )
    parser.add_argument(
        "--depths",
        type=parse_depths,
        default=(),
        help="also score recall at these depths, e.g. 10,50,100,all (all = both pools)",
    )
    parser.add_argument("--rerankers", type=lambda s: s.split(","), default=[])
    parser.add_argument("--depth", type=int, help="rerank the fused top DEPTH (with --rerankers)")
    parser.add_argument(
        "--e5-device",
        choices=("cpu", "cuda"),
        help="where e5 runs; cpu keeps the index the one M3 measured when a GPU is visible",
    )
    args = parser.parse_args(argv)
    for name in args.rerankers:
        if name not in rerank.RERANKERS:
            parser.error(f"unknown reranker {name!r}")
    if args.rerankers and args.depth is None:
        parser.error("--rerankers needs --depth")
    # Before the embedder and the index: a missing GPU or weights must fail in seconds.
    rerankers = {name: rerank.RERANKERS[name]() for name in args.rerankers}

    embedder = (
        HashingEmbedder(dim=index.DIM)
        if args.embedder == "hashing"
        else E5Embedder(device=args.e5_device)
    )
    rows = extract.read_rows(args.corpus)
    migrate.apply_all(settings.pg_dsn)
    index.build(settings.pg_dsn, rows, embedder, labels=load_labels(args.labels))
    with psycopg.connect(settings.pg_dsn) as conn:
        report = run_synthetic(
            conn,
            embedder,
            k=args.k,
            per_group=args.per_group,
            depths=args.depths,
            rerankers=rerankers or None,
            depth=args.depth,
        )
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
