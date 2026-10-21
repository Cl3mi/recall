# Insight window, Plan 1 — the deterministic report and its release guard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m insight` reads the 38-column export and writes a `report.json` an AI may read: where tickets come from (Baugruppe, vehicles, titles), plus model-free evidence about the text, with every released value floored, entity-swept and checked by a guard that refuses to write on any doubt.

**Architecture:** A new top-level `insight/` package beside `profiler/`. Section builders return plain dicts; every released string goes through one shared function (`insight.release`) that applies the floor and the per-field entity sweep, and an independent walker (`insight.guard`) re-checks the finished report using that same function. The CLI reuses `profiler.safety` so errors carry a code and a schema path, never a value.

**Tech Stack:** Python 3.12, stdlib `csv`/`json`, `datasketch` (via `profiler.stats.clusters`), existing `profiler.*` and `recall.*` helpers. No model, no GPU, no network.

**Spec:** `docs/superpowers/specs/2026-10-11-insight-window-report-design.md`. This plan is stage 1 only. See "Follow-on plans" at the end.

## Read this before touching anything

- **Never read `local/quarantine/` or `<export-dir>/`.** Real data stays inside manual, AI-free windows. Everything here runs against a synthetic stand-in built in `tmp_path`.
- **A harness hook rejects any Bash command containing `.csv`.** Drive the CLI through pytest, with the path inside the Python test file, exactly as the committed integration tests do. Do not evade the hook.
- **`uv` is gone.** Use `.venv/bin/python -m pytest` and `.venv/bin/ruff`.
- **Commit trailer.** Every commit in this plan ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Two measured facts the design rests on

1. **The full entity sweep cannot be applied to product codes.** `entities.looks_like_entity` flags `B-10`, `TX-2210` and `SN2000` (the plate heuristic matches them), while `looks_like_named_entity` flags none of them and still flags `Huber GmbH` and `bauer`. Probing each pattern separately showed that **only the plate pattern** collides with product codes; the e-mail, phone and IBAN patterns hit none of them. This is the conflict `profiler.selfcheck.PRODUCT_DIMENSION_COLUMNS` documents for `vehicleModelId` and two other columns. So each released field names its own sweep (`insight/release.py`): code fields (Baugruppe, model, serial prefix) get everything `looks_like_entity` checks **except the plate shape**, and free-text tokens get the full sweep plus the profiler's identifier-like rule. An early draft gave code fields the name half only, which also dropped the e-mail, phone and IBAN checks; code review caught that.
2. **Baugruppe is sparse.** It lives in the `customData` envelope and the profile records it on about a quarter of the rows. Every Baugruppe section therefore carries a `coverage` block, so no reader mistakes it for the whole corpus.

## Decisions the operator must still make (flagged, not taken)

- **Serial prefix buckets loosen an existing control.** `vehicleSerialNo` is on `profiler.selfcheck.DENYLISTED_COLUMNS` ("no value is ever emitted, at any frequency"). This plan **does not touch that list**. Prefix buckets are behind `--serial-prefixes`, **off by default**, and `insight` never imports the denylist. The operator decides whether the real window passes the flag.
- **`insight.guard` is a new gate beside `profiler.blessing`**, because `blessing.unblessed` is bound to `profiler/schema.json` and to module-level path lists. Extending it would change a safety control. The guard applies the same discipline: every dict key declared, every string accounted for.

## File structure

| File | Responsibility |
|---|---|
| `insight/__init__.py` | Package marker. |
| `insight/release.py` | The floor `K`, the per-field entity sweeps, `release()` and `flagged()`. The single definition of "may this value leave". |
| `insight/measures.py` | `ratio`, `coverage`, `gini`, `top_share`. Pure arithmetic, no strings. |
| `insight/extract.py` | `Ticket`, `read_rows`, `custom_field`, `tickets`. The only place that touches raw rows. |
| `insight/origin.py` | `baugruppe`, `vehicles`, `prefixes`, `titles`. Spec section 1. |
| `insight/crosstab.py` | `baugruppe_model_year`. Floors every cell, not only the margins. |
| `insight/texts.py` | Model-free evidence: lengths, identifier density, repetition share. |
| `insight/guard.py` | `KEYS`, `unaccounted`, `assert_safe`. Independent re-check of the finished report. |
| `insight/report.py` | `build()`: sections, suppression ledger, guard. |
| `insight/__main__.py` | CLI: arguments, source facts, exit codes, atomic write after the guard. |
| `tests/insight_standin.py` | Synthetic export with planted leaks and an exactly-known answer. |
| `tests/unit/test_insight_*.py` | One file per module above. |
| `tests/integration/test_insight_report.py`, `test_insight_cli.py` | End to end on the stand-in. |

---

### Task 1: Amend the spec, register the package

**Files:**
- Modify: `docs/superpowers/specs/2026-10-11-insight-window-report-design.md` (append)
- Modify: `pyproject.toml:35`

- [ ] **Step 1: Append the planning amendments to the spec**

```bash
cat >> docs/superpowers/specs/2026-10-11-insight-window-report-design.md <<'EOF'

## Amendments from planning (2026-10-11)

Found while writing Plan 1, against the code rather than the brainstorm.

1. **Titles release floored tokens and bigrams, not "shape-normalised templates".** Window A v2
   already rules "never shape prose"; a title is prose.
2. **Serial prefix buckets are opt-in** (`--serial-prefixes`, default off) and need an operator
   ruling before a real window passes the flag, because `vehicleSerialNo` is on
   `profiler.selfcheck.DENYLISTED_COLUMNS` ("no value emitted at any frequency"). A bucket never
   releases more than half of any serial it covers, never more than 8 characters, and is
   floored on distinct VEHICLES rather than tickets, so one vehicle with many tickets cannot
   form a bucket on its own.
3. **`report.json` is checked by `insight.guard`, not `profiler.blessing`.** `blessing.unblessed`
   is bound to `profiler/schema.json` and to module-level path lists, so extending it would
   change a safety control. The guard applies the same rule: every dict key declared, every
   string accounted for, every released value at or above `k` and swept.
4. **The entity sweep is per released field.** `looks_like_entity` flags product codes such as
   `B-10` and `TX-2210` through its licence-plate pattern alone. Baugruppe, model and
   serial-prefix values therefore get every check except the plate shape (company suffixes,
   surnames, e-mail, phone and IBAN still apply), the narrower sibling of the exemption
   `PRODUCT_DIMENSION_COLUMNS` documents for `vehicleModelId`. Free-text tokens also withhold
   any part that carries a digit and is longer than six characters, mirroring the
   identifier-like rule `selfcheck` applies to dimension-hint tokens.
5. **Baugruppe covers about a quarter of tickets** (per the profile), so every
   Baugruppe section carries a coverage block.
6. **Plan split.** Plan 1 is the deterministic stage with no model. Stage 2 (clusters, labels,
   review, coverage and ablation evidence) and the window itself are separate plans.
7. **Token lengths in plan 1 are whitespace tokens, labelled as such.** The e5 truncation share
   needs the tokenizer and belongs to stage 2.
8. **Floors count tickets or vehicles depending on what is released.** Serial prefix buckets
   count distinct vehicles, because the released string is part of an identifier. Cross-tab
   cells count tickets, because no component of a cell is a serial and a cell describes a model
   line and a year. A distinct-vehicle floor of `k` there would suppress most real cells.
9. **Cells and values under the floor are withheld and tallied, not folded into `other`.** The
   report states how many distinct values and rows were withheld per reason, as numbers only.
10. **Accepted residuals at `k = 50`.** Margins, cells and the withheld tally are all published,
    so when exactly one cell of a margin is withheld a reader can subtract to learn its count,
    which is some number below `k` about a product line and not personal data.
    `tickets_per_serial_quantiles.max` is an unfloored count that identifies nothing. Equal
    counts are ordered by key, so the report does not depend on the row order of the export.
11. **Identifier density is measured raw and after cleaning.** The cleaning pipeline's phone
    pattern redacts a part number such as `1234.56789`, which is what the part-number pattern
    matches, so the cleaned text a RAG index would hold has lost it. Reporting `tickets` beside
    `tickets_after_cleaning` turns that loss into a number and is itself a data-quality finding.
    Blank problem texts are excluded from clustering and counted, and the largest cluster's
    share is withheld when that cluster is smaller than the floor.
12. **The guard refuses anything it was not told about.** Every key is declared, every string is
    accounted for by path and shape and matched in full, every value must be a JSON leaf, dict
    or list (a tuple would be written as an unexamined list), and the root must be a dict. A
    code field also withholds a value over 16 characters that carries a digit, which is what a
    VIN or serial typed into a free-ish field looks like. Provenance arguments are validated
    before any data is read, so a bad value costs nothing. Known limit, inherited and not
    introduced: `profiler.entities` knows company suffixes, common surnames and contact shapes,
    so an uncommon lowercase name that clears the floor of 50 would pass a free-text token
    sweep; the floor is what bounds it.
13. **`report.build` isolates its inputs, and clustering is canonical.** It deep-copies `source`
    and `provenance`, accepts exactly the expected keys, checks `row_count` against the rows and
    computes the provenance fields it owns, so a caller cannot alias or override what was
    guarded.
    Documents are sorted before the near-duplicate clustering, which is greedy and otherwise
    order-dependent on chains of overlapping texts, so the whole report is a function of the
    set of rows and not of their order.
14. **The CLI cannot destroy the input or leave a misleading report.** It refuses `--out` equal
    to the input under any spelling, symlink or hardlink; removes any stale report before
    anything else; writes under a temporary name and moves it into place; aborts when required
    columns are missing (printing only a count) instead of emitting an all-zero report; replies
    to argument errors with a fixed code that never echoes the value; and refuses a floor below
    the release floor unless `--allow-weak-floor` is passed.
EOF
```

- [ ] **Step 2: Register `insight` in the wheel's package list**

In `pyproject.toml` change:

```toml
packages = ["src/recall", "profiler", "fixtures"]
```

to:

```toml
packages = ["src/recall", "profiler", "fixtures", "insight"]
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-11-insight-window-report-design.md pyproject.toml
git commit -m "docs(insight): amend the spec with what planning found in the code" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The release rule and the arithmetic helpers

**Files:**
- Create: `insight/__init__.py`, `insight/release.py`, `insight/measures.py`
- Test: `tests/unit/test_insight_release.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_insight_release.py`:

```python
from collections import Counter

import pytest

from insight import measures, release
from profiler import entities

# Shapes a code field (Baugruppe, model, serial prefix) must never release.
CONTACTS = [
    "a@b.de",
    "hans.huber@x.de",
    "+49 170 1234567",
    "0171 1234567",
    "DE89370400440532013000",
]
# Product and assembly codes it must keep: they have a licence plate's shape and nothing else.
CODES = ["B-10", "B-20", "TX-2210", "LR-45", "SN2000", "SER0", "TX22-"]


def test_the_floor_is_the_profilers_floor():
    assert release.K == 50


def test_release_keeps_exactly_k_and_counts_what_it_withholds():
    kept, withheld = release.release(Counter({"a": 60, "b": 50, "c": 49, "d": 1}), "value", 50)
    assert kept == [("a", 60), ("b", 50)]
    assert withheld["below_floor"] == {"distinct": 2, "rows": 50}
    assert withheld["entity_like"] == {"distinct": 0, "rows": 0}


def test_a_frequent_name_is_withheld_not_released():
    counts = Counter({"Huber GmbH": 60, "B-10": 60})
    kept, withheld = release.release(counts, "value", 50)
    assert kept == [("B-10", 60)]
    assert withheld["entity_like"] == {"distinct": 1, "rows": 60}


def test_a_frequent_surname_token_is_withheld():
    kept, withheld = release.release(Counter({"bauer": 60, "pumpe": 80}), "token", 50)
    assert kept == [("pumpe", 80)]
    assert withheld["entity_like"]["distinct"] == 1


def test_product_codes_survive_the_value_sweep_but_not_the_token_sweep():
    """Measured, not assumed: looks_like_entity flags B-10 and TX-2210 (the plate heuristic
    cannot tell them from a licence plate). Each field therefore names its own sweep."""
    assert not release.flagged("value", "B-10")
    assert not release.flagged("model", "TX-2210")
    assert release.flagged("token", "TX-2210")


def test_a_prefix_longer_than_the_cap_is_flagged():
    assert not release.flagged("prefix", "A" * release.MAX_PREFIX)
    assert release.flagged("prefix", "A" * (release.MAX_PREFIX + 1))


def test_cells_are_floored_as_cells_not_only_as_margins():
    """Each margin clears the floor; the smallest cell must not."""
    cells = Counter({("B-10", "TX-2210"): 60, ("B-10", "TX-2240"): 3, ("B-20", "TX-2210"): 3})
    kept, withheld = release.release(cells, ("value", "model"), 50)
    assert kept == [(("B-10", "TX-2210"), 60)]
    assert withheld["below_floor"] == {"distinct": 2, "rows": 6}


def test_a_structural_component_is_not_swept():
    kept, _ = release.release(Counter({("B-10", "2022"): 60}), ("value", None), 50)
    assert kept == [(("B-10", "2022"), 60)]


def test_ratio_is_rounded_and_safe_on_zero():
    assert measures.ratio(1, 3) == 0.3333
    assert measures.ratio(5, 0) == 0.0


def test_coverage_reports_present_total_and_share():
    assert measures.coverage(9, 13) == {"present": 9, "total": 13, "share": 0.6923}


def test_gini_is_zero_for_equal_counts_and_positive_for_skew():
    assert measures.gini([4, 4, 4]) == 0.0
    assert measures.gini([]) == 0.0
    assert measures.gini([5, 3, 1]) == pytest.approx(0.2963, abs=1e-4)


def test_top_share_is_the_leading_slice_over_the_total():
    assert measures.top_share([5, 3, 1], 1, 9) == 0.5556
    assert measures.top_share([5, 3, 1], 5, 9) == 1.0
    assert measures.top_share([], 1, 0) == 0.0


def test_gini_counts_zeros_as_holders_of_nothing():
    assert measures.gini([0, 0, 6]) == pytest.approx(0.6667, abs=1e-4)


def test_the_default_floor_is_applied_when_none_is_passed():
    kept, _ = release.release(Counter({"a": release.K, "b": release.K - 1}), "value")
    assert kept == [("a", release.K)]


@pytest.mark.parametrize("field", ["value", "model", "prefix"])
def test_a_code_field_withholds_contact_shapes_but_keeps_product_codes(field):
    """Review finding: the first version relaxed the whole contact half of the sweep for code
    fields, so an e-mail, phone or IBAN repeated at the floor would have been released from a
    Baugruppe field. Only the licence-plate shape collides with product codes (measured)."""
    for leak in CONTACTS:
        assert release.flagged(field, leak), (field, "contact shape was released")
    for code in CODES:
        assert not release.flagged(field, code), (field, "a product code was withheld")


def test_the_code_sweep_is_looks_like_entity_minus_the_plate_shape():
    """A drift canary. If profiler.entities gains a contact pattern, this disagrees and says so
    instead of the code sweep silently going stale."""
    samples = CONTACTS + CODES + ["Huber GmbH", "bauer", "Hydraulikpumpe", "W-12345A", "A1"]
    for value in samples:
        if entities._PLATE.match(value.strip()):
            continue
        assert release.flagged("value", value) == entities.looks_like_entity(value), value


