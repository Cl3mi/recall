# M2 Finding 3 — Joint Null Masks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `customData` missingness correlated the way the real corpus's is, so the fixture contains handover forms — closing the last open M2 finding and `PROJECT_BRIEF.md` §8's *joint null-mask patterns* requirement.

**Architecture:** No new modules and no new profiling. The planner already reads every field's `present_count`; it now groups fields that share one into a **block**. The renderer assigns a block to rows as a unit rather than field by field, seats it on the largest near-duplicate group, and keeps the remaining fields off those rows. The verifier checks both properties structurally, with no tolerance, because they are exact facts rather than distributions.

**Tech Stack:** Python 3.12, uv, pytest, ruff. No LLM, no network, no GPU, no airlock window.

---

## Data handling rules

**Never read anything under `local/quarantine/` or the client working directory.** `local/artifacts/profile.json` IS readable — it passed `blessing.unblessed` with zero findings, and every number in this plan came from it.

**A session hook rejects any Bash command whose text contains `.csv`.** Do not work around it with globs, variables, a different output filename or any other obfuscation. The CLI's `--out` path ends in `.csv`, so drive it through pytest as the existing tests do.

**Do not generate a fixture and do not commit anything under `local/`** as part of this plan. Generation is the step after it.

## The rule about failing tests

**If a test fails and you believe the test is wrong, STOP and report it rather than adjusting the test. On this project a failing test has been right and the plan wrong nine times. The tests encode intent; the implementation bends.**

Every task here adds tests. Two tasks change a function signature, and the mechanical call-site updates that follow are written out verbatim. Nothing else about an existing test may change. Any other failing test is a finding: stop, report it, do not touch it.

## What was measured

From `local/artifacts/profile.json`, tens of thousands of real tickets:

- **Exactly 21 emitted fields share one `present_count`** (about 16% of tickets). Every other emitted field has a distinct count (`ansprechpartner-tel` and `ansprechpartner` in most tickets, `baugruppe`, `fehlercode` and `operations` in a minority). So the block is *derived* from the profile by grouping on `present_count`, not hard-coded.
- **`records_per_row_quantiles`: a median of about 3, and p90 through p999 all at exactly 21 (max a little higher).** That is only possible if the form rows carry the 21 form fields and essentially nothing else — if they also carried `ansprechpartner`, p95 and p99 would exceed 21.
- **The arithmetic agrees.** The form rows carry 21 descriptors each; the other five fields spread over the remaining rows at a mean of a few descriptors per row, and all five fit inside those non-form rows (the largest is a little under the non-form row count). Disjointness is arithmetically possible and is the only arrangement consistent with the quantiles.
- **The cluster is the form.** Roughly 80% of the form carriers are the largest near-duplicate group. Every cluster member carries the form; a minority of form carriers sit outside it.

Simulated at 1,500 rows, against the real quantiles (real figures rounded or omitted):

| | p50 | p75 | p90 | p95 | p99 | max | rows ≥21 |
|---|---:|---:|---:|---:|---:|---:|---:|
| real corpus | ~3 | ~4 | **21** | **21** | **21** | a little over 21 | — |
| today | 5 | 7 | 8 | 9 | 10 | 13 | **0** |
| joint block only | 2 | 3 | 23 | 23 | 25 | 26 | ~240 |
| **joint + disjoint (this plan)** | **3** | 3 | **21** | **21** | **21** | 21 | ~240 |

**This plan's Task 1 and Task 2 code was run against the real profile before the plan was
handed over**, not just simulated in the abstract. On seeds 7, 1 and 42 it produced
identical results: block sizes `[21, 1, 1, 1, 1, 1]`, the quantiles in the last row above,
the expected number of form rows, every member of the largest group carrying the form, and **every field's
presence share still exact**. So the expected numbers in the steps below are measured, not
predicted. If an implementation of these steps produces something else, the implementation
differs from the plan — check it before changing any target.

## What this plan will still not fix

The two remaining residuals are the same cause and it is not reachable from here: the profile emits only about half of the distinct fields, the rest **suppressed** by the presence floor and the entity sweep. Those unnamed fields are what carry real rows from 21 descriptors up to the real max, and what lifts p75 slightly. Reproducing them would mean inventing field names that no measurement supports. Left alone deliberately; `max` is a design-doc target that the fixture will miss at 21 against a somewhat higher real value, and that is the honest number to report rather than to manufacture.

