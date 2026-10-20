"""Raw rows to `Ticket`s. Nothing downstream reads a CSV row, so a column that must never
leave (names, e-mail, phone) is simply never carried across this boundary."""

from __future__ import annotations

import ast
import csv
import json
import math
import pathlib
import re
from dataclasses import KW_ONLY, dataclass, field
from datetime import date

from profiler.stats import customdata

# ASCII digits only: \d would also accept full-width and Arabic-Indic digits, which would form
# a bucket of their own and slip past a guard that trusts "four digits".
_YEAR = re.compile(r"^[0-9]{4}$")
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?: [0-9]{2}:[0-9]{2}:[0-9]{2})?")
_GERMAN_DATE = re.compile(r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})")
_HOURS = re.compile(r"[0-9]+(?:[.,][0-9]+)?")


def _hidden():
    return field(default=None, repr=False)


@dataclass(frozen=True)
class Ticket:
    # repr=False on the free text, the serial, every id of a vehicle, a ticket, a person or an
    # organisation, and every date and hour reading: a Ticket formatted into an exception, a log
    # line or a pytest assertion diff would otherwise print raw corpus text. Those are the only
    # paths by which a raw value can leave this module.
    title: str = field(repr=False)
    description: str = field(repr=False)
    solutions: str = field(repr=False)
    # The ids the ticket carries, as written; () when the field is absent or its list is empty.
    baugruppe: tuple[str, ...]
    serial: str | None = field(repr=False)
    model: str | None
    created_year: str | None
    vehicle_year: str | None
    _: KW_ONLY
    # True only when the field is present and its list is empty, which is not the same as absent.
    baugruppe_empty: bool = False
    vehicle_id: str | None = _hidden()
    serial_index: str | None = _hidden()
    ticket_number: str | None = _hidden()
    row_id: str | None = _hidden()
    vehicle_status: str | None = None
    category: str | None = None
    status: str | None = None
    priority: str | None = None
    sub_status: str | None = None
    show_in_proteam: str | None = None
    contract_transaction: str | None = None
    # Codes, but typed by hand into a free field, so treated as text: a long one is a sentence.
    fehlercode: str | None = _hidden()
    # Quasi-identifiers: a delivery date or an hour reading beside a model can single out one
    # vehicle, so these stay out of the repr as well.
    hours: float | None = _hidden()
    created: date | None = _hidden()
    created_month: str | None = _hidden()
    delivery: date | None = _hidden()
    warranty_start: date | None = _hidden()
    warranty_end: date | None = _hidden()
    status_changed: date | None = _hidden()
    deadline: date | None = _hidden()
    merchant: str | None = _hidden()
    end_customer: str | None = _hidden()
    creator: str | None = _hidden()
    assignee: str | None = _hidden()
    person: str | None = _hidden()
    last_modified: str | None = _hidden()
    # The customData dates as written, for the format section: a shape cannot be taken from the
    # parsed date, and an unparseable one is still a format worth counting.
    delivery_raw: str | None = _hidden()
    warranty_start_raw: str | None = _hidden()
    warranty_end_raw: str | None = _hidden()


MAX_CELL_BYTES = 1 << 24


def read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    # errors="replace" as in the profiler: a decode error quotes the offending bytes. The csv module
    # refuses a cell over 128 KiB by default, and one pasted mail thread would then abort a sealed
    # window; real cells are a few KB, so 16 MiB is generous and still a bound.
    csv.field_size_limit(MAX_CELL_BYTES)
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def custom_field(value: str | None, name: str) -> str | None:
    """The value of the customData descriptor whose name attribute equals `name`.

    The export wraps customData as a list of {group, key, label, value, text, type}
    descriptors, so the client's field names are VALUES of `key`. parse_records handles the
    double JSON encoding; a malformed value comes back None and is simply absent here.

    The first descriptor with a NON-BLANK value wins. A blank duplicate is skipped rather than
    ending the search, so the rule is the same whichever order duplicates arrive in. The name
    attribute is the first of EAV_NAME_ATTRS the record carries, the profiler's own convention.
    """
    records = customdata.parse_records(value)
    if not records:
        return None
    for record in records:
        name_attr = next((a for a in customdata.EAV_NAME_ATTRS if a in record), None)
        if name_attr is None or record.get(name_attr) != name:
            continue
        for attr in customdata.EAV_VALUE_ATTRS:
            raw = record.get(attr)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _list_items(items: list) -> tuple[str, ...]:
    """The non-blank ids in a list. A number is an id written without quotes; anything else
    (a nested list, a dict, a bool, a float) is not an id and is dropped."""
    out = []
    for item in items:
        if isinstance(item, int) and not isinstance(item, bool):
            item = str(item)
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return tuple(out)


def _bracketed(text: str) -> list | None:
    """A list written as a string, in JSON or as a Python repr ("['5', '12']"), else None."""
    try:
        loaded = json.loads(text)
    except (ValueError, RecursionError):
        try:
            loaded = ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None
    return loaded if isinstance(loaded, list) else None


