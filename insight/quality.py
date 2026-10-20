"""How many tickets a retrieval system could actually use, split by every filter the view offers.

Each ticket gets one grade, computed here and never released per ticket:

  * noise: a blank problem text, a templated problem text (a near-duplicate cluster of at least
    k, which is what the handover slip is, so no category id is named here), or a solution with
    no content left once workflow phrases are stripped (no solution at all, or only "bitte um
    Rückruf, Ticket wird geschlossen").
  * near-duplicate: not noise, but the stripped solution sits in a near-duplicate cluster of at
    least k. A text that many tickets share says nothing about any one of them.
  * retrievable at N: neither of the above, and at least N content words in the stripped
    solution. N is a ladder (LADDER), so the view can move the threshold without another window.

The phrase list is our own, written from the floored solution trigrams of the second real run,
which were already released and guard-checked. It is never derived from raw text here.

Released labels (a category, a model, a year cell, a bucket) go through `release.release`, so a
group stands on at least k tickets. The counts inside a group may be smaller: a count is not
personal data (amendment 8 of the stage-1 report spec).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from insight import dimensions, lifecycle, release, texts, timeline
from insight.extract import Ticket
from profiler.stats import clusters
from recall.clean import pipeline

LADDER = (3, 5, 8, 12)
# Every dimension the section splits by. `model_id`, not `model`: `model` is a released field
# name, and the guard refuses a dict under it.
DIMENSIONS = (*dimensions.COLUMNS, "model_id", "baugruppe")
DEFAULT_MIN_WORDS = 5
NOISE_REASONS = ("blank", "templated", "no_solution")

# Case-insensitive, matched on the CLEANED solution. Longest phrases first in each group, so a
# short alternative cannot eat the start of a longer one.
WORKFLOW_PHRASES = (
    # call-backs and reachability
    r"(?:hat angerufen,? )?(?:bitte|bittet) (?:nochmal |nochmals )?um r[üu]ckruf",
    r"um r[üu]ckruf",
    r"(?:tel\.? )?(?:nicht|keiner) erreichbar",
    r"keine r[üu]ckmeldung(?: mehr)?(?: erhalten)?",
    r"nichts mehr geh[öo]rt",
    r"(?:der )?(?:h[äa]ndler |er )?meldet sich (?:nochmal|nochmals|morgen|eventuell)?",
    r"schickt mir(?: mal)?",
    # mail traffic
    r"per mail (?:geantwortet|gesendet|beantwortet|erledigt)",
    r"mail (?:geantwortet|gesendet|beantwortet)",
    r"per mail",
    # ticket housekeeping
    r"ticket wird geschlossen",
    r"doppeltes ticket(?: siehe(?: nr\.?)?)?",
    r"ticket siehe nr\.?",
    r"hat sich erledigt",
    # warranty and goodwill administration
    r"(?:ga|garantie) (?:nicht )?verl[äa]ngert(?: bis)?",
    r"(?:material )?in kulanz zugesagt",
    r"keine kulanz mehr",
    r"gs erstellt",
    r"keine gs",
    r"kein fb",
    r"fb ok",
    # greetings and the bare call marker
    r"hallo",
    r"mfg",
    r"lg",
    r"(?:mit )?freundlichen gr[üu](?:ß|ss)en",
    r"tel\.?",
)
# The cleaner cuts a signature from its sign-off to the end, so a solution that OPENS with a
# greeting ("LG Steuergerät getauscht") would be emptied. A leading greeting goes before cleaning.
_LEADING_GREETING = re.compile(
    r"^\s*(?:(?:hallo|lg|mfg|(?:mit )?freundlichen gr[üu](?:ß|ss)en|gr[üu](?:ß|ss)e)"
    r"\b[\s,.:;!-]*)+",
    re.IGNORECASE,
)
_PHRASES = re.compile(r"\b(?:" + "|".join(WORKFLOW_PHRASES) + r")\b", re.IGNORECASE)
_DATE = re.compile(r"\b[0-9]{1,2}\.[0-9]{1,2}\.(?:[0-9]{2,4})?")
_PLACEHOLDER = re.compile(r"\[[A-Z_]+\]")
_WORD = re.compile(r"[^\W\d_]{2,}")

FIELDS: dict[str, Callable[[Ticket], bool]] = timeline._FILLED


def stripped_solution(text: str) -> str:
    """The cleaned solution with workflow phrases, dates and placeholders removed."""
    cleaned = pipeline.clean(_LEADING_GREETING.sub("", text)).text
    for pattern in (_PLACEHOLDER, _DATE, _PHRASES):
        cleaned = pattern.sub(" ", cleaned)
    return " ".join(cleaned.split())


def content_words(text: str) -> int:
    return len(_WORD.findall(text))


@dataclass(frozen=True)
class Grade:
    # Why a ticket is noise, the first rule that applies (one of NOISE_REASONS), or None.
    noise_reason: str | None
    near_duplicate: bool
    words: int

    @property
    def noise(self) -> bool:
        return self.noise_reason is not None

    def retrievable(self, min_words: int) -> bool:
        return not self.noise and not self.near_duplicate and self.words >= min_words


def _solution_cluster_sizes(stripped: list[str]) -> list[int]:
    """Per solution, the size of its near-duplicate cluster; 0 for an empty one. Sorted first,
    as in `texts.cluster_sizes`, so the sizes do not depend on the row order."""
    documents = sorted({d.casefold() for d in stripped if d})
    size_of: dict[str, int] = {}
    counts = Counter(d.casefold() for d in stripped if d)
    for members in clusters.groups(documents):
        # Members are distinct texts; a cluster's size is the number of TICKETS behind them.
        n = sum(counts[documents[i]] for i in members)
        for i in members:
            size_of[documents[i]] = n
    return [size_of[d.casefold()] if d else 0 for d in stripped]


def grades(tickets: list[Ticket], k: int = release.K) -> list[Grade]:
    problem_sizes = texts.cluster_sizes(tickets)
    stripped = [stripped_solution(t.solutions) for t in tickets]
    words = [content_words(s) for s in stripped]
    # Only solutions with content can be near-duplicates; an empty one is already noise.
    solution_sizes = _solution_cluster_sizes(
        [s if w else "" for s, w in zip(stripped, words, strict=True)]
    )
    out = []
    for size, n_words, sol_size in zip(problem_sizes, words, solution_sizes, strict=True):
        reason = (
            "blank"
            if size == 0
            else "templated"
            if size >= k
            else "no_solution"
            if not n_words
            else None
        )
        out.append(
            Grade(
                noise_reason=reason, near_duplicate=reason is None and sol_size >= k, words=n_words
            )
        )
    return out


def _group(members: Iterable[tuple[Ticket, Grade]], reasons: bool = False) -> dict:
    members = list(members)
    out = {
        "count": len(members),
        "noise": sum(1 for _, g in members if g.noise),
        "near_duplicate": sum(1 for _, g in members if g.near_duplicate),
        "retrievable": [
            {"min_words": n, "tickets": sum(1 for _, g in members if g.retrievable(n))}
            for n in LADDER
        ],
        "fields": {f: sum(1 for t, _ in members if filled(t)) for f, filled in FIELDS.items()},
    }
    if reasons:
        # Released for the whole corpus and per year only: enough to see which rule makes the noise.
        out["noise_reasons"] = {
            r: sum(1 for _, g in members if g.noise_reason == r) for r in NOISE_REASONS
        }
    return out


Pair = tuple[Ticket, Grade]


def _split(
    pairs: list[Pair], values: Callable[[Ticket], Iterable[str]], fields: str | tuple, k: int
) -> tuple[list[tuple], dict, dict[str, list[Pair]]]:
    groups: dict[str, list[Pair]] = {}
    for pair in pairs:
        for v in values(pair[0]):
            groups.setdefault(v, []).append(pair)
    kept, withheld = release.release(Counter({v: len(g) for v, g in groups.items()}), fields, k)
    return kept, withheld, groups


def _dimension(pairs: list[Pair], values: Callable[[Ticket], Iterable[str]], k: int) -> dict:
    kept, withheld, groups = _split(pairs, values, "value", k)
    cells: dict[tuple[str, str], list[Pair]] = {}
    for pair in pairs:
        if pair[0].created_year:
            for v in values(pair[0]):
                cells.setdefault((v, pair[0].created_year), []).append(pair)
    by_year, by_year_withheld = release.release(
        Counter({key: len(g) for key, g in cells.items()}), ("value", None), k
    )
    return {
        "values": [{"value": v, **_group(groups[v])} for v, _ in kept],
        "withheld": withheld,
        "by_year": [{"value": v, "year": y, **_group(cells[(v, y)])} for (v, y), _ in by_year],
        "by_year_withheld": by_year_withheld,
    }


def _one(get: Callable[[Ticket], str | None]) -> Callable[[Ticket], tuple[str, ...]]:
    return lambda t: (v,) if (v := get(t)) else ()


def _labelled(pairs: list[Pair], label: Callable[[Ticket], str | None], labels, name, k) -> tuple:
    kept, withheld, groups = _split(pairs, _one(label), (None,), k)
    present = dict(kept)
    entries = [{name: lab, **_group(groups[lab])} for lab in labels if lab in present]
    return entries, withheld


def _hours(t: Ticket) -> str | None:
    return lifecycle._hours_label(t.hours) if t.hours is not None else None


def _days(t: Ticket) -> str | None:
    if t.created is None or t.delivery is None:
        return None
    return lifecycle._days_label(lifecycle._days_since(t.created, t.delivery))


def build(tickets: list[Ticket], k: int = release.K, graded: list[Grade] | None = None) -> dict:
    """`graded` is `grades(tickets, k)` when the caller has it already: the cube needs the same
    grades, and grading clusters every solution, which is the slow part."""
    graded = grades(tickets, k) if graded is None else graded
    pairs = list(zip(tickets, graded, strict=True))
    years, years_withheld = release.release(
        Counter(t.created_year for t in tickets if t.created_year), (None,), k
    )
    by_dimension = {
        column: _dimension(pairs, _one(get), k) for column, get in dimensions._GETTERS.items()
    }
    by_dimension["model_id"] = _dimension(pairs, _one(lambda t: t.model), k)
    # Multi-valued: a ticket counts once under each distinct id it carries.
    by_dimension["baugruppe"] = _dimension(pairs, lambda t: tuple(dict.fromkeys(t.baugruppe)), k)
    hours, hours_withheld = _labelled(pairs, _hours, lifecycle.BUCKETS["hours"], "bucket", k)
    days, days_withheld = _labelled(
        pairs, _days, lifecycle.BUCKETS["days_since_delivery"], "bucket", k
    )
    states, states_withheld = _labelled(
        pairs, lifecycle._warranty_state, lifecycle.STATES, "state", k
    )
    return {
        "default_min_words": DEFAULT_MIN_WORDS,
        "phrases": len(WORKFLOW_PHRASES),
        "overall": _group(pairs, reasons=True),
        "by_year": [
            {"year": y, **_group((p for p in pairs if p[0].created_year == y), reasons=True)}
            for y, _ in sorted(years)
        ],
        "by_year_withheld": years_withheld,
        "by_field": {f: _group(p for p in pairs if filled(p[0])) for f, filled in FIELDS.items()},
        "by_dimension": by_dimension,
        "by_lifecycle": {
            "hours": {"buckets": hours, "buckets_withheld": hours_withheld},
            "days_since_delivery": {"buckets": days, "buckets_withheld": days_withheld},
            "warranty": {"states": states, "states_withheld": states_withheld},
        },
    }
