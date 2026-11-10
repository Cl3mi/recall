# dev3/rows.py
"""One export row in the real 38-column shape, and its ground-truth label.

Unlike fixtures/render.py::row this fills the vehicle columns, because same-serial history is
what this fixture exists to test. Identity columns are never set and stay empty.
"""

from __future__ import annotations

import random

from dev3.planner import Planned
from dev3.profiles import Profile
from fixtures import render, values
from profiler.columns import EXPECTED_COLUMNS

IDENTITY_COLUMNS = (
    "personId",
    "merchantName",
    "merchantId",
    "merchantNumber",
    "merchantPhoneNumber",
    "endCustomerName",
    "endCustomerId",
    "endCustomerNumber",
    "endCustomerPhoneNumber",
    "contactEmail",
    "contactPhone",
    "contactPhoneTrimmed",
)
BASE_HOURS = 400
HOURS_PER_DAY = 8
# An arbitrary category id; ids are opaque.
CATEGORY_ID = "2"


def _hours(profile: Profile, planned: Planned) -> int:
    """Pure in the date, so one serial's hours never run backwards."""
    return BASE_HOURS + (planned.created - profile.start).days * HOURS_PER_DAY


def row(
    index: int,
    profile: Profile,
    recipe: dict,
    planned: Planned,
    text: tuple[str, str, str],
    rng: random.Random,
) -> dict[str, str]:
    title, description, solution = text
    custom = []
    if recipe["fehlercode_shape"]:
        custom.append(("fehlercode", values.from_shape(recipe["fehlercode_shape"], rng)))
    filled = {
        "id": str(index),
        "ticketNumber": f"DV-{200000 + index}",
        "title": title,
        "description": description,
        "solutions": solution,
        "customData": render.custom_data(custom),
        "timestampCreated": planned.created.isoformat(),
        "statusId": str(rng.choice([3, 3, 3, 3, 7])),
        "priorityId": str(rng.choice([1, 2, 2, 3])),
        "categoryId": CATEGORY_ID,
        "vehicleSerialNo": profile.serial,
        "vehicleId": profile.vehicle_id,
        "vehicleModelId": profile.model_id,
        "vehicleYear": str(profile.vehicle_year),
        "vehicleHours": str(_hours(profile, planned)),
    }
    return {column: filled.get(column, "") for column in EXPECTED_COLUMNS}


def label(index: int, profile: Profile, planned: Planned, id_of_number: dict[int, int]) -> dict:
    """`followup_of` is the vehicle-local number; `followup_of_id` the global row id."""
    followup = planned.followup_of
    return {
        "id": index,
        "vehicle": profile.name,
        "number": planned.number,
        "recipe_id": planned.recipe_id,
        "persona": planned.persona,
        "solution_mode": planned.solution_mode,
        "followup_of": followup,
        "followup_of_id": None if followup is None else id_of_number[followup],
    }
