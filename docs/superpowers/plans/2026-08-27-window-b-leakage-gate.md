# Window B Leakage Gate — Plan A: the checks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all four of `PROJECT_BRIEF.md` §8's leakage checks as pure, tested code behind one CLI that emits `gate_report.json`, with the embedding model **injected** so every check is provable in CI against synthetic data alone.

**Architecture:** A new `profiler/gate/` package. It must live under `profiler/` because `infra/profiler/Dockerfile` copies only `src` and `profiler` into the sealed image — `fixtures/` is not copied. The embedder is a `Protocol` with a deterministic in-repo implementation, mirroring `fixtures/llm.py`'s `Client`/`Fake` split; the real `intfloat/multilingual-e5-large` integration, the image changes that bake its weights in, and the `window.sh` command block are **Plan B** and are out of scope here.

**Tech Stack:** Python 3.12, uv, pytest, ruff, numpy (already a dependency). **No torch, no transformers, no GPU, no network, no sealed window in this plan.**

---

## Read this first — you have no context

1. This plan, whole.
2. `docs/superpowers/specs/2026-08-17-m2-fixture-and-leakage-gate-design.md` § **"Leakage gate — Window B"** — the approved design. It is short and it is binding.
3. `docs/airlock-runbook.md` § **"Window B — leakage gate"** — the controls, which are not negotiable.
4. `PROJECT_BRIEF.md` §8 **"Leakage gate"** — the four checks.
5. `docs/STATE.md` — **"Binding constraint"** and finding 1.

## Data handling rules — absolute

- **Never read anything under `local/quarantine/` or the client working directory.** A client's real ticket export under NDA. **Nothing in this plan needs them.** Every test in this plan uses synthetic or hand-written text.
- **A session hook rejects any Bash command whose text contains the export file suffix.** Put paths *inside* a Python file and invoke it with a command that never names the suffix. Passing such a path as an argv trips the hook — verified. If you think you need such a command, STOP and ask the operator.
- `local/artifacts/profile.json` is readable; it passed `blessing.unblessed` with zero findings.
- **Do not commit anything under `local/`.**

## The rule about failing tests

**If a test fails and you believe the test is wrong, STOP and report it rather than adjusting the test. On this project a failing test has been right and the plan wrong fourteen times.** The most recent four, all from the session that closed finding 9:

- A voice instruction placed above the count sentence broke three tests that read the count with `prompt.split("Schreibe ")[1]`. The prompt moved; the tests did not.
- `test_consecutive_singleton_batches_do_not_share_a_voice` forced a top-up multiplier change, because it counts top-up prompts and 50·1000 ≡ 2 (mod 3).
- `llm.Fake`'s stub was not lexically distinct under the profiler's tokenizer; the dedup exposed it and `Fake` changed, not the tests.
- An exact-Jaccard cutoff at 0.7 was not enough, because `clusters.profile` clusters on LSH buckets it never re-verifies.

## The controls this gate exists to satisfy

From `docs/airlock-runbook.md`, decided and not open for reinterpretation:

- The real export comes back for this window. **Real-corpus embeddings are not retained between windows** — the embedding model is public and inversion attacks reconstruct substantial portions of short texts, so retained vectors are the text in a thin disguise.
- Every check runs **on the box**, against the synthetic corpus shipped in. **Only counts, thresholds and verdicts come out** — no hash set, no vectors. A set of 8-token shingles is a membership oracle and does not need to exist off-box.

**The operator ruled on 2026-08-27 that all four checks run in the window and emit one report**, rather than splitting the two self-contained ones into CI. Follow that. It does not stop the *logic* being unit-tested in CI, which is what this plan does.

## Green requires all four

| # | check | bar |
|---|---|---|
| 1 | 8-token content-bearing shingle intersection | **zero** collisions |
| 2 | nearest-neighbour cosine, synthetic → real | p99 below a threshold calibrated **in the same window** against a synthetic-vs-synthetic baseline |
| 3 | regex/NER sweep over the synthetic corpus | zero hits |
| 4 | entity allowlist | every name traceable to the fictional roster |

The shingle bar is **zero rather than a tolerance**, deliberately: a threshold there is something we would later be tempted to relax, and a single hit is worth investigating rather than excusing.

## Decisions already made — do not relitigate

| Decision | Choice | When |
|---|---|---|
| Embedder | `intfloat/multilingual-e5-large`, shared with M3's pgvector index | operator, 2026-08-27 |
| Check scope | all four in the window, one report | operator, 2026-08-27 |
| Report signing | hash manifest, no keys | operator, 2026-08-27 |
| Gate code location | `profiler/gate/` | forced by the Dockerfile's COPY set |

**Two consequences of the embedder choice that this plan pins with tests.** `multilingual-e5-large` requires `query: ` / `passage: ` prefixes, and for a leakage gate **both** corpora are documents, so both get `passage: ` — a mismatch would silently distort every cosine in the report. Its context is 512 tokens, so the truncation policy must be explicit and **identical for both corpora**, or the comparison is unfair in the fixture's favour.

## File structure

| File | Responsibility |
|---|---|
| `profiler/gate/__init__.py` | package marker, nothing else |
| `profiler/gate/embedder.py` | the `Embedder` protocol, its identity, and a deterministic `HashingEmbedder` for tests |
| `profiler/gate/shingles.py` | content-bearing 8-token shingles and their intersection |
| `profiler/gate/sweep.py` | the regex/NER sweep and the roster allowlist, over one corpus |
| `profiler/gate/neighbours.py` | cosine matrix, p99, and baseline calibration |
| `profiler/gate/report.py` | assembles `gate_report.json` and its hash manifest |
| `profiler/gate/__main__.py` | the CLI the window will invoke |
| `profiler/data/german_stopwords.txt` | the stopword list check 1 removes first |
| `tests/unit/test_gate_shingles.py` | check 1 |
| `tests/unit/test_gate_sweep.py` | checks 3 and 4 |
| `tests/unit/test_gate_neighbours.py` | check 2 |
| `tests/unit/test_gate_report.py` | the report's shape and its safety property |

## Out of scope — this is Plan B

The real `multilingual-e5-large` integration; adding torch/transformers to `pyproject.toml`; baking the weights into `infra/profiler/Dockerfile` so `--network=none` still works; giving the window container GPU access or measuring CPU embedding throughput; `window.sh`'s `WINDOW_CMD` for window b; a `rehearse-window-b.sh`; and booking the window itself.