def test_the_prefix_field_also_withholds_names_and_overlong_prefixes():
    assert release.flagged("prefix", "MEIER")
    assert release.flagged("prefix", "GMBH-")
    assert not release.flagged("prefix", "SER0")
    kept, withheld = release.release(Counter({"MEIER": 60, "SER0": 60, "A" * 9: 60}), "prefix", 50)
    assert kept == [("SER0", 60)]
    assert withheld["entity_like"] == {"distinct": 2, "rows": 120}


def test_models_are_swept_through_release():
    kept, withheld = release.release(Counter({"TX-2210": 60, "Huber GmbH": 60}), "model", 50)
    assert kept == [("TX-2210", 60)]
    assert withheld["entity_like"] == {"distinct": 1, "rows": 60}


def test_a_flagged_component_inside_a_cell_withholds_the_whole_cell():
    cells = Counter({("Huber GmbH", "TX-2210"): 60, ("B-10", "TX-2210"): 60})
    kept, withheld = release.release(cells, ("value", "model"), 50)
    assert kept == [(("B-10", "TX-2210"), 60)]
    assert withheld["entity_like"] == {"distinct": 1, "rows": 60}


def test_a_token_part_that_looks_like_an_identifier_is_withheld():
    """The profiler's own identifier-like rule (a digit, longer than six characters), which the
    profiler only warns about. Applied per whitespace part so a bigram is judged part by part."""
    assert release.flagged("token", "hydraulik1234567")
    assert release.flagged("token", "fehler hydraulik1234567")
    assert not release.flagged("token", "hydraulikpumpe")
    assert not release.flagged("token", "motor startet")


def test_a_structure_error_is_raised_even_when_every_count_is_below_the_floor():
    """Review finding: the check used to run only for keys that cleared the floor, so a
    builder bug hid on a small corpus and surfaced in the real window."""
    with pytest.raises(ValueError, match="component"):
        release.release(Counter({("a", "b"): 1}), ("value",), 50)
    with pytest.raises(KeyError, match="bogus"):
        release.release(Counter({"a": 1}), "bogus", 50)
    with pytest.raises(TypeError, match="str"):
        release.release(Counter({5: 1}), "value", 50)
    with pytest.raises(TypeError, match="str"):
        release.release(Counter({None: 1}), "value", 50)


def test_a_structure_error_message_never_carries_a_value():
    with pytest.raises(TypeError) as raised:
        release.release(Counter({("secret-value", 7): 1}), ("value", "model"), 50)
    assert "secret-value" not in str(raised.value)


def test_a_long_identifier_like_code_is_withheld_from_every_code_field():
    """Review finding: a VIN or serial typed into a Baugruppe field passed, because only the token
    sweep had an identifier-like rule. Product codes are short, so a length cap with a digit is
    cheap. The boundary is exactly MAX_CODE_LENGTH."""
    vin = "WVWZZZ1JZ3W386752"
    at_cap = "A" * (release.MAX_CODE_LENGTH - 1) + "1"
    over_cap = "A" * release.MAX_CODE_LENGTH + "1"
    for field in ("value", "model"):
        assert release.flagged(field, vin)
        assert release.flagged(field, over_cap)
        assert not release.flagged(field, at_cap)
        assert not release.flagged(field, "TX-2210")
    assert not release.flagged("value", "Hydraulikzylinder links")  # long, but no digit


