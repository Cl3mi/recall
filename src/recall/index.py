"""Build the retrieval index: clean, embed, load, then the HNSW index.

    python -m recall.index build --csv <export> [--labels <labels file>]

The projection holds what retrieval may read (text, vectors, a few vehicle and date fields).
Identity columns never enter the database. Relevance labels go to `eval_label` only.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

import psycopg

from insight import extract
from recall.clean import pipeline

DIM = 1024
PASSAGE = "passage: "  # same prefix as the leakage gate, so stored vectors match what it measured
BATCH = 64
_SPACE = re.compile(r"\s+")


def normalise_code(code: str | None) -> str | None:
    """A fehlercode as a relevance key: upper-case, no whitespace; None when blank."""
    if not code:
        return None
    key = _SPACE.sub("", code).upper()
    return key or None


def vector_literal(values) -> str:
    return "[" + ",".join(f"{float(x):.8g}" for x in values) + "]"


def _embed(embedder, texts: list[str]) -> list:
    out: list = []
    for start in range(0, len(texts), BATCH):
        out.extend(embedder.encode([PASSAGE + t for t in texts[start : start + BATCH]]))
    return out


def build(
    dsn: str,
    rows: Iterable[dict[str, str]],
    embedder,
    *,
    labels: dict[str, str] | None = None,
) -> int:
    """Replace the index with `rows`. Returns the number of tickets indexed.

    `labels` maps a ticket id to its problem key (e.g. a dev3 recipe id). Without it the key is
    the normalised fehlercode, None when the ticket has none."""
    rows = list(rows)
    tickets = extract.tickets(rows)
    ids = [t.row_id or f"row-{n}" for n, t in enumerate(tickets, 1)]
    problems = [pipeline.clean(f"{t.title}\n{t.description}").text for t in tickets]
    solutions = [pipeline.clean(t.solutions).text for t in tickets]
    problem_vecs = _embed(embedder, problems)
    if problem_vecs and len(problem_vecs[0]) != DIM:
        raise ValueError(f"embedder dimension {len(problem_vecs[0])} is not {DIM}")
    has_solution = [i for i, s in enumerate(solutions) if s.strip()]
    solution_vecs = dict(
        zip(has_solution, _embed(embedder, [solutions[i] for i in has_solution]), strict=True)
    )
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    with psycopg.connect(dsn) as conn:
        conn.execute("drop index if exists ticket_problem_vec_idx")
        conn.execute("truncate ticket cascade")
        for i, t in enumerate(tickets):
            serial = (t.serial or "").strip().casefold() or None
            conn.execute(
                "insert into ticket (ticket_id, created, category_id, vehicle_model_id, "
                "vehicle_serial, problem_text, solution_text, problem_vec, solution_vec, "
                "source_sha256) values (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s::vector, %s)",
                (
                    ids[i],
                    t.created,
                    t.category,
                    t.model,
                    serial,
                    problems[i],
                    solutions[i],
                    vector_literal(problem_vecs[i]),
                    vector_literal(solution_vecs[i]) if i in solution_vecs else None,
                    digest,
                ),
            )
            key = labels.get(ids[i]) if labels is not None else normalise_code(t.fehlercode)
            conn.execute(
                "insert into eval_label (ticket_id, problem_key, fehlercode) values (%s, %s, %s)",
                (ids[i], key, normalise_code(t.fehlercode)),
            )
        conn.execute(
            "create index ticket_problem_vec_idx on ticket using hnsw "
            "(problem_vec vector_cosine_ops)"
        )
        conn.commit()
    return len(tickets)