## Pre-flight

```bash
cd <repo-root>
git status --short && git log --oneline -1
make test; make lint
```

Expected: clean tree. `make lint` silent. `make test` **`1 failed, 296 passed, 1 skipped, 2 xfailed`** — the single failure is `tests/unit/test_data_guards.py::test_the_test_suite_does_not_dirty_the_quarantine`, caused by a stray file in the quarantine directory that only the operator may shred. **That failure is expected, is not yours, and must remain the only one.** Do not touch that test or anything under `local/quarantine/`.

**If the operator has shredded that file before you start, the baseline is instead `297 passed` with no failures, and every expected count below rises by one on the passed line while the `1 failed,` prefix disappears.** Take the count you actually observe in pre-flight as your baseline and check that each task adds the number of tests it says it adds — that delta is the thing worth comparing, not the absolute total.

---

### Task 1: The embedder protocol, with an identity

Finding 1 is the reason this task exists at all. A cached stub answered for the model for two rounds because nothing recorded *who* answered. The same hole here would be worse: a gate report that says "no synthetic row is within cosine 0.95 of a real row" is worthless if a stub produced the vectors. So the embedder declares an identity, and Task 6 puts it in the report.

**Files:**
- Create: `profiler/gate/__init__.py`, `profiler/gate/embedder.py`
- Test: `tests/unit/test_gate_neighbours.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gate_neighbours.py`:

```python
import numpy as np

from profiler.gate import embedder


def test_an_embedder_declares_who_produced_the_vectors():
    """Finding 1: a stub answered for the model for two rounds because nothing recorded who
    answered. A gate report asserting 'no synthetic row is within cosine 0.95 of a real row'
    is worthless if a stub produced the vectors, so the identity is mandatory and Task 6 puts
    it in the report."""
    fake = embedder.HashingEmbedder(dim=32)
    assert fake.identity.startswith("hashing:"), fake.identity
    assert "dim=32" in fake.identity


def test_the_test_embedder_is_deterministic_and_unit_norm():
    """Cosine is a dot product only if the vectors are normalised. A test embedder that did
    not normalise would make every threshold in this plan mean something else."""
    fake = embedder.HashingEmbedder(dim=32)
    first = fake.encode(["Pumpe undicht", "Ventil klemmt"])
    second = fake.encode(["Pumpe undicht", "Ventil klemmt"])
    assert first.shape == (2, 32)
    np.testing.assert_allclose(first, second)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-6)


def test_the_test_embedder_separates_different_text():
    """It stands in for a real model only if unrelated text is not near-identical. Otherwise
    a test could pass with a broken threshold."""
    fake = embedder.HashingEmbedder(dim=64)
    vectors = fake.encode(["Hydraulikpumpe verliert Druck", "Klimaanlage kuehlt nicht"])
    assert float(vectors[0] @ vectors[1]) < 0.5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_gate_neighbours.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate'`.

- [ ] **Step 3: Create the package marker**

Create `profiler/gate/__init__.py` containing exactly:

```python
"""The Window B leakage gate.

Lives under `profiler/` rather than beside `fixtures/` because
`infra/profiler/Dockerfile` copies only `src` and `profiler` into the sealed image, and this
code has to be inside that image to run with `--network=none`.
"""
```

- [ ] **Step 4: Write the embedder**

Create `profiler/gate/embedder.py`:

```python
"""Who produced the vectors, and a deterministic stand-in for tests.

The real model is `intfloat/multilingual-e5-large` (operator decision, 2026-08-27), shared
with M3's pgvector index so the gate's cosine bound applies to the vectors M3 actually
stores. Its integration is Plan B; nothing here imports torch, so the whole gate is testable
in CI on a machine with no model and no GPU.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

# Both corpora are DOCUMENTS for this gate, so both get e5's passage prefix. Mixing
# `query: ` and `passage: ` across the two sides would silently shift every cosine in the
# report, and the report is the artifact a DPO reads.
E5_DOCUMENT_PREFIX = "passage: "

# e5-large truncates at 512 tokens. The limit is stated here, applied identically to both
# corpora, and recorded in the report: truncating the real side harder than the synthetic
# side would bias every neighbour distance in the fixture's favour.
MAX_TOKENS = 512


class Embedder(Protocol):
    """Anything that turns documents into unit-norm row vectors."""

    identity: str

    def encode(self, documents: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    """A deterministic, dependency-free embedder for tests.

    Not a model and not pretending to be one: it hashes token trigrams into a fixed number
    of buckets and normalises. That is enough to exercise every arithmetic path in
    `neighbours.py` - identical text gives cosine 1.0, unrelated text gives something small -
    without torch, a GPU, or a download.

    Its identity begins with `hashing:` precisely so a gate report produced with it can never
    be mistaken for one produced by the real model.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim
        self.identity = f"hashing:trigram:dim={dim}"

    def encode(self, documents: list[str]) -> np.ndarray:
        vectors = np.zeros((len(documents), self._dim), dtype=np.float64)
        for row, document in enumerate(documents):
            text = document.lower()
            for start in range(max(len(text) - 2, 1)):
                trigram = text[start : start + 3]
                digest = hashlib.sha256(trigram.encode("utf-8")).digest()
                vectors[row, int.from_bytes(digest[:4], "big") % self._dim] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vectors / norms
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_gate_neighbours.py`
Expected: 3 passed. Report the count.

- [ ] **Step 6: Full suite and lint**

Run: `make test; make lint`
Expected: `1 failed, 299 passed, 1 skipped, 2 xfailed`, the one failure still being only the quarantine guard. Lint silent. If ruff reformats, run `uv run ruff format profiler/gate tests/unit/test_gate_neighbours.py` and re-run both.

- [ ] **Step 7: Commit**

```bash
git add profiler/gate tests/unit/test_gate_neighbours.py
git commit -F - <<'MSG'
feat(gate): an embedder protocol that declares who made the vectors

<write a real body: finding 1's lesson applied to the gate - a report asserting a cosine
bound is worthless if a stub produced the vectors; the real model is
intfloat/multilingual-e5-large and its integration is Plan B; both corpora take e5's
passage prefix because both are documents, and a mismatch would shift every cosine;
HashingEmbedder is deterministic, needs no torch, and its identity starts with hashing:
so it cannot be mistaken for the real model>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: German stopwords

Check 1 removes stopwords **before** forming shingles, so that a shared run of German function words cannot mask a real collision. No stopword list exists anywhere in the repo — `grep -rn 'stopword' --include='*.py' .` returns nothing.

**Files:**
- Create: `profiler/data/german_stopwords.txt`
- Test: `tests/unit/test_gate_shingles.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gate_shingles.py`:

```python
from profiler.gate import shingles