def test_equal_counts_are_ordered_by_key_not_by_arrival():
    forward, _ = release.release(Counter({"a": 3, "b": 3}), "value", 3)
    backward, _ = release.release(Counter({"b": 3, "a": 3}), "value", 3)
    assert forward == backward == [("a", 3), ("b", 3)]
    cells = Counter({("B-20", "2022"): 3, ("B-10", "2022"): 3})
    kept, _ = release.release(cells, ("value", None), 3)
    assert [key for key, _ in kept] == [("B-10", "2022"), ("B-20", "2022")]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_release.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'insight'`.

- [ ] **Step 3: Write the implementation**

Create `insight/__init__.py`:

```python
"""A real-data overview an AI may read: floored, swept, and guarded. See the design spec."""
```

Create `insight/release.py`:

```python
"""One definition of "may this value leave", shared by the builders and the guard.

The M2 renderer and verifier read the same `block_key` for the same reason: a guard with its
own idea of what a builder should have dropped would bless exactly what the builder got
wrong. Builders call `release()`; the guard calls `flagged()`; neither has a private copy.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence

from profiler import entities
from profiler.stats import vocab

# The profiler's own floor, not a copy: a value that is rare in Window A is rare here.
K = vocab.DEFAULT_MIN_FREQUENCY

# A serial prefix never exceeds this, whatever the serials look like.
MAX_PREFIX = 8

# A code field value longer than this that also carries a digit reads as an identifier (a VIN
# or a serial typed into a free-ish field). Product and assembly codes ('B-10', 'TX-2210') are
# far shorter. A false positive only withholds, and the withheld rows are counted.
MAX_CODE_LENGTH = 16

# A token part carrying a digit and longer than this reads as an identifier (a serial, a part
# number). profiler.selfcheck only WARNS on that shape for dimension-hint tokens; here it is a
# withhold, because a new gate should not be more permissive than the one beside it.
IDENTIFIER_LIKE_LENGTH = 6


def _code_flagged(value: str) -> bool:
    """Every check `looks_like_entity` makes EXCEPT the licence-plate shape.

    Measured: the plate pattern matches product and assembly codes ('B-10', 'B-20', 'TX-2210',
    'LR-45', 'SN2000') because they genuinely have a plate's shape, while the e-mail, phone and
    IBAN patterns match none of them. A code field therefore keeps the three contact checks and
    the name checks and relaxes only the plate. profiler.selfcheck.PRODUCT_DIMENSION_COLUMNS
    documents the same relaxation for vehicleModelId, vehicleStatus and subStatusString.
    Baugruppe is NOT in that set; the reasoning is applied to it here on purpose, and more
    narrowly than "name half only", which would also have dropped the contact checks.
    """
    raw = value.strip()
    if len(raw) > MAX_CODE_LENGTH and any(c.isdigit() for c in raw):
        return True
    contact = (entities._EMAIL, entities._PHONE, entities._IBAN)
    if any(pattern.match(raw) for pattern in contact):
        return True
    return entities.looks_like_named_entity(value)


def _prefix_flagged(value: str) -> bool:
    return len(value) > MAX_PREFIX or _code_flagged(value)


def _token_flagged(value: str) -> bool:
    identifier_like = any(
        len(part) > IDENTIFIER_LIKE_LENGTH and any(c.isdigit() for c in part)
        for part in value.split()
    )
    return identifier_like or entities.looks_like_entity(value)


# The sweep each released field gets. Free-text tokens get the full sweep plus the
# identifier-like rule; code fields (Baugruppe, model, serial prefix) get everything but the
# plate shape, for the reason given on `_code_flagged`.
_SWEEPS = {
    "token": _token_flagged,
    "value": _code_flagged,
    "model": _code_flagged,
    "prefix": _prefix_flagged,
}

RELEASED_FIELDS = frozenset(_SWEEPS)


def flagged(field: str, value: str) -> bool:
    """True when `value` must not be released under `field`."""
    return _SWEEPS[field](value)


def _empty() -> dict[str, int]:
    return {"distinct": 0, "rows": 0}


def _parts(key: Hashable, names: tuple[str | None, ...]) -> tuple:
    """The key's components, after checking the key against `names`.

    Done for EVERY key before the floor test: a structure error that only raised for keys
    clearing the floor would hide on a small or synthetic corpus and surface in the real
    window. Messages name fields, counts and types only, never a value.
    """
    parts = key if isinstance(key, tuple) else (key,)
    if len(parts) != len(names):
        raise ValueError(
            f"a key has {len(parts)} component(s) but {len(names)} field(s) were named"
        )
    for name, part in zip(names, parts, strict=True):
        if name is None:
            continue
        if name not in _SWEEPS:
            raise KeyError(f"unknown released field {name!r}")
        if not isinstance(part, str):
            raise TypeError(f"released field {name!r} needs str values, got {type(part).__name__}")
    return parts


def release(
    counts: Counter, fields: str | Sequence[str | None], k: int = K
) -> tuple[list[tuple[Hashable, int]], dict[str, dict[str, int]]]:
    """Split `counts` into what may be released and a tally of what may not.

    A key may be one value or a tuple (a cross-tab cell). The floor applies to the key's
    count, so a cell is floored as a cell. `fields` names the sweep for each component, with
    None marking a structural component (a year) that is not swept.

    Returns (kept, withheld). `withheld` holds numbers only, so it is safe to emit: a reader
    can tell a section that was empty from one whose contents were suppressed.
    """
    names = (fields,) if isinstance(fields, str) else tuple(fields)
    kept: list[tuple[Hashable, int]] = []
    below = _empty()
    swept = _empty()
    # Ordered by count, then by key. most_common() leaves ties in arrival order, which would
    # make every section's output depend on the order of the rows in the export.
    for key, n in sorted(counts.items(), key=lambda item: (-item[1], repr(item[0]))):
        parts = _parts(key, names)
        if n < k:
            below["distinct"] += 1
            below["rows"] += n
            continue
        if any(f is not None and flagged(f, p) for f, p in zip(names, parts, strict=True)):
            swept["distinct"] += 1
            swept["rows"] += n
            continue
        kept.append((key, n))
    return kept, {"below_floor": below, "entity_like": swept}
```

Create `insight/measures.py`:

```python
"""Arithmetic only. Nothing here handles a string, so nothing here can leak one."""

from __future__ import annotations


def ratio(part: int | float, whole: int | float) -> float:
    return round(part / whole, 4) if whole else 0.0


def coverage(present: int, total: int) -> dict[str, int | float]:
    return {"present": present, "total": total, "share": ratio(present, total)}


def gini(values: list[int]) -> float:
    """Concentration of a count distribution: 0 when equal, towards 1 when one holds all."""
    n = len(values)
    total = sum(values)
    if n == 0 or total == 0:
        return 0.0
    ascending = sorted(values)
    weighted = sum((i + 1) * v for i, v in enumerate(ascending))
    return round(2 * weighted / (n * total) - (n + 1) / n, 4)


def top_share(ordered_desc: list[int], n: int, total: int) -> float:
    return ratio(sum(ordered_desc[:n]), total)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_release.py -v`
Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/__init__.py insight/release.py insight/measures.py tests/unit/test_insight_release.py
git commit -m "feat(insight): one release rule - floor plus a per-field entity sweep" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Extraction — the only code that touches raw rows

**Files:**
- Create: `insight/extract.py`
- Test: `tests/unit/test_insight_extract.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_insight_extract.py`:

```python
import dataclasses
import json

import pytest

from insight import extract


def envelope(**fields: str) -> str:
    """The way the real export wraps customData: descriptors, JSON-encoded twice."""
    records = [
        {"group": "g", "key": k, "label": f"Feld {k}", "value": v, "text": v, "type": "string"}
        for k, v in fields.items()
    ]
    return json.dumps(json.dumps(records, ensure_ascii=False), ensure_ascii=False)


def row(**kw: str) -> dict[str, str]:
    return {
        "title": "t",
        "description": "d",
        "solutions": "s",
        "customData": "",
        "vehicleSerialNo": "",
        "vehicleModelId": "",
        "timestampCreated": "",
        "vehicleYear": "",
        **kw,
    }


def test_custom_field_reads_a_named_value_from_a_double_encoded_envelope():
    blob = envelope(baugruppe="B-10", fehlercode="1234-5")
    assert extract.custom_field(blob, "baugruppe") == "B-10"
    assert extract.custom_field(blob, "fehlercode") == "1234-5"


def test_custom_field_falls_back_to_the_text_attribute():
    records = [{"key": "baugruppe", "value": "", "text": "B-20"}]
    assert extract.custom_field(json.dumps(records), "baugruppe") == "B-20"


def test_custom_field_is_none_when_the_field_is_absent():
    assert extract.custom_field(envelope(other="x"), "baugruppe") is None


def test_custom_field_is_none_when_the_value_is_blank():
    assert extract.custom_field(envelope(baugruppe="  "), "baugruppe") is None


def test_custom_field_is_none_when_the_envelope_is_malformed():
    assert extract.custom_field("<<<" + envelope(baugruppe="B-10"), "baugruppe") is None


def test_custom_field_is_none_when_there_is_no_customdata():
    assert extract.custom_field("", "baugruppe") is None
    assert extract.custom_field(None, "baugruppe") is None


def test_the_first_non_blank_duplicate_wins_whichever_order_they_arrive_in():
    """Review finding: a blank duplicate used to END the search, so [blank, 'B2'] gave None while
    ['B2', blank] gave 'B2'."""
    blank_first = [{"key": "baugruppe", "value": ""}, {"key": "baugruppe", "value": "B2"}]
    blank_last = [{"key": "baugruppe", "value": "B2"}, {"key": "baugruppe", "value": ""}]
    two = [{"key": "baugruppe", "value": "B1"}, {"key": "baugruppe", "value": "B2"}]
    assert extract.custom_field(json.dumps(blank_first), "baugruppe") == "B2"
    assert extract.custom_field(json.dumps(blank_last), "baugruppe") == "B2"
    assert extract.custom_field(json.dumps(two), "baugruppe") == "B1"


def test_a_record_without_a_name_attribute_is_skipped():
    records = [{"value": "orphan"}, {"key": "baugruppe", "value": "B-10"}]
    assert extract.custom_field(json.dumps(records), "baugruppe") == "B-10"


def test_a_ticket_carries_exactly_the_allowlisted_fields():
    """The privacy boundary, pinned: a new field must be added here deliberately."""
    assert {f.name for f in dataclasses.fields(extract.Ticket)} == {
        "title",
        "description",
        "solutions",
        "baugruppe",
        "serial",
        "model",
        "created_year",
        "vehicle_year",
    }


def test_a_ticket_never_prints_free_text_or_a_serial():
    """repr is how a raw value reaches an exception, a log line or a pytest assertion diff."""
    ticket = extract.tickets(
        [
            row(
                title="Hans Mueller meldet Pumpe",
                description="Rueckruf an hans.mueller@example.de",
                solutions="Pumpe getauscht",
                vehicleSerialNo="ZZLEAK77",
            )
        ]
    )[0]
    printed = repr(ticket)
    for secret in ("Mueller", "example.de", "Pumpe", "ZZLEAK77"):
        assert secret not in printed


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2022-03-10 08:30:00", "2022"),
        ("2019", "2019"),
        ("  2021 ", "2021"),
        ("20224", "2022"),
        ("abcd", None),
        ("", None),
        (None, None),
        ("２０２２", None),  # full-width digits are not a year here
        ("٢٠٢٢", None),  # nor are Arabic-Indic ones
    ],
)
def test_a_year_is_four_ascii_digits_or_nothing(raw, expected):
    assert extract.tickets([row(timestampCreated=raw)])[0].created_year == expected


def test_read_rows_decodes_bad_bytes_instead_of_raising(tmp_path):
    """A decode error quotes the offending bytes, so the file is read with errors='replace'."""
    path = tmp_path / "rows.dat"
    path.write_bytes(b"title,description\nPumpe \xff\xfe defekt,ok\n")
    rows = extract.read_rows(path)
    assert len(rows) == 1
    assert rows[0]["description"] == "ok"
    assert rows[0]["title"].startswith("Pumpe") and rows[0]["title"].endswith("defekt")


def test_tickets_map_the_columns_and_strip_values():
    t = extract.tickets(
        [
            row(
                title="Pumpe",
                customData=envelope(baugruppe=" B-10 "),
                vehicleSerialNo=" SER1-0001 ",
                vehicleModelId="TX-2210",
                timestampCreated="2022-03-10 08:30:00",
                vehicleYear="2019",
            )
        ]
    )[0]
    assert (t.title, t.baugruppe, t.serial, t.model) == ("Pumpe", "B-10", "SER1-0001", "TX-2210")
    assert (t.created_year, t.vehicle_year) == ("2022", "2019")


def test_blank_fields_are_none_and_a_garbage_year_is_not_a_year():
    t = extract.tickets([row(timestampCreated="soon", vehicleYear="abcd")])[0]
    assert (t.baugruppe, t.serial, t.model) == (None, None, None)
    assert (t.created_year, t.vehicle_year) == (None, None)


def test_a_row_missing_a_column_does_not_raise():
    t = extract.tickets([{"title": "only a title"}])[0]
    assert t.title == "only a title"
    assert t.description == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_extract.py -v`
Expected: collection error, `cannot import name 'extract'`.

- [ ] **Step 3: Write the implementation**

Create `insight/extract.py`:

```python
"""Raw rows to `Ticket`s. Nothing downstream reads a CSV row, so a column that must never
leave (names, e-mail, phone) is simply never carried across this boundary."""

from __future__ import annotations

import csv
import pathlib
import re
from dataclasses import dataclass, field

from profiler.stats import customdata

# ASCII digits only: \d would also accept full-width and Arabic-Indic digits, which would form
# a bucket of their own and slip past a guard that trusts "four digits".
_YEAR = re.compile(r"^[0-9]{4}$")


@dataclass(frozen=True)
class Ticket:
    # repr=False on the free text and the serial: a Ticket formatted into an exception, a log
    # line or a pytest assertion diff would otherwise print raw corpus text. Those are the
    # only paths by which a raw value can leave this module.
    title: str = field(repr=False)
    description: str = field(repr=False)
    solutions: str = field(repr=False)
    baugruppe: str | None
    serial: str | None = field(repr=False)
    model: str | None
    created_year: str | None
    vehicle_year: str | None


def read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    # errors="replace" as in the profiler: a decode error quotes the offending bytes.
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


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _year(value: str | None) -> str | None:
    head = (value or "").strip()[:4]
    return head if _YEAR.match(head) else None


def tickets(rows: list[dict[str, str]]) -> list[Ticket]:
    return [
        Ticket(
            title=row.get("title") or "",
            description=row.get("description") or "",
            solutions=row.get("solutions") or "",
            baugruppe=custom_field(row.get("customData"), "baugruppe"),
            serial=_clean(row.get("vehicleSerialNo")),
            model=_clean(row.get("vehicleModelId")),
            created_year=_year(row.get("timestampCreated")),
            vehicle_year=_year(row.get("vehicleYear")),
        )
        for row in rows
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_extract.py -v`
Expected: 23 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/extract.py tests/unit/test_insight_extract.py
git commit -m "feat(insight): extract tickets, reading baugruppe out of the customData envelope" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Where tickets come from

**Files:**
- Create: `insight/origin.py`
- Test: `tests/unit/test_insight_origin.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_insight_origin.py`:

```python
import json

import pytest

from insight import origin
from insight.extract import Ticket


def mk(**kw) -> Ticket:
    base = dict(
        title="",
        description="",
        solutions="",
        baugruppe=None,
        serial=None,
        model=None,
        created_year=None,
        vehicle_year=None,
    )
    base.update(kw)
    return Ticket(**base)


def serials_sharing(prefix: str, n: int) -> list[str]:
    """n DISTINCT serials that share a prefix: n vehicles, not n tickets of one vehicle."""
    return [f"{prefix}{i:06d}" for i in range(n)]


def test_baugruppe_floors_and_says_how_much_it_withheld():
    tickets = (
        [mk(baugruppe="B-10")] * 5
        + [mk(baugruppe="B-20")] * 3
        + [mk(baugruppe="B-90")]
        + [mk()] * 4
    )
    out = origin.baugruppe(tickets, k=3)
    assert out["top"] == [{"value": "B-10", "count": 5}, {"value": "B-20", "count": 3}]
    assert out["withheld"]["below_floor"] == {"distinct": 1, "rows": 1}
    assert out["distinct"] == 3
    assert out["coverage"] == {"present": 9, "total": 13, "share": 0.6923}


def test_baugruppe_concentration():
    tickets = [mk(baugruppe="B-10")] * 5 + [mk(baugruppe="B-20")] * 3 + [mk(baugruppe="B-90")]
    c = origin.baugruppe(tickets, k=3)["concentration"]
    assert c["top1_share"] == 0.5556
    assert c["top5_share"] == 1.0
    assert c["gini"] == pytest.approx(0.2963, abs=1e-4)


def test_a_swept_baugruppe_is_absent_everywhere_but_counted_in_the_ledger():
    tickets = (
        [mk(baugruppe="Huber GmbH", created_year="2022")] * 5
        + [mk(baugruppe="B-10", created_year="2022")] * 4
        + [mk(baugruppe="B-20")] * 3
    )
    out = origin.baugruppe(tickets, k=3)
    assert [e["value"] for e in out["top"]] == ["B-10", "B-20"]
    assert "Huber" not in json.dumps(out)
    assert out["withheld"]["entity_like"] == {"distinct": 1, "rows": 5}
    assert out["by_year_withheld"]["entity_like"] == {"distinct": 1, "rows": 5}
    assert [e["value"] for e in out["by_year"]] == ["B-10"]
    # Withheld values still count toward the aggregates: 5 of 12 is derivable from the ledger.
    assert out["distinct"] == 3
    assert out["concentration"]["top1_share"] == 0.4167


def test_case_variants_are_counted_as_written_and_the_collapse_is_reported():
    tickets = [mk(baugruppe="b-10")] * 3 + [mk(baugruppe="B-10")] * 3
    out = origin.baugruppe(tickets, k=3)
    assert {e["value"] for e in out["top"]} == {"b-10", "B-10"}
    assert out["distinct"] == 2
    assert out["distinct_casefolded"] == 1


def test_baugruppe_by_year_floors_each_cell():
    tickets = [mk(baugruppe="B-10", created_year="2022")] * 4 + [
        mk(baugruppe="B-10", created_year="2023")
    ] * 2
    out = origin.baugruppe(tickets, k=3)
    assert out["by_year"] == [{"value": "B-10", "year": "2022", "count": 4}]
    assert out["by_year_withheld"]["below_floor"] == {"distinct": 1, "rows": 2}


def test_serials_report_repeat_behaviour_without_a_single_serial():
    tickets = [mk(serial="SN-AAA")] * 4 + [mk(serial="SN-BBB"), mk(serial="SN-CCC")] + [mk()] * 2
    s = origin.vehicles(tickets, k=3)["serials"]
    assert s["distinct"] == 3
    assert s["repeat_rate"] == 0.6667
    assert s["top_percent_share"] == 0.6667
    assert s["coverage"] == {"present": 6, "total": 8, "share": 0.75}
    assert s["tickets_per_serial_quantiles"]["max"] == 4.0
    assert "SN-" not in json.dumps(origin.vehicles(tickets, k=3))


def test_serial_prefixes_are_off_unless_asked_for():
    assert origin.vehicles([mk(serial="SN-AAA")], k=1)["serials"]["prefixes"] == {"enabled": False}


def test_prefixes_take_the_longest_length_that_keeps_ninety_percent_in_floored_buckets():
    serials = serials_sharing("TX22-", 60) + serials_sharing("TX24-", 60) + ["ZZ99-000001"]
    out = origin.prefixes(serials, k=50)
    assert out["enabled"] is True
    assert out["length"] == 5
    assert {(b["prefix"], b["count"]) for b in out["buckets"]} == {("TX22-", 60), ("TX24-", 60)}
    assert out["covered_share"] == 0.9917
    assert out["too_short"] == 0


def test_a_short_prefix_that_is_a_company_suffix_does_not_end_the_search():
    """Found by running the plan: 'SE' is a company suffix, so the sweep flags the two-character
    prefix. Letting that steer the search stopped it at length 1. The sweep is not monotone in
    length ('SE' flagged, 'SER' not), so the length is chosen on the floor alone."""
    serials = serials_sharing("SER1-", 60) + serials_sharing("SER2-", 60)
    out = origin.prefixes(serials, k=50)
    assert out["length"] == 5
    assert {b["prefix"] for b in out["buckets"]} == {"SER1-", "SER2-"}


def test_a_chosen_prefix_that_the_sweep_flags_is_withheld_and_counted():
    """The sweep still applies at the length the floor chose: nothing is released that it flags,
    and the withheld vehicles are counted so the ledger shows it."""
    out = origin.prefixes(serials_sharing("GMBH-", 60), k=50)
    assert out["length"] == 5
    assert out["buckets"] == []
    assert out["withheld"]["entity_like"] == {"distinct": 1, "rows": 60}
    assert out["covered_share"] == 0.0


def test_a_prefix_never_reaches_past_half_of_a_serial():
    """Whatever the floor allows, a released prefix is never most of a serial."""
    serials = [f"AB{i:04d}" for i in range(80)]  # six characters: at most three
    out = origin.prefixes(serials, k=50)
    assert out["length"] == 3
    assert [(b["prefix"], b["count"]) for b in out["buckets"]] == [("AB0", 80)]


def test_one_vehicle_with_many_tickets_forms_no_bucket():
    """Review finding: the floor used to count tickets, so a single vehicle with k tickets formed
    a bucket on its own and released half of a denylisted serial. The floor counts vehicles."""
    out = origin.prefixes(["AB123456"] * 100, k=50)
    assert out["length"] == 0
    assert out["buckets"] == []
    through_vehicles = origin.vehicles([mk(serial="AB123456")] * 100, k=50, serial_prefixes=True)[
        "serials"
    ]["prefixes"]
    assert through_vehicles["buckets"] == []


def test_a_stray_short_serial_does_not_cap_the_length_for_everyone_else():
    """Review finding: the cap came from the shortest serial in the whole corpus, so one stray
    two-character serial collapsed every prefix to one character. Each serial is now limited by
    its own length; the stray one is simply left out, and counted."""
    serials = serials_sharing("TX22-", 60) + serials_sharing("TX24-", 60) + ["ab"]
    out = origin.prefixes(serials, k=50)
    assert out["length"] == 5
    assert out["too_short"] == 1
    assert out["covered_share"] == 0.9917


def test_prefixes_with_nothing_clearing_the_floor_release_nothing_and_say_so():
    out = origin.prefixes([f"SER{i}-000{i}" for i in range(5)], k=50)
    assert out["length"] == 0
    assert out["buckets"] == []
    assert out["withheld"]["below_floor"] == {"distinct": 5, "rows": 5}


def test_models_and_vehicle_years_are_floored():
    tickets = [mk(model="TX-2210", vehicle_year="2019")] * 4 + [
        mk(model="LR-45", vehicle_year="2020")
    ]
    v = origin.vehicles(tickets, k=3)
    assert v["models"] == [{"model": "TX-2210", "count": 4}]
    assert v["models_withheld"]["below_floor"] == {"distinct": 1, "rows": 1}
    assert v["vehicle_years"] == [{"year": "2019", "count": 4}]


def test_title_tokens_drop_a_frequent_surname_and_count_the_drop():
    tickets = [mk(title="Motor Bauer")] * 5 + [mk(title="Motor startet")] * 5
    out = origin.titles(tickets, k=3)
    assert [t["token"] for t in out["tokens"]] == ["motor", "startet"]
    assert out["tokens_withheld"]["entity_like"] == {"distinct": 1, "rows": 5}
    assert all("bauer" not in b["token"] for b in out["bigrams"])
    assert out["fill"] == 1.0
    assert out["tokens_omitted"] == 0


def test_a_blank_title_lowers_fill_and_the_token_cap_reports_what_it_omits():
    assert origin.titles([mk(title="   "), mk(title="pumpe")], k=1)["fill"] == 0.5
    words = [f"{a}{b}{c}pumpe" for a in "abcdef" for b in "abcdef" for c in "abcdef"]
    out = origin.titles([mk(title=w) for w in words[:150]], k=1)
    assert len(out["tokens"]) == origin.MAX_LISTED
    assert out["tokens_omitted"] == 50
    assert out["bigrams_omitted"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_origin.py -v`
Expected: collection error, `cannot import name 'origin'`.

- [ ] **Step 3: Write the implementation**

Create `insight/origin.py`:

```python
"""Spec section 1: where tickets come from.