## Pre-flight

```bash
cd <repo-root>
git status --short && git log --oneline -1
make test && make lint
```

Expected: clean tree on `feat/m2-fixture-generator` at `a261db1`, `252 passed, 2 skipped, 2 xfailed`, ruff silent.

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `fixtures/plan.py` | groups fields sharing a `present_count` into a block | 1 |
| `fixtures/render.py` | assigns a block as a unit, seats it on the largest group, keeps other fields off it | 2 |
| `fixtures/__main__.py` | passes the group assignment to the renderer | 3 |
| `fixtures/verify.py` | checks all-or-nothing and cluster seating, structurally | 4 |

---

### Task 1: The planner groups fields that share a presence count

**Files:**
- Modify: `fixtures/plan.py` — `CustomField`, `plan()`
- Test: `tests/unit/test_fixture_plan.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_plan.py`:

```python
def test_fields_sharing_a_presence_count_are_one_block():
    """21 real fields share one present_count exactly - they are one form, filled
    all-or-nothing. Assigning each an independent row subset gave a fixture whose p90 was
    8 descriptors against a real 21, and in which no row was a handover form at all."""
    profile = _full_profile()
    profile["custom_data"]["envelope"]["fields"] = [
        {"name": "warrantyPdf", "present_count": 2500, "kind": "short_text", "value_shapes": []},
        {"name": "checklist", "present_count": 2500, "kind": "short_text", "value_shapes": []},
        {"name": "fehlercode", "present_count": 2800, "kind": "identifier_like",
         "value_shapes": [{"shape": "DDDD-D", "count": 100}]},
    ]
    result = plan_mod.plan(profile, rows=1500, seed=7)
    blocks = {f.name: f.block for f in result.custom_fields}
    assert blocks["warrantyPdf"] == blocks["checklist"], "one form, one block"
    assert blocks["fehlercode"] != blocks["warrantyPdf"], "a distinct count is its own block"


def test_a_field_with_a_unique_presence_count_is_its_own_block():
    result = plan_mod.plan(_full_profile(), rows=1500, seed=7)
    blocks = [f.block for f in result.custom_fields]
    assert len(set(blocks)) == len(blocks), "no two fields here share a presence count"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_fixture_plan.py -q`
Expected: FAIL — `CustomField` has no attribute `block`.

- [ ] **Step 3: Add the block id**

In `fixtures/plan.py`, add the field to `CustomField` (last, so existing positional construction in tests is untouched):

```python
@dataclass(frozen=True)
class CustomField:
    """One customData field the client records, and how to synthesise its values."""

    name: str
    kind: str
    share: float
    shape_mix: list[tuple[str, float]]  # (shape, weight); weights sum to 1.0
    # Fields filled by the same form share a block. 21 real fields share present_count
    # one count exactly; they are one handover form, present or absent together, and that
    # correlation is the structural cause of the corpus's largest near-duplicate group.
    block: int = 0
```

In `plan()`, replace the `fields = []` loop's `fields.append(...)` call so the block id is derived from the presence count. The loop becomes:

```python
    fields = []
    block_ids: dict[int, int] = {}
    for field in profile.get("custom_data", {}).get("envelope", {}).get("fields", []):
        shapes = field.get("value_shapes", [])
        total = sum(s["count"] for s in shapes)
        present = field["present_count"]
        block_ids.setdefault(present, len(block_ids))
        fields.append(
            CustomField(
                name=field["name"],
                kind=field["kind"],
                share=present / real_rows,
                shape_mix=[(s["shape"], s["count"] / total) for s in shapes] if total else [],
                block=block_ids[present],
            )
        )
```

- [ ] **Step 4: Run the plan tests**

Run: `uv run pytest tests/unit/test_fixture_plan.py -q`
Expected: PASS. Report the count.

- [ ] **Step 5: Check it against the real profile**

Run:
```bash
uv run python -c "
import json, pathlib, sys; sys.path.insert(0,'.')
from collections import Counter
from fixtures.plan import plan
p = json.loads(pathlib.Path('local/artifacts/profile.json').read_text())
sizes = Counter(f.block for f in plan(p, 1500, 7).custom_fields)
print('block sizes:', sorted(sizes.values(), reverse=True))"
```
Expected exactly: `block sizes: [21, 1, 1, 1, 1, 1]`