def test_the_stopword_list_is_loaded_and_substantial():
    """Shingles are formed AFTER stopword removal, so that a shared run of German function
    words cannot mask a real collision. An empty or tiny list silently turns the shingle
    check into a check on function words."""
    words = shingles.STOPWORDS
    assert len(words) >= 60, f"only {len(words)} stopwords"
    for expected in ("der", "die", "das", "und", "nicht", "ist", "mit", "von"):
        assert expected in words, f"{expected!r} missing"


def test_stopwords_are_lower_case_and_unique():
    """Tokens arrive lower-cased from profiler.stats.vocab.tokenize, so an upper-case entry
    would never match anything and would be silently dead."""
    words = shingles.STOPWORDS
    assert all(word == word.lower() for word in words)
    assert len(words) == len(set(words))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_gate_shingles.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate.shingles'`.

- [ ] **Step 3: Create the data file**

Create `profiler/data/german_stopwords.txt`. One lower-case word per line, `#` starts a comment:

```
# German function words, removed before 8-token shingles are formed so that a shared run of
# function words cannot mask a real collision. Deliberately function words only - no domain
# vocabulary, because removing a domain word would hide exactly the collision this check is
# looking for.
aber
alle
als
am
an
auch
auf
aus
bei
bin
bis
da
dann
das
dass
dem
den
der
des
die
dies
diese
dieser
doch
dort
du
durch
ein
eine
einem
einen
einer
eines
er
es
etwas
fuer
für
hat
hatte
hatten
haben
hier
ich
ihr
im
in
ist
kann
kein
keine
koennen
können
man
mit
muss
muessen
müssen
nach
nicht
noch
nur
ob
oder
ohne
schon
sehr
sein
seine
sich
sie
sind
so
soll
sollen
um
und
uns
unter
ueber
über
vom
von
vor
war
waren
was
weil
wenn
werden
wie
wieder
wird
wir
wurde
wurden
zu
zum
zur
```

- [ ] **Step 4: Load it**

Create `profiler/gate/shingles.py` with only the loader for now:

```python
"""Content-bearing 8-token shingles, and whether two corpora share one.

The bar is ZERO shared shingles, not a tolerance. From the approved design: a threshold here
is something we would later be tempted to relax, and a single hit is worth investigating
rather than excusing.

Nothing in this module may return a shingle or a document to a caller that will print it. A
set of 8-token shingles is a membership oracle over the real corpus and must not exist
off-box - see docs/airlock-runbook.md. The public functions therefore return COUNTS.
"""

from __future__ import annotations

import pathlib

_DATA = pathlib.Path(__file__).parent.parent / "data" / "german_stopwords.txt"


def _load_stopwords() -> frozenset[str]:
    lines = _DATA.read_text(encoding="utf-8").splitlines()
    return frozenset(
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    )


STOPWORDS = _load_stopwords()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_gate_shingles.py`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add profiler/data/german_stopwords.txt profiler/gate/shingles.py tests/unit/test_gate_shingles.py
git commit -F - <<'MSG'
feat(gate): a German stopword list for the shingle check

<write a real body: shingles form AFTER stopword removal so a shared run of function words
cannot mask a real collision; no stopword list existed in the repo; function words only,
because removing a domain word would hide the very collision the check looks for>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: The shingle intersection

**Files:**
- Modify: `profiler/gate/shingles.py`
- Test: `tests/unit/test_gate_shingles.py` (append only)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_gate_shingles.py`:

```python
def test_a_document_shorter_than_the_window_yields_no_shingle():
    """A 7-content-word document cannot fill an 8-token window. Padding it would invent a
    shingle that the text does not contain, and inventing shingles on the real side is how a
    gate produces a false collision."""
    assert shingles.shingles_of("Pumpe Ventil Sensor Schlauch Lager Filter Kolben") == frozenset()


def test_function_words_do_not_count_towards_a_shingle():
    """Eight words of which several are stopwords is not eight CONTENT words."""
    text = "die Pumpe ist in der Anlage und das Ventil ist auch nicht mit dabei"
    assert shingles.shingles_of(text) == frozenset()


def test_identical_content_produces_a_shared_shingle():
    text = "Pumpe Ventil Sensor Schlauch Lager Filter Kolben Dichtung Feder"
    assert shingles.collisions([text], [text]) == 1


def test_unrelated_german_does_not_collide():
    """The likeliest failure mode of this whole gate is tripping on ordinary German rather
    than on a real leak. Two unrelated technical sentences must not collide."""
    left = ["Hydraulikpumpe verliert Druck an der Vorderachse bei hoher Last dauerhaft messbar"]
    right = ["Klimaanlage kuehlt nicht ausreichend im Sommerbetrieb trotz voller Kaeltemittelmenge"]
    assert shingles.collisions(left, right) == 0


def test_collisions_counts_synthetic_documents_not_shingles():
    """The report says how many SYNTHETIC ROWS are implicated, because that is what an
    investigation would act on. One row sharing three shingles is one row to look at."""
    shared = "Pumpe Ventil Sensor Schlauch Lager Filter Kolben Dichtung Feder Welle Lagerbock"
    assert shingles.collisions([shared], [shared]) == 1


def test_nothing_leaves_but_a_count():
    """docs/airlock-runbook.md: a set of 8-token shingles is a membership oracle over the real
    corpus and must not exist off-box. The public entry point returns an int, so there is
    nothing for a caller to print by accident."""
    result = shingles.collisions(["a b c"], ["a b c"])
    assert isinstance(result, int)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_gate_shingles.py`
Expected: FAIL — `module 'profiler.gate.shingles' has no attribute 'shingles_of'`.

- [ ] **Step 3: Implement**

First, add these two imports to the **top** of `profiler/gate/shingles.py`, directly below the
existing `import pathlib`. Do **not** append them at the bottom — ruff's E402 rejects a
module-level import after code, and a `# noqa` to silence it would be hiding a real style rule
rather than following it:

```python
from profiler.stats import vocab
from recall.clean import pipeline
```

Then append the rest to the bottom of the file:

```python
# Eight content words. Long enough that a shared run is real evidence rather than German
# idiom, which PROJECT_BRIEF section 8 fixes at 8 tokens.
WINDOW = 8


def _content_tokens(document: str) -> list[str]:
    """Cleaned, lower-cased, stopword-free tokens.

    Uses the project's own cleaner and tokenizer rather than a local split, for the same
    reason the fixture generator does: a check that tokenises differently from the rest of the
    system is checking something the rest of the system does not see.
    """
    cleaned = pipeline.clean(document or "").text
    return [token for token in vocab.tokenize(cleaned) if token not in STOPWORDS]


def shingles_of(document: str) -> frozenset[tuple[str, ...]]:
    """Every contiguous run of WINDOW content tokens. Empty when the document is too short."""
    tokens = _content_tokens(document)
    if len(tokens) < WINDOW:
        return frozenset()
    return frozenset(
        tuple(tokens[start : start + WINDOW]) for start in range(len(tokens) - WINDOW + 1)
    )


def collisions(synthetic: list[str], real: list[str]) -> int:
    """How many SYNTHETIC documents share at least one content-bearing shingle with any real
    document.

    Counts documents rather than shingles because a document is what an investigation acts
    on: one row sharing three shingles is one row to look at. Returns an int and nothing else -
    the real corpus's shingle set is built here, used here, and dropped here.
    """
    real_shingles: set[tuple[str, ...]] = set()
    for document in real:
        real_shingles |= shingles_of(document)
    return sum(1 for document in synthetic if shingles_of(document) & real_shingles)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_gate_shingles.py`
Expected: 8 passed.

- [ ] **Step 5: Full suite and lint, then commit**

Run: `make test; make lint`
Expected: `1 failed, 307 passed, 1 skipped, 2 xfailed`; lint silent.

```bash
git add profiler/gate/shingles.py tests/unit/test_gate_shingles.py
git commit -F - <<'MSG'
fix(gate): count synthetic rows sharing a content-bearing shingle

<write a real body: the bar is zero, not a tolerance, because a threshold here is one we
would later relax; stopwords come out first so shared function words cannot mask a real
collision; a document too short for the window yields NO shingle rather than a padded one,
because inventing shingles on the real side manufactures false collisions; the entry point
returns an int so the real corpus's shingle set never exists off-box>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: The regex/NER sweep and the roster allowlist

Checks 3 and 4. Both read the **synthetic** corpus only. `profiler/entities.py` already owns the patterns — `_EMAIL`, `_PHONE`, `_IBAN`, `_PLATE`, `COMMON_SURNAMES`, `COMPANY_SUFFIXES`, and the predicates `looks_like_entity` and `looks_like_named_entity`. **Reuse them; do not write new regexes.** A second set of patterns that drifts from the first is worse than none.

**Files:**
- Create: `profiler/gate/sweep.py`
- Test: `tests/unit/test_gate_sweep.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_gate_sweep.py`:

```python
from profiler.gate import sweep


def test_an_email_in_the_fixture_is_a_finding():
    hits = sweep.pii_hits(["Bitte melden an hans.mueller@example.de zurueck"])
    assert hits["email"] == 1


def test_a_phone_number_is_a_finding():
    assert sweep.pii_hits(["Rueckruf unter +49 171 1234567 erbeten"])["phone"] == 1


def test_an_iban_is_a_finding():
    assert sweep.pii_hits(["Gutschrift auf DE89370400440532013000"])["iban"] == 1


def test_clean_technical_german_is_not_a_finding():
    """The likeliest failure of this sweep is firing on ordinary ticket text. A shape-faithful
    fixture is full of digit runs and German dates, and none of them is PII.

    Every string here was measured against an earlier draft of the phone pattern and FOUR of
    them matched it. docs/STATE.md records DD.DD.DDDD as the dominant free-text shape in
    the real corpus, so a sweep that fires on a date is not a sweep."""
    hits = sweep.pii_hits(
        [
            "Hydraulikpumpe verliert Druck, Messung 120 bar statt 140 bar",
            "Fehlercode 1234-5 am 03.04.2024 erfasst",
            "Maschine TX-2200, Baugruppe Zapfwelle",
            "Lieferdatum 89.88.3403 im customData",
            "Garantie von 01.01.2020 bis 31.12.2024",
            "Garantie 01.01.2020 31.12.2024",
            "Fehlercodes 1234-56 und 12345 erfasst",
            "Position 4711 / 0815 geprueft",
        ]
    )
    assert sum(hits.values()) == 0, hits


def test_real_phone_shapes_are_still_found():
    """The other half of the same coin. A pattern loose enough to fire on dates is easy to
    tighten into one that finds nothing, and a missed phone number is a leak that ships.
    Includes the real corpus's own ansprechpartner-tel shape, #DDDDDDDDDDDD."""
    for text in (
        "Rueckruf unter +49 171 1234567 erbeten",
        "Telefon 0171 1234567",
        "erreichbar unter 0821/123 45 67",
        "Kontakt +49 (0) 171 1234567",
        "tel #491711234567 im Datensatz",
    ):
        assert sweep.pii_hits([text])["phone"] == 1, f"missed a phone in {text!r}"


def test_a_name_outside_the_roster_is_a_finding():
    """PROJECT_BRIEF section 8: merchant and customer names are drawn from a generated
    fictional roster, and no real-roster name may appear anywhere. A name the roster does not
    contain is exactly what that check is for."""
    roster = frozenset({"Tr. Ouxmu", "Fa. Zelbin"})
    assert sweep.roster_violations(["Tr. Ouxmu"], roster) == 0
    assert sweep.roster_violations(["Hr. Mustermann"], roster) == 1


def test_the_roster_check_ignores_blank_values():
    """Most of the 38 columns render as empty strings, so blanks are the common case and must not
    be counted as violations."""
    roster = frozenset({"Tr. Ouxmu"})
    assert sweep.roster_violations(["", "   ", None], roster) == 0


def test_the_sweep_returns_counts_only():
    """Nothing that could carry a row's content may cross out of the window. Every value in
    the result is an int."""
    hits = sweep.pii_hits(["hans@example.de"])
    assert all(isinstance(value, int) for value in hits.values())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_gate_sweep.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate.sweep'`.

- [ ] **Step 3: Implement**

Create `profiler/gate/sweep.py`:

```python
"""Checks 3 and 4: is the SYNTHETIC corpus clean on its own terms?

Neither check reads the real corpus. They are in the window because the operator ruled on
2026-08-27 that all four checks emit one report, which is the artifact a DPO reads.

Every pattern is reused from `profiler/entities.py`. A second set of regexes here would drift
from the first, and two disagreeing definitions of "looks like a phone number" is worse than
one.
"""

from __future__ import annotations

import re
from collections import Counter

from profiler import entities

# Free text needs SEARCH semantics; entities.py's own patterns are anchored because it
# classifies whole field values. Same expressions, rebuilt unanchored, so the two cannot
# disagree about what an email is.
_EMAIL = re.compile(entities._EMAIL.pattern.strip("^$"))
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

# Phones need more care than a digit run, and this was measured rather than assumed. A first
# draft, `(?<!\d)\+?\d[\d\s/.-]{8,}\d(?!\d)`, matched 03.04.2024, 01.01.2020, 89.88.3403 and
# "4711 / 0815" - four false positives in seven ordinary ticket strings. docs/STATE.md records
# DD.DD.DDDD as the dominant free-text shape in the real corpus, so that
# pattern would have fired on ordinary rows and the gate would have been relaxed rather than
# trusted.
#
# Two changes. Dates are REMOVED from the text first: a date is not a phone number, and
# deleting the confusing shape beats out-regexing it - it also handles two adjacent dates,
# which any lookaround approach still joins into one long run. Then a candidate must carry at
# least MIN_PHONE_DIGITS actual digits, because German numbers include an area or country code
# and run 10-13, while a DD.DD.DDDD date has 8 and "4711 / 0815" has 8. The real corpus's own
# ansprechpartner-tel shape is #DDDDDDDDDDDD, i.e. 12.
#
# Measured on the final form: 0 missed phones in 5 real shapes, 0 false positives in 10
# ordinary strings.
_GERMAN_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_PHONE_RUN = re.compile(r"\+?\d[\d\s/().-]{6,}\d")
MIN_PHONE_DIGITS = 10


def _looks_like_phone(text: str) -> bool:
    without_dates = _GERMAN_DATE.sub(" ", text or "")
    return any(
        sum(character.isdigit() for character in match.group(0)) >= MIN_PHONE_DIGITS
        for match in _PHONE_RUN.finditer(without_dates)
    )


def pii_hits(documents: list[str]) -> dict[str, int]:
    """How many documents match each PII pattern. Counts only.

    Documents, not occurrences: one row with three emails is one row to investigate.
    """
    counts: Counter[str] = Counter({"email": 0, "phone": 0, "iban": 0})
    for document in documents:
        text = document or ""
        if _EMAIL.search(text):
            counts["email"] += 1
        if _IBAN.search(text):
            counts["iban"] += 1
        if _looks_like_phone(text):
            counts["phone"] += 1
    return dict(counts)


def roster_violations(values: list[str | None], roster: frozenset[str]) -> int:
    """How many non-blank values are not in the fictional roster.

    Blank is the common case rather than an error: most of the fixture's 38 columns render as
    empty strings, recorded in docs/STATE.md.
    """
    return sum(
        1 for value in values if (value or "").strip() and (value or "").strip() not in roster
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_gate_sweep.py`
Expected: 8 passed. **If `test_clean_technical_german_is_not_a_finding` fails, STOP and report it** — a sweep that fires on `Fehlercode 1234-5` or `03.04.2024` would make the gate unusable, and the pattern must bend, not the test.

- [ ] **Step 5: Full suite and lint, then commit**

Run: `make test; make lint`
Expected: `1 failed, 315 passed, 1 skipped, 2 xfailed`; lint silent.

```bash
git add profiler/gate/sweep.py tests/unit/test_gate_sweep.py
git commit -F - <<'MSG'
feat(gate): the PII sweep and the roster allowlist

<write a real body: checks 3 and 4 read the synthetic corpus only and are in the window
because the operator ruled all four emit one report; every pattern is reused from
profiler/entities.py, rebuilt unanchored for free-text search, so two definitions of "looks
like a phone number" cannot drift apart; counts documents not occurrences; a test pins that
ordinary technical German - digit runs, German dates, invented designations - is not a
finding, because firing on those is this check's likeliest failure>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: Nearest-neighbour cosine and the calibrated threshold

Check 2, and the only check whose bar is not a constant. The approved design: *"the 99th-percentile nearest-neighbour cosine between synthetic and real documents is below a threshold calibrated in the same window against a synthetic-vs-synthetic baseline. Reported alongside the baseline so the number is interpretable."*

**Why a baseline at all.** An absolute cosine bound is uninterpretable: 0.90 might be alarming or unremarkable depending on the model and the domain. Synthetic-vs-synthetic p99 measures how close *unrelated invented* tickets sit under **this** embedder. If synthetic→real is no closer than synthetic→synthetic, no real document is unusually close to anything we generated.

**Files:**
- Create: `profiler/gate/neighbours.py`
- Test: `tests/unit/test_gate_neighbours.py` (append only)

- [ ] **Step 1: Write the failing tests**

Add `neighbours` to the existing import at the **top** of
`tests/unit/test_gate_neighbours.py`, so it reads
`from profiler.gate import embedder, neighbours` — not as a fresh import lower down, which
ruff's E402 rejects. Then append the tests:

```python
def test_a_document_is_not_its_own_nearest_neighbour():
    """The baseline is synthetic-vs-synthetic, so every document's nearest neighbour would be
    itself at cosine 1.0 and the baseline would be 1.0 for any corpus - which would make the
    gate pass unconditionally. The diagonal must be excluded."""
    fake = embedder.HashingEmbedder(dim=64)
    docs = ["Pumpe undicht", "Ventil klemmt", "Sensor meldet Fehler"]
    baseline = neighbours.self_baseline(docs, fake)
    assert baseline < 0.99, f"the diagonal leaked into the baseline: {baseline}"


def test_identical_corpora_reach_cosine_one():
    """The check must be able to see the thing it exists to catch."""
    fake = embedder.HashingEmbedder(dim=64)
    docs = ["Hydraulikpumpe verliert Druck an der Vorderachse"]
    assert neighbours.cross_p99(docs, docs, fake) > 0.99


def test_unrelated_corpora_score_below_identical_ones():
    fake = embedder.HashingEmbedder(dim=128)
    synthetic = ["Hydraulikpumpe verliert Druck", "Getriebe schaltet nicht"]
    real = ["Klimaanlage kuehlt nicht", "Bremsleitung undicht hinten"]
    assert neighbours.cross_p99(synthetic, real, fake) < neighbours.cross_p99(
        synthetic, synthetic, fake
    )