Every value released here goes through `release.release`; everything else is a count or a
ratio. A serial never appears: per-serial behaviour is reported as quantiles, and the only
serial-derived strings are the opt-in prefix buckets, which never release more than half of any
serial and are floored on distinct vehicles, not tickets.
"""

from __future__ import annotations

import math
from collections import Counter

from insight import measures, release
from insight.extract import Ticket
from profiler.stats import lengths, vocab
from recall.clean import pipeline

MAX_LISTED = 100
PREFIX_MIN_COVERED = 0.9


def baugruppe(tickets: list[Ticket], k: int = release.K) -> dict:
    counts = Counter(t.baugruppe for t in tickets if t.baugruppe)
    present = sum(counts.values())
    top, withheld = release.release(counts, "value", k)
    cells = Counter(
        (t.baugruppe, t.created_year) for t in tickets if t.baugruppe and t.created_year
    )
    by_year, by_year_withheld = release.release(cells, ("value", None), k)
    ordered = sorted(counts.values(), reverse=True)
    return {
        "coverage": measures.coverage(present, len(tickets)),
        "distinct": len(counts),
        # Case variants ('b-10' and 'B-10') are counted as written. How many collapse under
        # case-folding is a data-quality fact in its own right, so both numbers are reported.
        "distinct_casefolded": len({v.casefold() for v in counts}),
        "top": [{"value": v, "count": n} for v, n in top],
        "withheld": withheld,
        "concentration": {
            "top1_share": measures.top_share(ordered, 1, present),
            "top5_share": measures.top_share(ordered, 5, present),
            "top10_share": measures.top_share(ordered, 10, present),
            "gini": measures.gini(ordered),
        },
        "by_year": [{"value": v, "year": y, "count": n} for (v, y), n in by_year],
        "by_year_withheld": by_year_withheld,
    }


def prefixes(serials: list[str], k: int = release.K, max_len: int = release.MAX_PREFIX) -> dict:
    """Serial prefix buckets, each shared by at least k DISTINCT vehicles.

    The floor counts vehicles, not tickets. Counted per ticket, one vehicle with k tickets
    formed a bucket on its own and released half of a denylisted serial. A bucket's `count` is
    therefore a number of vehicles, and `withheld` rows are vehicles too.

    The length is the longest whose floored buckets still cover 90% of the vehicles. A serial
    takes part only at lengths up to half its OWN length, so no serial ever releases more than
    half of itself; a serial too short for the chosen length is left out and counted in
    `too_short`, instead of one stray short serial capping the length for everyone.
    """
    distinct = sorted(set(serials))
    total = len(distinct)
    chosen = 0
    for length in range(1, max_len + 1):
        counts = Counter(s[:length] for s in distinct if len(s) // 2 >= length)
        # Chosen on the floor alone. The entity sweep is not monotone in length - 'SE' is a
        # company suffix while 'SER' is not - so letting it steer the search would end it at
        # the first short prefix that happens to be a dictionary word, and a real window would
        # return a one-character bucket. The sweep still applies, at the chosen length below.
        floored = sum(n for n in counts.values() if n >= k)
        if not total or floored / total < PREFIX_MIN_COVERED:
            break
        chosen = length
    if chosen == 0:
        return {
            "enabled": True,
            "length": 0,
            "covered_share": 0.0,
            "too_short": 0,
            "buckets": [],
            "withheld": {
                "below_floor": {"distinct": total, "rows": total},
                "entity_like": {"distinct": 0, "rows": 0},
            },
        }
    eligible = [s for s in distinct if len(s) // 2 >= chosen]
    kept, withheld = release.release(Counter(s[:chosen] for s in eligible), "prefix", k)
    covered = sum(n for _, n in kept)
    return {
        "enabled": True,
        "length": chosen,
        "covered_share": measures.ratio(covered, total),
        "too_short": total - len(eligible),
        "buckets": [{"prefix": p, "count": n} for p, n in kept],
        "withheld": withheld,
    }


def vehicles(tickets: list[Ticket], k: int = release.K, serial_prefixes: bool = False) -> dict:
    serials = [t.serial for t in tickets if t.serial]
    per_serial = sorted(Counter(serials).values(), reverse=True)
    top_n = max(1, math.ceil(len(per_serial) * 0.01)) if per_serial else 0
    models, models_withheld = release.release(
        Counter(t.model for t in tickets if t.model), "model", k
    )
    years, years_withheld = release.release(
        Counter(t.vehicle_year for t in tickets if t.vehicle_year), (None,), k
    )
    return {
        "serials": {
            "coverage": measures.coverage(len(serials), len(tickets)),
            "distinct": len(per_serial),
            "tickets_per_serial_quantiles": lengths.quantiles(per_serial),
            "repeat_rate": measures.ratio(sum(n for n in per_serial if n >= 2), len(serials)),
            "top_percent_share": measures.ratio(sum(per_serial[:top_n]), len(serials)),
            "prefixes": prefixes(serials, k) if serial_prefixes else {"enabled": False},
        },
        "models": [{"model": m, "count": n} for m, n in models],
        "models_withheld": models_withheld,
        "vehicle_years": [{"year": y, "count": n} for y, n in years],
        "vehicle_years_withheld": years_withheld,
    }


def titles(tickets: list[Ticket], k: int = release.K) -> dict:
    """Floored tokens and bigrams only. A title is prose, and prose is never shaped."""
    cleaned = [pipeline.clean(t.title).text for t in tickets]
    tokens, tokens_withheld = release.release(vocab.token_counts(cleaned), "token", k)
    bigrams, bigrams_withheld = release.release(vocab.bigram_counts(cleaned), "token", k)
    return {
        "fill": measures.ratio(sum(1 for t in tickets if t.title.strip()), len(tickets)),
        "tokens": [{"token": t, "count": n} for t, n in tokens[:MAX_LISTED]],
        "tokens_withheld": tokens_withheld,
        "tokens_omitted": max(0, len(tokens) - MAX_LISTED),
        "bigrams": [{"token": t, "count": n} for t, n in bigrams[:MAX_LISTED]],
        "bigrams_withheld": bigrams_withheld,
        "bigrams_omitted": max(0, len(bigrams) - MAX_LISTED),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_origin.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/origin.py tests/unit/test_insight_origin.py
git commit -m "feat(insight): baugruppe, vehicle and title origin sections" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Cross-tab with every cell floored

**Files:**
- Create: `insight/crosstab.py`
- Test: `tests/unit/test_insight_crosstab.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_insight_crosstab.py`:

```python
import pytest

from insight import crosstab, release
from insight.extract import Ticket


def mk(baugruppe, model, year) -> Ticket:
    return Ticket("", "", "", baugruppe, None, model, year, None)


def test_a_cell_is_floored_even_when_both_margins_clear_the_floor():
    """B-10 has 6 tickets and TX-2210 has 6, so each margin clears k=5. The cell that
    would single out one vehicle line is the 2-ticket one, and it must not be released."""
    tickets = (
        [mk("B-10", "TX-2210", "2022")] * 4
        + [mk("B-10", "TX-2240", "2022")] * 2
        + [mk("B-20", "TX-2210", "2022")] * 2
    )
    out = crosstab.baugruppe_model_year(tickets, k=4)
    assert out["cells"] == [{"value": "B-10", "model": "TX-2210", "year": "2022", "count": 4}]
    assert out["withheld"]["below_floor"] == {"distinct": 2, "rows": 4}


def test_a_swept_baugruppe_inside_a_cell_withholds_the_cell():
    out = crosstab.baugruppe_model_year([mk("Mueller GmbH", "TX-2210", "2022")] * 6, k=5)
    assert out["cells"] == []
    assert out["withheld"]["entity_like"] == {"distinct": 1, "rows": 6}


def test_empty_and_all_below_floor_input_is_safe():
    nothing = {"distinct": 0, "rows": 0}
    empty = crosstab.baugruppe_model_year([], k=5)
    assert empty == {
        "coverage": {"present": 0, "total": 0, "share": 0.0},
        "cells": [],
        "withheld": {"below_floor": nothing, "entity_like": nothing},
    }
    few = crosstab.baugruppe_model_year([mk("B-10", "TX-2210", "2022")] * 3, k=5)
    assert few["cells"] == []
    assert few["withheld"]["below_floor"] == {"distinct": 1, "rows": 3}


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_a_ticket_missing_any_one_component_is_excluded(missing):
    parts = ["B-10", "TX-2210", "2022"]
    parts[missing] = None
    out = crosstab.baugruppe_model_year([mk(*parts)] * 4, k=2)
    assert out["cells"] == []
    assert out["coverage"]["present"] == 0


def test_the_default_floor_is_the_release_floor():
    at_floor = [mk("B-10", "TX-2210", "2022")] * release.K
    under = [mk("B-20", "TX-2210", "2022")] * (release.K - 1)
    out = crosstab.baugruppe_model_year(at_floor + under)
    assert [c["value"] for c in out["cells"]] == ["B-10"]


def test_cells_are_floored_on_tickets_not_vehicles_by_design():
    """No component of a cell is a serial, so one vehicle's tickets may form a cell. Serial prefix
    buckets differ on purpose: there the released string is part of the identifier itself."""
    one_vehicle = [Ticket("", "", "", "B-10", "SN-1", "TX-2210", "2022", None)] * 60
    assert len(crosstab.baugruppe_model_year(one_vehicle, k=50)["cells"]) == 1


def test_cells_with_equal_counts_come_out_in_a_stable_order():
    tickets = [mk("B-10", "TX-2210", "2022")] * 3 + [mk("B-20", "TX-2210", "2022")] * 3
    forward = crosstab.baugruppe_model_year(tickets, k=3)["cells"]
    backward = crosstab.baugruppe_model_year(tickets[::-1], k=3)["cells"]
    assert forward == backward
    assert [c["value"] for c in forward] == ["B-10", "B-20"]


def test_rows_missing_any_of_the_three_are_excluded_and_counted_in_coverage():
    tickets = [mk("B-10", "TX-2210", "2022")] * 4 + [mk("B-10", None, "2022")] * 3
    out = crosstab.baugruppe_model_year(tickets, k=4)
    assert out["coverage"] == {"present": 4, "total": 7, "share": 0.5714}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_crosstab.py -v`
Expected: collection error, `cannot import name 'crosstab'`.

- [ ] **Step 3: Write the implementation**

Create `insight/crosstab.py`:

```python
"""Baugruppe x model x year, with the floor applied to each CELL.

Flooring the margins is not enough: B-10 and TX-2210 can each be common while the one cell
where they meet holds a single vehicle line's tickets. `release.release` floors the tuple.

The floor counts TICKETS here, unlike serial prefix buckets, which count vehicles. No
component of a cell is a serial, so a cell says something about a model line and a year, not
about one vehicle. Cells under the floor are withheld and tallied, never folded into an
'other' cell.
"""

from __future__ import annotations

from collections import Counter

from insight import measures, release
from insight.extract import Ticket


def baugruppe_model_year(tickets: list[Ticket], k: int = release.K) -> dict:
    complete = [t for t in tickets if t.baugruppe and t.model and t.created_year]
    cells = Counter((t.baugruppe, t.model, t.created_year) for t in complete)
    kept, withheld = release.release(cells, ("value", "model", None), k)
    return {
        "coverage": measures.coverage(len(complete), len(tickets)),
        "cells": [{"value": b, "model": m, "year": y, "count": n} for (b, m, y), n in kept],
        "withheld": withheld,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_crosstab.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/crosstab.py tests/unit/test_insight_crosstab.py
git commit -m "feat(insight): cross-tab that floors cells, not just margins" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Model-free text evidence

**Files:**
- Create: `insight/texts.py`
- Test: `tests/unit/test_insight_texts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_insight_texts.py`:

```python
import random

import pytest

from insight import texts
from insight.extract import Ticket


def mk(title="", description="", solutions="") -> Ticket:
    return Ticket(title, description, solutions, None, None, None, None, None)


def test_lengths_are_labelled_as_whitespace_tokens_not_model_tokens():
    out = texts.build([mk(title="a b c", description="d e", solutions="f")], k=50)["lengths"]
    assert out["unit"] == "whitespace_tokens"
    assert out["title"]["p50"] == 3.0
    assert out["description"]["p50"] == 2.0
    assert out["solutions"]["p50"] == 1.0


def test_length_quantiles_are_ordered_across_several_tickets():
    tickets = [mk(title=" ".join(["w"] * n)) for n in (1, 2, 3, 4, 5)]
    out = texts.build(tickets, k=50)["lengths"]["title"]
    assert (out["p1"], out["p50"], out["max"]) == (1.0, 3.0, 5.0)


def test_identifier_density_counts_tickets_by_kind():
    tickets = [mk(title="Fehler F1247 an TX-2210"), mk(title="Pumpe laeuft nicht")]
    out = texts.build(tickets, k=50)["identifiers"]["problem"]
    assert out["any_share"] == 0.5
    by_kind = {e["kind"]: e["tickets"] for e in out["by_kind"]}
    assert by_kind["error_code"] == 1
    assert by_kind["model_designation"] == 1
    assert by_kind["part_number"] == 0


def test_every_identifier_kind_is_always_listed_even_at_zero():
    out = texts.build([mk(title="nichts")], k=50)["identifiers"]["solutions"]
    assert [e["kind"] for e in out["by_kind"]] == list(texts.IDENTIFIER_KINDS)


def test_identifiers_in_the_solutions_only_are_counted_on_that_side_only():
    out = texts.build([mk(solutions="Teil F1247 getauscht")], k=50)["identifiers"]
    assert out["problem"]["any_share"] == 0.0
    assert out["solutions"]["any_share"] == 1.0


def test_cleaning_that_redacts_a_part_number_is_made_visible_on_both_sides():
    """Found by review: the cleaning pipeline's phone pattern redacts '1234.56789' as [TEL], and
    that is also exactly what the part_number pattern matches. Measuring one side raw and the
    other cleaned made the two incomparable; measuring both ways turns the loss into a number."""
    ticket = mk(title="Ersatzteil 1234.56789 bestellt", solutions="Ersatzteil 1234.56789 bestellt")
    out = texts.build([ticket], k=50)["identifiers"]
    for side in ("problem", "solutions"):
        part = {e["kind"]: e for e in out[side]["by_kind"]}["part_number"]
        assert part["tickets"] == 1, side
        assert part["tickets_after_cleaning"] == 0, side
        assert out[side]["any_share"] == 1.0
        assert out[side]["any_share_after_cleaning"] == 0.0


def test_repetition_reports_the_share_of_tickets_in_large_near_duplicate_clusters():
    same = [mk(title="pumpe defekt hydraulik")] * 60
    distinct = [mk(title=f"wort{i}a wort{i}b wort{i}c") for i in range(5)]
    out = texts.build(same + distinct, k=50)["repetition"]
    assert out["cluster_count"] == 6
    assert out["singleton_count"] == 5
    assert out["share_in_clusters_at_least_k"] == 0.9231
    assert out["largest_cluster_share"] == 0.9231
    assert out["blank_problem_text"] == 0


@pytest.mark.parametrize(("size", "share"), [(49, 0.0), (50, 1.0)])
def test_the_cluster_threshold_is_at_least_k(size, share):
    tickets = [mk(title="pumpe defekt hydraulik")] * size
    out = texts.build(tickets, k=50)["repetition"]
    assert out["share_in_clusters_at_least_k"] == share


def test_blank_problem_texts_are_left_out_of_the_clustering_and_counted():
    """Identical empty texts have identical MinHashes, so left in they form one spurious cluster."""
    tickets = [mk()] * 30 + [mk(title="pumpe defekt hydraulik")] * 5
    out = texts.build(tickets, k=3)["repetition"]
    assert out["blank_problem_text"] == 30
    assert out["cluster_count"] == 1
    assert out["share_in_clusters_at_least_k"] == 1.0


def test_the_largest_cluster_share_is_withheld_when_the_cluster_is_below_the_floor():
    """Reporting it would reveal that the largest group has exactly three tickets."""
    tickets = [mk(title="pumpe defekt hydraulik")] * 3
    tickets += [mk(title=f"wort{i}a wort{i}b wort{i}c") for i in range(20)]
    assert texts.build(tickets, k=50)["repetition"]["largest_cluster_share"] is None
    assert texts.build(tickets, k=3)["repetition"]["largest_cluster_share"] == 0.1304


def test_empty_input_is_safe():
    out = texts.build([], k=50)
    assert out["lengths"]["title"]["max"] == 0.0
    assert out["identifiers"]["problem"]["any_share"] == 0.0
    assert out["repetition"]["cluster_count"] == 0
    assert out["repetition"]["share_in_clusters_at_least_k"] == 0.0
    assert out["repetition"]["largest_cluster_share"] is None


def test_repetition_does_not_depend_on_row_order_even_for_chained_near_duplicates():
    """Review finding: the clustering is greedy and arrival-ordered, and LSH neighbours are not
    transitive, so on a chain of overlapping texts the cluster sizes changed with the order of
    the rows. The documents are sorted before clustering."""

    def word(j: int) -> str:
        return "wort" + chr(97 + j // 26) + chr(97 + j % 26)

    chain = [" ".join(word(j) for j in range(i, i + 8)) for i in range(20)]
    tickets = [mk(title=title) for title in chain]
    expected = texts.build(tickets, k=3)["repetition"]
    for seed in range(20):
        shuffled = list(tickets)
        random.Random(seed).shuffle(shuffled)
        assert texts.build(shuffled, k=3)["repetition"] == expected
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_texts.py -v`
Expected: collection error, `cannot import name 'texts'`.

- [ ] **Step 3: Write the implementation**

Create `insight/texts.py`:

```python
"""Evidence about the text that needs no model: lengths, identifier density, repetition.