- [ ] **Step 6: Full suite and lint**

Run: `make test && make lint`
Expected: `254 passed, 2 skipped, 2 xfailed`, ruff silent.

- [ ] **Step 7: Commit**

```bash
git add fixtures/plan.py tests/unit/test_fixture_plan.py
git commit -F - <<'MSG'
feat(fixtures): group customData fields that share a presence count

<write a real body: 21 fields share one present_count, they are one form, and
the planner now says so instead of leaving the renderer to treat them as 21
unrelated coincidences>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: A block is assigned as a unit, and seated on the largest group

**Files:**
- Modify: `fixtures/render.py` — `custom_fields_for_rows`
- Test: `tests/unit/test_fixture_render.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_render.py`:

```python
def test_a_block_is_present_all_or_nothing():
    """Independent subsets per field gave every row a few form fields and no row a whole
    form. The real form is filled by one action: 21 fields or none."""
    from fixtures.plan import CustomField

    fields = [
        CustomField("warrantyPdf", "short_text", 0.16, [("Aaaa", 1.0)], block=1),
        CustomField("checklist", "short_text", 0.16, [("Aaaa", 1.0)], block=1),
        CustomField("equipmentScope", "short_text", 0.16, [("Aaaa", 1.0)], block=1),
    ]
    per_row = render.custom_fields_for_rows(fields, 1000, random.Random(4))
    sizes = {len(row) for row in per_row}
    assert sizes == {0, 3}, f"a row carries the whole form or none of it, got {sizes}"
    assert sum(1 for row in per_row if row) == round(0.16 * 1000)


def test_the_form_is_seated_on_the_largest_group():
    """Most real form carriers ARE the largest near-duplicate group: the
    cluster is a form, not a fault. A form scattered over unrelated rows would reproduce
    the share and destroy the reason the cluster exists."""
    from fixtures.plan import CustomField

    fields = [
        CustomField("warrantyPdf", "short_text", 0.16, [("Aaaa", 1.0)], block=1),
        CustomField("checklist", "short_text", 0.16, [("Aaaa", 1.0)], block=1),
    ]
    groups = [0] * 100 + list(range(1, 901))  # one group of 100, then singletons
    per_row = render.custom_fields_for_rows(fields, 1000, random.Random(4), groups)
    assert all(per_row[i] for i in range(100)), "every cluster member carries the form"
    assert sum(1 for row in per_row if row) == round(0.16 * 1000)


def test_other_fields_keep_off_the_form_rows():
    """p90 = p95 = p99 = p999 = 21 in the real corpus: the form rows carry the form and
    essentially nothing else. Letting other fields land on them puts p90 at 23."""
    from fixtures.plan import CustomField

    fields = [
        CustomField("warrantyPdf", "short_text", 0.20, [("Aaaa", 1.0)], block=1),
        CustomField("checklist", "short_text", 0.20, [("Aaaa", 1.0)], block=1),
        CustomField("fehlercode", "identifier_like", 0.30, [("DDDD-D", 1.0)], block=2),
    ]
    per_row = render.custom_fields_for_rows(fields, 1000, random.Random(4))
    for row in per_row:
        names = {name for name, _ in row}
        if "warrantyPdf" in names:
            assert "fehlercode" not in names, "a form row carries only the form"


