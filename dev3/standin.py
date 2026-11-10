"""An invented catalog in the released shape, for tests and rehearsals. Nothing here comes
from the real corpus."""

from __future__ import annotations

import copy
import json
import pathlib


def _q(a: int, b: int, c: int) -> dict[str, int]:
    return {"p25": a, "p50": b, "p75": c}


def _recipe(n, component, symptom, cause, steps, templates, **style) -> dict:
    return {
        "recipe_id": f"R{n:03d}",
        "support": style.get("support", 120 - n * 5),
        "vehicles": 40 + n,
        "dealers": 25 + n,
        "component": component,
        "symptom": symptom,
        "cause": cause,
        "fix_steps": steps,
        "title_templates": templates,
        "description_style": {
            "fill": style.get("fill", 0.8),
            "words": style.get("desc", _q(6, 12, 25)),
            "tone": style.get("tone", "neutral"),
        },
        "solution_style": {
            "words": style.get("sol", _q(5, 9, 15)),
            "boilerplate": style.get("boiler", []),
        },
        "fehlercode_shape": style.get("shape"),
        "recurrence_gap_days": style.get("gap"),
        "co_occurs_with": style.get("co", []),
    }


def _templates(component: str) -> list[str]:
    return ["<component>: <symptom>", f"Stoerung {component}", "<symptom>"]


_CATALOG = {
    "schema_version": 1,
    "k": 50,
    "min_vehicles": 5,
    "min_dealers": 5,
    "recipes": [
        _recipe(
            1,
            "Hydraulikpumpe",
            "baut keinen Druck auf",
            "verschlissene Dichtung",
            [
                "Druck am Pruefanschluss messen",
                "Dichtung an der Pumpe erneuern",
                "Druckaufbau nach dem Einbau kontrollieren",
            ],
            _templates("Hydraulikpumpe"),
            shape="DDDD-D",
            gap=_q(14, 45, 120),
            boiler=["closing"],
            co=["R002"],
        ),
        _recipe(
            2,
            "Kuehlwasserschlauch",
            "Kuehlmittelverlust",
            "poroeser Schlauch",
            [
                "Schlauch auf Risse pruefen",
                "Schlauch ersetzen",
                "Kreislauf befuellen und entlueften",
            ],
            _templates("Kuehlwasserschlauch"),
            gap=_q(20, 60, 150),
            tone="verbose",
            desc=_q(10, 24, 50),
            co=["R001"],
        ),
        _recipe(
            3,
            "Getriebe",
            "schaltet nicht",
            "zu niedriger Oelstand",
            ["Oelstand messen", "Oel bis zur Markierung auffuellen", "Probefahrt durchfuehren"],
            _templates("Getriebe"),
            tone="terse",
            desc=_q(3, 6, 10),
            shape="ALL_DD",
            gap=_q(30, 90, 240),
            boiler=["callback"],
        ),
        _recipe(
            4,
            "Display",
            "bleibt dunkel",
            "Wackelkontakt im Stecker",
            [
                "Stecker am Display abziehen und reinigen",
                "Kontakte nachspannen",
                "Funktion mit Zuendung ein pruefen",
            ],
            _templates("Display"),
            fill=0.6,
            tone="terse",
            desc=_q(3, 7, 12),
            gap=_q(7, 21, 60),
        ),
        _recipe(
            5,
            "Batterie",
            "entlaedt sich ueber Nacht",
            "Dauerverbraucher",
            [
                "Ruhestrom messen",
                "Verbraucher durch Ziehen der Sicherungen eingrenzen",
                "defekte Komponente tauschen",
            ],
            _templates("Batterie"),
            shape="DDDD-DD",
            gap=_q(10, 30, 90),
            boiler=["warranty"],
            co=["R007"],
        ),
        _recipe(
            6,
            "Bremse",
            "quietscht",
            "verglaste Belaege",
            ["Belaege ausbauen und anschleifen", "Scheiben reinigen", "Probefahrt mit Bremstest"],
            _templates("Bremse"),
            fill=0.7,
            tone="terse",
            desc=_q(4, 8, 14),
        ),
        _recipe(
            7,
            "Drehzahlsensor",
            "meldet einen Fehlercode",
            "Kabelbruch",
            [
                "Kabelbaum auf Scheuerstellen pruefen",
                "Kabel reparieren oder Sensor ersetzen",
                "Fehlerspeicher loeschen und Gegenprobe machen",
            ],
            _templates("Drehzahlsensor"),
            shape="DDDD-D",
            gap=_q(5, 14, 45),
            tone="verbose",
            desc=_q(12, 28, 60),
            co=["R005"],
        ),
        _recipe(
            8,
            "Klimaanlage",
            "kuehlt nicht",
            "Kaeltemittelmangel",
            [
                "Kaeltemitteldruck messen",
                "Leck mit Kontrastmittel suchen",
                "Kaeltemittel nachfuellen",
            ],
            _templates("Klimaanlage"),
            fill=0.5,
            boiler=["goodwill", "closing"],
            gap=_q(60, 180, 365),
        ),
    ],
}


