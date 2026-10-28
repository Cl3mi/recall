# Dev3 Vehicle Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the code that (1) extracts a hand-reviewable, k-floored problem catalog from the real export and (2) generates three synthetic vehicles of 150-200 tickets each from that catalog alone, with ground-truth labels for retrieval evaluation.

**Architecture:** Two new top-level packages beside `insight/` and `fixtures/`. `catalog/` is Stage 1: it clusters eligible tickets semantically (e5 embeddings + k-means), has a local LLM draft one abstract recipe per cluster, scrubs it, drops anything that copies ticket text, and a closed-allowlist guard decides what may be released. `dev3/` is Stage 2: it reads only the released catalog, plans three vehicle timelines, has an LLM write title/description/solutions per ticket from a recipe plus a persona, renders the 38 export columns, and verifies the result. Everything is built and tested on synthetic stand-ins; only Stage 1's real run needs an airlock window, and that wiring is a separate plan (see "Out of scope").

**Tech Stack:** Python 3.12, numpy, scipy (`scipy.cluster.vq.kmeans2`), pytest, ruff; reuses `insight.extract`, `insight.quality`, `insight.names`, `profiler.entities`, `profiler.gate.embedder`, `recall.sealed`, `recall.clean.pipeline`, `fixtures.llm` and `fixtures.render`/`fixtures.values`.

Spec: `docs/superpowers/specs/2026-10-21-dev3-vehicle-fixture-design.md`.

**Run tests with** `.venv/bin/python -m pytest <path> -v` (`uv` is gone from the workstation). **Lint with** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`.

## Corrections to the spec, found while reading the code

1. **Stage 1 clusters semantically, not with `groups()`.** `profiler.stats.clusters.groups` is MinHash near-duplicate grouping, and `insight.quality.grades` already marks a problem near-duplicate cluster of `k` or more as `templated` noise. A recurring *problem* described in varied words is a semantic cluster, so Stage 1 uses e5 embeddings + k-means with a fixed K. The spec text is updated to match.
2. **The existing fixture has no `vehicleSerialNo`.** `fixtures/render.py::row` never fills it, so same-serial history cannot be tested with it. `dev3/rows.py` fills the vehicle columns.
3. **The n-gram overlap check cannot run off the box.** Copying from the *released* catalog is not a leak (the operator approved it). The real copy check (a recipe string sharing a 5-word run with a member ticket) runs in Stage 1 where the tickets are, in `catalog/verbatim.py`. Stage 2's verifier checks PII patterns, structure and per-vehicle profile shape instead.
4. **`customData` carries only `fehlercode`.** Baugruppe ids are opaque and the catalog does not release them, so Stage 2 does not invent them.
5. **Lint scope.** `tools/guard/recall_guard/lint.py` `SCOPE_PREFIXES` covers `src/`, `profiler/`, `insight/` and `fixtures/` only. `catalog/` sees real rows in the window, so it should be added. The guard is not ours to change: **ask the operator to add `catalog/`** (Task 0 reminder). Until then `catalog/` follows rule 4 by hand: every output goes through `recall.sealed.sealed_path`.

## File structure

| File | Responsibility |
|---|---|
| `catalog/__init__.py` | empty |
| `catalog/schema.py` | constants: caps, allowed keys, slots, tones |
| `catalog/scrub.py` | strip identifying strings from a phrase; `is_clean` |
| `catalog/verbatim.py` | 5-word run detector against a ticket corpus |
| `catalog/guard.py` | closed-allowlist check of a finished catalog; returns coded paths only |
| `catalog/select.py` | eligibility, semantic clustering, release floors -> `Candidate`s |
| `catalog/stats.py` | per-recipe style statistics and co-occurrence, whole numbers only |
| `catalog/draft.py` | LLM prompt, tolerant JSON parse, scrub, shape and copy checks |
| `catalog/build.py` | glue: candidates -> recipes -> catalog dict |
| `catalog/__main__.py` | CLI: `build` (writes the draft) and `release` (guard, then writes the catalog) |
| `dev3/__init__.py` | empty |
| `dev3/profiles.py` | the three vehicle profiles |
| `dev3/personas.py` | persona and solution-mode definitions, workflow sentences |
| `dev3/planner.py` | timeline and recipe plan per vehicle |
| `dev3/writer.py` | prompt, `EchoClient` (GPU-free), parser, `write()` |
| `dev3/rows.py` | one export row (38 columns) and the label record |
| `dev3/verify.py` | structural, PII and profile-shape checks |
| `dev3/standin.py` | tracked synthetic stand-in catalog (guard-valid) |
| `dev3/__main__.py` | CLI |
| `tests/catalog_corpus.py` | synthetic tickets for Stage 1 tests |
| `tests/unit/test_catalog_*.py`, `tests/unit/test_dev3_*.py` | tests |

---

### Task 0: Branch and packaging

**Files:**
- Modify: `pyproject.toml` (the `packages` line under `[tool.hatch.build.targets.wheel]`)

- [ ] **Step 1: Create the branch**

```bash
git switch -c feat/dev3-fixture
```

- [ ] **Step 2: Declare the two packages**

In `pyproject.toml` change

```toml
packages = ["src/recall", "profiler", "fixtures", "insight"]
```

to

```toml
packages = ["src/recall", "profiler", "fixtures", "insight", "catalog", "dev3"]
```

- [ ] **Step 3: Create the empty package markers**

```bash
mkdir -p catalog dev3
: > catalog/__init__.py
: > dev3/__init__.py
```

- [ ] **Step 4: Verify imports and commit**

Run: `.venv/bin/python -c "import catalog, dev3"` Expected: no output.

```bash
git add pyproject.toml catalog/__init__.py dev3/__init__.py docs/superpowers/specs/2026-10-21-dev3-vehicle-fixture-design.md docs/superpowers/plans/2026-10-21-dev3-vehicle-fixture.md
git commit -m "chore(dev3): spec, plan and empty catalog and dev3 packages"
```

**Reminder for the operator (not an agent step):** add `catalog/` to `SCOPE_PREFIXES` in `tools/guard/recall_guard/lint.py` (maintain the guard with `RECALL_GUARD_DEV=1`).

---

### Task 1: Schema constants

**Files:**
- Create: `catalog/schema.py`
- Test: `tests/unit/test_catalog_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_schema.py
from catalog import schema


def test_the_quantile_names_never_include_the_extremes():
    assert schema.QUANTILES == ("p25", "p50", "p75")


def test_every_cap_is_positive_and_ordered():
    assert 0 < schema.MIN_STEPS <= schema.MAX_STEPS
    assert 0 < schema.MIN_TEMPLATES <= schema.MAX_TEMPLATES
    assert schema.MAX_PHRASE > 0 and schema.MAX_STEP > 0 and schema.MAX_TEMPLATE > 0


def test_a_recipe_has_no_free_text_field_beyond_the_declared_ones():
    assert "title" not in schema.RECIPE_KEYS
    assert "description" not in schema.RECIPE_KEYS
    assert "solutions" not in schema.RECIPE_KEYS
    assert "serial" not in schema.RECIPE_KEYS
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_schema.py -v` Expected: FAIL, `ImportError: cannot import name 'schema'`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/schema.py
"""What a released recipe may contain. Constants only; catalog/guard.py enforces them."""

from __future__ import annotations

SCHEMA_VERSION = 1

MAX_PHRASE = 80
MAX_STEP = 140
MAX_TEMPLATE = 80
MIN_STEPS, MAX_STEPS = 2, 6
MIN_TEMPLATES, MAX_TEMPLATES = 3, 5
MAX_CO_OCCURS = 3

# The only angle-bracket tokens a title template may contain.
SLOTS = ("<component>", "<symptom>")
TONES = ("terse", "neutral", "verbose")
# Coarse classes of workflow note; the wording lives in dev3/personas.py, not here.
BOILERPLATE = ("callback", "closing", "warranty", "goodwill", "duplicate_ref")
# Never p1 or max: those are single tickets.
QUANTILES = ("p25", "p50", "p75")

CATALOG_KEYS = frozenset({"schema_version", "k", "min_vehicles", "min_dealers", "recipes"})
RECIPE_KEYS = frozenset(
    {
        "recipe_id",
        "support",
        "vehicles",
        "dealers",
        "component",
        "symptom",
        "cause",
        "fix_steps",
        "title_templates",
        "description_style",
        "solution_style",
        "fehlercode_shape",
        "recurrence_gap_days",
        "co_occurs_with",
    }
)
DESCRIPTION_KEYS = frozenset({"fill", "words", "tone"})
SOLUTION_KEYS = frozenset({"words", "boilerplate"})
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_schema.py -v` Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add catalog/schema.py tests/unit/test_catalog_schema.py
git commit -m "feat(catalog): recipe schema constants"
```

---

### Task 2: Scrub

**Files:**
- Create: `catalog/scrub.py`
- Test: `tests/unit/test_catalog_scrub.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_scrub.py
import pytest

from catalog import scrub
from insight import names

FIRST = sorted(names.FIRST_NAMES)[0].capitalize()


@pytest.mark.parametrize(
    "dirty",
    [
        "Mail an kunde@example.test senden",
        "Rueckruf unter +49 171 1234567 vereinbart",
        "Am 12.03.2024 getauscht",
        "Teil 1234.56789 verbaut",
        "Seriennummer A123456789012 geprueft",
        "siehe http://example.test/x",
        f"{FIRST} hat angerufen",
    ],
)
def test_identifying_strings_are_removed(dirty):
    cleaned = scrub.scrub(dirty)
    assert cleaned != dirty
    assert scrub.is_clean(cleaned)


def test_a_plain_phrase_is_untouched():
    phrase = "Stecker am Display reinigen und Kontakte pruefen"
    assert scrub.scrub(phrase) == phrase
    assert scrub.is_clean(phrase)


def test_is_clean_is_false_for_a_dirty_phrase():
    assert not scrub.is_clean("Teil 1234.56789 verbaut")


def test_whitespace_is_normalised():
    assert scrub.scrub("  Dichtung   tauschen ") == "Dichtung tauschen"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_scrub.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/scrub.py
"""Remove what could identify a person, a vehicle, a part or a dealer from a recipe phrase.

Deliberately blunt: it also removes harmless things such as a thread size like `M12`. A recipe
that loses a word is still a recipe; one that keeps an identifier is a leak.
"""

from __future__ import annotations

import re

from insight import names
from profiler import entities

_PATTERNS = (
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"\S+@\S+"),
    re.compile(r"\+?\d[\d\s/().-]{5,}\d"),
    re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?"),
    re.compile(r"\b[A-Za-z]{0,3}\d[\w-]*\d\b"),
    re.compile(r"\d{4,}"),
)
_EDGE = ".,;:()[]\"'!?"


def normalise(text: str) -> str:
    return " ".join(text.split())


def _is_name(word: str) -> bool:
    bare = word.strip(_EDGE)
    return bool(bare) and (
        names.contains_first_name(bare)
        or names.contains_surname(bare)
        or entities.looks_like_named_entity(bare)
    )


