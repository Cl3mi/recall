# dev3/writer.py
"""Turn one recipe and one persona into one ticket's title, description and solutions.

The prompt is built from catalog fields only. The model never sees a real ticket.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

from catalog import scrub
from dev3 import personas
from dev3.planner import Planned

ATTEMPTS = 3
_LABELS = (
    "NR",
    "KOMPONENTE",
    "SYMPTOM",
    "URSACHE",
    "SCHRITT",
    "VORLAGE",
    "PERSONA",
    "BESCHREIBUNG",
    "LOESUNG_MODUS",
)
_FIELD = re.compile(r"^(" + "|".join(_LABELS) + r"): (.*)$")
_PLACEHOLDER = re.compile(r"<[^<>]*>")
_ANSWER = re.compile(r"^(TITEL|BEFUND|LOESUNG)\s*:\s*(.*)$", re.IGNORECASE)


class WriterError(Exception):
    """Carries a code and a ticket label, never model text."""


def build_prompt(recipe: dict, planned: Planned, attempt: int = 0) -> str:
    persona = personas.PERSONAS[planned.persona]
    template = recipe["title_templates"][planned.template % len(recipe["title_templates"])]
    lines = [
        "Du schreibst ein synthetisches Support-Ticket fuer ein Test-Datenset. Erfinde keine "
        "Namen, E-Mail-Adressen, Telefonnummern, Seriennummern, Teilenummern oder Daten.",
        f"NR: {planned.profile}-{planned.number}-{attempt}",
        f"KOMPONENTE: {recipe['component']}",
        f"SYMPTOM: {recipe['symptom']}",
        f"URSACHE: {recipe['cause']}",
        *[f"SCHRITT: {step}" for step in recipe["fix_steps"]],
        f"VORLAGE: {template}",
        f"PERSONA: {planned.persona}",
        f"BESCHREIBUNG: {'nein' if persona.words is None else 'ja'}",
        f"LOESUNG_MODUS: {planned.solution_mode}",
        persona.instruction,
        personas.MODE_INSTRUCTION[planned.solution_mode],
        "Der TITEL folgt der VORLAGE; ersetze <component> und <symptom> sinngemaess.",
        "Antworte genau so:\nTITEL: ...\nBEFUND: ...\nLOESUNG: ...",
    ]
    return "\n".join(lines)


def parse_fields(prompt: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in prompt.splitlines():
        match = _FIELD.match(line)
        if match:
            found.setdefault(match.group(1), []).append(match.group(2))
    return found


class EchoClient:
    """GPU-free stand-in: deterministic text assembled from the prompt's own fields."""

    identity = "dev3-echo:v1"

    def __call__(self, prompt: str) -> str:
        f = parse_fields(prompt)
        rng = random.Random(f["NR"][0])
        title = (
            f["VORLAGE"][0]
            .replace("<component>", f["KOMPONENTE"][0])
            .replace("<symptom>", f["SYMPTOM"][0])
        )
        described = f["BESCHREIBUNG"][0] == "ja"
        description = (
            f"{f['SYMPTOM'][0]} an {f['KOMPONENTE'][0]}, vermutlich {f['URSACHE'][0]}."
            if described
            else ""
        )
        steps = "; ".join(rng.sample(f["SCHRITT"], k=min(2, len(f["SCHRITT"]))))
        mode = f["LOESUNG_MODUS"][0]
        solution = {
            "fix": steps,
            "fix+workflow": f"{steps}. Kunde wurde informiert.",
            "workflow": "Kunde wurde informiert, Ticket kann geschlossen werden.",
        }[mode]
        return f"TITEL: {title}\nBEFUND: {description}\nLOESUNG: {solution}"


def _parse_answer(text: str) -> dict[str, str] | None:
    parts: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        match = _ANSWER.match(line.strip())
        if match:
            current = match.group(1).upper()
            parts[current] = match.group(2).strip()
        elif current:
            parts[current] += " " + line.strip()
    return parts if "TITEL" in parts and "LOESUNG" in parts else None


def write(client: Callable[[str], str], recipe: dict, planned: Planned) -> tuple[str, str, str]:
    """Scrub first, then validate; a failed attempt is retried, never returned."""
    wants_description = personas.PERSONAS[planned.persona].words is not None
    for attempt in range(ATTEMPTS):
        parts = _parse_answer(client(build_prompt(recipe, planned, attempt)))
        if parts is None:
            continue
        title = scrub.scrub(parts["TITEL"]).strip()
        if not title or _PLACEHOLDER.search(parts["TITEL"]) or _PLACEHOLDER.search(title):
            continue
        description = scrub.scrub(parts.get("BEFUND", "")).strip() if wants_description else ""
        if wants_description and not description:
            continue
        return title, description, scrub.scrub(parts["LOESUNG"])
    raise WriterError(f"UNPARSEABLE {planned.profile}-{planned.number}")
