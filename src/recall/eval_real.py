"""Temporal coded-fault baseline. Only fixed aggregate fields leave this module."""

import math
from calendar import monthrange
from collections import defaultdict
from datetime import date

from profiler.gate.embedder import E5_MODEL, E5_REVISION, E5Embedder
from recall import eval as ev
from recall import retrieve

_COUNTS = {
    "n_tickets",
    "n_dated_tickets",
    "n_labeled_tickets",
    "n_query_tickets",
    "n_candidate_tickets",
}
_TOP = _COUNTS | {
    "schema_version",
    "k",
    "holdout_months",
    "coded_faults_only",
    "embedder_is_a_model",
    "modes",
}
_METRICS = {"recall_at_10", "mrr", "ndcg_at_10"}
_CELL_COUNTS = {"n_queries", "n_unscored", "n_groups"}
_MODES = {"full", "title", "head"}
_VARIANTS = {
    "dense_passage",
    "dense_query",
    "lexical",
    "fused",
    "fused_query",
    "fused_dense2",
}


def _count(value) -> bool:
    return type(value) is int and value >= 0


def _keys(value, keys) -> bool:
    return type(value) is dict and value.keys() == keys


def validate_report(report: object) -> bool:
    """Refuse extra fields, nonnumeric leaves and impossible counts; disclose no values."""
    if not _keys(report, _TOP):
        return False
    for key, want in (("schema_version", 1), ("k", 10), ("holdout_months", 6)):
        if type(report[key]) is not int or report[key] != want:
            return False
    if report["coded_faults_only"] is not True or type(report["embedder_is_a_model"]) is not bool:
        return False
    if not all(_count(report[k]) for k in _COUNTS):
        return False
    total, dated, labeled, queries, candidates = (
        report[k]
        for k in (
            "n_tickets",
            "n_dated_tickets",
            "n_labeled_tickets",
            "n_query_tickets",
            "n_candidate_tickets",
        )
    )
    if (
        dated > total
        or labeled > total
        or queries > labeled
        or queries + candidates > dated
        # Every other labeled ticket must be historical or undated.
        or labeled - queries > candidates + total - dated
        or (dated and candidates == dated)
    ):
        return False
    if not _keys(report["modes"], _MODES):
        return False
    coverage = None
    for variants in report["modes"].values():
        if not _keys(variants, _VARIANTS):
            return False
        for cell in variants.values():
            if not _keys(cell, _CELL_COUNTS | _METRICS | {"k"}):
                return False
            if type(cell["k"]) is not int or cell["k"] != 10:
                return False
            if not all(_count(cell[k]) for k in _CELL_COUNTS):
                return False
            scored, unscored, groups = (cell[k] for k in ("n_queries", "n_unscored", "n_groups"))
            if (
                scored + unscored != queries
                or groups > scored
                or groups > candidates
                or groups > labeled - queries
                or bool(groups) != bool(scored)
            ):
                return False
            current = (scored, unscored, groups)
            if coverage is not None and coverage != current:
                return False
            coverage = current
            for key in _METRICS:
                value = cell[key]
                if scored == 0:
                    if value is not None:
                        return False
                elif (
                    type(value) not in (int, float)
                    or not 0 <= value <= 1
                    or not math.isfinite(value)
                ):
                    return False
    return True


def holdout_cutoff(latest: date) -> date:
    """Six calendar months before the snapshot's latest date, clamped at month end."""
    month = (latest.month - 7) % 12 + 1
    year = latest.year - (latest.month <= 6)
    return date(year, month, min(latest.day, monthrange(year, month)[1]))


def run_real(conn, embedder) -> dict:
    """Evaluate labeled holdout tickets against strictly historical candidates only."""
    rows = conn.execute(
        "select t.ticket_id, t.problem_text, t.created, l.problem_key "
        "from ticket t left join eval_label l using (ticket_id) order by t.ticket_id"
    ).fetchall()
    dated = [r for r in rows if r[2] is not None]
    cutoff = holdout_cutoff(max(r[2] for r in dated)) if dated else None
    candidates = [r for r in dated if r[2] < cutoff]
    queries = [r for r in dated if r[2] >= cutoff and r[3] is not None]
    members = defaultdict(set)
    for ticket_id, _text, _created, key in candidates:
        if key is not None:
            members[key].add(ticket_id)
    relevant = {r[0]: members[r[3]] for r in queries}
    groups = {r[0]: r[3] for r in queries}
    # HNSW yields ef_search rows (default 40) before the cutoff filter applies. Without
    # these session settings the dense pool falls far short of retrieve.POOL here.
    conn.execute(f"set hnsw.ef_search = {retrieve.POOL}")
    conn.execute("set hnsw.iterative_scan = strict_order")
    modes = {}
    for mode in ev.QUERY_MODES:
        modes[mode] = {}
        for name, options in ev.VARIANTS.items():
            rankings = {
                ticket_id: [
                    hit.doc_id
                    for hit in retrieve.search(
                        conn,
                        embedder,
                        ev.query_text(mode, text),
                        k=10,
                        before=cutoff,
                        exclude_id=ticket_id,
                        **options,
                    )
                ]
                for ticket_id, text, _created, _key in queries
            }
            modes[mode][name] = ev.score(rankings, relevant, groups, k=10, per_group=False)
    return {
        "schema_version": 1,
        "k": 10,
        "holdout_months": 6,
        "coded_faults_only": True,
        "embedder_is_a_model": (
            isinstance(embedder, E5Embedder) and embedder.identity == f"e5:{E5_MODEL}@{E5_REVISION}"
        ),
        "n_tickets": len(rows),
        "n_dated_tickets": len(dated),
        "n_labeled_tickets": sum(r[3] is not None for r in rows),
        "n_query_tickets": len(queries),
        "n_candidate_tickets": len(candidates),
        "modes": modes,
    }