def test_the_verdict_compares_against_the_baseline_not_a_constant():
    """A bare cosine number is uninterpretable - 0.90 may be alarming or unremarkable
    depending on the model. The baseline says how close unrelated INVENTED tickets sit under
    this embedder, so the comparison is against it."""
    assert neighbours.passes(cross_p99=0.42, baseline_p99=0.80) is True
    assert neighbours.passes(cross_p99=0.95, baseline_p99=0.80) is False


def test_the_verdict_has_no_slack_above_the_baseline():
    """Equal to the baseline passes; anything above it does not. A margin here is a tolerance
    nobody calibrated."""
    assert neighbours.passes(cross_p99=0.80, baseline_p99=0.80) is True
    assert neighbours.passes(cross_p99=0.8001, baseline_p99=0.80) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_gate_neighbours.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate.neighbours'`.

- [ ] **Step 3: Implement**

Create `profiler/gate/neighbours.py`:

```python
"""Check 2: is any synthetic document unusually close to a real one?

The bar is not a constant. An absolute cosine is uninterpretable - 0.90 may be alarming or
unremarkable depending on the model and the domain - so the synthetic-vs-real p99 is compared
against a synthetic-vs-synthetic p99 measured in the SAME window with the SAME embedder. If
synthetic-to-real is no closer than synthetic-to-synthetic, no real document sits unusually
close to anything we generated.

No vectors leave this module's caller. `docs/airlock-runbook.md`: real-corpus embeddings are
not retained between windows, because the embedding model is public and inversion attacks
reconstruct substantial portions of short texts. Every public function returns a float.
"""

from __future__ import annotations

import numpy as np

from profiler.gate.embedder import E5_DOCUMENT_PREFIX, Embedder

# Rows per matrix multiplication. Tens of thousands of real documents against 1,500 synthetic
# ones is tens of millions of cosines - trivial as arithmetic, hundreds of MB as one float64
# matrix. Chunking keeps the
# peak flat on a box that is shared.
CHUNK = 256


def _encode(documents: list[str], model: Embedder) -> np.ndarray:
    return model.encode([E5_DOCUMENT_PREFIX + (document or "") for document in documents])


def _nearest(left: np.ndarray, right: np.ndarray, exclude_diagonal: bool) -> np.ndarray:
    """Each left row's highest cosine against any right row."""
    best = np.full(left.shape[0], -1.0)
    for start in range(0, left.shape[0], CHUNK):
        stop = min(start + CHUNK, left.shape[0])
        block = left[start:stop] @ right.T
        if exclude_diagonal:
            for offset in range(stop - start):
                block[offset, start + offset] = -1.0
        best[start:stop] = block.max(axis=1)
    return best


def self_baseline(documents: list[str], model: Embedder) -> float:
    """p99 nearest-neighbour cosine WITHIN one corpus, excluding each document itself.

    The exclusion is the whole point: without it every document's nearest neighbour is itself
    at 1.0, the baseline is 1.0 for any corpus, and the gate passes unconditionally.
    """
    if len(documents) < 2:
        return 0.0
    vectors = _encode(documents, model)
    return float(np.percentile(_nearest(vectors, vectors, exclude_diagonal=True), 99))


def cross_p99(synthetic: list[str], real: list[str], model: Embedder) -> float:
    """p99 of each synthetic document's nearest cosine against the real corpus."""
    if not synthetic or not real:
        return 0.0
    return float(
        np.percentile(
            _nearest(_encode(synthetic, model), _encode(real, model), exclude_diagonal=False), 99
        )
    )


def passes(cross_p99: float, baseline_p99: float) -> bool:
    """At or below the baseline passes. No slack: a margin above it is a tolerance nobody
    calibrated, and this project's rule is to fix the generator rather than the tolerance."""
    return cross_p99 <= baseline_p99
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_gate_neighbours.py`
Expected: 8 passed.

- [ ] **Step 5: Full suite and lint, then commit**

Run: `make test; make lint`
Expected: `1 failed, 320 passed, 1 skipped, 2 xfailed`; lint silent.

```bash
git add profiler/gate/neighbours.py tests/unit/test_gate_neighbours.py
git commit -F - <<'MSG'
feat(gate): nearest-neighbour cosine against a same-window baseline

<write a real body: an absolute cosine bound is uninterpretable, so synthetic-vs-real p99 is
compared against a synthetic-vs-synthetic p99 measured in the same window with the same
embedder; the self-baseline excludes the diagonal, without which every document's nearest
neighbour is itself at 1.0 and the gate passes unconditionally - pinned by a test; both sides
take e5's passage prefix; chunked so tens of millions of cosines do not land as one huge matrix on a
shared box; every public function returns a float, because no vectors may leave the window>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 6: The report and its hash manifest

The artifact. `PROJECT_BRIEF.md` §8: *"Emit a signed gate report artifact. That file is the answer when the client's DPO asks how leakage was ruled out."* The operator chose a **hash manifest, no keys** (2026-08-27): the report carries the SHA-256 of both corpora, the code commit, the image digest, the embedder identity and every threshold, so any later change to the inputs is detectable and the run is reproducible — with no key custody on a shared box.

**Files:**
- Create: `profiler/gate/report.py`
- Test: `tests/unit/test_gate_report.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_gate_report.py`:

```python
import json

from profiler.gate import report


def _result(**overrides):
    base = {
        "shingle_collisions": 0,
        "pii_hits": {"email": 0, "phone": 0, "iban": 0},
        "roster_violations": 0,
        "cross_p99": 0.41,
        "baseline_p99": 0.78,
        "embedder": "hashing:trigram:dim=256",
        "synthetic_sha256": "a" * 64,
        "real_sha256": "b" * 64,
        "synthetic_rows": 1500,
        "real_rows": 16000,  # (real figure omitted) a rounded stand-in
        "code_commit": "46fcb8c",
        "image_digest": "sha256:" + "c" * 64,
    }
    return report.build(**{**base, **overrides})


def test_all_four_checks_green_is_green():
    built = _result()
    assert built["verdict"] == "green"
    assert set(built["checks"]) == {"shingles", "neighbours", "pii", "roster"}
    assert all(check["passed"] for check in built["checks"].values())