The bases differ between measures, so they are stated here rather than left to be guessed:

  * lengths: `title`, `description` and `solutions` are measured on the RAW text; `problem_text`
    is the CLEANED title + description (HTML, quoted replies and signatures stripped, PII
    redacted to placeholders that themselves count as tokens).
  * identifiers: counted on the raw text AND after the cleaning pipeline, for the problem and
    the solutions alike. Both sides share one basis, and what cleaning destroys becomes a number
    (`tickets` against `tickets_after_cleaning`) instead of a silent bias. The pipeline's phone
    pattern, for one, redacts a part number such as 1234.56789.
  * repetition: `k` is the release floor, reused as the minimum cluster size. Tickets with a
    blank problem text are left out of the clustering and counted, because identical empty
    texts would otherwise form one spurious cluster.

Lengths are WHITESPACE tokens and labelled so. The e5 truncation share needs the model's own
tokenizer and belongs to stage 2; reporting a proxy under the real name would be a number that
looks measured and is not.
"""

from __future__ import annotations

from insight import measures, release
from insight.extract import Ticket
from profiler.stats import clusters, lengths
from recall.clean import pipeline
from recall.german import identifiers

# Our own closed list, taken from the extractor's patterns: kind names are never corpus text.
IDENTIFIER_KINDS = tuple(kind for kind, _ in identifiers.PATTERNS)


def _lengths(tickets: list[Ticket], problem: list[str]) -> dict:
    def quantiles(values: list[str]) -> dict[str, float]:
        return lengths.quantiles([len(v.split()) for v in values])

    return {
        "unit": "whitespace_tokens",
        "title": quantiles([t.title for t in tickets]),
        "description": quantiles([t.description for t in tickets]),
        "solutions": quantiles([t.solutions for t in tickets]),
        "problem_text": quantiles(problem),
    }


def _kinds(documents: list[str]) -> list[set[str]]:
    return [{i.kind for i in identifiers.extract(text)} for text in documents]


def _density(raw: list[str], cleaned: list[str]) -> dict:
    """Identifier density on the raw text and again after cleaning, so the loss is visible."""
    before = _kinds(raw)
    after = _kinds(cleaned)
    total = len(raw)
    by_kind = []
    for kind in IDENTIFIER_KINDS:
        n = sum(1 for kinds in before if kind in kinds)
        kept = sum(1 for kinds in after if kind in kinds)
        by_kind.append(
            {
                "kind": kind,
                "tickets": n,
                "tickets_after_cleaning": kept,
                "share": measures.ratio(n, total),
            }
        )
    return {
        "any_share": measures.ratio(sum(1 for kinds in before if kinds), total),
        "any_share_after_cleaning": measures.ratio(sum(1 for kinds in after if kinds), total),
        "by_kind": by_kind,
    }


def _repetition(problem: list[str], k: int) -> dict:
    # Sorted first. The clustering is greedy and arrival-ordered over LSH neighbours that are
    # not transitive, so on a chain of overlapping texts the cluster sizes changed with the row
    # order of the export. Sorting makes the result a function of the set of texts.
    documents = sorted(d for d in problem if d.strip())
    profile = clusters.profile(documents)
    distribution = {int(size): count for size, count in profile["size_distribution"].items()}
    in_large = sum(size * count for size, count in distribution.items() if size >= k)
    largest = max(distribution, default=0)
    return {
        "blank_problem_text": len(problem) - len(documents),
        "cluster_count": profile["cluster_count"],
        "singleton_count": profile["singleton_count"],
        "share_in_clusters_at_least_k": measures.ratio(in_large, len(documents)),
        # A group smaller than the floor is not described, not even by its share of the corpus.
        "largest_cluster_share": measures.ratio(largest, len(documents)) if largest >= k else None,
    }


def build(tickets: list[Ticket], k: int = release.K) -> dict:
    problem_raw = [f"{t.title} {t.description}" for t in tickets]
    problem = [pipeline.clean(text).text for text in problem_raw]
    solutions_raw = [t.solutions for t in tickets]
    solutions = [pipeline.clean(text).text for text in solutions_raw]
    return {
        "lengths": _lengths(tickets, problem),
        "identifiers": {
            "problem": _density(problem_raw, problem),
            "solutions": _density(solutions_raw, solutions),
        },
        "repetition": _repetition(problem, k),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_texts.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/texts.py tests/unit/test_insight_texts.py
git commit -m "feat(insight): model-free text evidence, lengths labelled as whitespace tokens" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The guard

**Files:**
- Create: `insight/guard.py`
- Test: `tests/unit/test_insight_guard.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_insight_guard.py`:

```python
import pytest

from insight import guard
from profiler import safety


def entry(**kw):
    return {"origin": {"baugruppe": {"top": [kw]}}}


def test_a_floored_swept_entry_passes():
    assert guard.unaccounted(entry(value="B-10", count=60), 50) == []


def test_an_entry_below_the_floor_is_refused():
    assert guard.unaccounted(entry(value="B-10", count=49), 50) == [
        ("origin.baugruppe.top", "BELOW_FLOOR")
    ]


def test_a_frequent_name_is_refused():
    assert guard.unaccounted(entry(value="Huber GmbH", count=60), 50) == [
        ("origin.baugruppe.top", "ENTITY_LIKE")
    ]


def test_an_entry_without_a_count_is_refused():
    assert guard.unaccounted(entry(value="B-10"), 50) == [("origin.baugruppe.top", "MISSING_COUNT")]


def test_a_prefix_over_the_cap_is_refused():
    report = {
        "origin": {
            "vehicles": {"serials": {"prefixes": {"buckets": [{"prefix": "A" * 9, "count": 60}]}}}
        }
    }
    assert [code for _, code in guard.unaccounted(report, 50)] == ["ENTITY_LIKE"]


def test_a_corpus_derived_dict_key_is_refused():
    """Counts keyed by value would leak the value as a key. Entries are lists, never dicts."""
    report = {"origin": {"baugruppe": {"Mueller": 60}}}
    assert guard.unaccounted(report, 50) == [("origin.baugruppe", "UNDECLARED_KEY")]


def test_a_bare_string_inside_a_list_is_refused():
    """Found by attacking the first version: list items that were not dicts were never examined,
    so a list of strings sailed through."""
    flat = {"origin": {"baugruppe": {"top": ["Mueller GmbH"]}}}
    assert guard.unaccounted(flat, 50) == [("origin.baugruppe.top", "UNACCOUNTED_STRING")]
    nested = {"origin": {"baugruppe": {"top": [["Mueller GmbH"]]}}}
    assert guard.unaccounted(nested, 50) == [("origin.baugruppe.top", "UNACCOUNTED_STRING")]


def test_a_long_numeric_key_is_refused_but_years_and_quantile_points_are_not():
    """The first version admitted any all-digit key, so a serial number could travel as a key."""
    assert guard.unaccounted({"origin": {"baugruppe": {"1234567": 5}}}, 50) == [
        ("origin.baugruppe", "UNDECLARED_KEY")
    ]
    assert guard.unaccounted({"origin": {"baugruppe": {"2022": 5}}}, 50) == []
    # Months are not emitted by any section, so a year-month key is refused like any other.
    assert guard.unaccounted({"origin": {"baugruppe": {"2022-03": 5}}}, 50) == [
        ("origin.baugruppe", "UNDECLARED_KEY")
    ]
    quantiles = {"p1": 1, "p25": 1, "p999": 1, "max": 1}
    assert guard.unaccounted({"origin": {"baugruppe": quantiles}}, 50) == []


def test_a_string_where_none_is_declared_is_refused():
    report = {"origin": {"baugruppe": {"distinct": "Mueller"}}}
    assert guard.unaccounted(report, 50) == [("origin.baugruppe.distinct", "UNACCOUNTED_STRING")]


def test_a_year_is_accepted_but_a_longer_number_is_not():
    ok = {"origin": {"baugruppe": {"by_year": [{"value": "B-10", "year": "2022", "count": 60}]}}}
    assert guard.unaccounted(ok, 50) == []
    bad = {"origin": {"baugruppe": {"by_year": [{"value": "B-10", "year": "20007", "count": 60}]}}}
    assert guard.unaccounted(bad, 50) == [("origin.baugruppe.by_year.year", "UNACCOUNTED_STRING")]


def test_a_full_width_year_is_not_a_year():
    """\\d matches Unicode digits, so the first version of the guard accepted these."""
    wide = {
        "origin": {"baugruppe": {"by_year": [{"value": "B-10", "year": "２０２２", "count": 60}]}}
    }
    assert guard.unaccounted(wide, 50) == [("origin.baugruppe.by_year.year", "UNACCOUNTED_STRING")]


def test_declared_literals_must_have_the_declared_shape():
    good = {"source": {"filename": "export.csv", "sha256": "0" * 64}}
    assert guard.unaccounted(good, 50) == []
    bad = {"source": {"filename": "kunde-mueller.csv", "sha256": "0" * 64}}
    assert guard.unaccounted(bad, 50) == [("source.filename", "UNACCOUNTED_STRING")]


def test_assert_safe_raises_without_the_value_and_logs_it_locally():
    with pytest.raises(safety.SafetyViolation) as raised:
        guard.assert_safe(entry(value="Huber GmbH", count=60), 50)
    assert "Huber" not in str(raised.value)
    assert raised.value.code == "ENTITY_PATTERN_MATCH"
    assert "Huber GmbH" in safety.DETAIL_LOG.read_text(encoding="utf-8")


def test_below_floor_maps_to_the_floor_code():
    with pytest.raises(safety.SafetyViolation) as raised:
        guard.assert_safe(entry(value="B-90", count=3), 50)
    assert raised.value.code == "TOPVALUE_BELOW_MIN_FREQ"


def test_a_location_that_is_not_a_plain_path_degrades_instead_of_raising_valueerror():
    report = {"origin": {"Mueller GmbH": {"x": 1}}}
    with pytest.raises(safety.SafetyViolation) as raised:
        guard.assert_safe(report, 50)
    assert "Mueller" not in str(raised.value)


def test_a_tuple_or_any_non_json_container_is_refused():
    """Review finding, critical: only list and dict were walked, so a tuple (which json.dumps
    writes as a list) was never examined and a tuple of strings reached the file."""
    for report in (
        {"origin": {"top": [("Mueller GmbH",)]}},
        {"origin": {"top": ({"value": "Huber GmbH", "count": 1},)}},
        {"origin": {"top": {"Mueller GmbH"}}},
        {"origin": {"top": b"Mueller"}},
    ):
        assert [code for _, code in guard.unaccounted(report, 50)] == ["UNACCOUNTED_TYPE"]
    in_entry = {"origin": {"baugruppe": {"top": [{"value": ("Mueller GmbH",), "count": 60}]}}}
    assert guard.unaccounted(in_entry, 50) == [("origin.baugruppe.top.value", "UNACCOUNTED_TYPE")]


@pytest.mark.parametrize("root", ["Mueller", None, [], 7])
def test_the_root_must_be_a_dict(root):
    assert guard.unaccounted(root, 50) == [("<root>", "UNACCOUNTED_TYPE")]


@pytest.mark.parametrize("bad", [{1: 2}, {None: 1}, {(1, 2): 3}])
def test_a_non_string_key_is_refused_instead_of_raising(bad):
    assert guard.unaccounted(bad, 50) == [("<root>", "UNDECLARED_KEY")]


def test_a_cell_with_two_flagged_fields_reports_both():
    cell = {"value": "Huber GmbH", "model": "Mueller GmbH", "year": "2022", "count": 60}
    report = {"origin": {"baugruppe_model_year": {"cells": [cell]}}}
    assert guard.unaccounted(report, 50) == [
        ("origin.baugruppe_model_year.cells", "ENTITY_LIKE"),
        ("origin.baugruppe_model_year.cells", "ENTITY_LIKE"),
    ]


def test_a_serial_typed_into_a_code_field_is_refused():
    """The guard cannot know which field a builder should have used, but the sweep it shares with
    the builders now withholds a long identifier-like value from every code field."""
    for report in (
        {"origin": {"baugruppe": {"top": [{"value": "WVWZZZ1JZ3W386752", "count": 60}]}}},
        {"origin": {"vehicles": {"models": [{"model": "WVWZZZ1JZ3W386752", "count": 60}]}}},
    ):
        assert [code for _, code in guard.unaccounted(report, 50)] == ["ENTITY_LIKE"]


@pytest.mark.parametrize(
    ("path", "value", "accepted"),
    [
        ("provenance.code_commit", "abc1234", True),
        ("provenance.code_commit", "unknown", True),
        ("provenance.code_commit", "max.mustermann@firma.at", False),
        ("provenance.code_commit", "abc1234\n", False),
        ("provenance.image_digest", "sha256:" + "a" * 64, True),
        ("provenance.image_digest", "Maria@Gruber.at", False),
        ("suppression.section", "origin.baugruppe.withheld", True),
        ("suppression.section", "mueller", False),
        ("source.filename", "export.csv\n", False),
    ],
)
def test_declared_literals_are_matched_in_full_and_tightly(path, value, accepted):
    report: dict = {}
    node = report
    *parents, leaf = path.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
    if parents == ["suppression"]:
        report = {"suppression": [report["suppression"]]}
    assert (guard.unaccounted(report, 50) == []) is accepted


def test_a_four_digit_string_is_only_a_year_under_a_key_named_year():
    assert guard.unaccounted({"origin": {"baugruppe": {"distinct": "9999"}}}, 50) == [
        ("origin.baugruppe.distinct", "UNACCOUNTED_STRING")
    ]
    trailing = {
        "origin": {"baugruppe": {"by_year": [{"value": "B-10", "year": "2022\n", "count": 60}]}}
    }
    assert guard.unaccounted(trailing, 50) == [
        ("origin.baugruppe.by_year.year", "UNACCOUNTED_STRING")
    ]


@pytest.mark.parametrize("key", ["p0000", "p3", "max\n", "p25\n", "20223", "1234567"])
def test_only_real_quantile_points_and_years_are_structural_keys(key):
    assert guard.unaccounted({"origin": {"baugruppe": {key: 5}}}, 50) == [
        ("origin.baugruppe", "UNDECLARED_KEY")
    ]


def test_assert_safe_prints_nothing(capsys):
    with pytest.raises(safety.SafetyViolation):
        guard.assert_safe(entry(value="Huber GmbH", count=60), 50)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_raised_code_does_not_depend_on_traversal_order():
    leak = {"value": "Huber GmbH", "count": 60}
    low = {"value": "B-90", "count": 3}
    for entries in ([leak, low], [low, leak]):
        with pytest.raises(safety.SafetyViolation) as raised:
            guard.assert_safe({"origin": {"baugruppe": {"top": entries}}}, 50)
        assert raised.value.code == "ENTITY_PATTERN_MATCH"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_guard.py -v`
Expected: collection error, `cannot import name 'guard'`.

- [ ] **Step 3: Write the implementation**

Create `insight/guard.py`:

```python
"""Independent re-check of the finished report. Nothing leaves that this does not accept.

The builders already floor and sweep; this exists because a builder is only as safe as the
last person to edit it. It walks the finished dict and refuses any key that is not declared,
any string that is not accounted for, any value of a type JSON would not write as itself, and
any released value under the floor k or flagged by the sweep - calling `release.flagged`, the
same function the builders use, so the two cannot disagree about what should have been dropped.

