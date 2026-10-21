"""Synthetic stand-in export, built per test session into tmp_path.

Nothing is written into the working tree - see the plan's data handling rules.
The seed is fixed so failures are reproducible; the product line is deliberately
fictional (TX-22xx / LR-45) so any real value showing up here is obvious.
"""

import csv
import json
import pathlib
import random

import pytest

from profiler.columns import EXPECTED_COLUMNS

SEED = 20260804
ROWS = 400

FAULTS = [
    ("Hydraulikpumpe baut keinen Druck auf", "F1247", "Druck geprueft, Pumpe getauscht"),
    ("Getriebe schaltet nicht", "F2013", "Getr. Oel gewechselt"),
    ("Kuehlwasserverlust am Motor", "F0891", "Schlauch ersetzt"),
    ("Bremsleitung undicht", "F3402", "erledigt"),
    ("Motor startet nicht", "F0102", ""),
]


def build_standin(
    path: pathlib.Path, rows: int = ROWS, drop_column: str | None = None
) -> pathlib.Path:
    columns = [c for c in EXPECTED_COLUMNS if c != drop_column]
    rng = random.Random(SEED)
    # The runbook's Phase 0 rehearsal and the README both call this with a path under a
    # directory that does not exist yet, so creating it here keeps those copy-pasteable.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for i in range(1, rows + 1):
            title, code, solution = FAULTS[i % len(FAULTS)]
            tail = "\n> Am 12.03.2019 schrieb Test:\n> alter Text\n" * (40 if i % 97 == 0 else 0)
            row = dict.fromkeys(columns, "")
            # Adversarial customData: one instance of every failure mode the profiler
            # must survive. See docs/superpowers/specs/2026-08-10-window-a-v2-design.md.
            custom = {
                "fehlercode": code,  # identifier_like -> shape ADDDD
                "betriebsstunden": str(1000 + i),  # numeric -> shapes only
                "bemerkung": "die pumpe baut keinen druck mehr auf und muss getauscht werden",
                "kundenname": "Musterhaendler GmbH",  # PII values, never emitted
                "telefon": "+43 512 123456",  # PII values, never emitted
                "seltsam": f"A({i % 10})",  # exotic punctuation -> '#'
                "langtext": "x" * 120,  # over-long -> not shaped
            }
            # Not a multiple of 50: build_standin counts from 1, so i % 400 == 0 lands
            # on row 400, which is also a malformed row - the only row carrying this key
            # would never parse, and the below-the-floor case would go untested.
            if i % 400 == 7:
                custom["sonderfall_standort"] = "Beispielstadt"  # below the presence floor
            if i % 3 == 0:
                custom["huber_sonderfeld"] = "1"  # entity-named key, suppressed
            # Wrapped the way the real export wraps it: a list of field DESCRIPTORS,
            # serialised to JSON and then serialised again, so the field opens with a
            # quote and json.loads returns a string rather than a container. The client's
            # field names are VALUES of `key`, not JSON keys. Round 2 parsed none of the
            # real values because the stand-in used a plain object and nothing here
            # rehearsed the format the client actually uses.
            records = [
                {
                    "group": "Allgemein",
                    "key": key,
                    "label": f"Feld {key}",
                    "value": value,
                    "text": value,
                    "type": "string",
                }
                for key, value in custom.items()
            ]
            blob = json.dumps(json.dumps(records, ensure_ascii=False), ensure_ascii=False)
            if i % 50 == 0:
                blob = "<<<" + blob  # malformed, counted not echoed
            row.update(
                {
                    k: v
                    for k, v in {
                        "id": i,
                        "ticketNumber": f"TN-{100000 + i}",
                        "title": title,
                        "description": (
                            f"{title}. Fehlercode {code}.{tail}"
                            "\n\nMit freundlichen Gruessen\nTestperson"
                        ),
                        "solutions": solution,
                        "customData": blob,
                        "statusId": rng.choice([1, 2, 3]),
                        "categoryId": rng.choice([5, 7, 9]),
                        "priorityId": rng.choice([1, 2]),
                        "vehicleModelId": rng.choice(["TX-2210", "TX-2240", "LR-45"]),
                        "vehicleYear": rng.choice([2012, 2016, 2020]),
                        "vehicleHours": rng.randint(50, 9000),
                        "timestampCreated": (
                            f"20{rng.randint(14, 25)}-0{rng.randint(1, 9)}-"
                            f"1{rng.randint(0, 9)} 08:30:00"
                        ),
                        "merchantName": "Musterhaendler GmbH",
                        "endCustomerName": "Beispielkunde AG",
                        "contactEmail": "test@example.invalid",
                        "contactPhone": "+43 000 0000000",
                        "vehicleSerialNo": f"SN{rng.randint(10000, 99999)}",
                        "showInProteam": rng.choice(["true", "false"]),
                        "subStatusString": rng.choice(["offen", "in Bearbeitung", "erledigt"]),
                    }.items()
                    if k in row
                }
            )
            writer.writerow(row)
    return path


@pytest.fixture(scope="session")
def standin_csv(tmp_path_factory) -> pathlib.Path:
    return build_standin(tmp_path_factory.mktemp("standin") / "export.csv")


@pytest.fixture(autouse=True)
def _detail_log_never_touches_the_real_quarantine(tmp_path, monkeypatch):
    """Redirect the profiler's verbatim detail sink into tmp_path for every test.

    `safety.DETAIL_LOG` defaults to `local/quarantine/profiler_detail.log`, and any
    test that triggers a selfcheck rejection writes there. That leaves the working
    tree dirty and makes `make check-clean` fail - the very assertion the plan calls
    the one guarantee it can actually prove. Autouse rather than per-test so a new
    test cannot reintroduce the leak by forgetting to monkeypatch.
    """
    from profiler import safety

    monkeypatch.setattr(safety, "DETAIL_LOG", tmp_path / "profiler_detail.log")
