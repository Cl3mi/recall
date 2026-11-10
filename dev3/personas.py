"""Who writes a ticket and how, and the generic workflow sentences a solution may carry.

Every sentence here is invented and domain-neutral; none comes from the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    words: tuple[int, int] | None  # description length range; None means no description
    instruction: str


PERSONAS = {
    "title_only": Persona(None, "Schreibe keinen Befund; lasse BEFUND leer."),
    "terse": Persona((3, 10), "Schreibe einen sehr knappen Befund wie ein Haendler am Telefon."),
    "neutral": Persona((10, 30), "Schreibe einen sachlichen Befund in zwei bis drei Saetzen."),
    "verbose": Persona(
        (30, 70), "Schreibe einen ausfuehrlichen Befund mit Umstaenden und Verlauf."
    ),
}

PERSONA_BY_TONE = {
    "terse": (("terse", 0.7), ("neutral", 0.3)),
    "neutral": (("terse", 0.25), ("neutral", 0.6), ("verbose", 0.15)),
    "verbose": (("neutral", 0.3), ("verbose", 0.7)),
}

SOLUTION_MODES = ("fix", "fix+workflow", "workflow")
SOLUTION_MODE_WEIGHTS = (0.6, 0.3, 0.1)

MODE_INSTRUCTION = {
    "fix": "Die LOESUNG beschreibt nur die technische Behebung in eigenen Worten.",
    "fix+workflow": "Die LOESUNG beschreibt die Behebung und endet mit einem kurzen Hinweis zum "
    "Ablauf (Kunde informiert oder Rueckruf vereinbart).",
    "workflow": "Die LOESUNG enthaelt nur einen kurzen Ablaufhinweis (Kunde informiert, Ticket "
    "kann geschlossen werden), keine technische Behebung.",
}
