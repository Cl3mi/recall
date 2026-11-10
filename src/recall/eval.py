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
from collections import defaultdict
from dataclasses import dataclass

from insight import extract
from recall import index, retrieve

QUERY_PREFIX = "query: "
CAVEAT = (
    "Scores on a synthetic corpus are evidence that the code is correct, not evidence of "
    "retrieval quality on real tickets: stand-in text is far more regular than real text."
)
VARIANTS = {
    "dense_passage": {"arms": ("dense",), "prefix": index.PASSAGE},
    "dense_query": {"arms": ("dense",), "prefix": QUERY_PREFIX},
    "lexical": {"arms": ("lexical",)},
    "fused": {},
}
# What a ticket is asked with. A technician rarely pastes a whole indexed ticket: "title" is the
# first line only, "head" the first HEAD_WORDS words, a short search phrase.
QUERY_MODES = ("full", "title", "head")
HEAD_WORDS = 8


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
) -> dict:
    """Macro-averaged recall@k, MRR and nDCG@k. A query with no relevant document is counted
    in `n_unscored` and otherwise ignored; with nothing scorable the metrics are None."""
    per_group: dict[str, list[QueryMetrics]] = defaultdict(list)
    unscored = 0
    for query, ranked in rankings.items():
        wanted = relevant.get(query, set())
        if not wanted:
            unscored += 1
            continue
        per_group[group[query]].append(query_metrics(ranked, wanted, k))

    def macro(pick) -> float | None:
        if not per_group:
            return None
        return sum(sum(pick(m) for m in ms) / len(ms) for ms in per_group.values()) / len(per_group)

    return {
        "k": k,
        "n_queries": sum(len(ms) for ms in per_group.values()),
        "n_unscored": unscored,
        "n_groups": len(per_group),
        f"recall_at_{k}": macro(lambda m: m.recall),
        "mrr": macro(lambda m: m.rr),
        f"ndcg_at_{k}": macro(lambda m: m.ndcg),
    }


def run_synthetic(conn, embedder, k: int = 10) -> dict:
    """Score the indexed corpus against its labels: every ticket whose group has at least two
    members is a query, the rest of its group is relevant, and the ticket itself is excluded.

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

    modes = {}
    for mode in QUERY_MODES:
        modes[mode] = {}
        for name, options in VARIANTS.items():
            rankings = {
                ticket_id: [
                    hit.doc_id
                    for hit in retrieve.search(
                        conn, embedder, query_text(mode, text), k=k, exclude_id=ticket_id, **options
                    )
                ]
                for ticket_id, text, *_ in queries
            }
            modes[mode][name] = score(rankings, relevant, group, k)

    earlier = {r[0]: (r[2], r[3]) for r in rows}
    with_history = sum(
        any(
            earlier[other][1] == serial and earlier[other][0] < created
            for other in relevant[ticket_id]
            if serial and created and earlier[other][0]
        )
        for ticket_id, _text, created, serial, _key in queries
    )
    return {
        "k": k,
        "embedder": embedder.identity,
        "caveat": CAVEAT,
        "n_tickets": len(rows),
        "n_singleton_tickets": sum(len(m) == 1 for m in members.values()),
        "same_serial_relevant_share": with_history / len(queries) if queries else 0.0,
        "modes": modes,
    }


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
    from recall.config import settings
    from recall.db import migrate

    parser = argparse.ArgumentParser(prog="recall.eval")
    parser.add_argument("--corpus", type=pathlib.Path, required=True)
    parser.add_argument("--labels", type=pathlib.Path, required=True)
    parser.add_argument("--embedder", choices=("hashing", "e5"), default="hashing")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args(argv)

    embedder = HashingEmbedder(dim=index.DIM) if args.embedder == "hashing" else E5Embedder()
    rows = extract.read_rows(args.corpus)
    migrate.apply_all(settings.pg_dsn)
    index.build(settings.pg_dsn, rows, embedder, labels=load_labels(args.labels))
    with psycopg.connect(settings.pg_dsn) as conn:
        print(json.dumps(run_synthetic(conn, embedder, k=args.k), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
