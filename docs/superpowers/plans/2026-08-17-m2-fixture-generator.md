# M2 Synthetic Fixture Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a 1,500-row synthetic ticket corpus whose measured structure matches the real corpus, so retrieval work proceeds without an airlock window.

**Architecture:** A pure planner reads the gated `profile.json` and decides every number (group sizes, fill rates, field shares). A generator asks a local LLM on the H100 for German fault text, one prompt per near-duplicate group, with every response cached by prompt hash. A renderer assembles the 38-column CSV including double-encoded EAV `customData`. A verifier checks the output against the plan.

**Tech Stack:** Python 3.12, uv, pytest, ruff. Reuses `profiler.stats.customdata` and `recall.german.identifiers.shape_of`. LLM served by vLLM over an OpenAI-compatible API.

**Scope note:** The Window B leakage gate is a separate plan, written once a fixture exists — its nearest-neighbour threshold is calibrated against a synthetic-vs-synthetic baseline that cannot be measured before then.

---

## Data handling rules

**Never read anything under `local/quarantine/` or `<export-dir>`.** `local/artifacts/profile.json` IS readable — it passed `blessing.unblessed` with zero findings.

The generator must never send corpus text to the LLM. Its prompts carry plan *numbers* and invented themes only. Task 8 makes that a test rather than an intention.

## Pre-flight

Read `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md`. It carries the measured targets this plan implements.

Verify the toolchain and the input artifact:

```bash
cd ~/mci/recall
make test && make lint
uv run python -c "
import json, pathlib, sys; sys.path.insert(0,'.')
from profiler import blessing
p = json.loads(pathlib.Path('local/artifacts/profile.json').read_text())
print('rows:', p['source']['row_count'], 'unblessed:', len(blessing.unblessed(p)))"
```

Expected: tests green, `rows: <corpus row count> unblessed: 0`.

## File structure

| File | Responsibility |
|---|---|
| `fixtures/__init__.py` | package marker |
| `fixtures/plan.py` | pure: profile → `FixturePlan`. Every number decided here |
| `fixtures/values.py` | pure: a shape (`DDDD-D`) → a conforming value (`4821-7`) |
| `fixtures/render.py` | `FixturePlan` + texts → 38-column CSV rows, EAV `customData` |
| `fixtures/llm.py` | LLM client protocol, disk cache, fake client for tests |
| `fixtures/generate.py` | drives the LLM per group; returns texts |
| `fixtures/verify.py` | rendered CSV vs plan; fails loudly on drift |
| `fixtures/__main__.py` | CLI wiring |
| `tests/unit/test_fixture_plan.py` | planner |
| `tests/unit/test_fixture_values.py` | shape synthesis |
| `tests/unit/test_fixture_render.py` | rendering and `customData` |
| `tests/unit/test_fixture_generate.py` | prompting, caching, no-real-data |
| `tests/integration/test_fixture_end_to_end.py` | acceptance |

Add `"fixtures"` to `packages` in `pyproject.toml` (Task 1).

---

### Task 1: `fixtures.plan` — group sizes

The scaling defect this task exists to avoid: scaling group *counts* by `1500/<corpus row count>` rounds the four largest groups to zero while still owing their tickets, deleting the corpus's most prominent structure. Large groups scale by **size**, small groups are **sampled**, singletons take the **remainder**.

**Files:**
- Create: `fixtures/__init__.py`, `fixtures/plan.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_fixture_plan.py`

- [ ] **Step 1: Create the package marker and register it**

Create `fixtures/__init__.py` as an empty file.

In `pyproject.toml`, change:

```toml
packages = ["src/recall", "profiler"]
```

to:

```toml
packages = ["src/recall", "profiler", "fixtures"]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_fixture_plan.py
import pytest

from fixtures import plan as plan_mod


def _profile(**overrides) -> dict:
    """An illustrative stand-in for the real corpus's measured shape, trimmed to what
    the planner reads (real figures omitted: rounded, same structure - mostly
    singletons, a thin mid band, one dominant large group and three smaller ones)."""
    profile = {
        "source": {"row_count": 15100},
        "clusters": {
            "size_distribution": {
                "1": 11400, "2": 300, "3": 70, "4": 40, "5": 20, "6": 10, "7": 10,
                "8": 5, "10": 5, "12": 5, "14": 5,
                "60": 2, "160": 1, "2000": 1,
            }
        },
    }
    profile.update(overrides)
    return profile


def test_the_dominant_group_survives_scaling():
    """Scaling group COUNTS rounds 4 groups of 50+ to zero while still owing their
    tickets, deleting the handover cluster - the corpus's most prominent structure."""
    result = plan_mod.group_sizes(_profile(), rows=1500, seed=7)
    ranked = sorted(result, reverse=True)
    assert ranked[0] >= 50, "the dominant group, scaled by size"
    assert ranked[0] == round(2000 * 1500 / 15100)
    assert all(2 <= s < 50 for s in ranked[1:4]), "the three smaller large groups, scaled"


def test_every_ticket_is_accounted_for():
    result = plan_mod.group_sizes(_profile(), rows=1500, seed=7)
    assert sum(result) == 1500


def test_band_shares_match_the_real_corpus():
    """M3 reports metrics on both corpora, so a number only transfers if the
    distributions do."""
    result = plan_mod.group_sizes(_profile(), rows=1500, seed=7)
    total = sum(result)
    singles = sum(s for s in result if s == 1)
    mid = sum(s for s in result if 2 <= s <= 49)
    large = sum(s for s in result if s >= 50)
    # Targets rounded (real figures omitted); the large target is what the planner
    # produced at this point, before the band-share fix of the findings plan.
    assert abs(singles / total - 0.75) < 0.02
    assert abs(mid / total - 0.10) < 0.02
    assert abs(large / total - 0.13) < 0.02


def test_planning_is_deterministic_for_a_seed():
    """The fixture is committed, so a regeneration that silently differs is a
    review problem."""
    assert plan_mod.group_sizes(_profile(), rows=1500, seed=7) == plan_mod.group_sizes(
        _profile(), rows=1500, seed=7
    )
    assert plan_mod.group_sizes(_profile(), rows=1500, seed=8) != plan_mod.group_sizes(
        _profile(), rows=1500, seed=7
    )


def test_a_row_count_too_small_to_hold_the_large_groups_is_refused():
    """Silently dropping the structure would produce a fixture that looks fine and
    tests nothing."""
    with pytest.raises(ValueError, match="too small"):
        plan_mod.group_sizes(_profile(), rows=100, seed=7)
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures'` or `AttributeError: module 'fixtures.plan' has no attribute 'group_sizes'`.