def test_a_field_too_common_to_avoid_the_form_still_gets_its_share():
    """ansprechpartner-tel is in most rows against a ~16% form, so disjointness is a
    preference, not a promise - the share is what must not bend."""
    from fixtures.plan import CustomField

    fields = [
        CustomField("warrantyPdf", "short_text", 0.50, [("Aaaa", 1.0)], block=1),
        CustomField("ansprechpartner", "short_text", 0.90, [("Aa._Laaaaa", 1.0)], block=2),
    ]
    per_row = render.custom_fields_for_rows(fields, 1000, random.Random(4))
    carriers = sum(1 for row in per_row if any(n == "ansprechpartner" for n, _ in row))
    assert carriers == 900
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_fixture_render.py -q`
Expected: FAIL — `test_a_block_is_present_all_or_nothing` sees sizes like `{0, 1, 2, 3}`, and `custom_fields_for_rows` takes 3 positional arguments.

- [ ] **Step 3: Implement block assignment**

In `fixtures/render.py`, replace `custom_fields_for_rows` entirely with:

```python
def custom_fields_for_rows(
    fields: list[CustomField],
    rows: int,
    rng: random.Random,
    groups: list[int] | None = None,
) -> list[list[tuple[str, str]]]:
    """Which fields each ticket carries, at exactly the measured share.

    Deciding each field independently per row reproduces a share only in expectation. At
    1,500 rows the standard error on a ~16% field is ~0.9 points against a +/-2.0 point
    acceptance tolerance, and across all the emitted fields that breached on most measured seeds -
    so the committed fixture would have depended on a lucky number. Assigning exactly
    round(share * rows) rows per field makes the share exact and seed-independent.

    Fields are assigned in plan order, so a row's descriptors keep the profile's ordering.

    The same holds for the SHAPE each value takes: shapes are allocated by largest
    remainder over the measured mix and shuffled, not drawn per row, so the mix is
    exact on any seed.

    Fields sharing a block are one form and move together - 21 real fields share
    one present_count, and treating them as 21 independent coincidences gave a fixture
    whose p90 was 8 descriptors against a real 21, with no row carrying a whole form. A
    multi-field block is seated on the largest near-duplicate group first, because in the
    real corpus that cluster IS the form: most of its carriers are the group.
    Remaining fields then avoid the form's rows where their own share allows, which is
    what puts p90, p95 and p99 all at exactly 21, as measured.
    """
    per_row: list[list[tuple[str, str]]] = [[] for _ in range(rows)]
    blocks: dict[int, list[CustomField]] = defaultdict(list)
    for field in fields:
        blocks[field.block].append(field)

    # Forms first, so single fields know which rows to avoid.
    ordered = sorted(blocks.values(), key=lambda block: len(block), reverse=True)
    form_rows: set[int] = set()
    for block in ordered:
        count = round(block[0].share * rows)
        if len(block) > 1:
            indices = _seat_on_largest_group(count, rows, rng, groups)
            form_rows |= set(indices)
        else:
            free = [index for index in range(rows) if index not in form_rows]
            if count <= len(free):
                indices = rng.sample(free, count)
            else:  # commoner than the form; disjointness is a preference, the share is not
                taken = [index for index in range(rows) if index in form_rows]
                indices = free + rng.sample(taken, count - len(free))
        for field in block:
            shapes = _allocate(field.shape_mix, len(indices)) if field.shape_mix else []
            rng.shuffle(shapes)
            for offset, index in enumerate(indices):
                value = values.from_shape(shapes[offset], rng) if shapes else ""
                per_row[index].append((field.name, value))
    return per_row


def _seat_on_largest_group(
    count: int, rows: int, rng: random.Random, groups: list[int] | None
) -> list[int]:
    """The form's rows: every member of the largest near-duplicate group, then others.

    All members of the real largest group carry the form and a minority of further rows
    do too. Seating the form anywhere else reproduces its share while destroying the reason
    the cluster exists, which is the one thing the near-duplicate pipeline is built on.
    """
    seats: list[int] = []
    if groups:
        largest = Counter(groups).most_common(1)[0][0]
        seats = [index for index, group in enumerate(groups) if group == largest][:count]
    rest = [index for index in range(rows) if index not in set(seats)]
    return seats + rng.sample(rest, count - len(seats))
```

Add the imports this needs at the top of `fixtures/render.py`, alongside the existing ones:

```python
from collections import Counter, defaultdict
```

- [ ] **Step 4: Run the render tests**

Run: `uv run pytest tests/unit/test_fixture_render.py -q`
Expected: PASS. `test_fields_are_present_in_exactly_their_measured_share_of_rows`, `test_exact_shares_do_not_depend_on_the_seed` and `test_shape_counts_are_exact_on_every_seed` must all still pass untouched — every field's share is still exact.

- [ ] **Step 5: Full suite and lint**

Run: `make test && make lint`
Expected: `258 passed, 2 skipped, 2 xfailed`, ruff silent.

- [ ] **Step 6: Commit**

```bash
git add fixtures/render.py tests/unit/test_fixture_render.py
git commit -F - <<'MSG'
feat(fixtures): a form is filled all at once, on the cluster that is the form