It is deliberately NOT an extension of profiler.blessing, which is bound to profiler/schema.json
and to module-level path lists; changing those is a change to a safety control. For the same
reason it reuses the registered codes in profiler.safety rather than adding new ones: the guard's
own code (BELOW_FLOOR, ENTITY_LIKE, ...) goes into the local detail log beside the value.
"""

from __future__ import annotations

import re

from insight import release
from insight.texts import IDENTIFIER_KINDS
from profiler import safety
from profiler.stats import lengths

KEYS = frozenset(
    {
        "any_share",
        "any_share_after_cleaning",
        "baugruppe",
        "baugruppe_model_year",
        "blank_problem_text",
        "below_floor",
        "bigrams",
        "bigrams_omitted",
        "bigrams_withheld",
        "buckets",
        "bytes",
        "cells",
        "cluster_count",
        "code_commit",
        "concentration",
        "count",
        "coverage",
        "covered_share",
        "description",
        "distinct",
        "distinct_casefolded",
        "enabled",
        "entity_like",
        "fill",
        "gini",
        "identifiers",
        "image_digest",
        "kind",
        "largest_cluster_share",
        "length",
        "lengths",
        "min_frequency",
        "model",
        "models",
        "models_withheld",
        "origin",
        "passed",
        "prefix",
        "prefixes",
        "present",
        "problem",
        "problem_text",
        "provenance",
        "reason",
        "repeat_rate",
        "repetition",
        "row_count",
        "rows",
        "schema_version",
        "section",
        "selfcheck",
        "serial_prefixes_enabled",
        "serials",
        "sha256",
        "share",
        "share_in_clusters_at_least_k",
        "singleton_count",
        "solutions",
        "source",
        "stage",
        "suppression",
        "text",
        "tickets",
        "tickets_after_cleaning",
        "too_short",
        "tickets_per_serial_quantiles",
        "title",
        "titles",
        "token",
        "tokens_omitted",
        "tokens",
        "tokens_withheld",
        "top",
        "top1_share",
        "top5_share",
        "top10_share",
        "top_percent_share",
        "total",
        "unit",
        "value",
        "vehicle_years",
        "vehicle_years_withheld",
        "vehicles",
        "by_kind",
        "by_year",
        "by_year_withheld",
        "filename",
        "withheld",
        "year",
    }
)

# Keys that are structure rather than content: quantile points, "max" and four-digit years. No
# all-digit key is admitted, because a serial number could then travel as a dict key.
_STRUCTURAL_KEY = re.compile("|".join([*lengths.QUANTILE_POINTS, "max", "[0-9]{4}"]))
# ASCII digits only: \d would accept full-width and Arabic-Indic digits.
_YEAR_VALUE = re.compile("[0-9]{4}")

# What the operator may pass for provenance. Public so the CLI can refuse a bad value BEFORE any
# real data is read, instead of discovering it when the finished report is refused.
COMMIT = re.compile("[0-9a-f]{7,40}|unknown")
DIGEST = re.compile("sha256:[0-9a-f]{64}|unknown")

# Every section path a builder may report withheld rows for. A closed set, so a new withheld
# block has to be declared here, and test_every_declared_section_is_emitted fails if one is dead.
SECTIONS = (
    "origin.baugruppe.withheld",
    "origin.baugruppe.by_year_withheld",
    "origin.baugruppe_model_year.withheld",
    "origin.titles.tokens_withheld",
    "origin.titles.bigrams_withheld",
    "origin.vehicles.models_withheld",
    "origin.vehicles.vehicle_years_withheld",
    "origin.vehicles.serials.prefixes.withheld",
)

_KIND = re.compile("|".join(IDENTIFIER_KINDS))

# The only strings the report writes itself, blessed by PATH and constrained by SHAPE (matched
# with fullmatch, so a trailing newline does not pass), so the same text appearing anywhere else
# is still refused.
LITERALS = {
    "schema_version": re.compile("insight-[0-9]+"),
    "source.filename": re.compile("export\\.csv|<non-conforming>"),
    "source.sha256": re.compile("[0-9a-f]{64}"),
    "provenance.stage": re.compile("stage1-deterministic"),
    "provenance.code_commit": COMMIT,
    "provenance.image_digest": DIGEST,
    "suppression.section": re.compile("|".join(re.escape(s) for s in SECTIONS)),
    "suppression.reason": re.compile("below_floor|entity_like"),
    "text.lengths.unit": re.compile("whitespace_tokens"),
    "text.identifiers.problem.by_kind.kind": _KIND,
    "text.identifiers.solutions.by_kind.kind": _KIND,
}

# What a finished report may hold. A tuple, a set, bytes or any object is refused: json.dumps
# writes a tuple as a list, so one would reach the file without ever having been examined.
_LEAVES = (str, int, float, bool, type(None))

_Found = list[tuple[str, str, str]]


def _literal_ok(path: str, value: str) -> bool:
    pattern = LITERALS.get(path)
    if pattern is not None:
        return bool(pattern.fullmatch(value))
    # A year, and only under a key named year: four digits anywhere else is just a number
    # that happens to look like one.
    return path.endswith(".year") and bool(_YEAR_VALUE.fullmatch(value))


def _scan(node: object, path: str, k: int, found: _Found) -> None:
    if isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                # No list of bare strings is declared anywhere in a report: entries are dicts,
                # so a string here is unaccounted for whatever it says.
                found.append((path, "UNACCOUNTED_STRING", item))
            else:
                _scan(item, path, k, found)
        return
    if not isinstance(node, dict):
        if not isinstance(node, _LEAVES):
            found.append((path or "<root>", "UNACCOUNTED_TYPE", type(node).__name__))
        return
    released = [f for f in sorted(release.RELEASED_FIELDS) if isinstance(node.get(f), str)]
    count = node.get("count")
    for field in released:
        value = node[field]
        if not isinstance(count, int) or isinstance(count, bool):
            found.append((path, "MISSING_COUNT", value))
        elif count < k:
            found.append((path, "BELOW_FLOOR", value))
        elif release.flagged(field, value):
            found.append((path, "ENTITY_LIKE", value))
    for key, value in node.items():
        if not isinstance(key, str):
            found.append((path or "<root>", "UNDECLARED_KEY", repr(key)))
            continue
        known = key in KEYS or bool(_STRUCTURAL_KEY.fullmatch(key))
        if not known:
            found.append((path or "<root>", "UNDECLARED_KEY", key))
        # An undeclared key is corpus text, so it never becomes part of a location.
        child = (f"{path}.{key}" if path else key) if known else path
        if isinstance(value, str):
            if key not in released and not _literal_ok(child, value):
                found.append((child, "UNACCOUNTED_STRING", value))
        else:
            _scan(value, child, k, found)


def _found(report: object, k: int) -> _Found:
    if not isinstance(report, dict):
        return [("<root>", "UNACCOUNTED_TYPE", type(report).__name__)]
    found: _Found = []
    _scan(report, "", k, found)
    return sorted(found, key=lambda item: (item[0], item[1]))


def unaccounted(report: object, k: int = release.K) -> list[tuple[str, str]]:
    """(path, reason) for everything refused, in a stable order. Never the value."""
    return [(path, code) for path, code, _ in _found(report, k)]


def _safety_code(code: str) -> str:
    return "TOPVALUE_BELOW_MIN_FREQ" if code == "BELOW_FLOOR" else "ENTITY_PATTERN_MATCH"


def _violation(code: str, location: str, offenders: int) -> safety.SafetyViolation:
    try:
        return safety.SafetyViolation(code, location, offenders=offenders)
    except ValueError:
        # The location was not a plain schema path, so it may carry corpus text.
        return safety.SafetyViolation(code, "insight", offenders=offenders)


def assert_safe(report: object, k: int = release.K) -> None:
    """Raise SafetyViolation if anything is refused. Verbatim values go to the local log only.

    The raised code does not depend on traversal order: anything that is not merely a
    below-floor value outranks one that is, and the location is the first in sorted order.
    """
    found = _found(report, k)
    if not found:
        return
    for path, code, value in found:
        safety.detail(_safety_code(code), path, f"{code}: {value}")
    serious = [item for item in found if item[1] != "BELOW_FLOOR"]
    path, code, _ = (serious or found)[0]
    raise _violation(_safety_code(code), path, len(found))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_guard.py -v`
Expected: 43 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/guard.py tests/unit/test_insight_guard.py
git commit -m "feat(insight): a guard that re-checks the finished report with the builders' own rule" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The stand-in export and `report.build`

**Files:**
- Create: `tests/insight_standin.py`, `insight/report.py`
- Test: `tests/integration/test_insight_report.py`

- [ ] **Step 1: Write the stand-in**

Create `tests/insight_standin.py`:

```python
"""A synthetic 38-column export for the insight report, with planted leaks and an answer that
is known exactly because it is built from a plan, not drawn at random.

Kept apart from tests/conftest.py's stand-in on purpose: that one has no baugruppe field, and
adding one would shift counts the profiler's own tests pin.
"""

from __future__ import annotations

import csv
import json
import pathlib

from profiler.columns import EXPECTED_COLUMNS

K_TEST = 20
ROWS = 600

# (code, tickets). Rows divisible by 4 carry a Baugruppe, in this order: 150 rows, 25%.
BAUGRUPPE_PLAN = [("B-10", 60), ("B-20", 40), ("B-30", 25), ("B-90", 3), ("Huber GmbH", 22)]
MODELS = ["TX-2210", "TX-2240", "LR-45"]
FAULTS = [
    ("Hydraulikpumpe baut keinen Druck auf", "Druck geprueft, Pumpe getauscht"),
    ("Getriebe schaltet nicht", "Oel gewechselt"),
    ("Kuehlwasserverlust am Motor", "Schlauch ersetzt"),
    ("Bremsleitung undicht", ""),
    ("Motor startet nicht", "Neustart durchgefuehrt"),
]

# Planted leaks. None of these may appear in a report.
LEAK_SERIAL = "ZZLEAK77"  # one ticket: below the floor, and would be a bucket if it cleared
LEAK_EMAIL = "hans.mueller@example.de"  # in descriptions, which no section releases
SURNAME = "Bauer"  # appended to 60 titles: frequent, so only the entity sweep stops it


def _baugruppe_sequence() -> list[str]:
    return [code for code, n in BAUGRUPPE_PLAN for _ in range(n)]


def _envelope(fields: dict[str, str]) -> str:
    """Descriptors, JSON-encoded twice, as the real export wraps customData."""
    records = [
        {"group": "g", "key": k, "label": f"Feld {k}", "value": v, "text": v, "type": "string"}
        for k, v in fields.items()
    ]
    return json.dumps(json.dumps(records, ensure_ascii=False), ensure_ascii=False)


def build(path: pathlib.Path, rows: int = ROWS) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sequence = _baugruppe_sequence()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        for i in range(1, rows + 1):
            title, solution = FAULTS[i % len(FAULTS)]
            if i % 10 == 3:
                title = f"{title} {SURNAME}"
            description = f"{title}. Rueckruf an {LEAK_EMAIL}" if i % 25 == 0 else title
            fields = {"fehlercode": "1234-5"}
            if i % 4 == 0:
                fields["baugruppe"] = sequence[i // 4 - 1]
            blob = _envelope(fields)
            if i == 3:
                blob = "<<<" + blob  # one malformed row, counted by nobody and echoed nowhere
            residue = (i * 7) % 300
            serial = LEAK_SERIAL if i == 5 else f"SER{residue // 30}-{residue:04d}"
            row = dict.fromkeys(EXPECTED_COLUMNS, "")
            row.update(
                {
                    "id": i,
                    "title": title,
                    "description": description,
                    "solutions": solution,
                    "customData": blob,
                    "vehicleSerialNo": serial,
                    "vehicleModelId": MODELS[i % 3],
                    "vehicleYear": 2018 + i % 4,
                    "timestampCreated": f"{2022 + i % 2}-0{1 + i % 9}-10 08:30:00",
                    "merchantName": "Musterhaendler GmbH",
                    "contactEmail": LEAK_EMAIL,
                }
            )
            writer.writerow(row)
    return path
```

- [ ] **Step 2: Write the failing tests**

Create `tests/integration/test_insight_report.py`:

```python
import json
import random

import pytest

from insight import extract, guard, origin, report
from profiler import safety
from tests import insight_standin as standin

SOURCE = {"filename": "export.csv", "sha256": "0" * 64, "bytes": 1, "row_count": standin.ROWS}
PROVENANCE = {"code_commit": "abc1234", "image_digest": "sha256:" + "a" * 64}


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    path = standin.build(tmp_path_factory.mktemp("insight") / "export.csv")
    return extract.read_rows(path)


def build_with(rows, **overrides):
    options = {
        "source": SOURCE,
        "provenance": PROVENANCE,
        "k": standin.K_TEST,
        "serial_prefixes": True,
    }
    options.update(overrides)
    return report.build(rows, **options)


def dump(built):
    return json.dumps(built, ensure_ascii=False, allow_nan=False)


@pytest.fixture(scope="module")
def built(rows):
    return build_with(rows)


def walk_keys(node, found=None):
    found = set() if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            walk_keys(value, found)
    elif isinstance(node, list):
        for item in node:
            walk_keys(item, found)
    return found


def test_the_guard_accepts_what_the_builders_produced(built):
    assert guard.unaccounted(built, standin.K_TEST) == []
    assert built["selfcheck"] == {"passed": True}


def test_every_declared_key_is_used(built):
    """An allowlist entry that matches nothing reads as protection while doing none."""
    used = walk_keys(built)
    assert guard.KEYS - used == set(), sorted(guard.KEYS - used)


def test_no_planted_leak_reaches_the_report(built):
    text = json.dumps(built, ensure_ascii=False)
    assert "ZZLEAK" not in text  # the rare serial
    assert "SER1-0035" not in text  # a full serial
    assert standin.LEAK_EMAIL not in text
    assert "mueller" not in text.lower()
    assert "huber" not in text.lower()  # a frequent company-named Baugruppe
    assert "bauer" not in text.lower()  # a frequent surname in titles


def test_baugruppe_matches_the_plan_exactly(built):
    b = built["origin"]["baugruppe"]
    assert b["top"] == [
        {"value": "B-10", "count": 60},
        {"value": "B-20", "count": 40},
        {"value": "B-30", "count": 25},
    ]
    assert b["coverage"] == {"present": 150, "total": 600, "share": 0.25}
    assert b["distinct"] == 5
    assert b["withheld"]["below_floor"] == {"distinct": 1, "rows": 3}  # B-90
    assert b["withheld"]["entity_like"] == {"distinct": 1, "rows": 22}  # Huber GmbH
    assert b["by_year"] == [
        {"value": "B-10", "year": "2022", "count": 60},
        {"value": "B-20", "year": "2022", "count": 40},
        {"value": "B-30", "year": "2022", "count": 25},
    ]


def test_the_cross_tab_floors_cells_that_their_margins_would_have_released(built):
    """Rows divisible by 4 are all even, so every Baugruppe row is year 2022. B-10 spans rows
    4..240 whose i % 3 cycles evenly: three cells of exactly 20. B-20 and B-30 clear the floor
    as margins but split into cells under it, so they are withheld as cells."""
    cells = built["origin"]["baugruppe_model_year"]["cells"]
    assert len(cells) == 3
    assert {c["value"] for c in cells} == {"B-10"}
    assert {c["count"] for c in cells} == {20}
    # What was withheld is stated too: B-20 (40) + B-30 (25) + B-90 (3) + Huber GmbH (22) rows.
    withheld = built["origin"]["baugruppe_model_year"]["withheld"]["below_floor"]
    assert withheld["rows"] == 90


def test_serials_report_behaviour_and_prefix_buckets_only(built):
    s = built["origin"]["vehicles"]["serials"]
    assert s["distinct"] == 301  # 300 vehicles plus the planted rare one
    # Two tickets per vehicle, except the planted row and the vehicle whose other ticket it
    # replaced: 598 of 600 tickets belong to a vehicle with at least two.
    assert s["repeat_rate"] == round(598 / 600, 4)
    p = s["prefixes"]
    assert p["length"] == 4  # half of the shortest serial: 'ZZLEAK77' is 8, the rest 9
    assert {b["count"] for b in p["buckets"]} == {30}  # 30 VEHICLES each, not 60 tickets
    assert p["too_short"] == 0
    assert {b["prefix"] for b in p["buckets"]} == {f"SER{d}" for d in range(10)}
    assert max(len(b["prefix"]) for b in p["buckets"]) < 8


def test_the_ledger_states_what_was_withheld_even_when_it_is_nothing(built):
    ledger = {(e["section"], e["reason"]): e for e in built["suppression"]}
    below = ledger[("origin.baugruppe.withheld", "below_floor")]
    assert (below["distinct"], below["rows"]) == (1, 3)
    swept = ledger[("origin.titles.tokens_withheld", "entity_like")]
    assert swept["distinct"] >= 1 and swept["rows"] >= 60  # 'bauer'
    zero = ledger[("origin.vehicles.models_withheld", "below_floor")]
    assert (zero["distinct"], zero["rows"]) == (0, 0)


def test_provenance_records_how_the_report_was_made(built):
    assert built["provenance"] == {
        "stage": "stage1-deterministic",
        "min_frequency": standin.K_TEST,
        "serial_prefixes_enabled": True,
        **PROVENANCE,
    }


def test_text_evidence_is_present_and_labelled(built):
    assert built["text"]["lengths"]["unit"] == "whitespace_tokens"
    assert built["text"]["repetition"]["cluster_count"] >= 1
    # Five fault titles of 120 tickets each: all clustered, the largest a fifth of the corpus.
    assert built["text"]["repetition"]["share_in_clusters_at_least_k"] == 1.0
    assert built["text"]["repetition"]["largest_cluster_share"] == 0.2


def string_paths(node, path="", found=None):
    found = set() if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            string_paths(value, f"{path}.{key}" if path else key, found)
    elif isinstance(node, list):
        for item in node:
            string_paths(item, path, found)
    elif isinstance(node, str):
        found.add(path)
    return found


def test_every_literal_path_is_used(built):
    """Same trap as KEYS: a LITERALS path that matches nothing reads as protection while doing
    none."""
    assert set(guard.LITERALS) - string_paths(built) == set()


def test_every_declared_section_is_emitted(built):
    """The ledger names every withheld block, zeros included, so the closed list of section names
    must equal what the builders emit in both directions."""
    emitted = {entry["section"] for entry in built["suppression"]}
    assert emitted == set(guard.SECTIONS)


def test_the_report_does_not_depend_on_the_order_of_the_rows(rows, built):
    """Review finding: nothing pinned this, and an earlier defect (ties ordered by arrival) had
    made the output a function of the export's row order."""
    expected = dump(built)
    assert dump(build_with(rows[::-1])) == expected
    for seed in range(5):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        assert dump(build_with(shuffled)) == expected