def scrub(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(" ", text)
    return " ".join(word for word in text.split() if not _is_name(word))


def is_clean(text: str) -> bool:
    return scrub(text) == normalise(text)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_scrub.py -v` Expected: all pass. If `test_a_plain_phrase_is_untouched` fails because one of its words is on a name list, replace that word in the test with a neutral one; do not edit the name lists.

- [ ] **Step 5: Commit**

```bash
git add catalog/scrub.py tests/unit/test_catalog_scrub.py
git commit -m "feat(catalog): scrub identifying strings from recipe phrases"
```

---

### Task 3: Verbatim detector

**Files:**
- Create: `catalog/verbatim.py`
- Test: `tests/unit/test_catalog_verbatim.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_verbatim.py
from catalog import verbatim

TICKET = "Die Dichtung an der Pumpe wurde getauscht und der Druck kontrolliert"


def test_a_five_word_run_from_a_ticket_is_a_copy():
    corpus = verbatim.word_ngrams(TICKET)
    assert verbatim.copies(["Dichtung an der Pumpe wurde ersetzt"], corpus)


def test_a_paraphrase_is_not_a_copy():
    corpus = verbatim.word_ngrams(TICKET)
    assert not verbatim.copies(["Pumpendichtung erneuern, Druck pruefen"], corpus)


def test_short_phrases_are_never_flagged():
    corpus = verbatim.word_ngrams(TICKET)
    assert not verbatim.copies(["Dichtung an der Pumpe"], corpus)


def test_case_and_punctuation_do_not_hide_a_copy():
    corpus = verbatim.word_ngrams(TICKET)
    assert verbatim.copies(["DICHTUNG, an der Pumpe, wurde getauscht!"], corpus)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_verbatim.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/verbatim.py
"""Detect a recipe string that repeats a run of words from a real ticket.

Strings under N words are never flagged: a component name or a short symptom cannot identify a
ticket, and flagging them would reject every recipe.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

N = 5
_WORD = re.compile(r"\w+")


def word_ngrams(text: str, n: int = N) -> set[tuple[str, ...]]:
    words = [w.casefold() for w in _WORD.findall(text)]
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def copies(strings: Iterable[str], corpus: set[tuple[str, ...]], n: int = N) -> bool:
    return any(word_ngrams(s, n) & corpus for s in strings)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_verbatim.py -v` Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add catalog/verbatim.py tests/unit/test_catalog_verbatim.py
git commit -m "feat(catalog): detect recipe strings copied from tickets"
```

---

### Task 4: Catalog guard

**Files:**
- Create: `catalog/guard.py`
- Test: `tests/unit/test_catalog_guard.py`

The guard returns lines of the form `CODE path`. It never includes a value or a key name from the checked file.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_guard.py
import copy

import pytest

from catalog import guard

FLOORS = {"k": 50, "min_vehicles": 5, "min_dealers": 5}


def good_recipe(n: int = 1, **over) -> dict:
    recipe = {
        "recipe_id": f"R{n:03d}",
        "support": 80,
        "vehicles": 12,
        "dealers": 9,
        "component": "Hydraulikpumpe",
        "symptom": "baut keinen Druck auf",
        "cause": "verschlissene Dichtung",
        "fix_steps": ["Druck am Pruefanschluss messen", "Dichtung an der Pumpe erneuern"],
        "title_templates": ["<component>: <symptom>", "Stoerung <component>", "<symptom>"],
        "description_style": {
            "fill": 0.8,
            "words": {"p25": 6, "p50": 12, "p75": 25},
            "tone": "neutral",
        },
        "solution_style": {"words": {"p25": 5, "p50": 9, "p75": 15}, "boilerplate": ["closing"]},
        "fehlercode_shape": "DDDD-D",
        "recurrence_gap_days": {"p25": 14, "p50": 40, "p75": 120},
        "co_occurs_with": [],
    }
    recipe.update(over)
    return recipe


def good_catalog(*recipes: dict) -> dict:
    return {"schema_version": 1, **FLOORS, "recipes": list(recipes) or [good_recipe()]}


def problems(catalog: dict) -> list[str]:
    return guard.problems(catalog, **FLOORS)


def test_a_valid_catalog_passes():
    assert problems(good_catalog(good_recipe(1), good_recipe(2))) == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r.update(extra="x"), "UNKNOWN_KEY"),
        (lambda r: r.pop("cause"), "UNKNOWN_KEY"),
        (lambda r: r.update(support=49), "BELOW_FLOOR"),
        (lambda r: r.update(vehicles=4), "BELOW_FLOOR"),
        (lambda r: r.update(dealers=4), "BELOW_FLOOR"),
        (lambda r: r.update(component="x" * 81), "TOO_LONG"),
        (lambda r: r.update(component="Teil 1234.56789"), "NOT_CLEAN"),
        (lambda r: r.update(fix_steps=["nur ein Schritt"]), "WRONG_COUNT"),
        (lambda r: r.update(title_templates=["<component>", "<serial>", "<symptom>"]), "NOT_CLEAN"),
        (lambda r: r.update(fehlercode_shape="1234-5"), "BAD_SHAPE"),
        (lambda r: r.update(recipe_id="X1"), "BAD_ID"),
        (lambda r: r["description_style"].update(tone="angry"), "BAD_VALUE"),
        (lambda r: r["description_style"].update(fill=0.8123), "NOT_WHOLE"),
        (lambda r: r["description_style"]["words"].update(p50=1.5), "NOT_WHOLE"),
        (lambda r: r["description_style"]["words"].update(max=99), "WRONG_TYPE"),
        (lambda r: r["solution_style"].update(boilerplate=["secrets"]), "BAD_VALUE"),
        (lambda r: r.update(recurrence_gap_days={"p25": 90, "p50": 40, "p75": 20}), "NOT_MONOTONE"),
        (lambda r: r.update(co_occurs_with=["R999"]), "BAD_REF"),
    ],
)
def test_each_mutation_is_refused_with_its_code(mutate, code):
    recipe = copy.deepcopy(good_recipe())
    mutate(recipe)
    found = problems(good_catalog(recipe))
    assert any(line.startswith(code) for line in found), found


def test_a_duplicate_id_is_refused():
    assert any(
        line.startswith("DUPLICATE_ID") for line in problems(good_catalog(good_recipe(1), good_recipe(1)))
    )


def test_a_floor_mismatch_in_the_header_is_refused():
    catalog = good_catalog()
    catalog["k"] = 10
    assert any(line.startswith("FLOOR_MISMATCH") for line in problems(catalog))


def test_no_message_carries_a_value_or_a_key_name():
    recipe = good_recipe(component="Teil 1234.56789", leaked_field_name="secret-value")
    text = "\n".join(problems(good_catalog(recipe)))
    assert "1234" not in text and "secret" not in text and "leaked_field_name" not in text


def test_an_empty_recipe_list_is_refused():
    assert problems({"schema_version": 1, **FLOORS, "recipes": []})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_guard.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/guard.py
"""Closed-allowlist check of a finished catalog. Nothing is released that this refuses.

Returns lines `CODE path`. A line never contains a value or a key name from the file under
test: a key or a value may itself be what leaked, and the log must not repeat it.
"""

from __future__ import annotations

import re

from catalog import schema, scrub
from recall.german.identifiers import SHAPE_ALPHABET, SHAPE_MAX

_SHAPE = re.compile(f"[{SHAPE_ALPHABET}]{{1,{SHAPE_MAX}}}")
_ID = re.compile(r"R\d{3,4}")
_ANGLE = re.compile(r"<[^<>]*>")


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _keys(out: list[str], path: str, value: object, allowed: frozenset[str]) -> bool:
    if not isinstance(value, dict):
        out.append(f"WRONG_TYPE {path}")
        return False
    if set(value) != allowed:
        out.append(f"UNKNOWN_KEY {path}")
        return False
    return True


def _text(out: list[str], path: str, value: object, limit: int, slots: bool = False) -> None:
    if not isinstance(value, str) or not value.strip():
        out.append(f"WRONG_TYPE {path}")
        return
    if len(value) > limit:
        out.append(f"TOO_LONG {path}")
    probe = value
    if slots:
        for slot in schema.SLOTS:
            probe = probe.replace(slot, " ")
    if _ANGLE.search(probe) or not scrub.is_clean(probe):
        out.append(f"NOT_CLEAN {path}")


def _texts(out, path, value, low, high, limit, slots=False) -> None:
    if not isinstance(value, list):
        out.append(f"WRONG_TYPE {path}")
        return
    if not low <= len(value) <= high:
        out.append(f"WRONG_COUNT {path}")
    for i, item in enumerate(value):
        _text(out, f"{path}[{i}]", item, limit, slots)


def _quantiles(out: list[str], path: str, value: object) -> None:
    if not isinstance(value, dict) or set(value) != set(schema.QUANTILES):
        out.append(f"WRONG_TYPE {path}")
        return
    numbers = []
    for name in schema.QUANTILES:
        if not _whole(value[name]):
            out.append(f"NOT_WHOLE {path}.{name}")
        else:
            numbers.append(value[name])
    if len(numbers) == len(schema.QUANTILES) and numbers != sorted(numbers):
        out.append(f"NOT_MONOTONE {path}")


def _recipe(out, path, recipe, floors, ids) -> None:
    if not _keys(out, path, recipe, schema.RECIPE_KEYS):
        return
    if not isinstance(recipe["recipe_id"], str) or not _ID.fullmatch(recipe["recipe_id"]):
        out.append(f"BAD_ID {path}.recipe_id")
    for field, floor in zip(("support", "vehicles", "dealers"), floors, strict=True):
        value = recipe[field]
        if not _whole(value):
            out.append(f"NOT_WHOLE {path}.{field}")
        elif value < floor:
            out.append(f"BELOW_FLOOR {path}.{field}")
    for field in ("component", "symptom", "cause"):
        _text(out, f"{path}.{field}", recipe[field], schema.MAX_PHRASE)
    _texts(out, f"{path}.fix_steps", recipe["fix_steps"], schema.MIN_STEPS, schema.MAX_STEPS,
           schema.MAX_STEP)
    _texts(out, f"{path}.title_templates", recipe["title_templates"], schema.MIN_TEMPLATES,
           schema.MAX_TEMPLATES, schema.MAX_TEMPLATE, slots=True)

    style = recipe["description_style"]
    if _keys(out, f"{path}.description_style", style, schema.DESCRIPTION_KEYS):
        fill = style["fill"]
        if not isinstance(fill, (int, float)) or isinstance(fill, bool) or not 0 <= fill <= 1:
            out.append(f"BAD_VALUE {path}.description_style.fill")
        elif round(fill, 2) != fill:
            out.append(f"NOT_WHOLE {path}.description_style.fill")
        _quantiles(out, f"{path}.description_style.words", style["words"])
        if style["tone"] not in schema.TONES:
            out.append(f"BAD_VALUE {path}.description_style.tone")

    solution = recipe["solution_style"]
    if _keys(out, f"{path}.solution_style", solution, schema.SOLUTION_KEYS):
        _quantiles(out, f"{path}.solution_style.words", solution["words"])
        boiler = solution["boilerplate"]
        if not isinstance(boiler, list) or any(b not in schema.BOILERPLATE for b in boiler):
            out.append(f"BAD_VALUE {path}.solution_style.boilerplate")

    shape = recipe["fehlercode_shape"]
    if shape is not None and not (isinstance(shape, str) and _SHAPE.fullmatch(shape)):
        out.append(f"BAD_SHAPE {path}.fehlercode_shape")
    if recipe["recurrence_gap_days"] is not None:
        _quantiles(out, f"{path}.recurrence_gap_days", recipe["recurrence_gap_days"])
    refs = recipe["co_occurs_with"]
    if not isinstance(refs, list) or len(refs) > schema.MAX_CO_OCCURS:
        out.append(f"WRONG_COUNT {path}.co_occurs_with")
    elif any(
        not isinstance(ref, str) or ref not in ids or ref == recipe["recipe_id"] for ref in refs
    ):
        out.append(f"BAD_REF {path}.co_occurs_with")


def problems(catalog: object, *, k: int, min_vehicles: int, min_dealers: int) -> list[str]:
    out: list[str] = []
    if not _keys(out, "$", catalog, schema.CATALOG_KEYS):
        return out
    for name, floor in (("k", k), ("min_vehicles", min_vehicles), ("min_dealers", min_dealers)):
        if catalog[name] != floor:
            out.append(f"FLOOR_MISMATCH $.{name}")
    recipes = catalog["recipes"]
    if not isinstance(recipes, list) or not recipes:
        out.append("WRONG_TYPE $.recipes")
        return out
    ids = [r.get("recipe_id") for r in recipes if isinstance(r, dict)]
    seen: set[object] = set()
    for i, identifier in enumerate(ids):
        if identifier in seen:
            out.append(f"DUPLICATE_ID $.recipes[{i}]")
        seen.add(identifier)
    known = {i for i in ids if isinstance(i, str)}
    for i, recipe in enumerate(recipes):
        _recipe(out, f"$.recipes[{i}]", recipe, (k, min_vehicles, min_dealers), known)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_guard.py -v` Expected: all pass. If `test_no_message_carries_a_value_or_a_key_name` or an `UNKNOWN_KEY` case fails because an exception fires first, fix the guard (not the test): the guard must never raise on a malformed file.

- [ ] **Step 5: Commit**

```bash
git add catalog/guard.py tests/unit/test_catalog_guard.py
git commit -m "feat(catalog): closed-allowlist guard for a finished catalog"
```

---

### Task 5: Synthetic Stage 1 corpus (test helper)

**Files:**
- Create: `tests/catalog_corpus.py`
- Test: `tests/unit/test_catalog_corpus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_corpus.py
from tests import catalog_corpus as corpus


def test_the_corpus_has_the_planned_shape():
    tickets = corpus.tickets(per_problem=30, problems=3, vehicles=8, dealers=8)
    assert len(tickets) == 90
    assert len({t.serial for t in tickets}) == 8
    assert len({t.merchant for t in tickets}) == 8


def test_a_thin_problem_spans_too_few_vehicles():
    tickets = corpus.tickets(per_problem=30, problems=3, vehicles=8, dealers=8, thin=12)
    thin = [t for t in tickets if t.title.startswith(corpus.PROBLEMS[3][0])]
    assert len(thin) == 12
    assert len({t.serial for t in thin}) == 2


def test_rows_round_trip_through_the_real_extractor():
    from insight import extract

    rows = corpus.rows(per_problem=10, problems=2, vehicles=5, dealers=5)
    parsed = extract.tickets(rows)
    assert len(parsed) == 20
    assert parsed[0].serial and parsed[0].merchant and parsed[0].created
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_corpus.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# tests/catalog_corpus.py
"""Invented tickets for Stage 1 tests. Every string here is made up.

Each problem has its own vocabulary so a semantic clusterer can separate them, and every ticket
adds a few filler words so no two are identical.
"""

from __future__ import annotations

from datetime import date, timedelta

from insight.extract import Ticket
from profiler.columns import EXPECTED_COLUMNS

PROBLEMS = (
    (
        "Hydraulikpumpe Druckverlust",
        "Pumpe baut keinen Druck auf und die Anzeige faellt ab",
        "Dichtung an der Pumpe getauscht und Druck am Pruefanschluss kontrolliert",
    ),
    (
        "Kuehlmittelverlust Schlauch",
        "Kuehlmittel tropft unter dem Motor und der Stand sinkt",
        "Kuehlwasserschlauch ersetzt und Kreislauf neu befuellt und entlueftet",
    ),
    (
        "Display bleibt dunkel",
        "Anzeige im Fahrerhaus bleibt nach dem Start dunkel",
        "Stecker am Display gereinigt und Kontakte nachgespannt und geprueft",
    ),
    (
        "Bremse quietscht",
        "Beim Abbremsen entsteht ein lautes Quietschen vorne",
        "Bremsbelaege angeschliffen und Scheiben gereinigt und Probefahrt gemacht",
    ),
)
FILLERS = tuple(
    f"{a}{b}"
    for a in ("alpha", "bravo", "delta", "echo", "foxtrot")
    for b in ("eins", "zwei", "drei", "vier", "fuenf", "sechs", "sieben", "acht")
)


def _spec(per_problem, problems, vehicles, dealers, thin):
    """Yield (problem index, ticket number, serial index, dealer index)."""
    for p in range(problems):
        for i in range(per_problem):
            yield p, i, (p + i) % vehicles, (p + 3 * i) % dealers  # 3 is coprime with 8
    for i in range(thin):  # a fourth problem on only two vehicles and two dealers
        yield 3, i, i % 2, i % 2


def _texts(p: int, n: int) -> tuple[str, str, str]:
    title, description, solution = PROBLEMS[p]
    filler = [FILLERS[(n * 7 + j * 11 + p) % len(FILLERS)] for j in range(4)]
    return (
        f"{title} {filler[0]}",
        f"{description} {filler[1]} {filler[2]}",
        f"{solution} {filler[3]}",
    )


def tickets(
    per_problem: int = 60, problems: int = 3, vehicles: int = 8, dealers: int = 8, thin: int = 0
) -> list[Ticket]:
    out = []
    for n, (p, i, v, d) in enumerate(_spec(per_problem, problems, vehicles, dealers, thin)):
        title, description, solution = _texts(p, n)
        out.append(
            Ticket(
                title,
                description,
                solution,
                (),
                f"Z90000000{v:04d}",
                "990101",
                "2024",
                "2021",
                merchant=f"D{d:03d}",
                created=date(2024, 1, 1) + timedelta(days=n),
            )
        )
    return out


def rows(
    per_problem: int = 60, problems: int = 3, vehicles: int = 8, dealers: int = 8, thin: int = 0
) -> list[dict[str, str]]:
    out = []
    for n, (p, i, v, d) in enumerate(_spec(per_problem, problems, vehicles, dealers, thin)):
        title, description, solution = _texts(p, n)
        row = dict.fromkeys(EXPECTED_COLUMNS, "")
        row.update(
            id=str(n + 1),
            title=title,
            description=description,
            solutions=solution,
            vehicleSerialNo=f"Z90000000{v:04d}",
            merchantId=f"D{d:03d}",
            vehicleModelId="990101",
            vehicleYear="2021",
            timestampCreated=(date(2024, 1, 1) + timedelta(days=n)).isoformat(),
        )
        out.append(row)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_corpus.py -v` Expected: 3 passed. If the round-trip test fails on a missing `customData`, that column is already `""` in `rows()`; check `extract.read_rows`/`extract.tickets` expectations in `insight/extract.py:242` and set only what it needs.

- [ ] **Step 5: Commit**

```bash
git add tests/catalog_corpus.py tests/unit/test_catalog_corpus.py
git commit -m "test(catalog): synthetic tickets for stage 1"
```

---

### Task 6: Candidate selection (eligibility, clustering, floors)

**Files:**
- Create: `catalog/select.py`
- Test: `tests/unit/test_catalog_select.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_select.py
import random

from catalog import select
from profiler.gate.embedder import HashingEmbedder
from tests import catalog_corpus as corpus

FLOORS = dict(k=20, min_vehicles=5, min_dealers=5, templated_k=10**9)


def run(tickets, clusters=3):
    # One k-means cluster per planted problem: a spare cluster would split a problem in two.
    return select.candidates(tickets, HashingEmbedder(), clusters=clusters, **FLOORS)


def test_three_real_problems_become_three_candidates():
    found = run(corpus.tickets(per_problem=30, problems=3))
    assert sorted(c.support for c in found) == [30, 30, 30]
    assert all(c.vehicles >= 5 and c.dealers >= 5 for c in found)


def test_a_problem_on_too_few_vehicles_is_not_released():
    found = run(corpus.tickets(per_problem=30, problems=3, thin=25), clusters=4)
    assert len(found) == 3  # the 25-ticket problem has support but only 2 vehicles


def test_a_problem_under_the_support_floor_is_not_released():
    found = run(corpus.tickets(per_problem=30, problems=3, thin=12), clusters=4)
    assert len(found) == 3


def test_handover_slips_are_excluded():
    from dataclasses import replace
    from datetime import date

    tickets = [replace(t, delivery=date(2024, 1, 1)) for t in corpus.tickets(per_problem=30)]
    assert run(tickets) == []


def test_the_result_does_not_depend_on_row_order():
    tickets = corpus.tickets(per_problem=30, problems=3)
    shuffled = tickets[:]
    random.Random(3).shuffle(shuffled)

    def shape(found, source):
        return sorted(
            (c.support, tuple(sorted(source[i].title for i in c.members))) for c in found
        )

    assert shape(run(tickets), tickets) == shape(run(shuffled), shuffled)


def test_candidate_ids_are_stable_across_row_order():
    tickets = corpus.tickets(per_problem=30, problems=3)
    shuffled = tickets[:]
    random.Random(5).shuffle(shuffled)
    first = [tickets[c.members[0]].title.split()[0] for c in run(tickets)]
    second = [shuffled[c.members[0]].title.split()[0] for c in run(shuffled)]
    assert sorted(first) == sorted(second)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_select.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/select.py
"""Which groups of tickets may become a recipe.

Eligible: not a handover slip (a delivery date is the proxy the quality section found), not
noise, and a solution with real content once workflow notes are stripped. Those tickets are
clustered on e5 embeddings with k-means; a cluster becomes a candidate only if it clears the
release floors counted over TICKETS, distinct vehicles and distinct dealers.

Row-order independence: the eligible tickets are sorted by a hash of their text before
clustering, because k-means is order-sensitive (insight's first clustering was too).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from insight import quality, release
from insight.extract import Ticket
from recall.clean import pipeline


@dataclass(frozen=True)
class Candidate:
    members: tuple[int, ...]  # indexes into the ticket list, ascending
    support: int
    vehicles: int
    dealers: int


def document(ticket: Ticket) -> str:
    return pipeline.clean(f"{ticket.title}\n{ticket.description}").text


def eligible(tickets: list[Ticket], templated_k: int = release.K) -> list[int]:
    graded = quality.grades(tickets, templated_k)
    return [
        i
        for i, (ticket, grade) in enumerate(zip(tickets, graded, strict=True))
        if ticket.delivery is None
        and not grade.noise
        and grade.words >= quality.DEFAULT_MIN_WORDS
    ]


def cluster(vectors: np.ndarray, clusters: int, seed: int) -> list[list[int]]:
    from scipy.cluster.vq import kmeans2

    norms = np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    unit = vectors / norms
    count = max(1, min(clusters, len(unit)))
    _, labels = kmeans2(unit, count, minit="++", seed=seed, missing="warn")
    groups: dict[int, list[int]] = {}
    for position, label in enumerate(labels):
        groups.setdefault(int(label), []).append(position)
    return list(groups.values())


def candidates(
    tickets: list[Ticket],
    embedder,
    *,
    k: int,
    min_vehicles: int,
    min_dealers: int,
    clusters: int,
    seed: int = 7,
    templated_k: int = release.K,
) -> list[Candidate]:
    keep = eligible(tickets, templated_k)
    if not keep:
        return []
    docs = {i: document(tickets[i]) for i in keep}
    digest = {i: hashlib.sha256(docs[i].encode()).hexdigest() for i in keep}
    keep.sort(key=lambda i: digest[i])
    vectors = np.asarray(embedder.encode([docs[i] for i in keep]))
    found = []
    for positions in cluster(vectors, clusters, seed):
        members = tuple(sorted(keep[p] for p in positions))
        vehicles = len({tickets[i].serial for i in members if tickets[i].serial})
        dealers = len({tickets[i].merchant for i in members if tickets[i].merchant})
        if len(members) >= k and vehicles >= min_vehicles and dealers >= min_dealers:
            found.append(Candidate(members, len(members), vehicles, dealers))
    # Order by size, ties by content, never by row index, so recipe ids survive a row shuffle.
    found.sort(key=lambda c: (-c.support, min(digest[i] for i in c.members)))
    return found
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_select.py -v` Expected: 6 passed. If clustering fails to recover the three problems (k-means local minimum), change the test's `seed` only after confirming the failure is a stable seed effect, not row order; the hash-sorted input makes the result deterministic.

- [ ] **Step 5: Commit**

```bash
git add catalog/select.py tests/unit/test_catalog_select.py
git commit -m "feat(catalog): semantic candidate selection with release floors"
```

---

### Task 7: Style statistics and co-occurrence

**Files:**
- Create: `catalog/stats.py`
- Test: `tests/unit/test_catalog_stats.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_stats.py
from dataclasses import replace
from datetime import date, timedelta

from catalog import stats
from tests import catalog_corpus as corpus


def members(n=40):
    return corpus.tickets(per_problem=n, problems=1, vehicles=8, dealers=8)


def test_style_reports_whole_numbers_and_no_extremes():
    style = stats.style(members())
    words = style["description_style"]["words"]
    assert set(words) == {"p25", "p50", "p75"}
    assert all(isinstance(v, int) for v in words.values())
    assert words["p25"] <= words["p50"] <= words["p75"]
    assert style["description_style"]["fill"] == 1.0


def test_blank_descriptions_lower_the_fill():
    tickets = [replace(t, description="") if i % 2 else t for i, t in enumerate(members(40))]
    assert stats.style(tickets)["description_style"]["fill"] == 0.5


def test_workflow_notes_are_reported_as_a_class_not_as_text():
    tickets = [
        replace(t, solutions=t.solutions + " Kunde wurde zurueckgerufen") for t in members(40)
    ]
    style = stats.style(tickets)
    assert style["solution_style"]["boilerplate"] == ["callback"]


def test_the_error_code_shape_is_reported_never_the_value():
    tickets = [replace(t, fehlercode="1234-5") for t in members(40)]
    assert stats.style(tickets)["fehlercode_shape"] == "DDDD-D"
    assert stats.style(members())["fehlercode_shape"] is None


def test_recurrence_gaps_come_from_repeat_tickets_on_one_serial():
    base = members(40)
    tickets = [
        replace(t, serial="Z1", created=date(2024, 1, 1) + timedelta(days=30 * i))
        for i, t in enumerate(base)
    ]
    gap = stats.style(tickets)["recurrence_gap_days"]
    assert gap == {"p25": 30, "p50": 30, "p75": 30}


def test_too_few_repeats_give_no_gap_statistic():
    tickets = [replace(t, serial=f"Z{i}") for i, t in enumerate(members(40))]
    assert stats.style(tickets)["recurrence_gap_days"] is None


def test_cooccurrence_needs_enough_distinct_vehicles():
    tickets = []
    assignment = {}
    for v in range(6):  # six vehicles each have a problem A then a problem B
        for j, recipe in enumerate(("R001", "R002")):
            tickets.append(
                replace(
                    corpus.tickets(per_problem=1, problems=1)[0],
                    serial=f"Z{v}",
                    created=date(2024, 1, 1) + timedelta(days=10 * j),
                )
            )
            assignment[len(tickets) - 1] = recipe
    found = stats.cooccurrence(tickets, assignment, min_vehicles=5)
    assert found["R001"] == ["R002"]
    assert stats.cooccurrence(tickets, assignment, min_vehicles=7) == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_stats.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/stats.py
"""Numbers and classes about a recipe's tickets. Nothing here is free text."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta

from catalog import schema
from insight import quality
from insight.extract import Ticket
from recall.german.identifiers import shape_of

_WORD = re.compile(r"\w+")
_BOILERPLATE = {
    "callback": re.compile(r"r(?:ü|ue)ckruf|zur(?:ü|ue)ckgerufen|angerufen", re.IGNORECASE),
    "closing": re.compile(r"geschlossen|abgeschlossen|erledigt", re.IGNORECASE),
    "warranty": re.compile(r"garantie|gew(?:ä|ae)hrleistung", re.IGNORECASE),
    "goodwill": re.compile(r"kulanz", re.IGNORECASE),
    "duplicate_ref": re.compile(r"doppelt|siehe ticket", re.IGNORECASE),
}
BOILERPLATE_SHARE = 0.3
SHAPE_SHARE = 0.2
MIN_GAPS = 10
CO_SHARE = 0.15


def quantiles(values: list[int]) -> dict[str, int]:
    """Nearest-rank p25, p50, p75 as whole numbers; all zero for no values."""
    if not values:
        return dict.fromkeys(schema.QUANTILES, 0)
    ordered = sorted(values)
    last = len(ordered) - 1
    points = {"p25": 0.25, "p50": 0.5, "p75": 0.75}
    return {name: int(ordered[round(q * last)]) for name, q in points.items()}


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def _tone(median_words: int) -> str:
    return "terse" if median_words < 8 else "neutral" if median_words < 25 else "verbose"


def _gaps(members: list[Ticket]) -> list[int]:
    by_serial: dict[str, list] = defaultdict(list)
    for ticket in members:
        if ticket.serial and ticket.created:
            by_serial[ticket.serial].append(ticket.created)
    gaps = []
    for dates in by_serial.values():
        dates.sort()
        gaps += [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    return gaps


def _shape(members: list[Ticket]) -> str | None:
    shapes = Counter()
    for ticket in members:
        code = (ticket.fehlercode or "").strip()
        if code:
            shapes[shape_of(re.split(r"[,;\s]+", code)[0])] += 1
    if not shapes:
        return None
    shape, count = shapes.most_common(1)[0]
    return shape if count / len(members) >= SHAPE_SHARE else None


def style(members: list[Ticket]) -> dict:
    described = [t for t in members if t.description.strip()]
    described_words = quantiles([_words(t.description) for t in described])
    solved = [t for t in members if t.solutions.strip()]
    solution_words = quantiles(
        [quality.content_words(quality.stripped_solution(t.solutions)) for t in solved]
    )
    boilerplate = [
        name
        for name, pattern in _BOILERPLATE.items()
        if sum(1 for t in members if pattern.search(t.solutions)) / len(members) >= BOILERPLATE_SHARE
    ]
    gaps = _gaps(members)
    return {
        "description_style": {
            "fill": round(len(described) / len(members), 2),
            "words": described_words,
            "tone": _tone(described_words["p50"]),
        },
        "solution_style": {"words": solution_words, "boilerplate": boilerplate},
        "fehlercode_shape": _shape(members),
        "recurrence_gap_days": quantiles(gaps) if len(gaps) >= MIN_GAPS else None,
    }


def cooccurrence(
    tickets: list[Ticket], assignment: dict[int, str], min_vehicles: int
) -> dict[str, list[str]]:
    """Recipes that follow another within 90 days on the same serial, by distinct vehicles."""
    by_serial: dict[str, list[tuple]] = defaultdict(list)
    for index, recipe in assignment.items():
        ticket = tickets[index]
        if ticket.serial and ticket.created:
            by_serial[ticket.serial].append((ticket.created, recipe))
    having: Counter = Counter()
    pairs: Counter = Counter()
    for events in by_serial.values():
        events.sort()
        recipes = {recipe for _, recipe in events}
        having.update(recipes)
        seen = set()
        for i, (when, a) in enumerate(events):
            for later, b in events[i + 1 :]:
                if later - when > timedelta(days=90):
                    break
                if a != b:
                    seen.add((a, b))
        pairs.update(seen)
    out: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (a, b), vehicles in pairs.items():
        share = vehicles / having[a]
        if vehicles >= min_vehicles and share >= CO_SHARE:
            out[a].append((share, b))
    return {
        a: [b for _, b in sorted(found, key=lambda x: (-x[0], x[1]))[: schema.MAX_CO_OCCURS]]
        for a, found in out.items()
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_stats.py -v` Expected: 7 passed. `test_workflow_notes...` expects `["callback"]` only; the corpus solutions contain no other class keyword.

- [ ] **Step 5: Commit**

```bash
git add catalog/stats.py tests/unit/test_catalog_stats.py
git commit -m "feat(catalog): per-recipe style statistics and co-occurrence"
```

---

### Task 8: LLM drafting

**Files:**
- Create: `catalog/draft.py`
- Test: `tests/unit/test_catalog_draft.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_catalog_draft.py
import json

from catalog import draft, verbatim
from tests import catalog_corpus as corpus

GOOD = {
    "coherent": True,
    "component": "Hydraulikpumpe",
    "symptom": "baut keinen Druck auf",
    "cause": "verschlissene Dichtung",
    "fix_steps": ["Druck am Pruefanschluss messen", "Dichtung an der Pumpe erneuern"],
    "title_templates": ["<component>: <symptom>", "Stoerung <component>", "<symptom>"],
}


def client(payload):
    def call(prompt: str) -> str:
        return payload if isinstance(payload, str) else "Hier das Ergebnis:\n" + json.dumps(payload)

    return call


def samples():
    return corpus.tickets(per_problem=12, problems=1)


def run(payload, ngrams=frozenset()):
    return draft.draft(samples(), client(payload), set(ngrams))


def test_a_good_answer_becomes_recipe_fields():
    fields, code = run(GOOD)
    assert code == "ok"
    assert fields["component"] == "Hydraulikpumpe"
    assert len(fields["fix_steps"]) == 2


def test_the_prompt_carries_the_samples_and_asks_for_no_identifiers():
    seen = []
    draft.draft(samples(), lambda p: seen.append(p) or json.dumps(GOOD), set())
    assert "Hydraulikpumpe Druckverlust" in seen[0]
    assert "keine Namen" in seen[0]


def test_an_incoherent_cluster_is_rejected():
    assert run({**GOOD, "coherent": False}) == (None, "incoherent")


def test_unparseable_output_is_rejected():
    assert run("kein json hier") == (None, "unparseable")


def test_the_wrong_number_of_steps_is_rejected():
    assert run({**GOOD, "fix_steps": ["nur einer"]}) == (None, "shape")


def test_an_unknown_slot_is_rejected():
    bad = {**GOOD, "title_templates": ["<serial>", "<component>", "<symptom>"]}
    assert run(bad) == (None, "shape")


def test_identifiers_in_the_answer_are_scrubbed_not_released():
    dirty = {**GOOD, "cause": "Dichtung 1234.56789 verschlissen"}
    fields, code = run(dirty)
    assert code == "ok" and "1234" not in fields["cause"]


def test_a_copied_run_of_words_is_rejected():
    ngrams = verbatim.word_ngrams("Dichtung an der Pumpe erneuern und danach pruefen")
    assert run(GOOD, ngrams) == (None, "copied")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_draft.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# catalog/draft.py
"""Ask the model for one abstract recipe per cluster, then refuse anything unsafe.

The prompt holds real ticket text, so this only ever runs inside the window. Whatever the model
answers is scrubbed, length-capped, slot-checked and compared against the cluster's own tickets
for copied runs of words before it can become part of a draft.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from catalog import schema, scrub, verbatim
from insight.extract import Ticket

PROMPT = """Du analysierst Support-Tickets zu Fahrzeugen. Unten stehen {n} Tickets, die ein \
Clustering zusammengefasst hat.

Entscheide, ob sie dasselbe wiederkehrende technische Problem beschreiben. Antworte NUR mit \
einem JSON-Objekt mit diesen Feldern:
"coherent": true oder false
"component": Bauteil oder System (kurze Phrase)
"symptom": beobachtetes Symptom (kurze Phrase)
"cause": wahrscheinliche Ursache (kurze Phrase)
"fix_steps": 2 bis 6 allgemeine Loesungsschritte als Liste
"title_templates": 3 bis 5 abstrakte Titelvorlagen als Liste; erlaubte Platzhalter sind \
<component> und <symptom>

Regeln: keine Namen, keine Nummern (Seriennummern, Teilenummern, Telefonnummern, Daten), keine \
Firmen. Formuliere eigene, allgemeine Saetze; uebernimm keine Saetze aus den Tickets.

{tickets}
"""
_JSON = re.compile(r"\{.*\}", re.DOTALL)
_ANGLE = re.compile(r"<[^<>]*>")
MAX_SAMPLE = 12
EXCERPT = 600


def _render(number: int, ticket: Ticket) -> str:
    return (
        f"[{number}] TITEL: {ticket.title}\n"
        f"BEFUND: {ticket.description[:EXCERPT]}\n"
        f"LOESUNG: {ticket.solutions[:EXCERPT]}"
    )


def _parse(text: str) -> dict | None:
    match = _JSON.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _phrase(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = scrub.scrub(value)
    return text if text and len(text) <= limit else None


def _phrases(value: object, low: int, high: int, limit: int, slots: bool = False):
    if not isinstance(value, list) or not low <= len(value) <= high:
        return None
    out = []
    for item in value:
        text = _phrase(item, limit)
        if text is None:
            return None
        probe = text
        if slots:
            for slot in schema.SLOTS:
                probe = probe.replace(slot, " ")
        if _ANGLE.search(probe):
            return None
        out.append(text)
    return out if len(set(out)) == len(out) else None


def _fields(data: dict) -> dict | None:
    parts = {
        "component": _phrase(data.get("component"), schema.MAX_PHRASE),
        "symptom": _phrase(data.get("symptom"), schema.MAX_PHRASE),
        "cause": _phrase(data.get("cause"), schema.MAX_PHRASE),
        "fix_steps": _phrases(
            data.get("fix_steps"), schema.MIN_STEPS, schema.MAX_STEPS, schema.MAX_STEP
        ),
        "title_templates": _phrases(
            data.get("title_templates"),
            schema.MIN_TEMPLATES,
            schema.MAX_TEMPLATES,
            schema.MAX_TEMPLATE,
            slots=True,
        ),
    }
    return None if any(v is None for v in parts.values()) else parts


def _strings(fields: dict) -> list[str]:
    return [
        fields["component"],
        fields["symptom"],
        fields["cause"],
        *fields["fix_steps"],
        *fields["title_templates"],
    ]


def draft(
    samples: list[Ticket], client: Callable[[str], str], corpus_ngrams: set
) -> tuple[dict | None, str]:
    """(fields, "ok") or (None, one of incoherent / unparseable / shape / copied)."""
    prompt = PROMPT.format(
        n=len(samples), tickets="\n\n".join(_render(i, t) for i, t in enumerate(samples, 1))
    )
    data = _parse(client(prompt))
    if data is None:
        return None, "unparseable"
    if data.get("coherent") is not True:
        return None, "incoherent"
    fields = _fields(data)
    if fields is None:
        return None, "shape"
    if verbatim.copies(_strings(fields), corpus_ngrams):
        return None, "copied"
    return fields, "ok"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_draft.py -v` Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add catalog/draft.py tests/unit/test_catalog_draft.py
git commit -m "feat(catalog): LLM recipe drafting with scrub, slot and copy checks"
```

---

### Task 9: Build and CLI

**Files:**
- Create: `catalog/build.py`, `catalog/__main__.py`
- Test: `tests/unit/test_catalog_build.py`, `tests/unit/test_catalog_main.py`

- [ ] **Step 1: Write the failing build test**

```python
# tests/unit/test_catalog_build.py
import json

from catalog import build, guard
from profiler.gate.embedder import HashingEmbedder
from tests import catalog_corpus as corpus

FLOORS = dict(k=20, min_vehicles=5, min_dealers=5, templated_k=10**9)
# One k-means cluster per planted problem; a spare cluster would split a problem in two.


def scripted(prompt: str) -> str:
    component = "Hydraulikpumpe" if "Hydraulikpumpe" in prompt else "Bauteil"
    return json.dumps(
        {
            "coherent": True,
            "component": component,
            "symptom": "zeigt ein Symptom",
            "cause": "eine Ursache",
            "fix_steps": ["Ersten Schritt ausfuehren", "Zweiten Schritt ausfuehren"],
            "title_templates": ["<component>: <symptom>", "Stoerung <component>", "<symptom>"],
        }
    )


def test_build_produces_a_catalog_the_guard_accepts_once_floors_match():
    tickets = corpus.tickets(per_problem=30, problems=3, thin=12)
    catalog, rejected = build.build(tickets, HashingEmbedder(), scripted, clusters=4, **FLOORS)
    assert [r["recipe_id"] for r in catalog["recipes"]] == ["R001", "R002", "R003"]
    assert all(r["support"] == 30 for r in catalog["recipes"])
    assert guard.problems(catalog, k=20, min_vehicles=5, min_dealers=5) == []
    assert rejected == {}


def test_a_rejected_draft_is_counted_by_code_and_does_not_enter_the_catalog():
    tickets = corpus.tickets(per_problem=30, problems=3)

    def refuses(prompt: str) -> str:
        return json.dumps({"coherent": False})

    catalog, rejected = build.build(tickets, HashingEmbedder(), refuses, clusters=3, **FLOORS)
    assert catalog["recipes"] == []
    assert rejected == {"incoherent": 3}


def test_the_catalog_header_records_the_floors():
    tickets = corpus.tickets(per_problem=30, problems=3)
    catalog, _ = build.build(tickets, HashingEmbedder(), scripted, clusters=3, **FLOORS)
    assert (catalog["k"], catalog["min_vehicles"], catalog["min_dealers"]) == (20, 5, 5)


def test_no_ticket_text_or_serial_reaches_the_catalog():
    tickets = corpus.tickets(per_problem=30, problems=3)
    catalog, _ = build.build(tickets, HashingEmbedder(), scripted, clusters=3, **FLOORS)
    text = json.dumps(catalog)
    assert "Z90000000" not in text and "D00" not in text
    assert all(t.title not in text for t in tickets[:30])
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_build.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write `catalog/build.py`**

```python
# catalog/build.py
"""Candidates -> recipes -> one catalog dict. Pure; the CLI owns files and exit codes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from catalog import draft, schema, select, stats, verbatim
from insight import release
from insight.extract import Ticket


def _sample(members: list[Ticket]) -> list[Ticket]:
    step = max(1, len(members) // draft.MAX_SAMPLE)
    return members[::step][: draft.MAX_SAMPLE]


def _ngrams(members: list[Ticket]) -> set:
    found: set = set()
    for ticket in members:
        found |= verbatim.word_ngrams(f"{ticket.title} {ticket.description} {ticket.solutions}")
    return found


def build(
    tickets: list[Ticket],
    embedder,
    client: Callable[[str], str],
    *,
    k: int,
    min_vehicles: int,
    min_dealers: int,
    clusters: int,
    seed: int = 7,
    templated_k: int = release.K,
) -> tuple[dict, dict[str, int]]:
    found = select.candidates(
        tickets,
        embedder,
        k=k,
        min_vehicles=min_vehicles,
        min_dealers=min_dealers,
        clusters=clusters,
        seed=seed,
        templated_k=templated_k,
    )
    recipes: list[dict] = []
    assignment: dict[int, str] = {}
    rejected: Counter = Counter()
    for candidate in found:
        members = [tickets[i] for i in candidate.members]
        fields, code = draft.draft(_sample(members), client, _ngrams(members))
        if fields is None:
            rejected[code] += 1
            continue
        recipe_id = f"R{len(recipes) + 1:03d}"
        recipes.append(
            {
                "recipe_id": recipe_id,
                "support": candidate.support,
                "vehicles": candidate.vehicles,
                "dealers": candidate.dealers,
                **fields,
                **stats.style(members),
                "co_occurs_with": [],
            }
        )
        assignment.update(dict.fromkeys(candidate.members, recipe_id))
    together = stats.cooccurrence(tickets, assignment, min_vehicles)
    for recipe in recipes:
        recipe["co_occurs_with"] = together.get(recipe["recipe_id"], [])
    catalog = {
        "schema_version": schema.SCHEMA_VERSION,
        "k": k,
        "min_vehicles": min_vehicles,
        "min_dealers": min_dealers,
        "recipes": recipes,
    }
    return catalog, dict(rejected)
```

- [ ] **Step 4: Run to verify the build test passes**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_build.py -v` Expected: 4 passed.

- [ ] **Step 5: Write the failing CLI test**

```python
# tests/unit/test_catalog_main.py
import csv
import json

import pytest

from catalog import __main__ as cli
from profiler.columns import EXPECTED_COLUMNS
from tests import catalog_corpus as corpus

COMMON = ["--k", "20", "--min-vehicles", "5", "--min-dealers", "5", "--allow-weak-floor"]


@pytest.fixture
def window(tmp_path, monkeypatch):
    sealed = tmp_path / "sealed"
    monkeypatch.setenv("RECALL_SEALED_ROOT", str(sealed))
    export = tmp_path / "export.csv"
    with export.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        writer.writerows(corpus.rows(per_problem=30, problems=3, vehicles=8, dealers=8))
    return export, sealed


def build_args(export):
    return [
        "build", "--csv", str(export), "--draft", "catalog.draft.json", "--embedder", "hashing",
        "--llm", "fake", "--clusters", "3", "--templated-k", "1000000", *COMMON,
    ]


def test_build_then_release_writes_a_guarded_catalog(window, capsys):
    export, sealed = window
    assert cli.main(build_args(export)) == 0
    draft = sealed / "catalog.draft.json"
    assert draft.is_file() and (sealed / ".sealed").is_file()
    assert cli.main(["release", "--draft", "catalog.draft.json", "--out", "catalog.json", *COMMON]) == 0
    assert json.loads((sealed / "catalog.json").read_text())["recipes"]


def test_output_never_prints_a_value(window, capsys):
    export, _ = window
    cli.main(build_args(export))
    printed = capsys.readouterr().out
    assert "Hydraulikpumpe" not in printed and "Z90000000" not in printed


def test_release_refuses_a_tampered_draft_and_leaves_no_catalog(window, capsys):
    export, sealed = window
    cli.main(build_args(export))
    draft = sealed / "catalog.draft.json"
    data = json.loads(draft.read_text())
    data["recipes"][0]["cause"] = "Teil 1234.56789 defekt"
    draft.write_text(json.dumps(data))
    assert cli.main(["release", "--draft", "catalog.draft.json", "--out", "catalog.json", *COMMON]) == 2
    assert not (sealed / "catalog.json").exists()
    assert "1234" not in capsys.readouterr().out


def test_a_stale_catalog_is_removed_before_a_failed_release(window):
    export, sealed = window
    (sealed / "catalog.json").parent.mkdir(parents=True, exist_ok=True)
    (sealed / "catalog.json").write_text("{}")
    cli.main(["release", "--draft", "missing.json", "--out", "catalog.json", *COMMON])
    assert not (sealed / "catalog.json").exists()


def test_weak_floors_are_refused_without_the_explicit_flag(window):
    export, _ = window
    assert cli.main(["build", "--csv", str(export), "--draft", "d.json", "--k", "10",
                     "--min-vehicles", "5", "--min-dealers", "5", "--llm", "fake",
                     "--embedder", "hashing"]) == 4


def test_a_names_with_dots_cannot_escape_the_sealed_root(window):
    export, _ = window
    assert cli.main(["build", "--csv", str(export), "--draft", "../x.json", *COMMON,
                     "--llm", "fake", "--embedder", "hashing"]) == 4
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_main.py -v` Expected: FAIL, `ImportError` on `catalog.__main__`.

- [ ] **Step 7: Write `catalog/__main__.py`**

```python
# catalog/__main__.py
"""Stage 1: draft a problem catalog from the real export, then release it through the guard.

    python -m catalog build   --csv export.csv --draft catalog.draft.json ...
    python -m catalog release --draft catalog.draft.json --out catalog.json ...

Runs in an airlock window with no AI to help. `build` writes only a DRAFT under the sealed root;
the operator reads and edits it by hand; `release` runs the guard and writes the catalog only if
nothing is refused. Output names are relative to the sealed root (`recall.sealed.sealed_path`).
Messages carry codes, counts and schema paths, never a value.

Exit codes: 0 ok, 2 the guard refused, 3 unexpected failure (profiler.safety), 4 bad arguments
or input.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from catalog import build, guard
from insight import extract, release
from profiler import safety
from recall import sealed

MIN_K = release.K
MIN_VEHICLES = 5
MIN_DEALERS = 5


class _BadArguments(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _BadArguments


def _abort(code: str, message: str) -> int:
    print(f"ABORT {code} {message}", flush=True)
    return 4


def _floors(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--k", type=int, default=MIN_K)
    parser.add_argument("--min-vehicles", type=int, default=MIN_VEHICLES)
    parser.add_argument("--min-dealers", type=int, default=MIN_DEALERS)
    parser.add_argument("--allow-weak-floor", action="store_true")


def _weak(args) -> bool:
    return not args.allow_weak_floor and (
        args.k < MIN_K or args.min_vehicles < MIN_VEHICLES or args.min_dealers < MIN_DEALERS
    )


def _name(value: str) -> pathlib.Path | None:
    try:
        return sealed.sealed_path(value)
    except ValueError:
        return None


def _client(args):
    from fixtures import llm

    if args.llm == "vllm":
        return llm.VLLM(args.base_url, args.model)
    return _FakeDrafter()


class _FakeDrafter:
    """GPU-free stand-in for rehearsals: a coherent, generic recipe for every cluster."""

    identity = "catalog-fake:v1"

    def __call__(self, prompt: str) -> str:
        return json.dumps(
            {
                "coherent": True,
                "component": "Bauteil",
                "symptom": "zeigt ein Symptom",
                "cause": "eine Ursache",
                "fix_steps": ["Ersten Schritt ausfuehren", "Zweiten Schritt ausfuehren"],
                "title_templates": ["<component>: <symptom>", "Stoerung <component>", "<symptom>"],
            }
        )


def _embedder(name: str):
    if name == "e5":
        from profiler.gate.embedder import E5Embedder

        return E5Embedder()
    from profiler.gate.embedder import HashingEmbedder

    return HashingEmbedder()


def _build(args) -> int:
    if _weak(args):
        return _abort("BAD_ARGUMENT", "a floor is below the release minimum; see --help")
    target = _name(args.draft)
    if target is None:
        return _abort("BAD_ARGUMENT", "--draft must be a name inside the sealed root")
    target.unlink(missing_ok=True)
    if not args.csv.is_file():
        return _abort("MISSING_INPUT", "the input file does not exist or is not a file")
    rows = extract.read_rows(args.csv)
    if not rows:
        return _abort("EMPTY_INPUT", "the export parsed to 0 data rows")
    tickets = extract.tickets(rows)
    catalog, rejected = build.build(
        tickets,
        _embedder(args.embedder),
        _client(args),
        k=args.k,
        min_vehicles=args.min_vehicles,
        min_dealers=args.min_dealers,
        clusters=args.clusters,
        seed=args.seed,
        templated_k=args.templated_k,
    )
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(  # guard: ok(sealed_path target)
            json.dumps(catalog, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"wrote draft: tickets={len(tickets)} recipes={len(catalog['recipes'])}")
    print("rejected " + " ".join(f"{k}={v}" for k, v in sorted(rejected.items())))
    return 0


def _release(args) -> int:
    if _weak(args):
        return _abort("BAD_ARGUMENT", "a floor is below the release minimum; see --help")
    out = _name(args.out)
    source = _name(args.draft)
    if out is None or source is None:
        return _abort("BAD_ARGUMENT", "names must stay inside the sealed root")
    out.unlink(missing_ok=True)  # a failed release must not leave an older catalog behind
    if not source.is_file():
        return _abort("MISSING_INPUT", "the draft does not exist")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except ValueError:
        return _abort("WRONG_INPUT", "the draft is not valid JSON")
    found = guard.problems(
        data, k=args.k, min_vehicles=args.min_vehicles, min_dealers=args.min_dealers
    )
    if found:
        for line in found:
            print(f"REFUSED {line}")
        return 2
    temporary = out.with_name(out.name + ".tmp")
    try:
        temporary.write_text(  # guard: ok(sealed_path target)
            json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        os.replace(temporary, out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"released {len(data['recipes'])} recipes")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="catalog", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    built = sub.add_parser("build")
    built.add_argument("--csv", required=True, type=pathlib.Path)
    built.add_argument("--draft", required=True)
    built.add_argument("--embedder", choices=("e5", "hashing"), default="e5")
    built.add_argument("--llm", choices=("vllm", "fake"), default="vllm")
    built.add_argument("--base-url", default="http://localhost:8000")
    built.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    built.add_argument("--clusters", type=int, default=300)
    built.add_argument("--seed", type=int, default=7)
    built.add_argument("--templated-k", type=int, default=release.K)
    _floors(built)
    released = sub.add_parser("release")
    released.add_argument("--draft", required=True)
    released.add_argument("--out", required=True)
    _floors(released)
    try:
        args = parser.parse_args(argv)
    except _BadArguments:
        return _abort("BAD_ARGUMENT", "the arguments were not understood; run with --help")
    except SystemExit as exc:  # --help
        return 0 if exc.code in (0, None) else _abort("BAD_ARGUMENT", "see --help")
    return _build(args) if args.command == "build" else _release(args)


if __name__ == "__main__":
    # Never let a raw traceback reach stdout: a decode or csv error quotes the input.
    sys.exit(safety.run_scrubbed(main))
```

- [ ] **Step 8: Run both test files and lint**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog_build.py tests/unit/test_catalog_main.py -v` Expected: all pass.
Run: `.venv/bin/ruff check catalog tests && .venv/bin/ruff format catalog tests` Expected: clean (the formatter may rewrap long lines; commit what it produces).

Notes for the implementer: `_build` calls `sealed.sealed_path` before the export is read, so the sealed root exists and is marked first. `test_a_names_with_dots...` relies on `sealed_path` raising `ValueError` for `..`. The test named `test_weak_floors...` expects exit 4 because `_weak` runs before any file is touched.

- [ ] **Step 9: Commit**

```bash
git add catalog/build.py catalog/__main__.py tests/unit/test_catalog_build.py tests/unit/test_catalog_main.py
git commit -m "feat(catalog): build and release CLI with guard and sealed outputs"
```

---

### Task 10: Stand-in catalog (tracked, synthetic)

**Files:**
- Create: `dev3/standin.py`
- Test: `tests/unit/test_dev3_standin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_standin.py
from catalog import guard
from dev3 import standin


def test_the_standin_passes_the_real_guard():
    assert guard.problems(standin.catalog(), k=50, min_vehicles=5, min_dealers=5) == []


def test_the_standin_has_enough_recipes_for_three_profiles():
    recipes = standin.catalog()["recipes"]
    assert len(recipes) == 8
    assert len({r["recipe_id"] for r in recipes}) == 8


def test_the_standin_is_a_copy_each_time():
    standin.catalog()["recipes"].clear()
    assert len(standin.catalog()["recipes"]) == 8
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_standin.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# dev3/standin.py
"""An invented catalog in the released shape, for tests and rehearsals. Nothing here comes
from the real corpus."""

from __future__ import annotations

import copy


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
            1, "Hydraulikpumpe", "baut keinen Druck auf", "verschlissene Dichtung",
            ["Druck am Pruefanschluss messen", "Dichtung an der Pumpe erneuern",
             "Druckaufbau nach dem Einbau kontrollieren"],
            _templates("Hydraulikpumpe"), shape="DDDD-D", gap=_q(14, 45, 120),
            boiler=["closing"], co=["R002"],
        ),
        _recipe(
            2, "Kuehlwasserschlauch", "Kuehlmittelverlust", "poroeser Schlauch",
            ["Schlauch auf Risse pruefen", "Schlauch ersetzen", "Kreislauf befuellen und entlueften"],
            _templates("Kuehlwasserschlauch"), gap=_q(20, 60, 150), tone="verbose",
            desc=_q(10, 24, 50), co=["R001"],
        ),
        _recipe(
            3, "Getriebe", "schaltet nicht", "zu niedriger Oelstand",
            ["Oelstand messen", "Oel bis zur Markierung auffuellen", "Probefahrt durchfuehren"],
            _templates("Getriebe"), tone="terse", desc=_q(3, 6, 10), shape="ALL_DD",
            gap=_q(30, 90, 240), boiler=["callback"],
        ),
        _recipe(
            4, "Display", "bleibt dunkel", "Wackelkontakt im Stecker",
            ["Stecker am Display abziehen und reinigen", "Kontakte nachspannen",
             "Funktion mit Zuendung ein pruefen"],
            _templates("Display"), fill=0.6, tone="terse", desc=_q(3, 7, 12), gap=_q(7, 21, 60),
        ),
        _recipe(
            5, "Batterie", "entlaedt sich ueber Nacht", "Dauerverbraucher",
            ["Ruhestrom messen", "Verbraucher durch Ziehen der Sicherungen eingrenzen",
             "defekte Komponente tauschen"],
            _templates("Batterie"), shape="DDDD-DD", gap=_q(10, 30, 90), boiler=["warranty"],
            co=["R007"],
        ),
        _recipe(
            6, "Bremse", "quietscht", "verglaste Belaege",
            ["Belaege ausbauen und anschleifen", "Scheiben reinigen", "Probefahrt mit Bremstest"],
            _templates("Bremse"), fill=0.7, tone="terse", desc=_q(4, 8, 14),
        ),
        _recipe(
            7, "Drehzahlsensor", "meldet einen Fehlercode", "Kabelbruch",
            ["Kabelbaum auf Scheuerstellen pruefen", "Kabel reparieren oder Sensor ersetzen",
             "Fehlerspeicher loeschen und Gegenprobe machen"],
            _templates("Drehzahlsensor"), shape="DDDD-D", gap=_q(5, 14, 45), tone="verbose",
            desc=_q(12, 28, 60), co=["R005"],
        ),
        _recipe(
            8, "Klimaanlage", "kuehlt nicht", "Kaeltemittelmangel",
            ["Kaeltemitteldruck messen", "Leck mit Kontrastmittel suchen",
             "Kaeltemittel nachfuellen"],
            _templates("Klimaanlage"), fill=0.5, boiler=["goodwill", "closing"],
            gap=_q(60, 180, 365),
        ),
    ],
}


def catalog() -> dict:
    return copy.deepcopy(_CATALOG)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_standin.py -v` Expected: 3 passed. If a recipe string trips the scrub (a word on a name list, or digits), the guard output names its path (`$.recipes[i].field`); reword that string. Do not weaken the guard.

- [ ] **Step 5: Commit**

```bash
git add dev3/standin.py tests/unit/test_dev3_standin.py
git commit -m "feat(dev3): synthetic stand-in catalog in the released shape"
```

---

### Task 11: Profiles and planner

**Files:**
- Create: `dev3/profiles.py`, `dev3/personas.py`, `dev3/planner.py`
- Test: `tests/unit/test_dev3_planner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_planner.py
from collections import Counter

from dev3 import planner, profiles, standin

RECIPES = standin.catalog()["recipes"]
V1, V2, V3 = profiles.PROFILES


def plan(profile, seed=7):
    return planner.plan(profile, RECIPES, seed)


def test_the_three_profiles_have_distinct_invented_serials():
    serials = [p.serial for p in profiles.PROFILES]
    assert len(set(serials)) == 3
    assert all(len(s) == 13 and s[0] == "Z" and s[1:].isdigit() for s in serials)


def test_ticket_counts_match_the_profile():
    for profile in profiles.PROFILES:
        assert len(plan(profile)) == profile.tickets
        assert 150 <= profile.tickets <= 200


def test_the_plan_is_deterministic_and_seed_dependent():
    assert plan(V1) == plan(V1)
    assert plan(V1, 1) != plan(V1, 2)


def test_dates_are_inside_the_window_and_sorted():
    for profile in profiles.PROFILES:
        dates = [t.created for t in plan(profile)]
        assert dates == sorted(dates)
        assert all(profile.start <= d <= profile.end for d in dates)


def test_numbers_are_one_based_and_followups_point_backwards():
    for profile in profiles.PROFILES:
        tickets = plan(profile)
        assert [t.number for t in tickets] == list(range(1, len(tickets) + 1))
        assert all(t.followup_of is None or t.followup_of < t.number for t in tickets)


def test_chronic_vehicle_is_dominated_by_three_recipes():
    counts = Counter(t.recipe_id for t in plan(V1))
    top3 = sum(n for _, n in counts.most_common(3))
    assert top3 / V1.tickets >= 0.6
    assert any(t.followup_of for t in plan(V1))


def test_broad_vehicle_spreads_over_every_recipe_without_a_dominant_one():
    counts = Counter(t.recipe_id for t in plan(V2))
    assert len(counts) == len(RECIPES)
    assert max(counts.values()) / V2.tickets <= 0.25
    assert all(t.followup_of is None for t in plan(V2))


def test_evolving_vehicle_changes_its_main_problem_over_time():
    tickets = plan(V3)
    third = len(tickets) // 3
    mains = [Counter(t.recipe_id for t in tickets[i * third : (i + 1) * third]).most_common(1)[0][0]
             for i in range(3)]
    assert len(set(mains)) >= 2
    assert any(t.followup_of for t in tickets)


def test_title_only_personas_follow_the_recipe_fill_rate():
    tickets = plan(V2)
    fill = {r["recipe_id"]: r["description_style"]["fill"] for r in RECIPES}
    low = [t for t in tickets if fill[t.recipe_id] <= 0.5]
    high = [t for t in tickets if fill[t.recipe_id] >= 0.8]
    share = lambda group: sum(t.persona == "title_only" for t in group) / len(group)  # noqa: E731
    assert share(low) > share(high)


def test_solution_mode_is_fix_only_when_the_recipe_has_no_workflow_notes():
    plain = {r["recipe_id"] for r in RECIPES if not r["solution_style"]["boilerplate"]}
    assert all(t.solution_mode == "fix" for t in plan(V2) if t.recipe_id in plain)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_planner.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write `dev3/profiles.py`**

```python
# dev3/profiles.py
"""The three invented vehicles. Serials are in an obviously synthetic range (Z9...), of the real
shape: a letter plus 12 digits."""

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
    Profile("v1-chronic", "Z900000000001", "990001", "990101", 2019, 180,
            date(2022, 1, 3), date(2025, 12, 19), "chronic"),
    Profile("v2-broad", "Z900000000002", "990002", "990102", 2021, 160,
            date(2022, 6, 1), date(2025, 12, 19), "broad"),
    Profile("v3-evolving", "Z900000000003", "990003", "990103", 2020, 170,
            date(2022, 3, 7), date(2025, 12, 19), "evolving"),
)
```

- [ ] **Step 4: Write `dev3/personas.py`**

```python
# dev3/personas.py
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
    "verbose": Persona((30, 70), "Schreibe einen ausfuehrlichen Befund mit Umstaenden und Verlauf."),
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
```

- [ ] **Step 5: Write `dev3/planner.py`**

```python
# dev3/planner.py
"""Lay one vehicle's tickets on a timeline. Pure and seeded: same inputs, same plan."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from dev3 import personas
from dev3.profiles import Profile

DEFAULT_GAP = {"p25": 14, "p50": 45, "p75": 120}
FOLLOWUP_CHANCE = {"chronic": 0.3, "evolving": 0.5, "broad": 0.0}
CHRONIC_SHARE = 0.7
PRIMARY_SHARE = 0.75


@dataclass(frozen=True)
class Planned:
    number: int
    profile: str
    recipe_id: str
    persona: str
    solution_mode: str
    template: int
    created: date
    followup_of: int | None


def _allocate(weights: list[tuple[str, float]], count: int) -> list[str]:
    """Largest-remainder allocation, so shares are exact on any seed."""
    exact = [w * count for _, w in weights]
    counts = [int(x) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: exact[i] - counts[i], reverse=True)
    for i in order[: count - sum(counts)]:
        counts[i] += 1
    return [name for (name, _), n in zip(weights, counts, strict=True) for _ in range(n)]


def _uniform(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _recurring(rng, recipe, count, start, end) -> list[date]:
    """Dates that repeat with the recipe's own gap distribution, scaled to fit the window."""
    gap = recipe["recurrence_gap_days"] or DEFAULT_GAP
    gaps = [rng.choice((gap["p25"], gap["p50"], gap["p75"])) + rng.randint(0, 3) for _ in range(count)]
    span = (end - start).days
    total = sum(gaps)
    scale = min(1.0, span / total) if total else 1.0
    day, dates = 0.0, []
    for g in gaps:
        day += g * scale
        dates.append(start + timedelta(days=min(span, int(day))))
    return dates


def _persona(recipe, rng) -> str:
    style = recipe["description_style"]
    if rng.random() > style["fill"]:
        return "title_only"
    names, weights = zip(*personas.PERSONA_BY_TONE[style["tone"]], strict=True)
    return rng.choices(names, weights)[0]


def _mode(recipe, rng) -> str:
    if not recipe["solution_style"]["boilerplate"]:
        return "fix"
    return rng.choices(personas.SOLUTION_MODES, personas.SOLUTION_MODE_WEIGHTS)[0]


def _assignments(profile: Profile, recipes: list[dict], rng) -> list[tuple[str, date, bool]]:
    """(recipe id, date, eligible for a follow-up link) for every ticket, unsorted."""
    by_support = sorted(recipes, key=lambda r: (-r["support"], r["recipe_id"]))
    ids = [r["recipe_id"] for r in recipes]
    n = profile.tickets
    out: list[tuple[str, date, bool]] = []
    if profile.kind == "broad":
        for recipe_id in _allocate([(i, 1 / len(ids)) for i in ids], n):
            out.append((recipe_id, _uniform(rng, profile.start, profile.end), False))
    elif profile.kind == "chronic":
        chronic = [r["recipe_id"] for r in by_support[:3]]
        rest = [i for i in ids if i not in chronic]
        weights = [(i, CHRONIC_SHARE / 3) for i in chronic]
        weights += [(i, (1 - CHRONIC_SHARE) / len(rest)) for i in rest]
        counts: dict[str, int] = {}
        for recipe_id in _allocate(weights, n):
            counts[recipe_id] = counts.get(recipe_id, 0) + 1
        by_id = {r["recipe_id"]: r for r in recipes}
        for recipe_id, count in counts.items():
            if recipe_id in chronic:
                dates = _recurring(rng, by_id[recipe_id], count, profile.start, profile.end)
                out += [(recipe_id, d, True) for d in dates]
            else:
                out += [(recipe_id, _uniform(rng, profile.start, profile.end), False)
                        for _ in range(count)]
    else:  # evolving: three phases, each with its own main problem
        mains = [r["recipe_id"] for r in by_support[:3]]
        span = (profile.end - profile.start).days
        for phase, main in enumerate(mains):
            lo = profile.start + timedelta(days=span * phase // 3)
            hi = profile.start + timedelta(days=span * (phase + 1) // 3)
            size = n // 3 + (1 if phase < n % 3 else 0)
            others = [i for i in ids if i != main]
            weights = [(main, PRIMARY_SHARE)] + [
                (i, (1 - PRIMARY_SHARE) / len(others)) for i in others
            ]
            for recipe_id in _allocate(weights, size):
                out.append((recipe_id, _uniform(rng, lo, hi), recipe_id == main))
    return out


def plan(profile: Profile, recipes: list[dict], seed: int = 7) -> list[Planned]:
    rng = random.Random(f"{seed}:{profile.name}")
    by_id = {r["recipe_id"]: r for r in recipes}
    raw = sorted(_assignments(profile, recipes, rng), key=lambda x: (x[1], x[0]))
    chance = FOLLOWUP_CHANCE[profile.kind]
    last: dict[str, int] = {}
    out = []
    for number, (recipe_id, created, eligible) in enumerate(raw, 1):
        recipe = by_id[recipe_id]
        follow = last.get(recipe_id) if eligible and rng.random() < chance else None
        out.append(
            Planned(
                number=number,
                profile=profile.name,
                recipe_id=recipe_id,
                persona=_persona(recipe, rng),
                solution_mode=_mode(recipe, rng),
                template=rng.randrange(len(recipe["title_templates"])),
                created=created,
                followup_of=follow,
            )
        )
        last[recipe_id] = number
    return out
```

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_planner.py -v` Expected: 10 passed. Likely tuning points if one fails: the broad profile's `<= 0.25` bound (uniform over 8 recipes is 0.125), the chronic top-3 `>= 0.6` (target 0.7), and the evolving test's thirds (phase boundaries are by date, the test slices by ticket count; the 75% main share leaves wide margin).

- [ ] **Step 7: Commit**

```bash
git add dev3/profiles.py dev3/personas.py dev3/planner.py tests/unit/test_dev3_planner.py
git commit -m "feat(dev3): three vehicle profiles and a seeded timeline planner"
```

---

### Task 12: Writer (prompt, GPU-free client, parser)

**Files:**
- Create: `dev3/writer.py`
- Test: `tests/unit/test_dev3_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_writer.py
from datetime import date

import pytest

from catalog import scrub
from dev3 import planner, standin, writer

RECIPES = {r["recipe_id"]: r for r in standin.catalog()["recipes"]}


def planned(recipe_id="R001", persona="neutral", mode="fix", template=0, number=1):
    return planner.Planned(number, "v1-chronic", recipe_id, persona, mode, template,
                           date(2024, 1, 1), None)


def test_the_prompt_holds_only_catalog_fields_and_the_persona():
    prompt = writer.build_prompt(RECIPES["R001"], planned())
    assert "KOMPONENTE: Hydraulikpumpe" in prompt
    assert "SCHRITT: Dichtung an der Pumpe erneuern" in prompt
    assert "PERSONA: neutral" in prompt
    assert "keine Namen" in prompt


def test_the_prompt_is_unique_per_ticket_so_the_cache_does_not_collapse_them():
    a = writer.build_prompt(RECIPES["R001"], planned(number=1))
    b = writer.build_prompt(RECIPES["R001"], planned(number=2))
    assert a != b


def test_write_returns_title_description_solution():
    title, description, solution = writer.write(writer.EchoClient(), RECIPES["R001"], planned())
    assert "Hydraulikpumpe" in title
    assert description and solution


def test_a_title_only_persona_has_no_description_whatever_the_model_says():
    def chatty(prompt: str) -> str:
        return "TITEL: Pumpe\nBEFUND: ein langer Befund\nLOESUNG: getauscht"

    _, description, _ = writer.write(chatty, RECIPES["R001"], planned(persona="title_only"))
    assert description == ""


def test_the_workflow_mode_gives_a_workflow_only_solution():
    _, _, solution = writer.write(writer.EchoClient(), RECIPES["R001"], planned(mode="workflow"))
    assert "Dichtung" not in solution


def test_an_unparseable_answer_raises_a_coded_error_without_the_text():
    with pytest.raises(writer.WriterError) as caught:
        writer.write(lambda p: "ich antworte frei", RECIPES["R001"], planned())
    assert "UNPARSEABLE" in str(caught.value) and "frei" not in str(caught.value)


def test_a_retry_recovers_a_first_bad_answer():
    answers = iter(["unsinn", "TITEL: Pumpe\nBEFUND: x\nLOESUNG: y"])
    title, _, _ = writer.write(lambda p: next(answers), RECIPES["R001"], planned())
    assert title == "Pumpe"


def test_identifiers_in_a_model_answer_are_scrubbed():
    def leaky(prompt: str) -> str:
        return "TITEL: Pumpe 1234.56789\nBEFUND: Anruf unter +49 171 1234567\nLOESUNG: getauscht"

    title, description, _ = writer.write(leaky, RECIPES["R001"], planned())
    assert scrub.is_clean(title) and scrub.is_clean(description)


def test_the_echo_client_is_deterministic_and_declares_its_identity():
    client = writer.EchoClient()
    prompt = writer.build_prompt(RECIPES["R002"], planned("R002"))
    assert client(prompt) == client(prompt)
    assert client.identity.startswith("dev3-echo:")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_writer.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# dev3/writer.py
"""Turn one recipe and one persona into one ticket's title, description and solutions.

The prompt is built from catalog fields only. The model never sees a real ticket.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

from catalog import scrub
from dev3 import personas
from dev3.planner import Planned

ATTEMPTS = 3
_LABELS = (
    "NR", "KOMPONENTE", "SYMPTOM", "URSACHE", "SCHRITT", "VORLAGE", "PERSONA", "BESCHREIBUNG",
    "LOESUNG_MODUS",
)
_FIELD = re.compile(r"^(" + "|".join(_LABELS) + r"): (.*)$")
_ANSWER = re.compile(r"^(TITEL|BEFUND|LOESUNG)\s*:\s*(.*)$", re.IGNORECASE)


class WriterError(Exception):
    """Carries a code and a ticket label, never model text."""


def build_prompt(recipe: dict, planned: Planned, attempt: int = 0) -> str:
    persona = personas.PERSONAS[planned.persona]
    template = recipe["title_templates"][planned.template % len(recipe["title_templates"])]
    lines = [
        "Du schreibst ein synthetisches Support-Ticket fuer ein Test-Datenset. Erfinde keine "
        "Namen, E-Mail-Adressen, Telefonnummern, Seriennummern, Teilenummern oder Daten.",
        f"NR: {planned.profile}-{planned.number}-{attempt}",
        f"KOMPONENTE: {recipe['component']}",
        f"SYMPTOM: {recipe['symptom']}",
        f"URSACHE: {recipe['cause']}",
        *[f"SCHRITT: {step}" for step in recipe["fix_steps"]],
        f"VORLAGE: {template}",
        f"PERSONA: {planned.persona}",
        f"BESCHREIBUNG: {'nein' if persona.words is None else 'ja'}",
        f"LOESUNG_MODUS: {planned.solution_mode}",
        persona.instruction,
        personas.MODE_INSTRUCTION[planned.solution_mode],
        "Der TITEL folgt der VORLAGE; ersetze <component> und <symptom> sinngemaess.",
        "Antworte genau so:\nTITEL: ...\nBEFUND: ...\nLOESUNG: ...",
    ]
    return "\n".join(lines)


def parse_fields(prompt: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in prompt.splitlines():
        match = _FIELD.match(line)
        if match:
            found.setdefault(match.group(1), []).append(match.group(2))
    return found


class EchoClient:
    """GPU-free stand-in: deterministic text assembled from the prompt's own fields."""

    identity = "dev3-echo:v1"

    def __call__(self, prompt: str) -> str:
        f = parse_fields(prompt)
        rng = random.Random(f["NR"][0])
        title = (
            f["VORLAGE"][0]
            .replace("<component>", f["KOMPONENTE"][0])
            .replace("<symptom>", f["SYMPTOM"][0])
        )
        described = f["BESCHREIBUNG"][0] == "ja"
        description = (
            f"{f['SYMPTOM'][0]} an {f['KOMPONENTE'][0]}, vermutlich {f['URSACHE'][0]}."
            if described
            else ""
        )
        steps = "; ".join(rng.sample(f["SCHRITT"], k=min(2, len(f["SCHRITT"]))))
        mode = f["LOESUNG_MODUS"][0]
        solution = {
            "fix": steps,
            "fix+workflow": f"{steps}. Kunde wurde informiert.",
            "workflow": "Kunde wurde informiert, Ticket kann geschlossen werden.",
        }[mode]
        return f"TITEL: {title}\nBEFUND: {description}\nLOESUNG: {solution}"


def _parse_answer(text: str) -> dict[str, str] | None:
    parts: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        match = _ANSWER.match(line.strip())
        if match:
            current = match.group(1).upper()
            parts[current] = match.group(2).strip()
        elif current:
            parts[current] += " " + line.strip()
    return parts if "TITEL" in parts and "LOESUNG" in parts else None


def write(
    client: Callable[[str], str], recipe: dict, planned: Planned
) -> tuple[str, str, str]:
    for attempt in range(ATTEMPTS):
        parts = _parse_answer(client(build_prompt(recipe, planned, attempt)))
        if parts is None or not parts["TITEL"].strip():
            continue
        title = scrub.scrub(parts["TITEL"])
        description = scrub.scrub(parts.get("BEFUND", ""))
        if personas.PERSONAS[planned.persona].words is None:
            description = ""
        return title, description, scrub.scrub(parts["LOESUNG"])
    raise WriterError(f"UNPARSEABLE {planned.profile}-{planned.number}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_writer.py -v` Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add dev3/writer.py tests/unit/test_dev3_writer.py
git commit -m "feat(dev3): ticket writer with a GPU-free echo client"
```

---

### Task 13: Row rendering and labels

**Files:**
- Create: `dev3/rows.py`
- Test: `tests/unit/test_dev3_rows.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_rows.py
import json
import random
from datetime import date

from dev3 import planner, profiles, rows, standin
from profiler.columns import EXPECTED_COLUMNS

RECIPE = standin.catalog()["recipes"][0]  # has a fehlercode shape
PROFILE = profiles.PROFILES[0]


def planned(number=1, created=date(2024, 5, 6), followup=None):
    return planner.Planned(number, PROFILE.name, "R001", "neutral", "fix", 0, created, followup)


def build(text=("Titel", "Befund", "Loesung"), **kw):
    return rows.row(1, PROFILE, RECIPE, planned(**kw), text, random.Random(1))


def test_every_expected_column_is_present():
    assert set(build()) == set(EXPECTED_COLUMNS)


def test_vehicle_columns_are_filled_from_the_profile():
    row = build()
    assert row["vehicleSerialNo"] == PROFILE.serial
    assert row["vehicleId"] == PROFILE.vehicle_id
    assert row["vehicleModelId"] == PROFILE.model_id
    assert row["vehicleYear"] == str(PROFILE.vehicle_year)
    assert row["timestampCreated"] == "2024-05-06"


def test_text_columns_hold_the_written_text():
    row = build()
    assert (row["title"], row["description"], row["solutions"]) == ("Titel", "Befund", "Loesung")


def test_identity_columns_are_empty():
    row = build()
    for column in rows.IDENTITY_COLUMNS:
        assert row[column] == ""


def test_hours_grow_with_the_date():
    early = build(created=date(2022, 3, 1))
    late = build(created=date(2025, 3, 1))
    assert int(late["vehicleHours"]) > int(early["vehicleHours"])


def test_custom_data_is_double_encoded_and_carries_only_a_fehlercode():
    row = build()
    records = json.loads(json.loads(row["customData"]))
    assert [r["key"] for r in records] == ["fehlercode"]
    assert len(records[0]["value"]) == len("1234-5")


def test_a_recipe_without_a_shape_has_no_custom_data_record():
    recipe = dict(RECIPE, fehlercode_shape=None)
    row = rows.row(1, PROFILE, recipe, planned(), ("a", "b", "c"), random.Random(1))
    assert json.loads(json.loads(row["customData"])) == []


def test_the_label_record_links_a_ticket_to_its_recipe():
    label = rows.label(7, PROFILE, planned(number=3, followup=1))
    assert label == {
        "id": 7, "vehicle": PROFILE.name, "number": 3, "recipe_id": "R001",
        "persona": "neutral", "solution_mode": "fix", "followup_of": 1,
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_rows.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
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
    "personId", "merchantName", "merchantId", "merchantNumber", "merchantPhoneNumber",
    "endCustomerName", "endCustomerId", "endCustomerNumber", "endCustomerPhoneNumber",
    "contactEmail", "contactPhone", "contactPhoneTrimmed",
)
BASE_HOURS = 400
HOURS_PER_DAY = 8
# An ordinary category, never the handover one the insight report found; ids are opaque.
CATEGORY_ID = "2"


def _hours(profile: Profile, planned: Planned, rng: random.Random) -> int:
    days = (planned.created - profile.start).days
    return BASE_HOURS + days * HOURS_PER_DAY + rng.randint(0, 20)


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
        "vehicleHours": str(_hours(profile, planned, rng)),
    }
    return {column: filled.get(column, "") for column in EXPECTED_COLUMNS}


def label(index: int, profile: Profile, planned: Planned) -> dict:
    return {
        "id": index,
        "vehicle": profile.name,
        "number": planned.number,
        "recipe_id": planned.recipe_id,
        "persona": planned.persona,
        "solution_mode": planned.solution_mode,
        "followup_of": planned.followup_of,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_rows.py -v` Expected: 8 passed. `render.custom_data([])` json-encodes an empty list twice, so the round-trip yields `[]`.

- [ ] **Step 5: Commit**

```bash
git add dev3/rows.py tests/unit/test_dev3_rows.py
git commit -m "feat(dev3): render the 38 export columns and the label record"
```

---

### Task 14: Verifier

**Files:**
- Create: `dev3/verify.py`
- Test: `tests/unit/test_dev3_verify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_verify.py
import copy
import random

import pytest

from dev3 import planner, profiles, rows, standin, verify, writer

CATALOG = standin.catalog()
RECIPES = {r["recipe_id"]: r for r in CATALOG["recipes"]}


@pytest.fixture(scope="module")
def built():
    out_rows, out_labels, index = [], [], 0
    client = writer.EchoClient()
    rng = random.Random(1)
    for profile in profiles.PROFILES:
        for p in planner.plan(profile, CATALOG["recipes"], 7):
            index += 1
            text = writer.write(client, RECIPES[p.recipe_id], p)
            out_rows.append(rows.row(index, profile, RECIPES[p.recipe_id], p, text, rng))
            out_labels.append(rows.label(index, profile, p))
    return out_rows, out_labels


def check(built, rows_=None, labels=None):
    return verify.check(rows_ or built[0], labels or built[1], profiles.PROFILES, CATALOG["recipes"])


def test_a_faithful_fixture_has_no_problems(built):
    assert check(built) == []


def test_a_filled_identity_column_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[3]["contactEmail"] = "x@example.test"
    assert any(line.startswith("IDENTITY_FILLED") for line in check(built, bad))


def test_a_missing_serial_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[0]["vehicleSerialNo"] = ""
    assert any(line.startswith("SERIAL_COUNTS") for line in check(built, bad))


def test_a_fourth_serial_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[0]["vehicleSerialNo"] = "Z900000000009"
    assert any(line.startswith("SERIAL_COUNTS") for line in check(built, bad))


def test_a_blank_title_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[5]["title"] = ""
    assert any(line.startswith("BLANK_TITLE") for line in check(built, bad))


def test_a_phone_number_in_text_is_flagged_without_printing_it(built):
    bad = copy.deepcopy(built[0])
    bad[7]["description"] = "Rueckruf unter +49 171 1234567"
    found = check(built, bad)
    assert any(line.startswith("NOT_CLEAN") for line in found)
    assert "1234567" not in "\n".join(found)


def test_a_date_outside_the_profile_window_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[0]["timestampCreated"] = "2010-01-01"
    assert any(line.startswith("OUT_OF_WINDOW") for line in check(built, bad))


def test_a_flattened_chronic_vehicle_is_flagged(built):
    labels = copy.deepcopy(built[1])
    ids = sorted(RECIPES)
    for i, label in enumerate(lab for lab in labels if lab["vehicle"] == "v1-chronic"):
        label["recipe_id"] = ids[i % len(ids)]
    assert any(line.startswith("PROFILE_SHAPE v1-chronic") for line in check(built, labels=labels))


def test_a_duplicate_ticket_number_is_flagged(built):
    bad = copy.deepcopy(built[0])
    bad[1]["ticketNumber"] = bad[0]["ticketNumber"]
    assert any(line.startswith("DUPLICATE_NUMBER") for line in check(built, bad))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_verify.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# dev3/verify.py
"""Every way the generated fixture drifted from its plan. Empty means faithful.

Lines are `CODE detail` with a row index or a vehicle name, never row text.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from catalog import scrub
from dev3.profiles import Profile
from dev3.rows import IDENTITY_COLUMNS
from profiler.columns import EXPECTED_COLUMNS

TEXT_COLUMNS = ("title", "description", "solutions")
MIN_SOLUTION_FILL = 0.8
CHRONIC_TOP3 = 0.6
BROAD_MAX_SHARE = 0.25
BROAD_MIN_RECIPES = 6
EVOLVING_MAIN_SHARE = 0.2


def check(
    rows: list[dict[str, str]], labels: list[dict], profiles: tuple[Profile, ...], recipes: list[dict]
) -> list[str]:
    problems: list[str] = []
    if len(rows) != len(labels):
        return ["COUNT rows and labels differ"]
    if rows and set(rows[0]) != set(EXPECTED_COLUMNS):
        problems.append("COLUMNS the column set differs from the export")

    expected = {p.serial: p.tickets for p in profiles}
    if dict(Counter(r["vehicleSerialNo"] for r in rows)) != expected:
        problems.append("SERIAL_COUNTS tickets per serial differ from the profiles")

    numbers = Counter(r["ticketNumber"] for r in rows)
    problems += [f"DUPLICATE_NUMBER row {i}" for i, r in enumerate(rows) if numbers[r["ticketNumber"]] > 1]

    by_serial = {p.serial: p for p in profiles}
    for i, row in enumerate(rows):
        if any(row[c] for c in IDENTITY_COLUMNS):
            problems.append(f"IDENTITY_FILLED row {i}")
        if not row["title"].strip():
            problems.append(f"BLANK_TITLE row {i}")
        for column in TEXT_COLUMNS:
            if not scrub.is_clean(row[column]):
                problems.append(f"NOT_CLEAN row {i} {column}")
        profile = by_serial.get(row["vehicleSerialNo"])
        try:
            created = date.fromisoformat(row["timestampCreated"])
        except ValueError:
            problems.append(f"OUT_OF_WINDOW row {i}")
            continue
        if profile and not profile.start <= created <= profile.end:
            problems.append(f"OUT_OF_WINDOW row {i}")

    if rows and sum(1 for r in rows if r["solutions"].strip()) / len(rows) < MIN_SOLUTION_FILL:
        problems.append("SOLUTION_FILL below the minimum")

    for profile in profiles:
        mine = [lab for lab in labels if lab["vehicle"] == profile.name]
        counts = Counter(lab["recipe_id"] for lab in mine)
        total = len(mine) or 1
        shape_ok = True
        if profile.kind == "chronic":
            shape_ok = sum(n for _, n in counts.most_common(3)) / total >= CHRONIC_TOP3 and any(
                lab["followup_of"] for lab in mine
            )
        elif profile.kind == "broad":
            shape_ok = (
                len(counts) >= min(len(recipes), BROAD_MIN_RECIPES)
                and max(counts.values(), default=0) / total <= BROAD_MAX_SHARE
            )
        elif profile.kind == "evolving":
            mains = [r for r, n in counts.items() if n / total >= EVOLVING_MAIN_SHARE]
            shape_ok = len(mains) >= 2 and any(lab["followup_of"] for lab in mine)
        if not shape_ok:
            problems.append(f"PROFILE_SHAPE {profile.name} does not show its intended pattern")
    return problems
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_verify.py -v` Expected: 9 passed. If `test_a_faithful_fixture_has_no_problems` fails with `NOT_CLEAN` on EchoClient text, a stand-in word is on a name list: reword that stand-in string (Task 10), not the verifier.

- [ ] **Step 5: Commit**

```bash
git add dev3/verify.py tests/unit/test_dev3_verify.py
git commit -m "feat(dev3): verify structure, identity, text and per-vehicle pattern"
```

---

### Task 15: Dev3 CLI, end to end

**Files:**
- Create: `dev3/__main__.py`
- Test: `tests/unit/test_dev3_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev3_main.py
import csv
import json

import pytest

from dev3 import __main__ as cli
from dev3 import standin
from profiler.columns import EXPECTED_COLUMNS


@pytest.fixture
def catalog_file(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(standin.catalog()), encoding="utf-8")
    return path


def run(catalog_file, tmp_path, *extra):
    return cli.main(["--catalog", str(catalog_file), "--out-dir", str(tmp_path / "out"),
                     "--fake", *extra])


def test_the_fake_run_writes_tickets_and_labels(catalog_file, tmp_path):
    assert run(catalog_file, tmp_path) == 0
    out = tmp_path / "out"
    with (out / "tickets.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    labels = [json.loads(line) for line in (out / "labels.jsonl").read_text().splitlines()]
    assert len(rows) == len(labels) == 510
    assert list(rows[0]) == list(EXPECTED_COLUMNS)
    assert len({r["vehicleSerialNo"] for r in rows}) == 3


def test_the_run_is_reproducible(catalog_file, tmp_path):
    run(catalog_file, tmp_path)
    first = (tmp_path / "out" / "tickets.csv").read_bytes()
    run(catalog_file, tmp_path)
    assert (tmp_path / "out" / "tickets.csv").read_bytes() == first


def test_a_catalog_that_fails_the_guard_is_refused_and_writes_nothing(tmp_path):
    bad = standin.catalog()
    bad["recipes"][0]["cause"] = "Teil 1234.56789 defekt"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert run(path, tmp_path) == 2
    assert not (tmp_path / "out" / "tickets.csv").exists()


def test_a_catalog_with_weak_floors_is_refused(tmp_path):
    weak = standin.catalog()
    weak["k"] = 10
    path = tmp_path / "weak.json"
    path.write_text(json.dumps(weak), encoding="utf-8")
    assert run(path, tmp_path) == 2


def test_a_stale_output_is_removed_when_the_run_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "tickets.csv").write_text("stale")
    bad = standin.catalog()
    bad["recipes"] = []
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert run(path, tmp_path) == 2
    assert not (out / "tickets.csv").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_main.py -v` Expected: FAIL, `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# dev3/__main__.py
"""Generate the three-vehicle dev fixture from a released catalog.

    python -m dev3 --catalog local/released/catalog.json --out-dir local/fixtures/dev3 --fake

Drop --fake and pass --base-url to use the model on the H100. It reads only the catalog (which
passed catalog.guard) and writes invented text, so it needs no airlock window.

Exit codes: 0 ok, 2 the catalog was refused, 3 the fixture drifted from its plan.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import sys

from catalog import guard
from dev3 import planner, profiles, rows, verify, writer
from fixtures import llm

MIN_K, MIN_VEHICLES, MIN_DEALERS = 50, 5, 5
OUTPUTS = ("tickets.csv", "labels.jsonl")


def _refusals(catalog: object) -> list[str]:
    if not isinstance(catalog, dict):
        return ["WRONG_TYPE $"]
    floors = {name: catalog.get(name) for name in ("k", "min_vehicles", "min_dealers")}
    if not all(isinstance(v, int) for v in floors.values()):
        return ["WRONG_TYPE $ floors"]
    found = guard.problems(catalog, **floors)
    if floors["k"] < MIN_K or floors["min_vehicles"] < MIN_VEHICLES:
        found.append("FLOOR_TOO_WEAK $.k or $.min_vehicles")
    if floors["min_dealers"] < MIN_DEALERS:
        found.append("FLOOR_TOO_WEAK $.min_dealers")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dev3")
    parser.add_argument("--catalog", type=pathlib.Path, required=True)
    parser.add_argument("--out-dir", type=pathlib.Path, default=pathlib.Path("local/fixtures/dev3"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fake", action="store_true", help="no GPU; deterministic stub")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    args = parser.parse_args(argv)

    for name in OUTPUTS:  # a failed run must not leave an older fixture looking current
        (args.out_dir / name).unlink(missing_ok=True)

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    refused = _refusals(catalog)
    if refused:
        for line in refused:
            print(f"REFUSED {line}")
        return 2
    recipes = catalog["recipes"]
    by_id = {r["recipe_id"]: r for r in recipes}

    inner = writer.EchoClient() if args.fake else llm.VLLM(args.base_url, args.model)
    client = llm.Cached(inner, args.out_dir / "cache", inner.identity)

    rng = random.Random(args.seed)
    out_rows: list[dict[str, str]] = []
    out_labels: list[dict] = []
    for profile in profiles.PROFILES:
        for planned in planner.plan(profile, recipes, args.seed):
            recipe = by_id[planned.recipe_id]
            text = writer.write(client, recipe, planned)
            index = len(out_rows) + 1
            out_rows.append(rows.row(index, profile, recipe, planned, text, rng))
            out_labels.append(rows.label(index, profile, planned))

    problems = verify.check(out_rows, out_labels, profiles.PROFILES, recipes)
    if problems:
        print("ABORT the fixture drifted from its plan:")
        for line in problems:
            print(f"  - {line}")
        return 3

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "tickets.csv").open(  # guard: ok(synthetic fixture)
        "w", newline="", encoding="utf-8"
    ) as handle:
        table = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        table.writeheader()
        table.writerows(out_rows)
    (args.out_dir / "labels.jsonl").write_text(  # guard: ok(synthetic fixture)
        "".join(json.dumps(label, ensure_ascii=False) + "\n" for label in out_labels),
        encoding="utf-8",
    )
    print(f"wrote {args.out_dir} ({len(out_rows)} rows, {len(profiles.PROFILES)} vehicles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes, then lint**

Run: `.venv/bin/python -m pytest tests/unit/test_dev3_main.py -v` Expected: 5 passed.
Run: `.venv/bin/ruff check catalog dev3 tests && .venv/bin/ruff format catalog dev3 tests` Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add dev3/__main__.py tests/unit/test_dev3_main.py
git commit -m "feat(dev3): CLI that writes tickets and labels from a released catalog"
```

---

### Task 16: Whole-suite check and record

**Files:**
- Modify: `docs/STATE.md` (add a short section; read the file first, it was scrubbed on 2026-10-21 and its layout may differ from the version this plan was written against)

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` Expected: all previous tests still pass plus the new ones. Known, unrelated: `test_the_test_suite_does_not_dirty_the_quarantine` may fail on a workstation with leftovers; the two Postgres files need `PG_DSN`. Report any other failure.

- [ ] **Step 2: Lint the repo**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .` Expected: clean.

- [ ] **Step 3: Smoke the fake path end to end on the stand-in**

The stand-in catalog must be written by a script because the guard blocks nothing here (`.json` is allowed):

```bash
.venv/bin/python -c "import json, pathlib; from dev3 import standin; pathlib.Path('local/fixtures').mkdir(parents=True, exist_ok=True); pathlib.Path('local/fixtures/standin-catalog.json').write_text(json.dumps(standin.catalog()))"
.venv/bin/python -m dev3 --catalog local/fixtures/standin-catalog.json --out-dir local/fixtures/dev3 --fake
```

Expected: `wrote local/fixtures/dev3 (510 rows, 3 vehicles)`. The output CSV cannot be read by an agent (the guard blocks `.csv`); the operator may open it.

- [ ] **Step 4: Add the record to `docs/STATE.md`**

Add a section after the Insight sections, in the file's own style, with: what was built, that Stage 1 has never run on real data, the three open operator items from the spec, the lint-scope reminder, and "Next: Window E wiring plan". No row values, no coarse real figures.

- [ ] **Step 5: Commit**

```bash
git add docs/STATE.md
git commit -m "docs: record the dev3 fixture work and what is left for the operator"
```

---

## Self-review against the spec

| Spec requirement | Where |
|---|---|
| Recipe schema, closed allowlist, no extremes, whole numbers | Tasks 1, 4 |
| Scrub of names, serials, part numbers, phones, dates | Task 2 |
| Release floors k / vehicles / dealers counted per ticket | Tasks 6, 4 |
| Handover slips dropped, noise dropped | Task 6 (`eligible`) |
| Semantic clustering, row-order independent | Task 6 (and the spec correction) |
| LLM drafts a recipe, rejects incoherent, copied, malformed | Tasks 3, 8 |
| Style statistics, gap quantiles, co-occurrence, fehlercode shape | Task 7 |
| Draft -> hand review -> guard -> release, sealed outputs, stale removal | Task 9 |
| Three vehicle profiles with invented serials | Task 11 |
| Planner from recurrence gaps and co-occurrence | Tasks 7, 11 |
| Writer sees catalog fields only; personas; solution modes | Task 12 |
| 38-column rows, identity columns empty (operator ruling) | Task 13 |
| Ground-truth labels | Task 13 |
| Verification: structure, PII sweep, per-vehicle pattern | Task 14 |
| Tests built on stand-ins only | all tasks |

Names checked across tasks: `catalog.guard.problems(catalog, *, k, min_vehicles, min_dealers)`, `catalog.select.candidates(...)` and `Candidate`, `catalog.stats.style` / `cooccurrence` / `quantiles`, `catalog.draft.draft`, `catalog.build.build`, `dev3.planner.Planned` fields, `dev3.rows.row(index, profile, recipe, planned, text, rng)` and `rows.label(index, profile, planned)`, `dev3.writer.write(client, recipe, planned)` and `EchoClient`, `dev3.verify.check(rows, labels, profiles, recipes)`.

## Changes after the plan (2026-10-21) - read before trusting the code blocks above

The tasks were executed by subagents; a final review and the operator's leak-gate requirement
changed the code. Where this section and a code block above disagree, the code in the repository
and this section win.

- **Guard hardened:** never raises, validates `schema_version` and exact-int floors, hard minimums
  (`allow_weak` keyword for rehearsals only), closed character class (shared helpers in
  `catalog/schema.py`).
- **Draft:** rejects angle tokens and characters outside the class in every field, checks the RAW
  model strings for copied runs as well as the scrubbed ones, swallows client exceptions
  (`client_error`).
- **Statistics:** released numbers need at least k source tickets (gaps also `min_vehicles`
  distinct serials); co-occurrence needs both vehicle and dealer floors; serials and dealers are
  counted case-insensitively; shape ties break by shape string; same-day pairs are ignored.
- **Sampling:** hash-ordered, at most 2 tickets per dealer, round-robin (row-order independent).
- **Planner:** `PlanError` for fewer than 4 recipes and for a ticket-count mismatch; follow-ups
  link only to an earlier eligible ticket of the same recipe within 180 days.
- **Writer:** scrubs before validating, retries on empty titles, leftover placeholders and empty
  descriptions of personas that need one.
- **Rows/labels:** `vehicleHours` is non-decreasing by date; labels carry `followup_of_id` (global
  ticket id) next to the vehicle-local `followup_of`; `rows.label` takes an `id_of_number` map.
- **Verifier:** ties labels to rows per index, checks persona/description consistency, validates
  follow-ups, reports malformed rows instead of raising.
- **Leak gate:** see the spec section of the same name (`catalog/leakcheck.py`,
  `catalog/release_gate.py`, `tests/leak/`, `make leak-test`). The CLI gained the `leakcheck`
  subcommand and a required `release --report`; its built-in `--llm fake` drafter now builds
  recipes from words the sampled tickets share, because invented generic words are rejected by
  the rare-word floor.

## Out of scope (separate plan after operator decisions)

**Window E wiring.** Running Stage 1 on real data needs: a local LLM inside the `--network=none` container (the sealed image has e5 weights only; the model weights and a server must be baked in, which grows the image far beyond today's 9.3 GB and the ship time beyond an hour), a `window.sh` stanza `e` with `WINDOW_OUT=(catalog.json)`, a shred list, a GPU claim through the fair-use guard, `infra/profiler/rehearse-window-e.sh` and `make window-e-rehearsal`, and a runbook section written for reading with no AI. That plan needs the operator's ruling on the model and its size (open item 2 in the spec), on the `catalog/` lint scope, and on whether the leakage gate runs once on the finished fixture. Everything in this plan runs and is tested without it.