- [ ] **Step 4: Implement**

```python
# fixtures/plan.py
"""Decide every number in the fixture from the profile artifact.

Pure: no LLM, no network, no filesystem. This is the only place profile.json is
interpreted, so the fixture's fidelity is decided in one readable place and can be
tested without generating a single word of German.
"""

from __future__ import annotations

import random

# At or above this many members, a group's SIZE is scaled rather than the group being
# sampled. Scaling counts instead would round the four largest real groups to zero while
# still owing their tickets, deleting the handover cluster entirely.
LARGE_GROUP = 50


def group_sizes(profile: dict, rows: int, seed: int) -> list[int]:
    """One entry per near-duplicate group; the list sums to `rows`.

    Large groups keep their identity at scaled size, mid-sized groups are sampled from
    the real size distribution until their ticket budget is spent, and singletons take
    whatever remains so the total is exact however the rest rounds.
    """
    rng = random.Random(seed)
    real_rows = profile["source"]["row_count"]
    dist = {int(size): n for size, n in profile["clusters"]["size_distribution"].items()}
    scale = rows / real_rows

    large = sorted(
        (size for size, n in dist.items() if size >= LARGE_GROUP for _ in range(n)),
        reverse=True,
    )
    sizes = [max(2, round(size * scale)) for size in large]

    mid_budget = round(sum(s * n for s, n in dist.items() if 2 <= s < LARGE_GROUP) * scale)
    pool = [s for s, n in dist.items() if 2 <= s < LARGE_GROUP for _ in range(n)]
    rng.shuffle(pool)
    spent = 0
    for size in pool:
        if spent + size > mid_budget:
            continue
        sizes.append(size)
        spent += size

    singletons = rows - sum(sizes)
    if singletons < 0:
        raise ValueError(
            f"rows={rows} is too small to hold the scaled large groups "
            f"({sum(sizes)} tickets); the fixture would lose its structure"
        )
    sizes.extend([1] * singletons)
    return sizes
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_plan.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add fixtures/__init__.py fixtures/plan.py pyproject.toml tests/unit/test_fixture_plan.py
git commit -m "feat(fixtures): scale near-duplicate group sizes from the profile

Scaling group counts by 1500/<corpus row count> rounds the four largest groups to zero while still
owing their tickets, which would delete the handover cluster - the corpus's most prominent
structure. Large groups scale by size, mid-sized groups are sampled, singletons take the
remainder so the total is exact.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `fixtures.plan` — the remaining targets

**Files:**
- Modify: `fixtures/plan.py`
- Test: `tests/unit/test_fixture_plan.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_plan.py`:

```python
def _full_profile() -> dict:
    profile = _profile()
    profile["solutions"] = {"fill_rate": 0.85}
    profile["temporal"] = {
        "fill_by_month": {
            "description": {"2020-06": 0.90, "2021-03": 0.85, "2024-07": 0.80},
            "solutions": {"2020-06": 0.30, "2021-03": 0.80, "2024-07": 0.80},
        }
    }
    profile["custom_data"] = {
        "envelope": {
            "detected": True,
            "name_attribute": "key",
            "fields": [
                {"name": "fehlercode", "present_count": 2800, "kind": "identifier_like",
                 "value_shapes": [{"shape": "DDDD-D", "count": 150},
                                  {"shape": "DDDD-DD", "count": 130}]},
                {"name": "baugruppe", "present_count": 4000, "kind": "identifier_like",
                 "value_shapes": [{"shape": "##D##", "count": 1900}]},
            ],
        }
    }
    return profile


def test_field_presence_shares_come_from_the_profile():
    result = plan_mod.plan(_full_profile(), rows=1500, seed=7)
    shares = {f.name: f.share for f in result.custom_fields}
    assert abs(shares["fehlercode"] - 2800 / 15100) < 0.001
    assert abs(shares["baugruppe"] - 4000 / 15100) < 0.001


def test_shape_mix_is_normalised_to_proportions():
    """Counts are per-shape occurrences, not shares; the renderer needs weights."""
    result = plan_mod.plan(_full_profile(), rows=1500, seed=7)
    field = next(f for f in result.custom_fields if f.name == "fehlercode")
    assert abs(sum(w for _, w in field.shape_mix) - 1.0) < 1e-9
    assert field.shape_mix[0][0] == "DDDD-D"


def test_fill_by_year_collapses_months():
    result = plan_mod.plan(_full_profile(), rows=1500, seed=7)
    assert abs(result.fill_by_year["2020"]["solutions"] - 0.30) < 0.001
    assert abs(result.fill_by_year["2024"]["description"] - 0.80) < 0.001


def test_the_plan_carries_the_group_sizes():
    result = plan_mod.plan(_full_profile(), rows=1500, seed=7)
    assert sum(result.group_sizes) == 1500
    assert result.rows == 1500
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_plan.py -v`
Expected: FAIL — `AttributeError: module 'fixtures.plan' has no attribute 'plan'`.

- [ ] **Step 3: Implement**

Add to the imports at the top of `fixtures/plan.py`:

```python
from collections import defaultdict
from dataclasses import dataclass
```

Append to `fixtures/plan.py`:

```python
@dataclass(frozen=True)
class CustomField:
    """One customData field the client records, and how to synthesise its values."""

    name: str
    kind: str
    share: float
    shape_mix: list[tuple[str, float]]  # (shape, weight); weights sum to 1.0


@dataclass(frozen=True)
class FixturePlan:
    rows: int
    seed: int
    group_sizes: list[int]
    solutions_fill: float
    fill_by_year: dict[str, dict[str, float]]
    custom_fields: list[CustomField]