def _values(raw: object) -> tuple[str, ...] | None:
    """The ids an attribute holds; None when it holds nothing that decides (blank, or not text)."""
    if isinstance(raw, list):
        return _list_items(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        items = _bracketed(text)
        if items is not None:
            return _list_items(items)
    return (text,)


def _descriptor_values(records: list[dict] | None, name: str) -> tuple[str, ...] | None:
    if not records:
        return None
    found = None
    for record in records:
        name_attr = next((a for a in customdata.EAV_NAME_ATTRS if a in record), None)
        if name_attr is None or record.get(name_attr) != name:
            continue
        # The first attribute that holds a list or a non-blank string decides for this record;
        # an empty list is an answer, so a display label in `text` never stands in for it.
        for attr in customdata.EAV_VALUE_ATTRS:
            held = _values(record.get(attr))
            if held is None:
                continue
            if held:
                return held
            found = ()
            break
    return found


def custom_values(value: str | None, name: str) -> tuple[str, ...] | None:
    """Every non-blank value of the customData descriptor named `name`, whatever its encoding.

    The real Baugruppe is a LIST of numeric id strings, sometimes empty. It may arrive as a real
    list, a JSON list string, a Python-repr list string ("['5', '12']") or a plain string, and
    all four read the same. None when the field is absent (or blank, as custom_field has it);
    () when it is present with an empty list. The first descriptor with a non-empty value wins,
    whichever order duplicates arrive in.
    """
    return _descriptor_values(customdata.parse_records(value), name)


def parse_date(value: str | None) -> date | None:
    """`YYYY-MM-DD`, optionally with ` HH:MM:SS`, or `DD.MM.YYYY`. Anything else is None."""
    text = (value or "").strip()
    iso = _ISO_DATE.fullmatch(text)
    german = _GERMAN_DATE.fullmatch(text)
    if iso:
        year, month, day = iso.groups()
    elif german:
        day, month, year = german.groups()
    else:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


# Operating hours above this are not a reading, they are a typo or an id in the wrong column.
MAX_HOURS = 1_000_000


def parse_hours(value: str | None) -> float | None:
    """A plain non-negative, finite, plausible number, with a decimal point or comma.

    Anything else is None. A 400-digit string parses to `inf`, which passes every check and then
    breaks `json.dumps(allow_nan=False)`: a sealed window spent on a crash.
    """
    text = (value or "").strip()
    if not _HOURS.fullmatch(text):
        return None
    number = float(text.replace(",", "."))
    return number if math.isfinite(number) and number <= MAX_HOURS else None


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


# A year outside this range is not a year (`73102` would otherwise become "7310"). It is applied
# here, where a junk value just becomes absent, and not in the guard, where one would abort the
# whole window.
YEAR_RANGE = (1900, 2100)


def _year(value: str | None) -> str | None:
    head = (value or "").strip()[:4]
    if not _YEAR.match(head):
        return None
    return head if YEAR_RANGE[0] <= int(head) <= YEAR_RANGE[1] else None


def _ticket(row: dict[str, str]) -> Ticket:
    records = customdata.parse_records(row.get("customData"))

    def custom_raw(name: str) -> str | None:
        values = _descriptor_values(records, name)
        return values[0] if values else None

    def custom_date(name: str) -> date | None:
        return parse_date(custom_raw(name))

    baugruppe = _descriptor_values(records, "baugruppe")
    fehlercode = _descriptor_values(records, "fehlercode")
    created = parse_date(row.get("timestampCreated"))
    return Ticket(
        title=row.get("title") or "",
        description=row.get("description") or "",
        solutions=row.get("solutions") or "",
        baugruppe=baugruppe or (),
        serial=_clean(row.get("vehicleSerialNo")),
        model=_clean(row.get("vehicleModelId")),
        created_year=_year(row.get("timestampCreated")),
        vehicle_year=_year(row.get("vehicleYear")),
        baugruppe_empty=baugruppe == (),
        vehicle_id=_clean(row.get("vehicleId")),
        serial_index=_clean(row.get("vehicleSerialIndex")),
        ticket_number=_clean(row.get("ticketNumber")),
        row_id=_clean(row.get("id")),
        vehicle_status=_clean(row.get("vehicleStatus")),
        category=_clean(row.get("categoryId")),
        status=_clean(row.get("statusId")),
        priority=_clean(row.get("priorityId")),
        sub_status=_clean(row.get("subStatusString")),
        show_in_proteam=_clean(row.get("showInProteam")),
        contract_transaction=_clean(row.get("contractTransaction")),
        fehlercode=", ".join(fehlercode) if fehlercode else None,
        hours=parse_hours(row.get("vehicleHours")),
        created=created,
        created_month=f"{created.year:04d}-{created.month:02d}" if created else None,
        delivery=custom_date("deliveryDate"),
        warranty_start=custom_date("warrantyStart"),
        warranty_end=custom_date("warrantyEnd"),
        status_changed=parse_date(row.get("subStatusChanged")),
        deadline=parse_date(row.get("deadline")),
        merchant=_clean(row.get("merchantId")),
        end_customer=_clean(row.get("endCustomerId")),
        creator=_clean(row.get("userCreatedId")),
        assignee=_clean(row.get("userAssignedId")),
        person=_clean(row.get("personId")),
        last_modified=_clean(row.get("lastModifiedUser")),
        delivery_raw=custom_raw("deliveryDate"),
        warranty_start_raw=custom_raw("warrantyStart"),
        warranty_end_raw=custom_raw("warrantyEnd"),
    )


def tickets(rows: list[dict[str, str]]) -> list[Ticket]:
    return [_ticket(row) for row in rows]