def test_build_runs_the_guard_itself(rows, monkeypatch):
    """Review finding: deleting the guard call from build left every test green, because the
    guard was only ever called directly. A builder that leaks must be stopped by build."""
    monkeypatch.setattr(
        origin, "baugruppe", lambda tickets, k: {"top": [{"value": "Leak-Value", "count": 1}]}
    )
    with pytest.raises(safety.SafetyViolation):
        build_with(rows)


def test_build_refuses_a_poisoned_source(rows):
    with pytest.raises(safety.SafetyViolation):
        build_with(rows, source={**SOURCE, "filename": "Mueller Hans.pdf"})


def test_a_caller_cannot_change_the_report_after_it_was_guarded(rows):
    source = dict(SOURCE)
    provenance = dict(PROVENANCE)
    out = build_with(rows, source=source, provenance=provenance)
    source["filename"] = "Mueller Hans.pdf"
    provenance["code_commit"] = "Mueller"
    assert out["source"]["filename"] == "export.csv"
    assert out["provenance"]["code_commit"] == "abc1234"


def test_the_inputs_cannot_override_or_extend_what_the_build_computes(rows):
    with pytest.raises(ValueError, match="provenance"):
        build_with(rows, provenance={**PROVENANCE, "min_frequency": 999})
    with pytest.raises(ValueError, match="source"):
        build_with(rows, source={**SOURCE, "extra": "x"})
    with pytest.raises(ValueError, match="row_count"):
        build_with(rows, source={**SOURCE, "row_count": 1})


def test_the_report_is_strict_json_and_holds_no_raw_ticket_text(built):
    text = dump(built)
    json.loads(text)
    for raw in ("Hydraulikpumpe", "Druck geprueft", "Rueckruf", "Musterhaendler"):
        assert raw not in text


def test_the_baugruppe_ledger_reconciles_with_its_coverage(built):
    b = built["origin"]["baugruppe"]
    released = sum(entry["count"] for entry in b["top"])
    withheld = b["withheld"]["below_floor"]["rows"] + b["withheld"]["entity_like"]["rows"]
    assert released + withheld == b["coverage"]["present"]


def test_serial_prefixes_stay_off_unless_asked_for(rows):
    out = build_with(rows, serial_prefixes=False)
    assert out["origin"]["vehicles"]["serials"]["prefixes"] == {"enabled": False}
    assert out["provenance"]["serial_prefixes_enabled"] is False


def test_an_empty_export_still_builds_a_guarded_report():
    out = report.build(
        [], source={**SOURCE, "row_count": 0}, provenance=PROVENANCE, k=standin.K_TEST
    )
    assert out["selfcheck"] == {"passed": True}
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_insight_report.py -v`
Expected: collection error, `cannot import name 'report'`.

- [ ] **Step 4: Write the implementation**

Create `insight/report.py`:

```python
"""Assemble the report, record what was withheld, and refuse to return anything the guard
does not accept."""

from __future__ import annotations

import copy

from insight import crosstab, extract, guard, origin, release, texts

SCHEMA_VERSION = "insight-1"
STAGE = "stage1-deterministic"

# Exactly these, so a caller cannot smuggle a key in or override what the build computes.
SOURCE_KEYS = frozenset({"filename", "sha256", "bytes", "row_count"})
PROVENANCE_KEYS = frozenset({"code_commit", "image_digest"})


def _suppression(node: object, path: str = "") -> list[dict]:
    """Flatten every `withheld` block into ledger rows: section, reason, distinct, rows.

    A zero is emitted as a zero. A reader must be able to tell a section that had nothing to
    withhold from one the ledger forgot, which is the lesson of checks.roster.values_traced.

    Rows are per block, so a ticket withheld from two sections (a Baugruppe is counted once in
    its distribution and again in its by-year cells) appears in both. Do not sum across sections.
    A block with only one of the two reasons is a bug in a builder and raises instead of being
    silently dropped.
    """
    if isinstance(node, list):
        found: list[dict] = []
        for item in node:
            found.extend(_suppression(item, path))
        return found
    if not isinstance(node, dict):
        return []
    reasons = {"below_floor", "entity_like"} & node.keys()
    if len(reasons) == 1:
        raise ValueError(f"the withheld block at {path} has only one of its two reasons")
    if reasons:
        return [
            {"section": path, "reason": reason, **node[reason]}
            for reason in ("below_floor", "entity_like")
        ]
    found = []
    for key, value in node.items():
        found.extend(_suppression(value, f"{path}.{key}" if path else key))
    return found


def build(
    rows: list[dict[str, str]],
    *,
    source: dict,
    provenance: dict,
    k: int = release.K,
    serial_prefixes: bool = False,
) -> dict:
    # Checked and copied first. The report must not alias the caller's dicts (mutating them
    # after the guard ran would change a "guarded" report), and the caller must not be able to
    # override a value the build computes: provenance is spread FIRST, computed keys after.
    if set(source) != SOURCE_KEYS:
        raise ValueError("source must carry exactly filename, sha256, bytes and row_count")
    if set(provenance) != PROVENANCE_KEYS:
        raise ValueError("provenance must carry exactly code_commit and image_digest")
    if source["row_count"] != len(rows):
        raise ValueError("source.row_count does not match the rows")
    tickets = extract.tickets(rows)
    built = {
        "schema_version": SCHEMA_VERSION,
        "source": copy.deepcopy(source),
        "provenance": {
            **copy.deepcopy(provenance),
            "stage": STAGE,
            "min_frequency": k,
            "serial_prefixes_enabled": serial_prefixes,
        },
        "origin": {
            "baugruppe": origin.baugruppe(tickets, k),
            "vehicles": origin.vehicles(tickets, k, serial_prefixes),
            "titles": origin.titles(tickets, k),
            "baugruppe_model_year": crosstab.baugruppe_model_year(tickets, k),
        },
        "text": texts.build(tickets, k),
    }
    built["suppression"] = _suppression(built)
    built["selfcheck"] = {"passed": False}
    guard.assert_safe(built, k)
    built["selfcheck"] = {"passed": True}
    return built
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_insight_report.py -v`
Expected: 20 passed. If `test_every_declared_key_is_used` fails, the message lists the dead names: remove them from `guard.KEYS`, do not add a section to use them.

- [ ] **Step 6: Commit**

```bash
git add tests/insight_standin.py insight/report.py tests/integration/test_insight_report.py
git commit -m "feat(insight): assemble the report, with a suppression ledger and the guard last" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The CLI

**Files:**
- Create: `insight/__main__.py`
- Test: `tests/integration/test_insight_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_insight_cli.py`:

```python
import json
import os

import pytest

import insight.origin
from insight.__main__ import main
from profiler import safety
from tests import insight_standin as standin

DIGEST = "sha256:" + "a" * 64


def provenance_args():
    return ["--code-commit", "abc1234", "--image-digest", DIGEST]


def run(tmp_path, *extra, name="export.csv"):
    csv_path = standin.build(tmp_path / name)
    out = tmp_path / "out" / "report.json"
    argv = [
        "--csv",
        str(csv_path),
        "--out",
        str(out),
        "--min-frequency",
        str(standin.K_TEST),
        "--allow-weak-floor",
        *provenance_args(),
        *extra,
    ]
    return safety.run_scrubbed(main, argv), out


def test_a_run_writes_a_guarded_report_and_exits_zero(tmp_path, capsys):
    code, out = run(tmp_path)
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["selfcheck"] == {"passed": True}
    assert report["source"]["row_count"] == standin.ROWS
    assert report["source"]["filename"] == "export.csv"
    assert len(report["source"]["sha256"]) == 64
    assert report["provenance"]["code_commit"] == "abc1234"
    assert report["provenance"]["image_digest"] == DIGEST
    assert "columns_expected_missing=0" in capsys.readouterr().out
    assert not out.with_name(out.name + ".tmp").exists()


def test_serial_prefixes_are_off_by_default(tmp_path):
    _, out = run(tmp_path)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["provenance"]["serial_prefixes_enabled"] is False
    assert report["origin"]["vehicles"]["serials"]["prefixes"] == {"enabled": False}


def test_serial_prefixes_appear_only_when_asked_for(tmp_path):
    _, out = run(tmp_path, "--serial-prefixes")
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["origin"]["vehicles"]["serials"]["prefixes"]["enabled"] is True


def test_a_non_conforming_filename_is_withheld_not_echoed(tmp_path, capsys):
    code, out = run(tmp_path, name="kunde-mueller-export.csv")
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["source"]["filename"] == "<non-conforming>"
    assert "mueller" not in capsys.readouterr().out.lower()


def test_nothing_is_written_when_the_guard_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        insight.origin,
        "baugruppe",
        lambda tickets, k: {"top": [{"value": "Leak-Value", "count": 1}]},
    )
    code, out = run(tmp_path)
    assert code == 2
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "ABORT" in printed
    assert "Leak-Value" not in printed
    assert "Leak-Value" in safety.DETAIL_LOG.read_text(encoding="utf-8")


def test_an_empty_export_aborts_with_code_four(tmp_path, capsys):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("title,description\n", encoding="utf-8")
    out = tmp_path / "report.json"
    assert safety.run_scrubbed(main, ["--csv", str(csv_path), "--out", str(out)]) == 4
    assert not out.exists()
    assert "EMPTY_INPUT" in capsys.readouterr().out


def test_a_zero_byte_file_aborts_with_code_four(tmp_path, capsys):
    csv_path = tmp_path / "export.csv"
    csv_path.write_bytes(b"")
    out = tmp_path / "report.json"
    assert safety.run_scrubbed(main, ["--csv", str(csv_path), "--out", str(out)]) == 4
    assert "EMPTY_INPUT" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["1", "0", "-3"])
def test_a_floor_below_the_schema_minimum_is_refused(tmp_path, bad, capsys):
    csv_path = standin.build(tmp_path / "export.csv")
    out = tmp_path / "report.json"
    argv = ["--csv", str(csv_path), "--out", str(out), "--min-frequency", bad]
    assert safety.run_scrubbed(main, argv) == 4
    assert not out.exists()
    assert "BAD_ARGUMENT" in capsys.readouterr().out


def test_a_floor_below_the_release_floor_needs_an_explicit_flag(tmp_path, capsys):
    csv_path = standin.build(tmp_path / "export.csv")
    out = tmp_path / "report.json"
    base = ["--csv", str(csv_path), "--out", str(out), "--min-frequency", "5"]
    assert safety.run_scrubbed(main, base) == 4
    assert not out.exists()
    assert "--allow-weak-floor" in capsys.readouterr().out
    assert safety.run_scrubbed(main, [*base, "--allow-weak-floor"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["provenance"]["min_frequency"] == 5


@pytest.mark.parametrize(
    ("flag", "bad"),
    [
        ("--code-commit", "Max.Mustermann@firma.at"),
        ("--code-commit", "abc12"),
        ("--image-digest", "latest"),
        ("--image-digest", "sha256:abc"),
    ],
)
def test_a_provenance_value_the_guard_would_refuse_aborts_before_any_data_is_read(
    tmp_path, flag, bad, capsys
):
    csv_path = standin.build(tmp_path / "export.csv")
    out = tmp_path / "report.json"
    argv = ["--csv", str(csv_path), "--out", str(out), flag, bad]
    assert safety.run_scrubbed(main, argv) == 4
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "BAD_ARGUMENT" in printed and flag in printed
    assert bad not in printed


def test_out_is_never_the_input_under_any_spelling(tmp_path, capsys):
    """Review finding, critical: nothing stopped --out being the input, so the real export, which
    cannot be fetched again inside the window, was replaced by the report. Same path, a lexically
    different path, a symlink and a hardlink all pointed at it."""
    csv_path = standin.build(tmp_path / "export.csv")
    before = csv_path.read_bytes()
    (tmp_path / "sub").mkdir()
    (tmp_path / "link").symlink_to(csv_path)
    (tmp_path / "hard").hardlink_to(csv_path)
    for out in (
        csv_path,
        tmp_path / "sub" / ".." / "export.csv",
        tmp_path / "link",
        tmp_path / "hard",
    ):
        argv = ["--csv", str(csv_path), "--out", str(out), "--allow-weak-floor"]
        assert safety.run_scrubbed(main, argv) == 4
        assert csv_path.read_bytes() == before
        assert "would overwrite" in capsys.readouterr().out


def test_a_failed_run_leaves_no_stale_report_behind(tmp_path):
    """Review finding: an old report claiming selfcheck.passed survived a run that failed."""
    csv_path = standin.build(tmp_path / "export.csv")
    out = tmp_path / "report.json"
    out.write_text(json.dumps({"selfcheck": {"passed": True}}), encoding="utf-8")
    argv = ["--csv", str(csv_path), "--out", str(out), "--code-commit", "not-a-commit"]
    assert safety.run_scrubbed(main, argv) == 4
    assert not out.exists()
    missing = tmp_path / "no-such-input"
    out.write_text(json.dumps({"selfcheck": {"passed": True}}), encoding="utf-8")
    assert safety.run_scrubbed(main, ["--csv", str(missing), "--out", str(out)]) == 4
    assert not out.exists()


def test_a_failed_write_leaves_neither_a_report_nor_a_temporary_file(tmp_path, monkeypatch):
    def refuse(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    code, out = run(tmp_path)
    assert code == 3
    assert not out.exists()
    assert not out.with_name(out.name + ".tmp").exists()


def test_a_missing_input_is_reported_without_its_path(tmp_path, capsys):
    out = tmp_path / "report.json"
    argv = ["--csv", str(tmp_path / "secret-client-name"), "--out", str(out)]
    assert safety.run_scrubbed(main, argv) == 4
    printed = capsys.readouterr().out
    assert "MISSING_INPUT" in printed
    assert "secret-client-name" not in printed


def test_a_file_that_is_not_the_export_aborts_instead_of_producing_an_empty_report(
    tmp_path, capsys
):
    """Review finding: a semicolon-delimited copy, or a different export, produced an exit-0,
    guard-passing, all-zero report that an operator with no AI to ask would accept."""
    export = standin.build(tmp_path / "export.csv").read_text(encoding="utf-8")
    semicolons = tmp_path / "semi" / "export.csv"
    semicolons.parent.mkdir()
    semicolons.write_text(export.replace(",", ";"), encoding="utf-8")
    foreign = tmp_path / "foreign" / "export.csv"
    foreign.parent.mkdir()
    foreign.write_text("foo,bar,baz\n1,2,3\n4,5,6\n", encoding="utf-8")
    for path in (semicolons, foreign):
        out = tmp_path / "report.json"
        assert safety.run_scrubbed(main, ["--csv", str(path), "--out", str(out)]) == 4
        assert not out.exists()
        printed = capsys.readouterr().out
        assert "WRONG_INPUT" in printed
        assert "foo" not in printed


@pytest.mark.parametrize(
    "argv", [["--min-frequency", "not-a-number"], ["--no-such-flag", "secret-value"], []]
)
def test_argument_errors_exit_four_and_never_echo_the_value(tmp_path, argv, capsys):
    csv_path = standin.build(tmp_path / "export.csv")
    full = ["--csv", str(csv_path), "--out", str(tmp_path / "r.json"), *argv] if argv else []
    assert safety.run_scrubbed(main, full) == 4
    captured = capsys.readouterr()
    assert "BAD_ARGUMENT" in captured.out
    assert "not-a-number" not in captured.out + captured.err
    assert "secret-value" not in captured.out + captured.err


def test_help_exits_zero(capsys):
    assert safety.run_scrubbed(main, ["--help"]) == 0
    assert "--allow-weak-floor" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_insight_cli.py -v`