def plan(profile: dict, rows: int = 1500, seed: int = 7) -> FixturePlan:
    """Every number the fixture needs, derived from the profile artifact."""
    real_rows = profile["source"]["row_count"]

    by_year: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for column, months in profile.get("temporal", {}).get("fill_by_month", {}).items():
        for month, rate in months.items():
            by_year[month[:4]][column].append(rate)
    fill_by_year = {
        year: {column: sum(v) / len(v) for column, v in columns.items()}
        for year, columns in by_year.items()
    }

    fields = []
    for field in profile.get("custom_data", {}).get("envelope", {}).get("fields", []):
        shapes = field.get("value_shapes", [])
        total = sum(s["count"] for s in shapes)
        fields.append(
            CustomField(
                name=field["name"],
                kind=field["kind"],
                share=field["present_count"] / real_rows,
                shape_mix=[(s["shape"], s["count"] / total) for s in shapes] if total else [],
            )
        )

    return FixturePlan(
        rows=rows,
        seed=seed,
        group_sizes=group_sizes(profile, rows, seed),
        solutions_fill=profile.get("solutions", {}).get("fill_rate", 0.0),
        fill_by_year=fill_by_year,
        custom_fields=fields,
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_plan.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/plan.py tests/unit/test_fixture_plan.py
git commit -m "feat(fixtures): derive fill rates, field shares and shape mixes from the profile

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `fixtures.values` — synthesise a value from a shape

`shape_of` reduces a value to a closed alphabet. This inverts it: given `DDDD-D`, produce `4821-7`. The round-trip is the test — a synthesised value must shape back to the shape it came from, or the fixture's `fehlercode` column would not match the real one.

**Files:**
- Create: `fixtures/values.py`
- Test: `tests/unit/test_fixture_values.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fixture_values.py
import random

from fixtures import values
from recall.german.identifiers import shape_of

# The measured fehlercode shape mix from the real corpus.
REAL_SHAPES = [
    "DDDD-D", "DDDD-DD", "DDDDD", "DDDD", "ALL_DD",
    "DDD-DD", "ALL_DDDD-D", "ALDD_DDDDD", "DDDD-DD#_DDDD-DD", "ALL_DDDD",
]


def test_a_synthesised_value_shapes_back_to_its_own_shape():
    """If it did not, the fixture's fehlercode column would not match the real one and
    the identifier work would be tested against a format the client does not use."""
    rng = random.Random(1)
    for shape in REAL_SHAPES:
        for _ in range(20):
            produced = values.from_shape(shape, rng)
            assert shape_of(produced) == shape, f"{produced!r} -> {shape_of(produced)!r}"


def test_separators_are_preserved_literally():
    rng = random.Random(1)
    assert values.from_shape("DD.DD.DDDD", rng).count(".") == 2
    assert values.from_shape("DDDD-D", rng).count("-") == 1


def test_values_from_one_shape_differ():
    """A single repeated value would collapse the identifier arm to one document."""
    rng = random.Random(1)
    produced = {values.from_shape("DDDD-D", rng) for _ in range(50)}
    assert len(produced) > 20


def test_the_choice_of_shape_follows_the_weights():
    rng = random.Random(1)
    mix = [("DDDD-D", 0.9), ("ALL_DD", 0.1)]
    picked = [values.pick_shape(mix, rng) for _ in range(1000)]
    assert 850 < picked.count("DDDD-D") < 950
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_values.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.values'`.

- [ ] **Step 3: Implement**

```python
# fixtures/values.py
"""Turn a character-class shape back into a conforming value.

shape_of reduces a value to a closed alphabet so it can leave a sealed window. This
inverts it, so the fixture's identifier columns carry the formats the real corpus uses
rather than formats we guessed. The invariant is a round trip: shape_of(from_shape(s))
must equal s, and that is what the tests assert.
"""

from __future__ import annotations

import random
import string

# Must shape back to '#': not a digit, not a letter, not whitespace, and not one of
# shape_of's preserved separators (-./:). '/' would shape to itself, so it is excluded.
_OTHER = "+(),*"


def from_shape(shape: str, rng: random.Random) -> str:
    """A value whose shape_of() is exactly `shape`."""
    out = []
    for char in shape:
        if char == "D":
            out.append(rng.choice(string.digits))
        elif char in ("A", "L"):
            out.append(rng.choice(string.ascii_uppercase))
        elif char == "a":
            out.append(rng.choice(string.ascii_lowercase))
        elif char == "_":
            out.append(" ")
        elif char == "#":
            out.append(rng.choice(_OTHER))
        else:
            out.append(char)  # -./: are kept literally by shape_of
    return "".join(out)


def pick_shape(mix: list[tuple[str, float]], rng: random.Random) -> str:
    """Choose a shape according to its measured weight."""
    shapes = [s for s, _ in mix]
    weights = [w for _, w in mix]
    return rng.choices(shapes, weights=weights, k=1)[0]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_values.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/values.py tests/unit/test_fixture_values.py
git commit -m "feat(fixtures): synthesise values that shape back to their own shape

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `fixtures.render` — the customData envelope

The client stores `customData` as a JSON string whose content is a JSON array of field descriptors. Two airlock windows were spent discovering that, because the old stand-in used a plain object. The fixture must not repeat it.

**Files:**
- Create: `fixtures/render.py`
- Test: `tests/unit/test_fixture_render.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fixture_render.py
import json
import random

from fixtures import render
from profiler.stats import customdata


def test_custom_data_is_double_encoded_like_the_real_export():
    """The real field opens with a quote because it is serialised twice. A plain object
    here would rehearse a format the client does not use - which is exactly how two
    windows were spent."""
    blob = render.custom_data([("fehlercode", "4821-7"), ("baugruppe", "+(1)*")])
    assert blob.startswith('"'), "the value must be a JSON string, not a JSON array"
    records = customdata.parse_records(blob)
    assert [r["key"] for r in records] == ["fehlercode", "baugruppe"]
    assert [r["value"] for r in records] == ["4821-7", "+(1)*"]


def test_the_envelope_is_detected_as_one():
    blob = render.custom_data([("fehlercode", "4821-7")])
    assert customdata.detect_envelope([customdata.parse_records(blob)]) == "key"


def test_every_descriptor_carries_the_six_attributes():
    records = customdata.parse_records(render.custom_data([("fehlercode", "4821-7")]))
    assert set(records[0]) == {"group", "key", "label", "value", "text", "type"}


def test_an_empty_field_list_still_parses():
    """A small share of real values are an empty array. Valid syntax carrying no fields."""
    blob = render.custom_data([])
    assert customdata.parse_records(blob) == []


def test_fields_are_chosen_by_their_measured_share():
    """A field present in a fifth of real tickets must appear in about a fifth of fixture rows (shares rounded here; real figures omitted)."""
    from fixtures.plan import CustomField

    fields = [
        CustomField("fehlercode", "identifier_like", 0.20, [("DDDD-D", 1.0)]),
        CustomField("baugruppe", "identifier_like", 0.25, [("##D##", 1.0)]),
    ]
    rng = random.Random(3)
    rows = [render.custom_fields_for_row(fields, rng) for _ in range(4000)]
    present = [sum(1 for r in rows if any(k == name for k, _ in r)) for name in ("fehlercode", "baugruppe")]
    assert abs(present[0] / 4000 - 0.20) < 0.02
    assert abs(present[1] / 4000 - 0.25) < 0.02
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.render'`.

- [ ] **Step 3: Implement**

```python
# fixtures/render.py
"""Assemble fixture rows in exactly the shape the real export uses."""

from __future__ import annotations

import json
import random

from fixtures import values
from fixtures.plan import CustomField


def custom_data(fields: list[tuple[str, str]]) -> str:
    """The client's customData encoding: descriptors, serialised twice.

    json.dumps of a json.dumps, so the CSV field opens with a quote and a single
    json.loads returns a string rather than a container. Round 2 parsed none of the
    real values because nothing rehearsed this.
    """
    records = [
        {
            "group": "Allgemein",
            "key": name,
            "label": f"Feld {name}",
            "value": value,
            "text": value,
            "type": "string",
        }
        for name, value in fields
    ]
    return json.dumps(json.dumps(records, ensure_ascii=False), ensure_ascii=False)


def custom_fields_for_row(
    fields: list[CustomField], rng: random.Random
) -> list[tuple[str, str]]:
    """Which fields this ticket carries, and a value for each, at measured shares."""
    chosen = []
    for field in fields:
        if rng.random() >= field.share:
            continue
        if field.shape_mix:
            shape = values.pick_shape(field.shape_mix, rng)
            chosen.append((field.name, values.from_shape(shape, rng)))
        else:
            chosen.append((field.name, ""))
    return chosen
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/render.py tests/unit/test_fixture_render.py
git commit -m "feat(fixtures): render customData the way the client encodes it

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `fixtures.render` — the 38-column row

**Files:**
- Modify: `fixtures/render.py`
- Test: `tests/unit/test_fixture_render.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_render.py`:

```python
def test_a_row_has_every_expected_column():
    from profiler.columns import EXPECTED_COLUMNS

    rng = random.Random(5)
    row = render.row(index=1, title="Pumpe defekt", description="Beschreibung",
                     solution="Pumpe getauscht", month="2024-07", custom=[], rng=rng)
    assert set(row) == set(EXPECTED_COLUMNS)


def test_the_timestamp_uses_the_month_it_was_planned_for():
    """fill_by_year is measured per month, so a row must land in its own month or the
    workflow step would not reproduce."""
    rng = random.Random(5)
    row = render.row(index=1, title="t", description="d", solution="s",
                     month="2022-03", custom=[], rng=rng)
    assert row["timestampCreated"].startswith("2022-03-")


def test_an_empty_solution_is_written_as_an_empty_field():
    """A minority of real solutions are empty strings, not filler text."""
    rng = random.Random(5)
    row = render.row(index=1, title="t", description="d", solution="",
                     month="2024-07", custom=[], rng=rng)
    assert row["solutions"] == ""


def test_writing_a_csv_round_trips_through_the_profiler_parser():
    import csv
    import io

    rng = random.Random(5)
    rows = [
        render.row(index=i, title="t", description="d", solution="s",
                   month="2024-07", custom=[("fehlercode", "4821-7")], rng=rng)
        for i in range(1, 4)
    ]
    buffer = io.StringIO()
    render.write_csv(rows, buffer)
    buffer.seek(0)
    parsed = list(csv.DictReader(buffer))
    assert len(parsed) == 3
    assert customdata.parse_records(parsed[0]["customData"])[0]["key"] == "fehlercode"
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: FAIL — `AttributeError: module 'fixtures.render' has no attribute 'row'`.

- [ ] **Step 3: Implement**

Add to the imports at the top of `fixtures/render.py`:

```python
import csv
from typing import TextIO

from profiler.columns import EXPECTED_COLUMNS
```

Append to `fixtures/render.py`:

```python
def row(
    index: int,
    title: str,
    description: str,
    solution: str,
    month: str,
    custom: list[tuple[str, str]],
    rng: random.Random,
) -> dict[str, str]:
    """One ticket, with every expected column present.

    Columns the profile shows as opaque identifiers are filled with opaque identifiers;
    the fixture is about structure, so a plausible-looking foreign key is enough.
    """
    day = rng.randint(1, 28)
    filled = {
        "id": str(index),
        "ticketNumber": f"TN-{100000 + index}",
        "title": title,
        "description": description,
        "solutions": solution,
        "customData": custom_data(custom),
        "timestampCreated": f"{month}-{day:02d}",
        "statusId": str(rng.choice([3, 3, 3, 3, 7])),
        "priorityId": str(rng.choice([1, 2, 2, 3])),
        "categoryId": str(rng.randint(1, 12)),
        "vehicleModelId": str(rng.randint(1, 66)),
        "vehicleYear": str(rng.randint(2008, 2025)),
        "vehicleHours": str(rng.randint(50, 12000)),
    }
    return {column: filled.get(column, "") for column in EXPECTED_COLUMNS}


def write_csv(rows: list[dict[str, str]], handle: TextIO) -> None:
    writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/render.py tests/unit/test_fixture_render.py
git commit -m "feat(fixtures): render the 38-column ticket row

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `fixtures.llm` — client, cache, and a fake

**Files:**
- Create: `fixtures/llm.py`
- Test: `tests/unit/test_fixture_generate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fixture_generate.py
from fixtures import llm


def test_a_cached_prompt_is_not_sent_twice(tmp_path):
    """Generation is the slow, expensive step and a partial failure must resume rather
    than restart."""
    calls = []

    def inner(prompt: str) -> str:
        calls.append(prompt)
        return "antwort"

    client = llm.Cached(inner, tmp_path)
    assert client("frage") == "antwort"
    assert client("frage") == "antwort"
    assert calls == ["frage"], "the second call must come from the cache"


def test_a_different_prompt_is_a_different_cache_entry(tmp_path):
    client = llm.Cached(lambda prompt: prompt.upper(), tmp_path)
    assert client("eins") == "EINS"
    assert client("zwei") == "ZWEI"


def test_the_cache_survives_a_new_client(tmp_path):
    llm.Cached(lambda prompt: "erste", tmp_path)("frage")
    second = llm.Cached(lambda prompt: "zweite", tmp_path)
    assert second("frage") == "erste", "a rerun must not regenerate what it already has"


def test_the_fake_client_is_deterministic():
    """Tests must not need a GPU."""
    assert llm.Fake(seed=1)("prompt") == llm.Fake(seed=1)("prompt")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_generate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.llm'`.

- [ ] **Step 3: Implement**

```python
# fixtures/llm.py
"""Talk to the model, and remember what it said.

Sampling is not reproducible, so the fixture ITSELF is the artifact: generated once,
verified, gated and committed. The cache exists so a partial failure resumes instead of
restarting, and so a rerun during review costs nothing.
"""

from __future__ import annotations

import hashlib
import pathlib
import random
from typing import Callable, Protocol


class Client(Protocol):
    def __call__(self, prompt: str) -> str: ...


class Cached:
    """Wrap a client with a content-addressed disk cache."""

    def __init__(self, inner: Callable[[str], str], cache_dir: pathlib.Path) -> None:
        self._inner = inner
        self._dir = pathlib.Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, prompt: str) -> str:
        key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:32]
        path = self._dir / f"{key}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        answer = self._inner(prompt)
        path.write_text(answer, encoding="utf-8")
        return answer


class Fake:
    """Deterministic stand-in so tests need no GPU.

    It must emit the same block format the real prompt asks for - a bare sentence would
    parse to zero tickets and every group would fall through to the padding path,
    producing one repeated string for the whole fixture. Content is derived from the
    prompt, so distinct prompts give distinct text and the cluster bands come out right.
    """

    _PARTS = ["Dichtung", "Ventil", "Sensor", "Schlauch", "Lager", "Pumpe", "Filter"]
    _ACTIONS = ["getauscht", "gereinigt", "nachgezogen", "entlueftet", "kalibriert"]
    BLOCKS = 40  # more than any single group needs; the caller takes what it wants

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def __call__(self, prompt: str) -> str:
        rng = random.Random(f"{self._seed}:{prompt}")
        subject = rng.choice(self._PARTS)
        blocks = []
        for n in range(self.BLOCKS):
            part, action = rng.choice(self._PARTS), rng.choice(self._ACTIONS)
            blocks.append(
                f"TITEL: {subject} Stoerung {rng.randrange(10**6)}\n"
                f"BEFUND: {subject} zeigt Auffaelligkeit {rng.randrange(10**6)} "
                f"bei Variante {n} im Betrieb.\n"
                f"LOESUNG: {part} {action}, Funktion geprueft, Pruefschritt {n}.\n---"
            )
        return "\n".join(blocks)


def vllm(base_url: str, model: str, temperature: float = 0.8) -> Client:
    """OpenAI-compatible client for vLLM on the H100.

    Imported lazily so the test suite never needs httpx installed for the fixture work,
    and so a machine without the box configured can still run everything else.
    """

    def call(prompt: str) -> str:
        import httpx

        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    return call
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_generate.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/llm.py tests/unit/test_fixture_generate.py
git commit -m "feat(fixtures): cached LLM client with a deterministic fake

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `fixtures.generate` — themes and variants

One prompt per group, asking for N *different approaches* to the same fault. Variants that differ only in wording would make the near-duplicate groups fake, and near-duplicate retrieval is the behaviour the product depends on most.

**Files:**
- Create: `fixtures/generate.py`
- Test: `tests/unit/test_fixture_generate.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_generate.py`:

```python
from fixtures import generate


def test_one_ticket_is_produced_per_group_member():
    tickets = generate.tickets([3, 1, 1], llm.Fake(seed=2))
    assert len(tickets) == 5


def test_members_of_a_group_share_a_theme_and_singletons_do_not():
    tickets = generate.tickets([3, 1], llm.Fake(seed=2))
    groups = {}
    for ticket in tickets:
        groups.setdefault(ticket.group, []).append(ticket)
    assert len(groups[0]) == 3
    assert len(groups[1]) == 1


def test_the_prompt_asks_for_different_approaches_not_rewordings():
    """Variants that differ only in wording make the groups fake, and near-duplicate
    retrieval is the behaviour the product depends on most."""
    seen = []
    generate.tickets([4], lambda prompt: seen.append(prompt) or "text")
    assert any("unterschiedlich" in p.lower() or "different" in p.lower() for p in seen)


def test_singletons_do_not_collapse_into_one_cluster():
    """With ten themes, a prompt per singleton yields ten identical prompts and therefore
    ten identical tickets. The fixture would be one huge cluster and every band share in
    the acceptance test would be wrong."""
    produced = generate.tickets([1] * 60, llm.Fake(seed=4))
    assert len(produced) == 60
    assert len({t.description for t in produced}) > 40, "singletons must differ"


def test_two_groups_sharing_a_theme_do_not_share_a_prompt():
    seen = []
    generate.tickets([2, 2, 2], lambda prompt: seen.append(prompt) or "")
    assert len(set(seen)) == len(seen), "each group needs its own prompt"


def test_no_corpus_string_ever_reaches_a_prompt():
    """The model must never see real data. This is asserted rather than intended."""
    seen = []
    generate.tickets([2, 1], lambda prompt: seen.append(prompt) or "text")
    joined = " ".join(seen)
    # Tokens known to occur in the real text: a workflow word, a dealer name, a person
    # name (the real terms are omitted from this document).
    for corpus_string in ("<workflow-term>", "<dealer-name>", "<person-name>"):
        assert corpus_string.lower() not in joined.lower()
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_generate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.generate'`.

- [ ] **Step 3: Implement**

```python
# fixtures/generate.py
"""Ask the model for German fault text, one prompt per near-duplicate group.

The model receives plan NUMBERS and invented themes only - never corpus text. That is
what makes the leakage gate a formality rather than a gamble: no real n-gram was ever
available to copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from fixtures.llm import Client

# Invented seed themes. Deliberately not drawn from the profile's top tokens: reusing
# real vocabulary would put real n-grams within the model's reach and the gate would be
# measuring our luck rather than our method.
THEMES = [
    "Hydraulikpumpe verliert Druck",
    "Getriebe schaltet nicht in den zweiten Gang",
    "Bremsleitung undicht an der Hinterachse",
    "Motor startet nach Kaltstart nicht",
    "Kuehlwasserverlust am Zylinderkopf",
    "Ladekran senkt sich selbstaendig ab",
    "Lenkung schwergaengig bei Volllast",
    "Elektronik meldet Sensorfehler am Ausleger",
    "Klimaanlage kuehlt nicht ausreichend",
    "Reifendruckverlust an der Vorderachse",
]


@dataclass(frozen=True)
class Ticket:
    group: int
    title: str
    description: str
    solution: str


# Singletons are asked for in batches of distinct faults rather than one prompt each.
# With ten themes and about a thousand singletons, a per-group prompt collapses to ten identical
# prompts and therefore ten identical tickets - the fixture would be one huge cluster and
# the measured band shares would be meaningless.
SINGLETON_BATCH = 25


def _prompt(theme: str, count: int, series: int) -> str:
    """Variants of ONE fault. `series` keeps two groups sharing a theme from sharing a
    prompt, and therefore from collapsing into a single cluster."""
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Fehlerbild: {theme}\n"
        f"Serie {series}\n\n"
        f"Schreibe {count} Tickets zu genau diesem Fehlerbild. Jedes Ticket muss einen "
        f"unterschiedlichen Loesungsweg beschreiben - andere Diagnose, andere Reihenfolge, "
        f"anderes Ersatzteil. Nicht dieselbe Loesung anders formuliert.\n\n"
        f"Format je Ticket, jeweils eine Zeile:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\nLOESUNG: <2-3 Saetze>\n---\n"
    )


def _prompt_distinct(count: int, series: int) -> str:
    """Unrelated faults, one per ticket - the corpus is about three quarters singletons."""
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Serie {series}\n\n"
        f"Schreibe {count} Tickets zu {count} VERSCHIEDENEN Fehlerbildern - "
        f"unterschiedliche Baugruppen, unterschiedliche Symptome, kein Zusammenhang "
        f"zwischen den Tickets.\n\n"
        f"Format je Ticket, jeweils eine Zeile:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\nLOESUNG: <2-3 Saetze>\n---\n"
    )


def _parse(text: str, group: int) -> list[Ticket]:
    tickets, current = [], {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TITEL:"):
            current["title"] = line[6:].strip()
        elif line.startswith("BEFUND:"):
            current["description"] = line[7:].strip()
        elif line.startswith("LOESUNG:"):
            current["solution"] = line[8:].strip()
        elif line.startswith("---") and current:
            tickets.append(
                Ticket(
                    group,
                    current.get("title", ""),
                    current.get("description", ""),
                    current.get("solution", ""),
                )
            )
            current = {}
    if current:
        tickets.append(
            Ticket(
                group,
                current.get("title", ""),
                current.get("description", ""),
                current.get("solution", ""),
            )
        )
    return tickets


def tickets(group_sizes: list[int], client: Client) -> list[Ticket]:
    """One ticket per group member.

    Multi-member groups get one prompt each, asking for that many different approaches to
    a single fault. Singletons are batched, because asking once per singleton would send
    the same prompt over a thousand times.
    """
    out: list[Ticket] = []

    for index, size in enumerate(group_sizes):
        if size < 2:
            continue
        theme = THEMES[index % len(THEMES)]
        produced = _parse(client(_prompt(theme, size, index)), index)
        attempt = 0
        while len(produced) < size and attempt < 2:
            attempt += 1
            shortfall = size - len(produced)
            produced.extend(
                _parse(client(_prompt(theme, shortfall, index * 1000 + attempt)), index)
            )
        while len(produced) < size:  # the model kept coming up short; do not stall the run
            produced.append(Ticket(index, theme, theme, ""))
        out.extend(produced[:size])

    singletons = [i for i, size in enumerate(group_sizes) if size < 2]
    for series, start in enumerate(range(0, len(singletons), SINGLETON_BATCH)):
        batch = singletons[start : start + SINGLETON_BATCH]
        produced = _parse(client(_prompt_distinct(len(batch), series)), -1)
        for offset, group in enumerate(batch):
            if offset < len(produced):
                item = produced[offset]
                out.append(Ticket(group, item.title, item.description, item.solution))
            else:
                out.append(Ticket(group, f"Stoerung {group}", "", ""))

    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_generate.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/generate.py tests/unit/test_fixture_generate.py
git commit -m "feat(fixtures): generate themes and variants, one prompt per group

Variants must differ in approach rather than wording: near-duplicate retrieval is the
behaviour the product depends on most, and rewordings would test a distinction the real
corpus does not contain.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `fixtures.verify` — does the output match the plan?

**Files:**
- Create: `fixtures/verify.py`
- Test: `tests/unit/test_fixture_render.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_render.py`:

```python
def test_verify_accepts_a_faithful_fixture():
    from fixtures import verify
    from fixtures.plan import CustomField, FixturePlan

    fixture_plan = FixturePlan(
        rows=100, seed=1, group_sizes=[1] * 100, solutions_fill=1.0,
        fill_by_year={}, custom_fields=[CustomField("fehlercode", "identifier_like", 1.0, [("DDDD-D", 1.0)])],
    )
    rng = random.Random(1)
    rows = [
        render.row(index=i, title="t", description="d", solution="s", month="2024-07",
                   custom=[("fehlercode", "4821-7")], rng=rng)
        for i in range(1, 101)
    ]
    assert verify.check(rows, fixture_plan) == []


def test_verify_reports_a_row_count_mismatch():
    from fixtures import verify
    from fixtures.plan import FixturePlan

    fixture_plan = FixturePlan(rows=100, seed=1, group_sizes=[1] * 100,
                               solutions_fill=1.0, fill_by_year={}, custom_fields=[])
    rng = random.Random(1)
    rows = [render.row(index=1, title="t", description="d", solution="s",
                       month="2024-07", custom=[], rng=rng)]
    problems = verify.check(rows, fixture_plan)
    assert any("row count" in p for p in problems)


def test_verify_reports_a_field_share_that_drifted():
    """Silent drift would produce a fixture that looks right and measures wrong."""
    from fixtures import verify
    from fixtures.plan import CustomField, FixturePlan

    fixture_plan = FixturePlan(
        rows=100, seed=1, group_sizes=[1] * 100, solutions_fill=1.0, fill_by_year={},
        custom_fields=[CustomField("fehlercode", "identifier_like", 0.50, [("DDDD-D", 1.0)])],
    )
    rng = random.Random(1)
    rows = [
        render.row(index=i, title="t", description="d", solution="s", month="2024-07",
                   custom=[], rng=rng)  # field never present, planned at 50%
        for i in range(1, 101)
    ]
    problems = verify.check(rows, fixture_plan)
    assert any("fehlercode" in p for p in problems)
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.verify'`.

- [ ] **Step 3: Implement**

```python
# fixtures/verify.py
"""Check the rendered fixture against the plan.

Generation is not reproducible, so correctness cannot come from repeating it. It comes
from checking the result. Every tolerance here is the one written in the design doc.
"""

from __future__ import annotations

from fixtures.plan import FixturePlan
from profiler.stats import customdata

FIELD_SHARE_TOLERANCE = 0.02
FILL_TOLERANCE = 0.02


def check(rows: list[dict[str, str]], plan: FixturePlan) -> list[str]:
    """Every way the fixture drifted from its plan. Empty means faithful."""
    problems: list[str] = []

    if len(rows) != plan.rows:
        problems.append(f"row count is {len(rows)}, planned {plan.rows}")

    if rows:
        filled = sum(1 for r in rows if (r.get("solutions") or "").strip())
        actual = filled / len(rows)
        if abs(actual - plan.solutions_fill) > FILL_TOLERANCE:
            problems.append(
                f"solutions fill is {actual:.3f}, planned {plan.solutions_fill:.3f}"
            )

    present: dict[str, int] = {}
    for row in rows:
        records = customdata.parse_records(row.get("customData")) or []
        for name in {r.get("key") for r in records if isinstance(r.get("key"), str)}:
            present[name] = present.get(name, 0) + 1

    for field in plan.custom_fields:
        actual = present.get(field.name, 0) / len(rows) if rows else 0.0
        if abs(actual - field.share) > FIELD_SHARE_TOLERANCE:
            problems.append(
                f"customData field {field.name} present in {actual:.3f} of rows, "
                f"planned {field.share:.3f}"
            )

    return problems
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_render.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add fixtures/verify.py tests/unit/test_fixture_render.py
git commit -m "feat(fixtures): verify the rendered fixture against its plan

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `fixtures.__main__` — the CLI

**Files:**
- Create: `fixtures/__main__.py`
- Test: `tests/integration/test_fixture_end_to_end.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_fixture_end_to_end.py
import csv
import json
import pathlib

import pytest

ROUND_THREE = pathlib.Path("local/artifacts/profile.json")


def test_the_cli_writes_a_fixture_without_a_gpu(tmp_path):
    """--fake must produce a complete, verifiable fixture, so the whole pipeline is
    testable on a workstation with no model served."""
    from fixtures.__main__ import main

    out = tmp_path / "export.csv"
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "source": {"row_count": 15100},  # illustrative, real figures omitted
                "clusters": {"size_distribution": {"1": 11400, "2": 300, "60": 1, "2000": 1}},
                "solutions": {"fill_rate": 1.0},
                "temporal": {"fill_by_month": {"description": {"2024-07": 1.0},
                                               "solutions": {"2024-07": 1.0}}},
                "custom_data": {"envelope": {"fields": [
                    {"name": "fehlercode", "present_count": 2800, "kind": "identifier_like",
                     "value_shapes": [{"shape": "DDDD-D", "count": 150}]}
                ]}},
            }
        )
    )
    assert main(["--profile", str(profile), "--out", str(out), "--rows", "200", "--fake"]) == 0
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 200
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/integration/test_fixture_end_to_end.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fixtures.__main__'`.