# Same component as an original (and for most the same symptom), another cause and another fix.
# The title templates are the original's, so a title alone cannot tell the pair apart: what
# separates them is in the description and the solution.
_CONFUSABLE = [
    _recipe(
        9,
        "Hydraulikpumpe",
        "baut keinen Druck auf",
        "Luft im Saugschlauch",
        [
            "Saugleitung auf Undichtigkeit abdruecken",
            "Schlauchschelle nachziehen oder Leitung ersetzen",
            "Anlage entlueften und Druck pruefen",
        ],
        _templates("Hydraulikpumpe"),
        tone="terse",
        desc=_q(4, 9, 16),
        gap=_q(10, 40, 100),
    ),
    _recipe(
        10,
        "Kuehlwasserschlauch",
        "Kuehlmittelverlust",
        "lose Schlauchschelle",
        [
            "Schellen am Kuehlkreislauf kontrollieren",
            "Schelle mit Drehmoment festziehen",
            "Kuehlmittelstand nach Probelauf kontrollieren",
        ],
        _templates("Kuehlwasserschlauch"),
        tone="neutral",
        desc=_q(5, 11, 20),
    ),
    _recipe(
        11,
        "Display",
        "bleibt dunkel",
        "defekte Hintergrundbeleuchtung",
        [
            "Hintergrundbeleuchtung per Diagnose ansteuern",
            "Displayeinheit austauschen",
            "Helligkeit und Anzeige nach dem Einbau pruefen",
        ],
        _templates("Display"),
        fill=0.7,
        desc=_q(4, 9, 15),
        gap=_q(15, 50, 140),
    ),
    _recipe(
        12,
        "Getriebe",
        "schaltet nicht",
        "defekter Kupplungsgeber",
        [
            "Kupplungsgeber mit Diagnose pruefen",
            "Geberzylinder erneuern",
            "Kupplung entlueften und Schaltung testen",
        ],
        _templates("Getriebe"),
        tone="verbose",
        desc=_q(8, 18, 35),
        shape="ALL_DD",
    ),
]


def catalog(confusable: bool = False) -> dict:
    """The stand-in catalog. With `confusable` four more recipes share a component, and mostly a
    symptom, with four of the eight, so retrieval has near neighbours it can get wrong."""
    result = copy.deepcopy(_CATALOG)
    if confusable:
        result["recipes"] += copy.deepcopy(_CONFUSABLE)
    return result


def write(path: pathlib.Path, *, confusable: bool = False) -> None:
    """Write the catalog as JSON, ready for `python -m dev3 --catalog <path>`."""
    path.write_text(json.dumps(catalog(confusable), indent=2, ensure_ascii=False), encoding="utf-8")