<write a real body: what all-or-nothing means, why the form is seated on the
largest group, and why disjointness is a preference that yields to the share>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: The CLI tells the renderer where the cluster is

**Files:**
- Modify: `fixtures/__main__.py`
- Test: `tests/integration/test_fixture_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_fixture_end_to_end.py`:

```python
@pytest.mark.skipif(not ROUND_THREE.exists(), reason="round-3 artifact not present")
def test_the_fixture_contains_handover_forms(tmp_path):
    """Finding 3: 21 real fields share one present_count and are one form. The fixture
    used to assign each an independent row subset, so p90 was 8 descriptors against a
    real 21 and NO row was a handover form. The real quantiles put p90 through p999 at
    exactly 21."""
    from fixtures.__main__ import main
    from profiler.stats import customdata

    out = tmp_path / "export.csv"
    assert main(["--profile", str(ROUND_THREE), "--out", str(out), "--rows", "1500",
                 "--fake", "--cache", str(tmp_path / "cache")]) == 0

    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    counts = [len(customdata.parse_records(row["customData"]) or []) for row in rows]

    form_rows = [n for n in counts if n >= 21]
    form_share = 0.16  # (real figure omitted) rounded; the exact share comes from the profile
    assert abs(len(form_rows) - round(form_share * 1500)) <= 5, "about 16% of rows carry the form"
    assert set(form_rows) == {21}, "a form row carries the form and nothing else"

    ordered = sorted(counts)
    assert ordered[int(0.90 * len(ordered))] == 21, "p90 is the form, as measured"
    assert ordered[len(ordered) // 2] <= 4, "p50 stays where the real corpus has it"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_fixture_end_to_end.py -q`
Expected: FAIL — no row carries 21 descriptors, because the CLI does not pass `groups` and the renderer seats the form at random.

- [ ] **Step 3: Pass the group assignment**

In `fixtures/__main__.py`, the `custom_by_row = ...` line currently reads:

```python
    custom_by_row = render.custom_fields_for_rows(fixture_plan.custom_fields, len(tickets), rng)
```

Replace it with:

```python
    custom_by_row = render.custom_fields_for_rows(
        fixture_plan.custom_fields, len(tickets), rng, [ticket.group for ticket in tickets]
    )
```

- [ ] **Step 4: Run the integration tests**

Run: `uv run pytest tests/integration/test_fixture_end_to_end.py -q`
Expected: PASS, including the 200-row smoke run and the year-by-year test.

- [ ] **Step 5: Full suite and lint**

Run: `make test && make lint`
Expected: `259 passed, 2 skipped, 2 xfailed`, ruff silent.

- [ ] **Step 6: Commit**

```bash
git add fixtures/__main__.py tests/integration/test_fixture_end_to_end.py
git commit -F - <<'MSG'
fix(fixtures): seat the handover form on the cluster it explains

<write a real body: the renderer cannot seat the form on the cluster without
being told which rows the cluster holds>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: `verify` refuses a fixture whose form fell apart

**Files:**
- Modify: `fixtures/verify.py`
- Test: `tests/unit/test_fixture_verify.py`

These two checks carry no tolerance. They are exact structural facts: a form is filled by one action, and the cluster is the form. A tolerance on either would be a tolerance on whether the fixture has the property at all.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_verify.py`:

```python
def _block_plan(**overrides) -> FixturePlan:
    base = dict(
        rows=10, seed=1, group_sizes=[4, 1, 1, 1, 1, 1, 1], solutions_fill=1.0,
        fill_by_year={},
        custom_fields=[
            CustomField("warrantyPdf", "short_text", 0.4, [("Aaaa", 1.0)], block=1),
            CustomField("checklist", "short_text", 0.4, [("Aaaa", 1.0)], block=1),
        ],
    )
    base.update(overrides)
    return FixturePlan(**base)


def test_verify_reports_a_form_that_is_only_half_filled():
    """A form is filled by one action. Half a form is not a form, and a fixture full of
    them reproduces every field share while containing no handover form at all."""
    fixture_plan = _block_plan()
    groups = [0] * 4 + list(range(1, 7))
    rows = _rows(4, [("warrantyPdf", "Abcd")]) + _rows(6)  # checklist missing
    problems = verify.check(rows, fixture_plan, groups)
    assert any("half-filled" in p for p in problems)


def test_verify_accepts_a_whole_form():
    fixture_plan = _block_plan()
    groups = [0] * 4 + list(range(1, 7))
    rows = _rows(4, [("warrantyPdf", "Abcd"), ("checklist", "Efgh")]) + _rows(6)
    assert verify.check(rows, fixture_plan, groups) == []


def test_verify_reports_a_form_that_missed_the_cluster():
    """Most real form carriers ARE the largest group. A form seated elsewhere
    keeps every share and loses the reason the cluster exists."""
    fixture_plan = _block_plan()
    groups = [0] * 4 + list(range(1, 7))
    rows = _rows(6) + _rows(4, [("warrantyPdf", "Abcd"), ("checklist", "Efgh")])
    problems = verify.check(rows, fixture_plan, groups)
    assert any("largest group" in p for p in problems)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_fixture_verify.py -q`
Expected: FAIL — no problem reported for either the half-filled form or the misplaced one.

- [ ] **Step 3: Implement both checks**

In `fixtures/verify.py`, append before `return problems`:

```python
    by_block: dict[int, list[str]] = defaultdict(list)
    for field in plan.custom_fields:
        by_block[field.block].append(field.name)

    for block, names in by_block.items():
        if len(names) < 2:
            continue
        carried = [{name for name in names if name in row_names} for row_names in per_row_names]
        broken = sum(1 for held in carried if held and len(held) != len(names))
        if broken:
            problems.append(
                f"block {block} is half-filled in {broken} rows: a form of "
                f"{len(names)} fields ({', '.join(sorted(names)[:3])}...) is filled by "
                f"one action, so a row carries all of it or none"
            )
        if len(groups) == len(rows):
            largest = Counter(groups).most_common(1)[0][0]
            missing = sum(
                1
                for index, group in enumerate(groups)
                if group == largest and not carried[index]
            )
            if missing:
                problems.append(
                    f"block {block} is absent from {missing} rows of the largest group; "
                    f"in the real corpus that cluster IS the form - most of its "
                    f"carriers are the group"
                )
```

This needs the set of field names each row carries. The row loop already parses every row's `customData`; collect the names there. Immediately after `shapes[name][shape_of(value)] += 1` in that loop, the loop body should also build `per_row_names`. Declare it beside `present`:

```python
    per_row_names: list[set[str]] = []
```

and append to it inside the loop — once per row, including for unparsable rows so the indices stay aligned with `rows` and `groups`:

```python
        records = customdata.parse_records(row.get("customData"))
        if records is None:
            unparsed += 1
            per_row_names.append(set())
            continue
```

and after the two inner `for` loops over `records`:

```python
        per_row_names.append({r.get("key") for r in records if isinstance(r.get("key"), str)})
```

- [ ] **Step 4: Run the verify tests**

Run: `uv run pytest tests/unit/test_fixture_verify.py -q`
Expected: PASS. Report the count.

- [ ] **Step 5: Run everything**

Run: `make test && make lint`
Expected: `262 passed, 2 skipped, 2 xfailed`, ruff silent.

- [ ] **Step 6: Commit**

```bash
git add fixtures/verify.py tests/unit/test_fixture_verify.py
git commit -F - <<'MSG'
feat(fixtures): verify the form is whole and sits on its cluster

<write a real body: why neither check has a tolerance>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

## After the last task

- [ ] `make test && make lint` green, tree clean, 4 commits.
- [ ] Confirm the measured quantiles against the real corpus, with no `.csv` in the command — run the integration test and read its assertions, or compute from a pytest-driven run.
- [ ] Update `docs/STATE.md`: finding 3 closed, with the quantiles it reached (p50 about 3, p90, p95 and p99 at 21) and the two residuals it did not (p75 slightly low, max 21 against a somewhat higher real value, both caused by the suppressed fields).
- [ ] **Then generation**, which is a separate act with its own preconditions: `./infra/fairuse/gpu-fairuse2.sh check` first, ~32 GB instruct model under vLLM on `hpc`, confirm the run wrote under `local/fixtures/cache/vllm-*` rather than reading `fake-seed-*`, read the padding WARNING, then `verify`.