- [ ] **Step 3: Implement**

```python
# fixtures/__main__.py
"""Generate the synthetic fixture.

    uv run python -m fixtures --profile local/artifacts/profile.json \\
        --out local/fixtures/export.csv --fake

Drop --fake and pass --base-url to use the model on the H100. Generation reads a gated
artifact and produces invented text, so it needs no airlock window - the box is used for
compute, not for data access.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

from fixtures import generate, llm, render, verify
from fixtures.plan import plan as build_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixtures")
    parser.add_argument("--profile", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--rows", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fake", action="store_true", help="no GPU; deterministic stub")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("local/fixtures/cache"))
    args = parser.parse_args(argv)

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    fixture_plan = build_plan(profile, rows=args.rows, seed=args.seed)

    inner = llm.Fake(seed=args.seed) if args.fake else llm.vllm(args.base_url, args.model)
    client = llm.Cached(inner, args.cache)

    tickets = generate.tickets(fixture_plan.group_sizes, client)
    rng = random.Random(args.seed)
    months = sorted(fixture_plan.fill_by_year) or ["2024"]
    rows = []
    for index, ticket in enumerate(tickets, start=1):
        year = months[index % len(months)]
        rows.append(
            render.row(
                index=index,
                title=ticket.title,
                description=ticket.description,
                solution=ticket.solution if rng.random() < fixture_plan.solutions_fill else "",
                month=f"{year}-{rng.randint(1, 12):02d}",
                custom=render.custom_fields_for_row(fixture_plan.custom_fields, rng),
                rng=rng,
            )
        )

    problems = verify.check(rows, fixture_plan)
    if problems:
        print("ABORT the fixture drifted from its plan:")
        for problem in problems:
            print(f"  - {problem}")
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        render.write_csv(rows, handle)
    print(f"wrote {args.out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/integration/test_fixture_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 5: Run everything**

Run: `make test && make lint`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fixtures/__main__.py tests/integration/test_fixture_end_to_end.py
git commit -m "feat(fixtures): CLI, runnable without a GPU via --fake

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Acceptance — the fixture must profile like the real corpus

The strongest available check costs nothing new: we own a corpus profiler. Run it over the fixture and compare.

**What `--fake` can and cannot prove.** The stub emits templated sentences, so every
ticket near-duplicates every other one and the corpus collapses into a handful of
clusters. A simulation at full scale produced about a thousand singletons carrying only a
couple of hundred distinct descriptions. So the fake path proves the *pipeline* — row count, columns, `customData`
encoding, field shares, all of which are produced independently of the text — and the
cluster bands are checked against the model-generated fixture. Asserting bands on stub
text would fail for a reason that has nothing to do with the planner.

**Files:**
- Test: `tests/integration/test_fixture_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_fixture_end_to_end.py`:

```python
@pytest.mark.skipif(not ROUND_THREE.exists(), reason="round-3 artifact not present")
def test_the_fake_path_reproduces_everything_that_does_not_depend_on_the_text(tmp_path):
    """customData, field shares and column structure are rendered independently of the
    generated German, so the stub can prove all of them. Cluster bands cannot be proven
    here - see the model-generated test below."""
    from fixtures.__main__ import main
    from profiler.__main__ import build_profile

    out = tmp_path / "export.csv"
    assert main(["--profile", str(ROUND_THREE), "--out", str(out),
                 "--rows", "1500", "--fake"]) == 0

    real = json.loads(ROUND_THREE.read_text())
    synthetic = build_profile(out, 5)

    assert synthetic["source"]["row_count"] == 1500
    assert len(synthetic["source"]["columns_found"]) == 38
    assert synthetic["custom_data"]["format"] == "json"
    assert synthetic["custom_data"]["envelope"]["detected"] is True

    real_fields = {f["name"]: f["present_count"] / real["source"]["row_count"]
                   for f in real["custom_data"]["envelope"]["fields"]}
    synthetic_fields = {f["name"]: f["present_count"] / 1500
                        for f in synthetic["custom_data"]["envelope"]["fields"]}
    for name, expected in real_fields.items():
        if expected >= 0.10:  # below this, 1,500 rows cannot resolve the share
            assert abs(synthetic_fields.get(name, 0.0) - expected) < 0.02, name


