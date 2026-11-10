"""Lay one vehicle's tickets on a timeline. Pure and seeded: same inputs, same plan."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from dev3 import personas
from dev3.profiles import Profile

DEFAULT_GAP = {"p25": 14, "p50": 45, "p75": 120}
FOLLOWUP_CHANCE = {"chronic": 0.3, "evolving": 0.5, "broad": 0.0}
CHRONIC_SHARE = 0.7
PRIMARY_SHARE = 0.75
FOLLOWUP_WINDOW_DAYS = 180
MIN_RECIPES = 4  # chronic needs 3 chronic + 1 other; evolving needs 3 mains + others


class PlanError(Exception):
    """Carries a code only."""


@dataclass(frozen=True)
class Planned:
    number: int
    profile: str
    recipe_id: str
    persona: str
    solution_mode: str
    template: int
    created: date
    followup_of: int | None


def _allocate(weights: list[tuple[str, float]], count: int) -> list[str]:
    """Largest-remainder allocation, so shares are exact on any seed."""
    exact = [w * count for _, w in weights]
    counts = [int(x) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: exact[i] - counts[i], reverse=True)
    for i in order[: count - sum(counts)]:
        counts[i] += 1
    return [name for (name, _), n in zip(weights, counts, strict=True) for _ in range(n)]


def _uniform(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _recurring(rng, recipe, count, start, end) -> list[date]:
    """Dates that repeat with the recipe's own gap distribution, scaled to fit the window."""
    gap = recipe["recurrence_gap_days"] or DEFAULT_GAP
    gaps = [
        rng.choice((gap["p25"], gap["p50"], gap["p75"])) + rng.randint(0, 3) for _ in range(count)
    ]
    span = (end - start).days
    total = sum(gaps)
    scale = min(1.0, span / total) if total else 1.0
    day, dates = 0.0, []
    for g in gaps:
        day += g * scale
        dates.append(start + timedelta(days=min(span, int(day))))
    return dates


def _persona(recipe, rng) -> str:
    style = recipe["description_style"]
    if rng.random() > style["fill"]:
        return "title_only"
    names, weights = zip(*personas.PERSONA_BY_TONE[style["tone"]], strict=True)
    return rng.choices(names, weights)[0]


def _mode(recipe, rng) -> str:
    if not recipe["solution_style"]["boilerplate"]:
        return "fix"
    return rng.choices(personas.SOLUTION_MODES, personas.SOLUTION_MODE_WEIGHTS)[0]


def _assignments(profile: Profile, recipes: list[dict], rng) -> list[tuple[str, date, bool]]:
    """(recipe id, date, eligible for a follow-up link) for every ticket, unsorted."""
    by_support = sorted(recipes, key=lambda r: (-r["support"], r["recipe_id"]))
    ids = [r["recipe_id"] for r in recipes]
    n = profile.tickets
    out: list[tuple[str, date, bool]] = []
    if profile.kind == "broad":
        for recipe_id in _allocate([(i, 1 / len(ids)) for i in ids], n):
            out.append((recipe_id, _uniform(rng, profile.start, profile.end), False))
    elif profile.kind == "chronic":
        chronic = [r["recipe_id"] for r in by_support[:3]]
        rest = [i for i in ids if i not in chronic]
        weights = [(i, CHRONIC_SHARE / 3) for i in chronic]
        weights += [(i, (1 - CHRONIC_SHARE) / len(rest)) for i in rest]
        counts: dict[str, int] = {}
        for recipe_id in _allocate(weights, n):
            counts[recipe_id] = counts.get(recipe_id, 0) + 1
        by_id = {r["recipe_id"]: r for r in recipes}
        for recipe_id, count in counts.items():
            if recipe_id in chronic:
                dates = _recurring(rng, by_id[recipe_id], count, profile.start, profile.end)
                out += [(recipe_id, d, True) for d in dates]
            else:
                out += [
                    (recipe_id, _uniform(rng, profile.start, profile.end), False)
                    for _ in range(count)
                ]
    else:  # evolving: three phases, each with its own main problem
        mains = [r["recipe_id"] for r in by_support[:3]]
        span = (profile.end - profile.start).days
        for phase, main in enumerate(mains):
            lo = profile.start + timedelta(days=span * phase // 3)
            hi = profile.start + timedelta(days=span * (phase + 1) // 3)
            size = n // 3 + (1 if phase < n % 3 else 0)
            others = [i for i in ids if i != main]
            weights = [(main, PRIMARY_SHARE)] + [
                (i, (1 - PRIMARY_SHARE) / len(others)) for i in others
            ]
            for recipe_id in _allocate(weights, size):
                out.append((recipe_id, _uniform(rng, lo, hi), recipe_id == main))
    return out


def plan(profile: Profile, recipes: list[dict], seed: int = 7) -> list[Planned]:
    if len(recipes) < MIN_RECIPES:
        raise PlanError("TOO_FEW_RECIPES")
    rng = random.Random(f"{seed}:{profile.name}")
    by_id = {r["recipe_id"]: r for r in recipes}
    raw = sorted(_assignments(profile, recipes, rng), key=lambda x: (x[1], x[0]))
    chance = FOLLOWUP_CHANCE[profile.kind]
    last: dict[str, tuple[int, date]] = {}  # most recent ELIGIBLE ticket per recipe
    out = []
    for number, (recipe_id, created, eligible) in enumerate(raw, 1):
        recipe = by_id[recipe_id]
        follow = None
        if eligible and rng.random() < chance:
            target = last.get(recipe_id)
            if target and (created - target[1]).days <= FOLLOWUP_WINDOW_DAYS:
                follow = target[0]
        out.append(
            Planned(
                number=number,
                profile=profile.name,
                recipe_id=recipe_id,
                persona=_persona(recipe, rng),
                solution_mode=_mode(recipe, rng),
                template=rng.randrange(len(recipe["title_templates"])),
                created=created,
                followup_of=follow,
            )
        )
        if eligible:
            last[recipe_id] = (number, created)
    if len(out) != profile.tickets:
        raise PlanError("TICKET_COUNT")
    return out