Expected: collection error, `No module named 'insight.__main__'`.

- [ ] **Step 3: Write the implementation**

Create `insight/__main__.py`:

```python
"""Insight report, stage 1. Runs inside an airlock window: no network, no model, no GPU.

    python -m insight --csv export --out report.json [--serial-prefixes]

Run by a human with no AI to help, on real data, so every failure is one coded line and never a
value, and a run that does not produce a guarded report leaves NO report behind: a stale file
from an earlier run is removed first, and the report is written under a temporary name and moved
into place, so a half-written file can never look finished. `--out` may never be the input.

Exit codes: 0 ok, 2 the guard refused (profiler.safety), 3 unexpected failure (profiler.safety),
4 the arguments or the input are wrong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

from insight import extract, guard, release, report
from profiler import safety
from profiler.columns import EXPECTED_COLUMNS
from profiler.stats import vocab

# Without these the report would be an all-zero artifact that looks like a result. A count of
# how many are missing is safe to print; their names are not needed and not printed.
REQUIRED_COLUMNS = (
    "title",
    "description",
    "solutions",
    "customData",
    "vehicleSerialNo",
    "vehicleModelId",
    "vehicleYear",
    "timestampCreated",
)


class _BadArguments(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's own text echoes the offending value, which may be a path or a string.
        raise _BadArguments


def _abort(code: str, message: str) -> int:
    print(f"ABORT {code} {message}", flush=True)
    return 4


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    """True if `a` and `b` are the same file under any spelling, symlink or hardlink."""
    if a.resolve() == b.resolve():
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="insight", allow_abbrev=False)
    parser.add_argument("--csv", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--min-frequency", type=int, default=release.K)
    # A floor below the release floor needs saying twice: a typo of 5 for 50 would otherwise
    # run a whole window with a weak floor and nothing but a number in the artifact to show it.
    parser.add_argument("--allow-weak-floor", action="store_true")
    # Off unless asked: vehicleSerialNo is on profiler.selfcheck.DENYLISTED_COLUMNS, and
    # releasing even a prefix is a loosening only the operator may choose.
    parser.add_argument("--serial-prefixes", action="store_true")
    parser.add_argument("--code-commit", default="unknown")
    parser.add_argument("--image-digest", default="unknown")
    try:
        args = parser.parse_args(argv)
    except _BadArguments:
        return _abort("BAD_ARGUMENT", "the arguments were not understood; run with --help")
    except SystemExit as exc:  # --help
        return 0 if exc.code in (0, None) else _abort("BAD_ARGUMENT", "see --help")

    # The one irreversible mistake, refused before anything else is touched: the export cannot
    # be fetched again inside the window.
    if _same_file(args.out, args.csv):
        return _abort("BAD_ARGUMENT", "--out is the input file and would overwrite it")
    # A report left by an earlier run must not survive a run that fails: it would still claim
    # selfcheck.passed. Whatever happens next, no output exists until a guarded one is written.
    args.out.unlink(missing_ok=True)

    if args.min_frequency < vocab.MIN_FREQUENCY_FLOOR:
        return _abort(
            "BAD_ARGUMENT",
            f"--min-frequency={args.min_frequency} is below the minimum of "
            f"{vocab.MIN_FREQUENCY_FLOOR}",
        )
    if args.min_frequency < release.K and not args.allow_weak_floor:
        return _abort(
            "BAD_ARGUMENT",
            f"--min-frequency={args.min_frequency} is below the release floor {release.K}; "
            "pass --allow-weak-floor only for a rehearsal",
        )

    # Provenance is checked BEFORE any real data is read: a value the guard would refuse at the
    # end should cost nothing, not a whole airlock window. The value is never echoed.
    for flag, value, pattern, form in (
        ("--code-commit", args.code_commit, guard.COMMIT, "7 to 40 hex characters or 'unknown'"),
        ("--image-digest", args.image_digest, guard.DIGEST, "sha256:<64 hex> or 'unknown'"),
    ):
        if not pattern.fullmatch(value):
            return _abort("BAD_ARGUMENT", f"{flag} must be {form}")

    if not args.csv.is_file():
        return _abort("MISSING_INPUT", "the input file does not exist or is not a file")
    rows = extract.read_rows(args.csv)
    if not rows:
        return _abort(
            "EMPTY_INPUT",
            "the export parsed to 0 data rows - check the transfer and the delimiter "
            "before re-running",
        )
    absent = sum(1 for column in REQUIRED_COLUMNS if column not in rows[0])
    if absent:
        return _abort(
            "WRONG_INPUT",
            f"{absent} of {len(REQUIRED_COLUMNS)} required columns are missing - "
            "wrong file or wrong delimiter",
        )
    missing = len(set(EXPECTED_COLUMNS) - set(rows[0]))

    # The filename reaches the artifact, so an export named after the client would put that
    # name in the one file an AI may read. Withheld rather than left to operator discipline.
    conforming = args.csv.name == "export.csv"
    if not conforming:
        print("NOTE source filename was not 'export.csv' and has been withheld", flush=True)
    source = {
        "filename": args.csv.name if conforming else "<non-conforming>",
        "sha256": _sha256(args.csv),
        "bytes": args.csv.stat().st_size,
        "row_count": len(rows),
    }
    built = report.build(
        rows,
        source=source,
        provenance={"code_commit": args.code_commit, "image_digest": args.image_digest},
        k=args.min_frequency,
        serial_prefixes=args.serial_prefixes,
    )

    # Written under a temporary name and moved into place, so a kill or a full disk can leave
    # a clearly partial `.tmp` file but never a truncated report that looks finished.
    data = json.dumps(built, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(args.out.name + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, args.out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    # Paths and counts only - never a field value.
    print(f"wrote {args.out} ({len(data)} bytes)")
    print(
        f"rows={source['row_count']} columns_expected_missing={missing} "
        f"selfcheck_passed={built['selfcheck']['passed']} ledger_rows={len(built['suppression'])}"
    )
    return 0


if __name__ == "__main__":
    # Never let a raw traceback reach stdout: a decode or csv error quotes the input.
    sys.exit(safety.run_scrubbed(main))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_insight_cli.py -v`
Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
git add insight/__main__.py tests/integration/test_insight_cli.py
git commit -m "feat(insight): CLI that writes nothing unless the guard accepts" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Whole-suite verification

- [ ] **Step 1: Run the new tests together**

Run: `.venv/bin/python -m pytest tests/unit/test_insight_release.py tests/unit/test_insight_extract.py tests/unit/test_insight_origin.py tests/unit/test_insight_crosstab.py tests/unit/test_insight_texts.py tests/unit/test_insight_guard.py tests/integration/test_insight_report.py tests/integration/test_insight_cli.py -v`
Expected: 176 passed.

- [ ] **Step 2: Run lint and format**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: `All checks passed!` and no files needing reformat. If format reports files, run `.venv/bin/ruff format insight tests` and re-check.

- [ ] **Step 3: Run the full suite and compare to baseline**

Run: `.venv/bin/python -m pytest -q`
Expected: no new failures. The pre-existing failure `test_the_test_suite_does_not_dirty_the_quarantine` is the operator's quarantine file and is not caused by this work. Report the totals as measured; do not paraphrase them.

- [ ] **Step 4: Prove the guard can fail (red-green on the whole pipeline)**

In a scratch Python file under the scratchpad directory (not in the repo; keep the stand-in path inside the file, never on a command line), build the stand-in report twice:

1. With `k=20` and confirm `guard.unaccounted(built, 20) == []`.
2. With `k=1`, replacing `insight.report.guard.assert_safe` by a no-op for that one call (a `k=1` build passes its own guard, because the guard is handed the same `k`). Confirm `guard.unaccounted(weak, 20)` reports `BELOW_FLOOR`.

This shows the guard judges a report by the floor it is *handed*, not by what the builders did. Measured while writing this plan: the weak report was refused at 20 with `['BELOW_FLOOR']`.

**What it does not show, stated so it is not assumed:** the CLI hands builders and guard the same `--min-frequency`, as `python -m profiler` does, and accepts any value of 2 or more so the small stand-in can run. A run started with a weak floor is therefore weak end to end. The recorded `provenance.min_frequency` makes that visible in the artifact, and Plan 3's `window.sh` must pin the real value at 50 rather than leave it to the operator.

- [ ] **Step 5: Record the result**

Append one dated entry to `docs/STATE.md` naming what shipped, the commit range, the measured test totals from Step 3, and the two operator decisions flagged at the top of this plan. Commit:

```bash
git add docs/STATE.md
git commit -m "docs: insight stage 1 shipped; serial prefixes await an operator ruling" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Follow-on plans (not part of this plan)

**Plan 2 — Stage 2, the model stage** (`insight/clusters.py`, `labels.py`, `review.py`, `evidence.py`). e5 embeddings on the sealed GPU path reusing `profiler.gate.embedder.E5Embedder`; hierarchical clusters with seed and threshold stability (adjusted Rand index); LLM label candidates through the existing vLLM client (`fixtures/llm.py`); the automated scrub (no digits, no serial-like shapes, no e-mail or phone, no capitalised non-dictionary word, at most six words); the human review file and `approved_labels.json`; the solution-type taxonomy derived from reviewed labels; cluster x solution-type matrix, solution diversity per cluster, clusters with no usable solution; leave-one-out coverage, field ablation, narrowing value; the real e5 truncation share. Extends `guard.KEYS` and `LITERALS` for `labels`, and adds a `label` released field whose sweep is the scrub.

**Plan 3 — The window** (`infra/profiler/window.sh` window `d`, `Dockerfile`, `rehearse-window-d.sh`, runbook section, `fetch --clean` shred list, HTML view). `window.sh` pinning `--min-frequency 50` and leaving `--serial-prefixes` to the operator's explicit ruling, the read-only HF-cache mount for the labelling model, GPU claim by UUID, thread cap, the stale-image guard from finding 20, assertions rather than notes for provenance fields, and the static HTML over `report.json` (dataviz skill).

Plan 2 needs a worked example of the label scrub against adversarial labels before any real window, so write its tests first.

---

## Self-review

**Spec coverage.**

| Spec requirement | Task |
|---|---|
| Section 0: provenance, suppression ledger | 8 (`provenance`, `suppression`); model identities deferred to Plan 2 |
| 1: Baugruppe distribution, concentration, trend, coverage | 4 |
| 1: Title content (amended to floored tokens and bigrams) | 4, spec amendment in 1 |
| 1: Vehicle quantiles, repeat rate, top-1% share, prefix buckets only | 4 |
| 1: Cross-tabs with cells floored | 5 |
| 4: Boilerplate/template share | 6 (`repetition`) |
| 4: Identifier density | 6 |
| 4: Token lengths | 6, labelled as whitespace tokens, e5 share deferred |
| Safety: blessed strings, cell floors, tokens swept, serial rules | 2, 7 |
| Testing: planted-leak stand-in, cell-floor test | 8 |
| Clusters, labels, review, solutions, coverage/ablation/narrowing, human bundle | Plan 2 |
| Window, rehearsal, shred list, HTML | Plan 3 |

**Placeholder scan.** No `TBD`/`TODO`; every code step carries the code. Task 10 Step 4 describes a scratch script rather than listing it because it is a one-off check, not committed work.

**Type consistency.** `release.release(counts, fields, k)` and `release.flagged(field, value)` are used identically in `origin`, `crosstab` and `guard`. `Ticket` fields (`title, description, solutions, baugruppe, serial, model, created_year, vehicle_year`) match between `extract`, the test helpers `mk`, and `crosstab`. The entry field names `value`, `model`, `prefix`, `token` match `release.RELEASED_FIELDS`. Section keys emitted by `origin`, `crosstab`, `texts` are all in `guard.KEYS`, and `test_every_declared_key_is_used` enforces the converse.
