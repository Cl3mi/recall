"""Spec section 2: what the identifier columns look like.

Only the STRUCTURE of a value leaves: its length, and its shape (`shape_of`: letters, digits and
separators folded into a closed alphabet, at most SHAPE_MAX characters). A shape cannot carry a
value, so the entity sweep does not apply to it, but the floor does. Shapes are taken from
identifier-like columns only, never from prose. The serial / vehicle id relationship is numbers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from insight import measures, release
from insight.extract import Ticket
from profiler.stats import lengths
from recall.german.identifiers import shape_of

MAX_SHAPES = 20

# Each column's value on a ticket. The dates are the raw strings, not the parsed dates, and
# `fehlercode` is the ticket's codes joined as the extractor keeps them.
_GETTERS: dict[str, Callable[[Ticket], str | None]] = {
    "vehicleSerialNo": lambda t: t.serial,
    "vehicleModelId": lambda t: t.model,
    "vehicleId": lambda t: t.vehicle_id,
    "ticketNumber": lambda t: t.ticket_number,
    "vehicleSerialIndex": lambda t: t.serial_index,
    "id": lambda t: t.row_id,
    "fehlercode": lambda t: t.fehlercode,
    "deliveryDate": lambda t: t.delivery_raw,
    "warrantyStart": lambda t: t.warranty_start_raw,
    "warrantyEnd": lambda t: t.warranty_end_raw,
}

COLUMNS = tuple(_GETTERS)

# For these a shape is released only when at least k DISTINCT VALUES share it, not k tickets: one
# serial on sixty tickets would otherwise release the shape of that one vehicle's serial, and a
# shape of a single value is that value's fingerprint (a manufacturer batch, a typing habit).
# The other columns describe codes and dates, not individual things, so tickets are the unit.
DISTINCT_FLOORED = ("vehicleSerialNo", "vehicleId", "vehicleSerialIndex", "ticketNumber", "id")


# extract.py joins a ticket's fehlercode values with this.
CODE_SEPARATOR = ", "


def _codes(stored: str) -> list[str]:
    return [code for code in stored.split(CODE_SEPARATOR) if code]


def _column(
    values: list[str], total: int, k: int, per_code: bool = False, distinct: bool = False
) -> dict:
    # A ticket counts once for each distinct shape it carries; per_code takes a shape from each
    # individual code in the stored value instead of from the whole string. With `distinct` the
    # unit is the distinct VALUE instead of the ticket (see DISTINCT_FLOORED).
    shapes = Counter()
    for v in set(values) if distinct else values:
        shapes.update({shape_of(c) for c in _codes(v)} if per_code else {shape_of(v)})
    kept, withheld = release.release(shapes, "shape", k)
    return {
        "coverage": measures.coverage(len(values), total),
        # Distinct STORED values: for fehlercode a two-code ticket is one value, not two codes.
        "distinct": len(set(values)),
        "length_quantiles": lengths.quantiles([len(v) for v in values]),
        "shapes": [{"shape": s, "count": n} for s, n in kept[:MAX_SHAPES]],
        "withheld": withheld,
    }


def _serial_vehicle_id(tickets: list[Ticket]) -> dict[str, int]:
    pairs = {(t.serial, t.vehicle_id) for t in tickets if t.serial and t.vehicle_id}
    vehicle_ids: Counter = Counter(serial for serial, _ in pairs)
    serials: Counter = Counter(vehicle_id for _, vehicle_id in pairs)
    return {
        "tickets_with_both": sum(1 for t in tickets if t.serial and t.vehicle_id),
        "serials_with_several_vehicle_ids": sum(1 for n in vehicle_ids.values() if n > 1),
        "vehicle_ids_with_several_serials": sum(1 for n in serials.values() if n > 1),
    }


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    out: dict = {}
    for column, get in _GETTERS.items():
        values = [v for t in tickets if (v := get(t))]
        out[column] = _column(
            values,
            len(tickets),
            k,
            per_code=column == "fehlercode",
            distinct=column in DISTINCT_FLOORED,
        )
    codes = [len(_codes(t.fehlercode)) for t in tickets if t.fehlercode]
    codes = [n for n in codes if n]
    out["fehlercode"]["codes_per_ticket_quantiles"] = lengths.quantiles(codes)
    out["fehlercode"]["multi_code_share"] = measures.ratio(
        sum(1 for n in codes if n >= 2), len(codes)
    )
    out["serial_vehicle_id"] = _serial_vehicle_id(tickets)
    return out