GENERATED = pathlib.Path("local/fixtures/export.csv")


@pytest.mark.skipif(
    not (ROUND_THREE.exists() and GENERATED.exists()),
    reason="model-generated fixture not present; run Task 10 Step 3 against the H100",
)
def test_the_generated_fixture_profiles_like_the_real_corpus():
    """Cluster bands need real generated prose. Tolerances are the design doc's. A drift
    means the planner is wrong, not that the tolerance is."""
    from profiler.__main__ import build_profile

    real = json.loads(ROUND_THREE.read_text())
    synthetic = build_profile(GENERATED, 5)

    def bands(profile):
        dist = {int(k): v for k, v in profile["clusters"]["size_distribution"].items()}
        total = profile["source"]["row_count"]
        return {
            "singletons": sum(s * n for s, n in dist.items() if s == 1) / total,
            "mid": sum(s * n for s, n in dist.items() if 2 <= s <= 49) / total,
            "large": sum(s * n for s, n in dist.items() if s >= 50) / total,
        }

    real_bands, synthetic_bands = bands(real), bands(synthetic)
    for band, expected in real_bands.items():
        assert abs(synthetic_bands[band] - expected) < 0.01, band
```

- [ ] **Step 2: Run it**

Run: `PG_DSN='postgresql://recall:recall_dev_only@localhost:5433/recall' uv run pytest tests/integration/test_fixture_end_to_end.py -v`
Expected: PASS (the generated-fixture test skips until Step 3's model run exists). If a band drifts later, the planner is wrong — fix `fixtures/plan.py`, not the tolerance.

- [ ] **Step 3: Generate the real fixture**

```bash
uv run python -m fixtures --profile local/artifacts/profile.json \
    --out local/fixtures/export.csv --rows 1500 --fake
