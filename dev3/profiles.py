"""The three invented vehicles. Serials are in an obviously synthetic range (Z9...)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Profile:
    name: str
    serial: str
    vehicle_id: str
    model_id: str
    vehicle_year: int
    tickets: int
    start: date
    end: date
    kind: str  # "chronic" | "broad" | "evolving"


PROFILES = (
    Profile(
        "v1-chronic",
        "Z900000000001",
        "990001",
        "990101",
        2019,
        180,
        date(2022, 1, 3),
        date(2025, 12, 19),
        "chronic",
    ),
    Profile(
        "v2-broad",
        "Z900000000002",
        "990002",
        "990102",
        2021,
        160,
        date(2022, 6, 1),
        date(2025, 12, 19),
        "broad",
    ),
    Profile(
        "v3-evolving",
        "Z900000000003",
        "990003",
        "990103",
        2020,
        170,
        date(2022, 3, 7),
        date(2025, 12, 19),
        "evolving",
    ),
)