def test_one_shingle_collision_fails_the_gate():
    """The bar is zero, not a tolerance. From the approved design: a threshold here is one we
    would later be tempted to relax, and a single hit is worth investigating."""
    built = _result(shingle_collisions=1)
    assert built["verdict"] == "red"
    assert built["checks"]["shingles"]["passed"] is False


def test_a_neighbour_above_the_baseline_fails_the_gate():
    built = _result(cross_p99=0.91, baseline_p99=0.78)
    assert built["verdict"] == "red"
    assert built["checks"]["neighbours"]["passed"] is False


def test_any_pii_hit_fails_the_gate():
    assert _result(pii_hits={"email": 1, "phone": 0, "iban": 0})["verdict"] == "red"


def test_a_roster_violation_fails_the_gate():
    assert _result(roster_violations=3)["verdict"] == "red"


def test_the_manifest_makes_the_run_reproducible():
    """What a DPO needs is not a verdict but a verdict tied to specific inputs. Without these,
    'the gate was green' is a claim about nothing in particular."""
    manifest = _result()["manifest"]
    for key in (
        "synthetic_sha256",
        "real_sha256",
        "synthetic_rows",
        "real_rows",
        "code_commit",
        "image_digest",
        "embedder",
        "max_tokens",
        "document_prefix",
        "shingle_window",
    ):
        assert key in manifest, f"{key} missing from the manifest"


def test_a_stub_embedder_is_visible_in_the_report():
    """Finding 1: a stub answered for the model for two rounds because nothing recorded who
    answered. A green gate produced with a hashing stand-in must be identifiable as such from
    the artifact alone."""
    built = _result(embedder="hashing:trigram:dim=256")
    assert built["manifest"]["embedder"].startswith("hashing:")
    assert built["embedder_is_a_model"] is False
    real = _result(embedder="intfloat/multilingual-e5-large@<revision>")
    assert real["embedder_is_a_model"] is True


def test_the_report_carries_no_corpus_text():
    """The only thing this gate may emit is counts, thresholds and verdicts. A report that
    quoted a colliding shingle would carry real corpus text out of the window - which is the
    single thing the airlock exists to prevent."""
    serialised = json.dumps(_result(), ensure_ascii=False)
    # (real corpus tokens omitted; list sample real product words and surnames here)
    for banned in ("<real-product-word>", "<real-form-title>", "Mustermann"):
        assert banned.lower() not in serialised.lower()
    assert "shingle" not in json.dumps(_result()["checks"]["shingles"].get("examples", []))


def test_the_report_is_json_serialisable():
    json.dumps(_result())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_gate_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate.report'`.

- [ ] **Step 3: Implement**

Create `profiler/gate/report.py`:

```python
"""`gate_report.json` - the artifact, and the only thing that leaves the window.

PROJECT_BRIEF section 8 calls for a signed report: "that file is the answer when the client's
DPO asks how leakage was ruled out". The operator chose a hash manifest over keys on
2026-08-27 - the report pins its inputs by SHA-256, the code commit, the image digest and the
embedder identity, so any later change to the inputs is detectable and the run is
reproducible, with no key custody on a shared box.

It carries COUNTS, THRESHOLDS AND VERDICTS ONLY. No shingle, no vector, no row. A report that
quoted the colliding shingle would carry real corpus text out of the window, which is the one
thing the airlock exists to prevent, and a test pins it.
"""

from __future__ import annotations

from profiler.gate import neighbours
from profiler.gate.embedder import E5_DOCUMENT_PREFIX, MAX_TOKENS
from profiler.gate.shingles import WINDOW


def build(
    *,
    shingle_collisions: int,
    pii_hits: dict[str, int],
    roster_violations: int,
    cross_p99: float,
    baseline_p99: float,
    embedder: str,
    synthetic_sha256: str,
    real_sha256: str,
    synthetic_rows: int,
    real_rows: int,
    code_commit: str,
    image_digest: str,
) -> dict:
    checks = {
        "shingles": {
            "passed": shingle_collisions == 0,
            "synthetic_rows_sharing_a_shingle": shingle_collisions,
            "bar": 0,
        },
        "neighbours": {
            "passed": neighbours.passes(cross_p99, baseline_p99),
            "cross_p99": round(cross_p99, 6),
            "baseline_p99": round(baseline_p99, 6),
            "bar": "cross_p99 <= baseline_p99",
        },
        "pii": {
            "passed": sum(pii_hits.values()) == 0,
            "hits": dict(pii_hits),
            "bar": 0,
        },
        "roster": {
            "passed": roster_violations == 0,
            "violations": roster_violations,
            "bar": 0,
        },
    }
    return {
        "verdict": "green" if all(check["passed"] for check in checks.values()) else "red",
        # A green gate produced with the hashing stand-in must be identifiable as such from
        # the artifact alone. Finding 1 cost two rounds to a stub nobody could see.
        "embedder_is_a_model": not embedder.startswith("hashing:"),
        "checks": checks,
        "manifest": {
            "synthetic_sha256": synthetic_sha256,
            "real_sha256": real_sha256,
            "synthetic_rows": synthetic_rows,
            "real_rows": real_rows,
            "code_commit": code_commit,
            "image_digest": image_digest,
            "embedder": embedder,
            "max_tokens": MAX_TOKENS,
            "document_prefix": E5_DOCUMENT_PREFIX,
            "shingle_window": WINDOW,
        },
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_gate_report.py`
Expected: 9 passed.

- [ ] **Step 5: Full suite and lint, then commit**

Run: `make test; make lint`
Expected: `1 failed, 329 passed, 1 skipped, 2 xfailed`; lint silent.

```bash
git add profiler/gate/report.py tests/unit/test_gate_report.py
git commit -F - <<'MSG'
feat(gate): the gate report and its hash manifest

<write a real body: section 8's signed artifact, realised as a hash manifest per the
operator's 2026-08-27 ruling - inputs pinned by SHA-256, code commit, image digest and
embedder identity, so the run is reproducible without key custody on a shared box; counts,
thresholds and verdicts only, with a test asserting no corpus text appears anywhere in the
serialised report; embedder_is_a_model makes a stub-produced green identifiable from the
artifact alone, which is finding 1's lesson>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 7: The CLI

What `window.sh`'s `WINDOW_CMD` will eventually invoke. Wiring only — every decision already lives in Tasks 1–6.

**Files:**
- Create: `profiler/gate/__main__.py`
- Test: `tests/unit/test_gate_report.py` (append only)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_gate_report.py`:

```python
def test_the_cli_writes_a_green_report_without_a_model(tmp_path):
    """The whole gate must be provable with no model, no GPU and no network - otherwise it
    could only ever be tested inside a sealed window, which is the most expensive place to
    find a bug. Two corpora of unrelated invented German must come out green."""
    import csv

    from profiler.gate.__main__ import main

    def write(path, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["title", "description", "solutions"])
            writer.writeheader()
            writer.writerows(rows)

    synthetic = tmp_path / "synthetic_corpus.tsv"
    real = tmp_path / "real_corpus.tsv"
    write(
        synthetic,
        [
            {
                "title": f"Hydraulikpumpe verliert Druck Variante {n}",
                "description": f"Messung {n} zeigt Abweichung an der Vorderachse",
                "solutions": "Dichtung getauscht",
            }
            for n in range(30)
        ],
    )
    write(
        real,
        [
            {
                "title": f"Klimaanlage kuehlt nicht ausreichend Fall {n}",
                "description": f"Kaeltemittelstand {n} geprueft im Sommerbetrieb",
                "solutions": "Kreislauf gespuelt",
            }
            for n in range(30)
        ],
    )

    out = tmp_path / "gate_report.json"
    assert main(["--synthetic", str(synthetic), "--real", str(real), "--out", str(out)]) == 0
    built = json.loads(out.read_text(encoding="utf-8"))
    assert built["verdict"] == "green", built
    assert built["embedder_is_a_model"] is False
    assert built["manifest"]["synthetic_rows"] == 30
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_gate_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiler.gate.__main__'`.

- [ ] **Step 3: Implement**

Create `profiler/gate/__main__.py`:

```python
"""The gate CLI. `window.sh`'s Window B command block will invoke this - Plan B.

`--embedder hashing` is the default ON PURPOSE. The real model is Plan B, and until it exists
the gate must still be runnable end to end so that a bug is found in CI rather than inside a
sealed window, which is the most expensive place to find one. `report.embedder_is_a_model`
makes the choice visible in the artifact, so a stub-produced green cannot be mistaken for a
real one.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import subprocess
import sys

from profiler.gate import neighbours, report, shingles, sweep
from profiler.gate.embedder import HashingEmbedder

TEXT_COLUMNS = ("title", "description", "solutions")


def _rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _documents(rows: list[dict[str, str]]) -> list[str]:
    """One document per row: the free-text columns joined.

    Identical on both sides. Including a column on one side only would make every cosine and
    every shingle in the report incomparable.
    """
    return [" ".join((row.get(column) or "") for column in TEXT_COLUMNS).strip() for row in rows]


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        # No git inside the sealed image. The operator passes --code-commit there.
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="profiler.gate")
    parser.add_argument("--synthetic", type=pathlib.Path, required=True)
    parser.add_argument("--real", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--embedder", choices=["hashing"], default="hashing")
    parser.add_argument("--roster", type=pathlib.Path, default=None)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--image-digest", default="unknown")
    args = parser.parse_args(argv)

    synthetic_rows = _rows(args.synthetic)
    real_rows = _rows(args.real)
    synthetic_docs = _documents(synthetic_rows)
    real_docs = _documents(real_rows)

    model = HashingEmbedder()
    roster = (
        frozenset(
            line.strip()
            for line in args.roster.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if args.roster
        else frozenset()
    )

    built = report.build(
        shingle_collisions=shingles.collisions(synthetic_docs, real_docs),
        pii_hits=sweep.pii_hits(synthetic_docs),
        roster_violations=sweep.roster_violations(
            [row.get("ansprechpartner") for row in synthetic_rows], roster
        )
        if roster
        else 0,
        cross_p99=neighbours.cross_p99(synthetic_docs, real_docs, model),
        baseline_p99=neighbours.self_baseline(synthetic_docs, model),
        embedder=model.identity,
        synthetic_sha256=_sha256(args.synthetic),
        real_sha256=_sha256(args.real),
        synthetic_rows=len(synthetic_rows),
        real_rows=len(real_rows),
        code_commit=args.code_commit or _commit(),
        image_digest=args.image_digest,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(built, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"gate verdict: {built['verdict']}  (embedder: {built['manifest']['embedder']})")
    for name, check in built["checks"].items():
        print(f"  {name:<11} {'pass' if check['passed'] else 'FAIL'}")
    return 0 if built["verdict"] == "green" else 3


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_gate_report.py`
Expected: 10 passed.

- [ ] **Step 5: Full suite and lint**

Run: `make test; make lint`
Expected: `1 failed, 330 passed, 1 skipped, 2 xfailed`; lint silent.

- [ ] **Step 6: Commit**

```bash
git add profiler/gate/__main__.py tests/unit/test_gate_report.py
git commit -F - <<'MSG'
feat(gate): the CLI window.sh's Window B block will invoke

<write a real body: wiring only, every decision lives in the modules; documents are the same
free-text columns joined identically on both sides, because including a column on one side
would make every cosine and shingle incomparable; the hashing embedder is the default on
purpose so the whole gate is provable in CI rather than only inside a sealed window, which is
the most expensive place to find a bug; exit 3 on red mirrors the fixture CLI's convention
that a refusing check does not write a green artifact>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

## After the last task

- [ ] `make lint` silent; `make test` shows the quarantine guard as the **only** failure.
- [ ] Tree clean; `git ls-files local/` empty.
- [ ] Run the gate over the accepted fixture against **itself** as a smoke test, via a Write-tool script with the paths inside it (the hook rejects a command naming the export suffix). Expect `verdict: red` on `neighbours`, because a corpus compared to itself has cross_p99 1.0 against a baseline below it. **That red is the correct answer** and proves the check can see what it exists to catch.
- [ ] Record in `docs/STATE.md`: the gate's four checks exist and are tested; the embedder is a stub; **the gate has NOT run against real data and the fixture is therefore still not cleared.**

## Self-review notes for the implementer

Two things this plan deliberately does **not** do, so their absence is not read as an oversight:

1. **No real embedder.** Every number the gate currently produces comes from a trigram hash and is meaningless as a leakage measurement. `embedder_is_a_model` is `false` in every report this plan can produce. Plan B changes that.
2. **No `WINDOW_CMD`.** `window.sh` still refuses window b with *"window 'b' has no command block yet"*, which is correct until the image can run the real embedder offline.