```

Expected: `wrote local/fixtures/export.csv (1500 rows)`.

This uses `--fake`, so the German is stub text and the file proves the pipeline only.

Then generate the fixture we actually ship, against the model on the H100. Check the box
is free first — `./infra/fairuse/gpu-fairuse2.sh check` — and serve a ~32 GB instruct
model with vLLM and `--disable-log-requests`:

```bash
uv run python -m fixtures --profile local/artifacts/profile.json \\
    --out local/fixtures/export.csv --rows 1500 \\
    --base-url http://localhost:8000 --model Qwen/Qwen2.5-32B-Instruct
```

Only this file can satisfy `test_the_generated_fixture_profiles_like_the_real_corpus`,
because cluster bands need real prose. It stays uncommitted until the Window B gate is
green.

- [ ] **Step 4: Run everything**

Run: `make test && make lint`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_fixture_end_to_end.py
git commit -m "test(fixtures): the fixture must profile like the real corpus

The strongest check available costs nothing new: run the corpus profiler over the fixture
and compare band shares, customData envelope detection and field presence to the real
artifact. A drift means the planner is wrong, not that the tolerance is.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Milestone acceptance

- [ ] `make test lint` green
- [ ] `uv run python -m fixtures --profile local/artifacts/profile.json --out local/fixtures/export.csv --rows 1500 --fake` writes 1,500 rows
- [ ] `verify.check` returns no problems
- [ ] the fixture profiles like the real corpus within the design doc's tolerances
- [ ] `customData` in the fixture is double-encoded and `detect_envelope` identifies it
- [ ] no prompt contains a corpus string

## Not in this plan

The Window B leakage gate. Its nearest-neighbour threshold is calibrated against a
synthetic-vs-synthetic baseline measured in the same window, which cannot be written
before a fixture exists. It gets its own plan, and until it is green the fixture is
**not** committed to git.

The real German fixture also waits on the H100: `--fake` proves the pipeline, the model
produces the corpus we actually ship.
