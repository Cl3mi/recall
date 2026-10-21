# Cluster Bands — Voices, Designations, and the Form's Text Shape

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close M2 finding 9 so the synthetic fixture reproduces the real corpus's near-duplicate cluster bands within ±1.0 point, which is the last acceptance criterion it fails.

**Architecture:** No new modules. `fixtures/generate.py` gains a *voice* per singleton batch and an invented product-line vocabulary, both of which raise lexical diversity so the singletons (about three quarters of the rows) stop accidentally near-duplicating each other. Task 3 changes the dominant cluster's text shape, and is gated on a measurement only the operator can take.

**Tech Stack:** Python 3.12, uv, pytest, ruff. Tasks 1–2 need no GPU. The regeneration in Task 4 needs vLLM on the H100.

---

## Read this first — you have no context

You are picking this up in a fresh session. Read, in order:

1. This plan, whole.
2. `docs/STATE.md` — the resume point. Read **"M2 findings"** (all nine), the **"Open questions that need a sealed window (2026-08-19)"** subsection, and **"Decisions already made — do not relitigate"**.
3. `docs/superpowers/specs/2026-08-19-cluster-structure-shared-problem-design.md` — the design finding 8 closed, which this plan builds on.
4. `PROJECT_BRIEF.md` §8 — the two requirements Tasks 1 and 2 implement, and §9's divergence rule.

## Data handling rules — absolute

- **Never read anything under `local/quarantine/` or the client working directory.** Those hold a client's real ticket export under NDA.
- `local/artifacts/profile.json` **is** readable — it passed `blessing.unblessed` with zero findings.
- **A session hook rejects any Bash command whose text contains `.csv`.** Do not work around it with globs, variables, a different filename, or any other obfuscation. The sanctioned route, which the committed integration tests already use: write the path **inside** a Python file (with Write/Edit) and invoke it with a command that never names the suffix. Passing the path as an argv **trips the hook** — verified. If you think you need such a command, STOP and ask the operator to run it.
- **Do not commit anything under `local/`.** It is gitignored. The fixture stays uncommitted until the Window B leakage gate is green — a separate plan and a sealed window.
- **Never put corpus vocabulary into a prompt.** `generate.py`'s contract is "plan numbers and invented themes only", asserted by `test_no_corpus_string_ever_reaches_a_prompt`. This matters for Task 2: real product words exist in `dimension_hints.vehicleModelId`, and copying them into the fixture would be the exact leak the Window B gate exists to catch.

## The rule about failing tests

**If a test fails and you believe the test is wrong, STOP and report it rather than adjusting the test. On this project a failing test has been right and the plan wrong ten times. The tests encode intent; the implementation bends.**

It has already happened three times inside this plan's lineage:

- Finding 7's fix was blocked by `test_fields_are_present_in_exactly_their_measured_share_of_rows`, which caught `CustomField.block` defaulting to `0` merging unrelated fields into a phantom form. The default became `None`; the test was not touched.
- Finding 8's first draft prompt dropped the literal word "unterschiedlich" and `test_the_prompt_asks_for_different_approaches_not_rewordings` failed. The prompt bent.
- `test_padding_is_reported_rather_than_silent` pins `stats["padded"] == 2` for a group of 5 against a one-record client. The operator ruled that **the two-top-up bound IS the intent**, so `TOPUP_ATTEMPTS` stays at 2 and that test stays untouched. Do not "fix" a padding problem by raising it.

## What has already been tried and must not be retried

- **Subsystem steering is not the cure for finding 9.** `SUBSYSTEMS` was added on 2026-08-19 and collisions went **182 → 173** — 5%, not a fix. The measurement showed why: collisions moved from *across* batches to *within* them (*Zapfwelle blockiert / nicht gerade / nicht dicht*). It was kept because the vocabulary is more realistic and because it exposed a real asymmetry (the singleton path had no top-up), but **do not present it as the fix and do not extend it**.
- **Do not absorb the collisions by shrinking the planner's mid budget.** The bands would match while relevance density stayed near double the real corpus, inflating recall@10 on synthetic — exactly what `PROJECT_BRIEF.md` §9's divergence rule exists to prevent.
- **Do not raise `TOPUP_ATTEMPTS`.** See above.

## Where the numbers stand before you start

Round 3 (2026-08-19), the current best, kept at `local/fixtures/export.round3-no-padding-2026-08-19.csv`:

| dimension | real | fixture | verdict |
|---|---:|---:|---|
| cluster band singletons | about three quarters | about two thirds | **FAIL** |
| cluster band mid (2–49) | about 0.1 | about 0.2 | **FAIL** |
| cluster band large (≥50) | about 0.14 | about 0.15 | PASS |
| `customData` field shares | — | all fields, worst deviation tiny | PASS |
| `fehlercode` shape mix | — | all shapes, worst deviation tiny | PASS |
| fill-by-year | — | all years | PASS |
| descriptors p90/p95/p99/p999 | 21 | 21 | PASS |
| padding | — | **0** | — |
| `verify` | — | clean, exit 0 | PASS |

**The single defect: 173 singletons (about 15% of them) land in clusters of ≥2, across 76 spurious clusters.** Those rows are exactly the singleton band's deficit and the mid band's surplus.

**Root cause:** clustering is `minhash-lsh(num_perm=128)` over the **token set** of cleaned `title + description` at threshold **0.7**. Two short, formulaic German descriptions collide whatever the component — *"Defektes X. Die Maschine zeigt …"* recurs. The generator asks for content and never for **voice**.

**Tokenizer detail you will need:** `profiler/stats/vocab.py` uses `_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,}")`. A token must *start* with a letter but may contain digits and hyphens. So `TX-2200` survives as **one token** (`tx-2200`), while `Stoerung 98` tokenizes to just `['stoerung']` — the bare `98` is dropped. That asymmetry is why designations work at all and why the old padding fallback collapsed.

**Jaccard arithmetic, so you do not over-expect Task 2:** two docs of ~30 tokens at Jaccard 0.75 share ~25.7 tokens. Adding one unique token to each drops them only to 0.708; two unique tokens each reach 0.671. Designations alone will not break a 0.9 collision. **Voices are the lever with real leverage; designations are a supporting change with independent value.**

## Pre-flight

```bash
cd <repo-root>
git status --short && git log --oneline -1
make test && make lint
```

Expected: clean tree on `feat/m2-fixture-generator`, `274 passed, 2 skipped, 2 xfailed`, ruff silent. If `make test` shows a failure in `test_the_generated_fixture_profiles_like_the_real_corpus`, a fixture is sitting at `local/fixtures/export.csv`; that test is *supposed* to be red then. Move the file aside (see Task 4 Step 9) rather than editing the test.

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `fixtures/generate.py` | voices, designations, the form's text shape | 1, 2, 3 |
| `tests/unit/test_fixture_generate.py` | append-only; new tests for each | 1, 2, 3 |
| `docs/STATE.md` | record the measured outcome | 4 |

---

### Task 1: A voice per singleton batch

`PROJECT_BRIEF.md` §8 requires variants "in different voices (terse mechanic, rambling customer email, template dump)". Nothing in `generate.py` asks for a voice. A terse mechanic's note and a rambling customer email about the same fault share few tokens, which is what breaks the collisions.

**Files:**
- Modify: `fixtures/generate.py` — add `VOICES`, use it in `_prompt_distinct`
- Test: `tests/unit/test_fixture_generate.py` (append only)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_generate.py`:

```python
def test_each_singleton_batch_is_given_a_voice():
    """PROJECT_BRIEF section 8 requires variants in different voices - terse mechanic,
    rambling customer email, template dump - and nothing asked for one. Finding 9: 173
    singletons (about 15%) accidentally near-duplicated each other because at MinHash 0.7 over a
    token SET two short formulaic German descriptions collide whatever the component. Voice
    is the lever with real leverage on Jaccard; subsystem steering was measured at 182 -> 173
    and is not."""
    seen: list[str] = []
    generate.tickets([1] * 200, lambda prompt: seen.append(prompt) or "")
    batch_prompts = [p for p in seen if "VERSCHIEDENEN" in p]
    assert len(batch_prompts) >= 8, f"expected several batches, got {len(batch_prompts)}"
    used = [v for v in generate.VOICES if any(v.cue in p for p in batch_prompts)]
    assert len(used) == len(generate.VOICES), (
        f"every voice must be exercised across the batches, saw {len(used)} of "
        f"{len(generate.VOICES)}"
    )


def test_consecutive_singleton_batches_do_not_share_a_voice():
    """Adjacent batches are the ones most likely to collide, so they must not also share a
    voice on top of anything else they share."""
    seen: list[str] = []
    generate.tickets([1] * 200, lambda prompt: seen.append(prompt) or "")
    batch_prompts = [p for p in seen if "VERSCHIEDENEN" in p]

    def voice_of(prompt: str) -> str:
        return next(v.cue for v in generate.VOICES if v.cue in prompt)

    voices = [voice_of(p) for p in batch_prompts]
    pairs = list(zip(voices, voices[1:], strict=False))
    assert all(a != b for a, b in pairs), f"consecutive batches share a voice: {voices[:6]}"


def test_a_voice_carries_an_instruction_not_just_a_label():
    """A bare label does not change the model's output. Each voice must state how to write."""
    for voice in generate.VOICES:
        assert len(voice.instruction) > 30, f"{voice.cue} has no real instruction"
        assert voice.cue in voice.instruction, "the cue must appear in the instruction it names"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_fixture_generate.py -q`
Expected: FAIL — `module 'fixtures.generate' has no attribute 'VOICES'`.

- [ ] **Step 3: Add the voices**

In `fixtures/generate.py`, add immediately after the `_PAD_MARKERS` definition:

```python
@dataclass(frozen=True)
class Voice:
    """How a ticket is written, not what it says.

    PROJECT_BRIEF section 8 asks for variants in different voices. Finding 9 is why it
    matters mechanically: clustering is minhash over the TOKEN SET of cleaned
    title+description at threshold 0.7, and two short formulaic descriptions collide
    whatever component they name. A terse mechanic's note and a rambling customer email
    about the same fault share few tokens, so voice moves Jaccard where a subsystem hint
    could not - that was measured at 182 collisions to 173.
    """

    cue: str
    instruction: str


VOICES = [
    Voice(
        cue="Monteurnotiz",
        instruction=(
            "Schreibe als Monteurnotiz: knapp, Stichworte, kein ganzer Satz, "
            "Fachbegriffe und Messwerte statt Erklaerungen."
        ),
    ),
    Voice(
        cue="Kundenmail",
        instruction=(
            "Schreibe als Kundenmail: weitschweifig, in Ich-Form, mit Vorgeschichte "
            "und Nebensaechlichkeiten, unsicher in der Fachsprache."
        ),
    ),
    Voice(
        cue="Formularauszug",
        instruction=(
            "Schreibe als Formularauszug: Feldnamen mit Werten, Abkuerzungen, "
            "immer gleiche Satzbausteine, keine Prosa."
        ),
    ),
]
```

- [ ] **Step 4: Use the voice in the prompt**

In `fixtures/generate.py`, `_prompt_distinct` currently reads:

```python
def _prompt_distinct(count: int, series: int) -> str:
    """Unrelated faults, one per ticket - most of the corpus is singletons.

    Each batch is steered to its own subsystem. Without that, 46 batches asked for "25
    different faults" produced 182 collisions across 73 spurious clusters, because the model
    cannot see what earlier batches already used and keeps reaching for the same components.
    """
    subsystem = SUBSYSTEMS[series % len(SUBSYSTEMS)]
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Serie {series}\n"
        f"Baugruppe: {subsystem}\n\n"
        f"Schreibe {count} Tickets zu {count} VERSCHIEDENEN Fehlerbildern an der "
        f"Baugruppe {subsystem} - unterschiedliche Bauteile, unterschiedliche Symptome, "
        f"kein Zusammenhang zwischen den Tickets. Verwende nur Fehlerbilder, die zu "
        f"{subsystem} gehoeren.\n\n"
        f"Format je Ticket, jeweils eine Zeile:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\nLOESUNG: <2-3 Saetze>\n---\n"
    )
```

Replace it **entirely** with:

```python
def _prompt_distinct(count: int, series: int) -> str:
    """Unrelated faults, one per ticket - most of the corpus is singletons.

    Each batch gets a subsystem AND a voice. The subsystem alone was not enough: it moved
    collisions from across batches to within them, 182 to 173, because 25 genuinely different
    faults inside one subsystem forces minor variations on one component. The VOICE is what
    moves Jaccard, because clustering compares token SETS and two differently-voiced tickets
    about the same fault barely overlap.

    Voice cycles on a different modulus from the subsystem so adjacent batches share neither.
    """
    subsystem = SUBSYSTEMS[series % len(SUBSYSTEMS)]
    voice = VOICES[series % len(VOICES)]
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Serie {series}\n"
        f"Baugruppe: {subsystem}\n"
        f"Stil: {voice.cue}\n\n"
        f"{voice.instruction}\n\n"
        f"Schreibe {count} Tickets zu {count} VERSCHIEDENEN Fehlerbildern an der "
        f"Baugruppe {subsystem} - unterschiedliche Bauteile, unterschiedliche Symptome, "
        f"kein Zusammenhang zwischen den Tickets. Verwende nur Fehlerbilder, die zu "
        f"{subsystem} gehoeren.\n"
        f"Formuliere jedes Ticket anders. Wiederhole keine Satzbausteine aus einem "
        f"anderen Ticket.\n\n"
        f"Format je Ticket, jeweils eine Zeile:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\nLOESUNG: <2-3 Saetze>\n---\n"
    )
```

`len(SUBSYSTEMS)` is 50 and `len(VOICES)` is 3, which are coprime, so the (subsystem, voice) pair does not repeat until batch 150 — well past the 46 batches a 1,500-row fixture uses.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_generate.py -q`
Expected: PASS. Report the count.

`test_a_singleton_topup_stays_in_its_subsystem` must still pass untouched. It asserts a top-up keeps its subsystem, and it does, because the top-up offset is a whole multiple of `len(SUBSYSTEMS)`. **Note:** that offset is *not* a multiple of 3, so a top-up may land on a different voice. That is acceptable and arguably good — more diversity — but if you decide otherwise, STOP and report rather than changing the test.

- [ ] **Step 6: Full suite and lint**

Run: `make test && make lint`
Expected: `277 passed, 2 skipped, 2 xfailed`, ruff silent. If ruff reformats your new block, run `uv run ruff format fixtures/generate.py` and re-run both.

- [ ] **Step 7: Commit**

```bash
git add fixtures/generate.py tests/unit/test_fixture_generate.py
git commit -F - <<'MSG'
feat(fixtures): give each singleton batch a voice

<write a real body: PROJECT_BRIEF section 8 asked for voices and nothing implemented
them; finding 9's 173 collisions are formulaic phrasing, not shared vocabulary; voice
moves token-set Jaccard where subsystem steering did not, measured at 182 -> 173>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: An invented product line

`PROJECT_BRIEF.md` §8: "Invent a fictional product line with obviously fake designations (`TX-2200`, `LR-45`) so any leak is visually obvious." Unimplemented. It is a **leak-detection aid first** — if a real designation ever appears in the fixture, it stands out against obviously fake ones — and a marginal help to finding 9 second.

**The designations must be invented, never extracted from the corpus.** `model_designations.family_count` in the profile is **0** — the real corpus has no alphanumeric designations to parse anyway, its `vehicleModelId` is an opaque numeric FK — but real product words do exist in `dimension_hints.vehicleModelId` top tokens, and copying those in would be a leak.

**Files:**
- Modify: `fixtures/generate.py` — add `MODEL_FAMILIES`, `_designation`, use it in both prompts
- Test: `tests/unit/test_fixture_generate.py` (append only)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fixture_generate.py`:

```python
def test_designations_are_invented_and_obviously_fake():
    """PROJECT_BRIEF section 8: an invented product line makes a leak visually obvious. The
    real corpus has none to copy - model_designations.family_count is 0 - and real product
    vocabulary that DOES exist (in dimension_hints.vehicleModelId) must never reach a prompt."""
    assert len(generate.MODEL_FAMILIES) >= 4
    for family in generate.MODEL_FAMILIES:
        assert family.isupper(), f"{family} must be an upper-case prefix"
        assert 2 <= len(family) <= 3, f"{family} should look like TX or LR"
    # (real corpus tokens omitted; list the real product words and the form title here)
    for forbidden in ("<real-product-word-1>", "<real-product-word-2>", "<real-form-title>"):
        assert not any(forbidden.upper() in f for f in generate.MODEL_FAMILIES)


def test_a_designation_survives_the_profiler_tokenizer_as_one_token():
    """profiler/stats/vocab.py _TOKEN requires a token to START with a letter but allows
    digits and hyphens inside, so TX-2200 is ONE token while `Stoerung 98` loses its 98
    entirely. A designation is only useful for lexical distinctness if it survives whole."""
    from profiler.stats import vocab

    designation = generate._designation(7)
    tokens = vocab.tokenize(designation)
    assert tokens == [designation.lower()], f"{designation!r} tokenized to {tokens}"
    assert "-" in designation and any(c.isdigit() for c in designation)


def test_designations_differ_across_singleton_batches():
    """A shared designation would be a shared token, which is the opposite of the point."""
    seen: list[str] = []
    generate.tickets([1] * 200, lambda prompt: seen.append(prompt) or "")
    batch_prompts = [p for p in seen if "VERSCHIEDENEN" in p]
    found = {
        d
        for i in range(300)
        for d in [generate._designation(i)]
        if any(d in p for p in batch_prompts)
    }
    assert len(found) >= 5, f"batches should name different machines, found {found}"


def test_no_corpus_string_reaches_a_prompt_including_designations():
    """The existing guard, restated against the new vocabulary. generate.py's contract is
    plan numbers and invented themes only."""
    seen: list[str] = []
    generate.tickets([3, 1, 1], lambda prompt: seen.append(prompt) or "text")
    joined = " ".join(seen).lower()
    # (real corpus tokens omitted; use the same list as in the designation test above)
    for corpus_string in ("<real-product-word-1>", "<real-product-word-2>", "<real-form-title>"):
        assert corpus_string not in joined
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_fixture_generate.py -q`
Expected: FAIL — no attribute `MODEL_FAMILIES`.

- [ ] **Step 3: Add the product line**

In `fixtures/generate.py`, add after the `VOICES` list:

```python
# An invented product line. PROJECT_BRIEF section 8: obviously fake designations make a leak
# visually obvious. These are INVENTED, never extracted: model_designations.family_count in the
# profile is 0, so there is nothing to parse, and the real product vocabulary that does exist
# (dimension_hints.vehicleModelId top tokens) must never reach a prompt.
#
# The shape matters. profiler/stats/vocab.py's _TOKEN is
# [A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,} - a token must START with a letter but may contain
# digits and hyphens - so "TX-2200" survives tokenization as ONE token while a bare "98" is
# dropped entirely. A designation is only lexically useful if it survives whole.
MODEL_FAMILIES = ["TX", "LR", "VG", "MK", "ND"]


def _designation(index: int) -> str:
    """An invented machine designation, e.g. TX-2240.

    Deterministic in `index` so a prompt is reproducible and its cache key stable.
    """
    family = MODEL_FAMILIES[index % len(MODEL_FAMILIES)]
    series = 2200 + (index // len(MODEL_FAMILIES)) * 10 % 800
    return f"{family}-{series}"
```

- [ ] **Step 4: Name a machine in both prompts**

In `_prompt_distinct`, change the header block. It currently reads:

```python
        f"Serie {series}\n"
        f"Baugruppe: {subsystem}\n"
        f"Stil: {voice.cue}\n\n"
```

Replace with:

```python
        f"Serie {series}\n"
        f"Maschine: {_designation(series)}\n"
        f"Baugruppe: {subsystem}\n"
        f"Stil: {voice.cue}\n\n"
```

In `_prompt` (the group/variants prompt), it currently reads:

```python
        f"Fehlerbild: {theme}\n"
        f"Serie {series}\n\n"
```

Replace with:

```python
        f"Fehlerbild: {theme}\n"
        f"Maschine: {_designation(series)}\n"
        f"Serie {series}\n\n"
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_fixture_generate.py -q`
Expected: PASS. `test_no_corpus_string_ever_reaches_a_prompt` must still pass untouched.

- [ ] **Step 6: Full suite and lint**

Run: `make test && make lint`
Expected: `281 passed, 2 skipped, 2 xfailed`, ruff silent.

- [ ] **Step 7: Commit**

```bash
git add fixtures/generate.py tests/unit/test_fixture_generate.py
git commit -F - <<'MSG'
feat(fixtures): invent a product line so a leak is visually obvious

<write a real body: PROJECT_BRIEF section 8's requirement, unimplemented until now;
invented not extracted, because family_count is 0 and real product vocabulary exists
in dimension_hints; the tokenizer keeps TX-2200 whole while dropping a bare 98>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: The dominant cluster's text shape — GATED, do not start blind

**Do not start this task until the operator has answered question 1 of `docs/STATE.md` → "Open questions that need a sealed window (2026-08-19)":**

> Of the rows in the largest near-duplicate cluster, what fraction have a non-empty `description`?

**Decision rule:**

- **Answer is roughly 0–10%** → the hypothesis holds: the real cluster is near-empty tickets. Implement Steps 1–6 below.
- **Answer is above ~50%** → the hypothesis is **wrong**. STOP, do not implement, and report. The real cluster clusters despite long descriptions, which would mean MinHash is bridging title-only and title+description rows by some mechanism this plan has not identified, and the design needs revisiting rather than patching.
- **Anything in between** → STOP and report the number. A partial answer is a finding, not a licence to guess.

**Why this task exists.** The fixture's largest group (a couple of hundred members) comes out as **about two thirds of its rows (with a description) + the rest (blanked)** in two clusters, because a blanked row's cleaned token set is the **title alone** and cannot reach 0.7 Jaccard against title+description. Both halves happen to clear 50, so the large band passes — but that is arithmetic luck, not design: at a 10% blank rate the blanked side would be about 20 rows and land in the mid band instead. The real corpus does not split this way.

**Files:**
- Modify: `fixtures/generate.py` — `_prompt` asks for a form-shaped problem for the dominant group
- Test: `tests/unit/test_fixture_generate.py` (append only)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_fixture_generate.py`:

```python
def test_the_dominant_group_is_written_as_a_form_not_a_narrative():
    """The real largest cluster's whole vocabulary is a couple of words naming handover
    paperwork. Its rows carry a short title and (per the window measurement) no description, so
    description blanking cannot split it. The fixture's largest group (about 200 members) carried
    a 3-sentence BEFUND, so blanking split it into two clusters. A form has no narrative."""
    seen: list[str] = []
    generate.tickets([200], lambda prompt: seen.append(prompt) or "", {})
    assert seen, "no prompt was sent"
    assert any("FORMULAR" in p.upper() for p in seen), (
        "the dominant group must be asked for as a form"
    )
    assert any("kein BEFUND" in p or "ohne BEFUND" in p for p in seen), (
        "a form row carries no narrative description"
    )


def test_small_groups_keep_their_narrative():
    """Only the dominant cluster is a form. A 5-member recurring fault is a real fault and
    still needs its BEFUND, or the mid band loses the text it clusters on."""
    seen: list[str] = []
    generate.tickets([5], lambda prompt: seen.append(prompt) or "", {})
    assert seen
    assert not any("FORMULAR" in p.upper() for p in seen), "a 5-member group is not a form"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_fixture_generate.py -q`
Expected: FAIL — no prompt mentions a form.

- [ ] **Step 3: Add the threshold and the form prompt**

In `fixtures/generate.py`, add after `TOPUP_ATTEMPTS`:

```python
# At or above this many members, a group is treated as a FORM rather than a recurring fault.
# The real corpus's largest cluster is thousands of tickets whose whole vocabulary is a couple of
# words - repeated handover paperwork, not thousands of narratives. Writing it
# as a narrative gave every member a 3-sentence BEFUND, and description blanking then split the
# fixture's largest group (about 200 members) in two because a blanked row's token set is its title alone.
# A form has no narrative to blank, so it cannot split. The value deliberately mirrors
# fixtures/plan.py's LARGE_GROUP = 50, which is the profiler's own large-band boundary, so
# exactly the groups the large band is made of are treated as forms. It is a separate constant
# rather than an import because the two mean different things - one bands a distribution, the
# other decides how text is written - and coupling them would make a future change to either
# silently change the other.
FORM_GROUP_MIN = 50
```

- [ ] **Step 4: Branch the prompt**

**Read this before writing the code.** `_prompt` receives `want`, the *batch* size, which finding 7 capped at `GROUP_BATCH = 20`. A 200-member group is asked for in 10 batches of 20, so `count` is **never** ≥ 50 and a `count >= FORM_GROUP_MIN` test would never fire. The group's size has to be passed in explicitly. No test calls `_prompt` directly (only `_parse` and `_parse_variants` are), so changing its signature is safe.

Change the signature. It currently reads:

```python
def _prompt(theme: str, count: int, series: int) -> str:
```

to:

```python
def _prompt(theme: str, count: int, series: int, form: bool = False) -> str:
```

and add to its docstring:

```
    `form` marks the dominant cluster, which is paperwork rather than a fault. It cannot be
    inferred from `count`: finding 7 caps a single ask at GROUP_BATCH, so a 200-member group
    arrives here as ten asks of 20 and `count` never reveals the group's real size.
```

Then insert at the top of the function body, immediately after the docstring and before the existing `return`:

```python
    if form:
        return (
            f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
            f"Vorgang: {theme}\n"
            f"Maschine: {_designation(series)}\n"
            f"Serie {series}\n\n"
            f"Das ist ein FORMULAR-Vorgang, kein Fehlerbericht: dieselbe Papierarbeit "
            f"wird immer wieder erfasst.\n"
            f"Schreibe EINEN kurzen Titel aus zwei bis drei Woertern, der bei jedem "
            f"Vorgang identisch waere, und dann {count} unterschiedliche Loesungswege.\n"
            f"Gib kein BEFUND-Feld aus - ein Formular hat keinen Befundtext.\n"
            f"Jeder Loesungsweg nennt SEINE EIGENE Diagnose und die durchgefuehrte "
            f"Reparatur.\n\n"
            f"Format - Titel genau einmal, dann {count} unterschiedliche Loesungswege:\n"
            f"TITEL: <zwei bis drei Woerter>\n"
            f"LOESUNG 1: <2-3 Saetze>\nLOESUNG 2: <2-3 Saetze>\n"
        )
```

`_parse_variants` needs no change: it already returns an empty `description` when no `BEFUND` line is present.

- [ ] **Step 5: Pass the flag, and handle the empty-description fallback**

Two edits in `tickets()`, both inside the multi-member group loop where `size` is in scope.

First, pass the flag. Both call sites currently read `_prompt(theme, want, _series(...))` and `_prompt(theme, shortfall, _series(...))`. Add `size >= FORM_GROUP_MIN` as the fourth argument to **both**:

```python
            got_title, got_desc, ways = _parse_variants(
                client(_prompt(theme, want, _series(index, batch, 0), size >= FORM_GROUP_MIN))
            )
```

and, in the top-up loop:

```python
                more_title, more_desc, more = _parse_variants(
                    client(
                        _prompt(
                            theme,
                            shortfall,
                            _series(index, batch, attempt),
                            size >= FORM_GROUP_MIN,
                        )
                    )
                )
```

Second, the fallback. `description or theme` would put the theme into a form row's description, reintroducing the narrative this task removes. The member construction currently reads:

```python
            members.extend(
                Ticket(index, title or theme, description or theme, way) for way in ways[:want]
            )
```

Replace with:

```python
            # A form legitimately has NO description, so `description or theme` must not
            # smuggle the theme back in - that is the narrative whose blanking split the
            # group into two clusters. Only fall back to the theme when the model gave us
            # nothing at all, which is the padding case.
            fallback = "" if size >= FORM_GROUP_MIN else theme
            members.extend(
                Ticket(index, title or theme, description or fallback, way)
                for way in ways[:want]
            )
```

- [ ] **Step 6: Run everything and commit**

Run: `make test && make lint`
Expected: `283 passed, 2 skipped, 2 xfailed`, ruff silent.

```bash
git add fixtures/generate.py tests/unit/test_fixture_generate.py
git commit -F - <<'MSG'
fix(fixtures): write the dominant cluster as a form, not a narrative

<write a real body: the window measurement that gated this; the real cluster's whole
vocabulary is a couple of words; a narrative BEFUND let description blanking split the
largest group in two; a form has no narrative to blank>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: Regenerate and measure

Tasks 1–3 change prompt text, so every affected prompt is a cache miss. The 230 cached responses under `local/fixtures/cache/vllm-Qwen-Qwen2.5-32B-Instruct-AWQ-t0.8/` still cover anything whose text is unchanged.

- [ ] **Step 1: Fair-use check**

Run: `./infra/fairuse/gpu-fairuse2.sh check`

Exit 0 means both GPUs are free. **Exit 1 is not necessarily a blocker** — it gates *both* GPUs, and one busy GPU is often another user's job. Check per-GPU with `./infra/fairuse/gpu-fairuse2.sh claim 0`; if that prints `GO GPU0` you may take GPU 0 without touching the other user's work.

**Never override the guard.** `FAIRUSE_ALLOW_FOREIGN_PROCS` and `FAIRUSE_VRAM_CAP_GB` exist; using either to take a GPU another user is on breaks the fair-use contract this shared box runs under. If both GPUs are busy, wait — generation is not time-critical.

- [ ] **Step 2: Serve the model**

`claim 0` prints the GPU UUID and `VLLM_GPU_MEMORY_UTILIZATION=0.75` (the 60 GB cap). Then, on the box:

```bash
ssh hpc
cd <data-dir>
podman rm -f vllm-recall 2>/dev/null
podman run -d --name vllm-recall \
  --device nvidia.com/gpu=<UUID from claim> \
  -v <data-dir>/hf-cache:/root/.cache/huggingface:Z \
  -p 8000:8000 --ipc=host \
  docker.io/vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-32B-Instruct-AWQ \
  --no-enable-log-requests \
  --gpu-memory-utilization 0.75 \
  --max-model-len 32768
```

Two traps already paid for:

- vLLM 0.27.1 **removed `--disable-log-requests`**. The equivalent is `--no-enable-log-requests`; request logging is off by default anyway. Passing the old flag makes the container exit immediately with `unrecognized arguments`.
- The CLI's default `Qwen/Qwen2.5-32B-Instruct` is **bf16 at ~65 GB and breaches the 60 GB cap.** Use the AWQ variant. The model id is part of the cache identity, so this choice is visible in the provenance directory name.

The model is already in `<data-dir>/hf-cache`, so startup is ~105s with no download. Poll `curl -sS -o /dev/null -w '%{http_code}' http://localhost:8000/health` until it returns `200`, and watch for the container dying — a silent exit looks identical to a slow start.

- [ ] **Step 3: Tunnel**

The CLI's `--base-url` default is `http://localhost:8000`, so from the workstation:

```bash
ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 8000:localhost:8000 hpc
```

Run this with `run_in_background: true` — it does not exit. Verify with `curl -sS -m 15 http://localhost:8000/v1/models`, which must report `Qwen/Qwen2.5-32B-Instruct-AWQ`.

- [ ] **Step 4: Write the generation harness**

The CLI's `--out` ends in the blocked suffix, so create this file with the **Write tool** (never a heredoc) at `<scratchpad>/test_generate_real_fixture.py`:

```python
"""Drive the fixture CLI against the model on the H100, through pytest."""

from __future__ import annotations

import csv
import json
import pathlib

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
TEMPERATURE = 0.8
BASE_URL = "http://localhost:8000"

PROFILE = pathlib.Path("local/artifacts/profile.json")
OUT = pathlib.Path("local/fixtures/export.csv")
CACHE = pathlib.Path("local/fixtures/cache")


def test_generate_the_shipped_fixture():
    # No capsys: this runs under -s, which disables capture, so capsys would come back empty
    # and the padding WARNING would look absent when it was merely unread.
    from fixtures.__main__ import main

    assert PROFILE.exists(), "the gated profile artifact must be present"
    before = {p.name for p in CACHE.glob("vllm-*")} if CACHE.exists() else set()

    code = main(
        [
            "--profile", str(PROFILE),
            "--out", str(OUT),
            "--rows", "1500",
            "--base-url", BASE_URL,
            "--model", MODEL,
        ]
    )
    print("=" * 70)
    print(f"CLI EXIT CODE: {code}  (3 = verify refused to write; 0 = fixture written)")
    print("=" * 70)

    # Provenance FIRST, regardless of exit code: even an aborted run proves who answered.
    after = {p.name for p in CACHE.glob("vllm-*")}
    expected = f"vllm-{MODEL.replace('/', '-')}-t{TEMPERATURE}"
    print(f"vllm cache dirs: {sorted(after)}  (before: {sorted(before) or '(none)'})")
    assert expected in after, (
        f"no {expected}/ under {CACHE} - the model was NOT called. A fake run writes "
        f"fake-seed-N/. This is finding 1's failure mode: it looks like success."
    )
    entries = list((CACHE / expected).glob("*.json"))
    print(f"cached model responses: {len(entries)}")
    identities = {json.loads(p.read_text(encoding="utf-8"))["identity"] for p in entries[:80]}
    assert identities == {f"vllm:{MODEL}@t{TEMPERATURE}"}, identities

    assert code == 0, (
        f"the CLI exited {code}. 3 means verify found drift and REFUSED to write the "
        f"fixture - read the ABORT list in the stdout above; that is the honest outcome, "
        f"not a test to be relaxed."
    )
    with OUT.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"rows written: {len(rows)}")
    assert len(rows) == 1500
```

- [ ] **Step 5: Generate**

Run, with `run_in_background: true`, redirecting to a log:

`uv run pytest <scratchpad>/test_generate_real_fixture.py -s -q > <scratchpad>/gen.log 2>&1`

**A foreground Bash command is capped at 10 minutes in this harness and a full run exceeds it.** Background it. Do not pipe the run through `tail` — that truncated the padding WARNING and the ABORT list once already, and the wrapper's exit code then reports `tail`'s status rather than pytest's. **Read the log file.**

If the run dies with `httpx.ReadTimeout`, that is usually a request left stalling by a previously killed run, not a real need for more than the client's 120s. A single subsystem batch takes ~33s and a 200-ask returns in ~10s. The cache makes a resume free — just re-run it.

- [ ] **Step 6: Read the padding WARNING and the verify result**

Read `<scratchpad>/gen.log` from the top. Expected:

```
wrote local/fixtures/export.csv (1500 rows)
CLI EXIT CODE: 0
```

A `WARNING padded N of 1500 tickets` line means N rows are byte-identical within their group and carry **no solution**. Round 3 achieved **padding 0**; anything above ~20 will pull corpus solutions fill below the ±0.02 tolerance and `verify` will refuse the fixture with exit 3. If it does, read the ABORT list — that is the honest outcome, not a tolerance to relax.

- [ ] **Step 7: Profile against the real corpus**

Create `<scratchpad>/profile_compare.py` with the **Write tool** (the path contains the blocked suffix), using the complete script in **Appendix A**. Run it with `uv run python <scratchpad>/profile_compare.py`.

One thing in it that is easy to get wrong and was already got wrong once: **fill-by-year must be compared the way `verify.check` does it** — the plan's per-year target is the unweighted mean of the real *monthly* rates, but the fixture's actual is counted over its own *rows* for that year, with tolerance `max(0.05, 0.5/n)`. Averaging the fixture's monthly rates instead reported three false failures, because in the fixture's smallest year (a handful of rows) a single row moves the number by many points.

**Acceptance:** all three bands within ±0.01. Round 3's failing numbers to beat: the singleton band was too low and the mid band too high (see the table above); large already passed.

**Expected shape even on success**, so it is not misread as a regression: the fixture has **one** cluster ≥50 where the corpus has a few, and its largest is somewhat larger than the real largest, because it absorbs the others. That is the accepted cost of finding 2's decision, recorded in `docs/STATE.md`.

Two residuals that are **expected to remain** and are not this plan's business: descriptors p75 slightly below the real value, and max 21 against a somewhat higher real value — both caused by the fields the profile suppresses (finding 3).

- [ ] **Step 8: Measure per-group purity and singleton collisions**

The bands alone do not say *why*. Use the complete script in **Appendix B**, created with the **Write tool**, and run `uv run python <scratchpad>/diagnose_clusters.py`.

Round 3's baseline to beat: **every group clustering, 0 fragmented**, and **173 singletons colliding across 76 spurious clusters**. If any group stops clustering, Task 3 broke something. If the group-0 split line still shows two clusters after Task 3, the form prompt did not take effect — check that the `form` flag actually reaches `_prompt` (see Task 3 Step 4's warning).

- [ ] **Step 9: Set the fixture aside if it is not accepted**

If any band still fails, **do not leave the file at `local/fixtures/export.csv`.** `test_the_generated_fixture_profiles_like_the_real_corpus` skips while that path is empty and runs when it is not, so an unaccepted fixture makes `make test` red — correctly — and a later session would mistake it for the accepted artifact. Move it aside with a Write-tool script naming the path inside the file, following the three already parked:

```
local/fixtures/export.bands-rejected-2026-08-19.csv          (round 1, no cluster structure)
local/fixtures/export.round2-singleton-collisions-2026-08-19.csv
local/fixtures/export.round3-no-padding-2026-08-19.csv       (padding 0, current best)
```

- [ ] **Step 10: Release the GPU**

```bash
ssh hpc 'podman stop -t 20 vllm-recall; podman rm -f vllm-recall'
```

Then stop the tunnel task. Confirm with `nvidia-smi --query-gpu=index,memory.free,utilization.gpu --format=csv,noheader`. Holding 60 GB on a shared box while a human decision is pending is not defensible.

- [ ] **Step 11: Record the outcome in `docs/STATE.md`**

Update finding 9 with the measured bands, the collision count, and — if a hypothesis failed — say so explicitly with its numbers, the way finding 9 records that subsystem steering moved 182 → 173. A wrong hypothesis recorded is worth more than a vague one omitted, because it stops the next session retrying it.

Then commit `docs/STATE.md` alone.

---

## After the last task

- [ ] `make test && make lint` green, tree clean.
- [ ] Nothing under `local/` committed: `git ls-files local/` must be empty.
- [ ] If all three bands pass: the fixture at `local/fixtures/export.csv` is the acceptance candidate. It still stays **uncommitted** until the Window B leakage gate is green — that is a separate plan and a sealed window, and re-gating a committed fixture costs another window.
- [ ] The four window questions in `docs/STATE.md` that remain unanswered stay recorded as open.

## Out of scope

- **The Window B leakage gate.** Its nearest-neighbour threshold is calibrated against a synthetic-vs-synthetic baseline measured in the same window, which cannot be written before an accepted fixture exists.
- **Programmatic noise injection** (`PROJECT_BRIEF.md` §8: signatures, quoted chains, corrupted casing, HTML). Deliberately separate — voices change how the model writes, noise is applied mechanically afterwards. It will also affect the bands, so it wants its own measurement.
- **The application-side model-family mapping.** `model_designations.family_count` is 0 so the designation-grammar route is dead, but `dimension_hints.vehicleModelId` gives per-model vocabulary from which a family mapping can be derived **on-prem**. That is M4 work on real data, and unrelated to Task 2's invented line for the fixture.
- **The retrieval requirement** that near-identical tickets with differing solutions must all reach the technician. Recorded in `docs/STATE.md` under decisions; it is an M3+ concern, not a fixture change.

---

## Appendix A - `profile_compare.py`

Verbatim, as used for rounds 1-3. Create it with the **Write tool**: the paths inside contain
the blocked suffix, which is fine in a file and forbidden in a Bash command. `--smoke` and
`--diag` point at throwaway fixtures in the scratchpad; with no flag it reads the shipped path.

```python
"""Profile the generated fixture and compare it to the real one, dimension by dimension.

The design doc's strongest acceptance test costs nothing new: we already own a corpus
profiler, so run it over the fixture and compare. Tolerances here are the design doc's:
bands +/-1.0 point, customData field shares +/-2.0, fehlercode shape mix +/-3.0,
fill-by-year +/-5.0.

Run from the repo root:  uv run python <this file>
Add --smoke or --diag to point at a throwaway fixture in this scratchpad instead.

Every candidate path is spelled out HERE, in the file, never on a command line: the session
hook rejects any Bash command naming the export suffix, and the sanctioned route is the one
the repo's committed integration tests already use.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys

sys.path.insert(0, ".")

REAL = pathlib.Path("local/artifacts/profile.json")
_SHIPPED = pathlib.Path("local/fixtures/export.csv")
_SMOKE = pathlib.Path(__file__).resolve().parent / "fake_smoketest_export.csv"
_DIAG = pathlib.Path(__file__).resolve().parent / "diag_export.csv"
if "--smoke" in sys.argv:
    GENERATED = _SMOKE
elif "--diag" in sys.argv:
    GENERATED = _DIAG
else:
    GENERATED = _SHIPPED

BAND_TOL = 0.01
SHARE_TOL = 0.02
SHAPE_TOL = 0.03
YEAR_TOL = 0.05


def bands(profile: dict) -> dict[str, float]:
    dist = {int(k): v for k, v in profile["clusters"]["size_distribution"].items()}
    total = profile["source"]["row_count"]
    return {
        "singletons": sum(s * n for s, n in dist.items() if s == 1) / total,
        "mid (2-49)": sum(s * n for s, n in dist.items() if 2 <= s <= 49) / total,
        "large (>=50)": sum(s * n for s, n in dist.items() if s >= 50) / total,
    }


def verdict(delta: float, tol: float) -> str:
    return "PASS" if abs(delta) <= tol else "**FAIL**"


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    if not GENERATED.exists():
        print(f"no generated fixture at {GENERATED} - nothing to profile")
        return 2

    from profiler.__main__ import build_profile

    real = json.loads(REAL.read_text(encoding="utf-8"))
    syn = build_profile(GENERATED, 5)
    failures: list[str] = []

    section("CLUSTER BANDS  (the number no amount of planning could predict)")
    rb, sb = bands(real), bands(syn)
    print(f"{'band':<16}{'real':>10}{'fixture':>10}{'delta':>10}{'tol':>8}  verdict")
    for band in rb:
        d = sb[band] - rb[band]
        v = verdict(d, BAND_TOL)
        print(f"{band:<16}{rb[band]:>10.4f}{sb[band]:>10.4f}{d:>+10.4f}{BAND_TOL:>8.2f}  {v}")
        if "FAIL" in v:
            failures.append(f"cluster band {band}")
    print()

    def top_clusters(profile: dict) -> str:
        # clusters.largest is a LIST of {share, size, top_tokens} in schema v2.
        return ", ".join(
            f"{c['size']} ({c['share']:.4f}) {'+'.join(c.get('top_tokens') or [])}"
            for c in profile["clusters"]["largest"]
        )

    for label, profile in (("real   ", real), ("fixture", syn)):
        print(
            f"{label} clusters: {profile['clusters']['cluster_count']}, "
            f"singletons {profile['clusters']['singleton_count']}"
        )
        print(f"        largest: {top_clusters(profile)}")
    print()
    print("Expected shape per docs/STATE.md finding 2: the fixture has ONE cluster >=50 where")
    print("the corpus has a few, and its largest is somewhat larger than the real largest because")
    print("it absorbs the others. Accepted cost, not a regression. If a BAND drifts, the")
    print("planner or the prompt is wrong, not the tolerance.")

    section("FILL BY YEAR  (description / solutions)")
    print("Compared the way verify.check does it: the plan's per-year TARGET is the unweighted")
    print("mean of the real MONTHLY rates, the fixture's ACTUAL is counted over its own ROWS")
    print("for that year, tolerance max(5.0 points, 0.5/n). Averaging the FIXTURE's monthly")
    print("rates instead reports false failures - in a year with a handful of rows one row moves it by many points.")

    real_fbm = real["temporal"]["fill_by_month"]

    def target_by_year(column: str) -> dict[str, float]:
        acc: dict[str, list[float]] = {}
        for month, rate in real_fbm.get(column, {}).items():
            acc.setdefault(month[:4], []).append(rate)
        return {y: sum(v) / len(v) for y, v in acc.items()}

    with GENERATED.open(newline="", encoding="utf-8") as fh:
        fixture_rows = list(csv.DictReader(fh))
    rows_by_year: dict[str, list[dict[str, str]]] = {}
    for r_ in fixture_rows:
        rows_by_year.setdefault((r_.get("timestampCreated") or "")[:4], []).append(r_)

    for column in ("description", "solutions"):
        print(f"\n-- {column}")
        targets = target_by_year(column)
        print(f"{'year':<7}{'n':>6}{'target':>9}{'actual':>9}{'delta':>9}{'tol':>8}  verdict")
        for year in sorted(targets):
            dated = rows_by_year.get(year, [])
            if not dated:
                print(f"{year:<7}{0:>6}{targets[year]:>9.4f}{'absent':>9}")
                failures.append(f"fill-by-year {column} {year} absent")
                continue
            actual = sum(1 for r_ in dated if (r_.get(column) or "").strip()) / len(dated)
            tol = max(YEAR_TOL, 0.5 / len(dated))
            d = actual - targets[year]
            v = verdict(d, tol)
            print(
                f"{year:<7}{len(dated):>6}{targets[year]:>9.4f}{actual:>9.4f}"
                f"{d:>+9.4f}{tol:>8.4f}  {v}"
            )
            if "FAIL" in v:
                failures.append(f"fill-by-year {column} {year}")

    section("customData FIELD SHARES  (tolerance +/-2.0 points)")
    real_rows = real["source"]["row_count"]
    syn_rows = syn["source"]["row_count"]
    real_fields = {f["name"]: f for f in real["custom_data"]["envelope"]["fields"]}
    syn_fields = {f["name"]: f for f in syn["custom_data"]["envelope"]["fields"]}
    print(f"real emitted {len(real_fields)} fields, fixture emitted {len(syn_fields)}")
    print(f"{'field':<26}{'real':>9}{'fixture':>9}{'delta':>9}  verdict")
    for name, f in sorted(real_fields.items(), key=lambda kv: -kv[1]["present_count"]):
        rs = f["present_count"] / real_rows
        if name not in syn_fields:
            print(f"{name:<26}{rs:>9.4f}{'absent':>9}")
            failures.append(f"field {name} absent")
            continue
        ss = syn_fields[name]["present_count"] / syn_rows
        d = ss - rs
        v = verdict(d, SHARE_TOL)
        print(f"{name:<26}{rs:>9.4f}{ss:>9.4f}{d:>+9.4f}  {v}")
        if "FAIL" in v:
            failures.append(f"field share {name}")

    section("fehlercode SHAPE MIX  (tolerance +/-3.0 points)")

    def mix(fields: dict, name: str) -> dict[str, float]:
        f = fields.get(name)
        if not f:
            return {}
        shapes = f.get("value_shapes", [])
        total = sum(s["count"] for s in shapes) or 1
        return {s["shape"]: s["count"] / total for s in shapes}

    rm, sm = mix(real_fields, "fehlercode"), mix(syn_fields, "fehlercode")
    print(f"{'shape':<22}{'real':>9}{'fixture':>9}{'delta':>9}  verdict")
    for shape, rv in sorted(rm.items(), key=lambda kv: -kv[1]):
        sv = sm.get(shape, 0.0)
        d = sv - rv
        v = verdict(d, SHAPE_TOL)
        print(f"{shape:<22}{rv:>9.4f}{sv:>9.4f}{d:>+9.4f}  {v}")
        if "FAIL" in v:
            failures.append(f"fehlercode shape {shape}")
    extra = set(sm) - set(rm)
    if extra:
        print(f"shapes in fixture not in real: {sorted(extra)}")

    section("DESCRIPTORS PER ROW  (finding 3; p75 and max are known residuals)")
    rq = real["custom_data"]["envelope"]["records_per_row_quantiles"]
    sq = syn["custom_data"]["envelope"]["records_per_row_quantiles"]
    print(f"{'quantile':<10}{'real':>9}{'fixture':>9}")
    for k in ("p1", "p25", "p50", "p75", "p90", "p95", "p99", "p999", "max"):
        if k in rq:
            print(f"{k:<10}{rq[k]:>9}{sq.get(k, '-'):>9}")
    print("\np75 slightly low and max 21 against a higher real value are the two residuals recorded in")
    print("docs/STATE.md finding 3 - the fields the profile suppresses. Expected.")

    section("SUMMARY")
    print(f"envelope detected in fixture: {syn['custom_data']['envelope']['detected']}")
    print(f"customData parse success:     {syn['custom_data']['parse_success_rate']}")
    print(f"rows: {syn_rows}")
    if failures:
        print(f"\n{len(failures)} dimension(s) outside tolerance:")
        for f in failures:
            print(f"  - {f}")
        print("\nA drift means the planner or the prompt is wrong, not that the tolerance is.")
        return 1
    print("\nevery compared dimension is within the design doc's tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## Appendix B - `diagnose_clusters.py`

Verbatim, as used to produce round 3's "every group clusters, 173 singletons
collide" numbers. It replicates `profiler/stats/clusters.py`'s greedy sweep exactly, so its
cluster ids line up with the profile's size distribution. Point `FIX` at whichever fixture you
are measuring.

```python
"""Per-group cluster purity and singleton collisions. The bands say WHAT, this says WHY.

Replicates profiler/stats/clusters.py's greedy sweep exactly, so cluster ids line up with the
profile's size distribution. Point FIX at whichever fixture you are measuring; the path lives
in this file because the session hook rejects Bash commands naming the export suffix.

Round 3 baseline to beat: every intended group clustering (0 fragmented), and 173
singletons landing in a cluster of >=2 across 76 spurious clusters.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, ".")

from datasketch import MinHash, MinHashLSH  # noqa: E402

from fixtures.plan import plan  # noqa: E402
from profiler.stats import vocab  # noqa: E402
from recall.clean import pipeline  # noqa: E402

FIX = pathlib.Path("local/fixtures/export.csv")

profile = json.loads(pathlib.Path("local/artifacts/profile.json").read_text())
fp = plan(profile, rows=1500, seed=7)

with FIX.open(newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
docs = [pipeline.clean(f"{r.get('title') or ''} {r.get('description') or ''}").text for r in rows]
print(f"{len(rows)} rows, plan has {len(fp.group_sizes)} groups")


def mh(text: str) -> MinHash:
    m = MinHash(num_perm=128)
    for tok in set(vocab.tokenize(text)):
        m.update(tok.encode())
    return m


lsh = MinHashLSH(threshold=0.7, num_perm=128)
hashes = {}
for i, d in enumerate(docs):
    h = mh(d)
    hashes[i] = h
    lsh.insert(str(i), h)

seen: set[int] = set()
cluster_of: dict[int, int] = {}
cluster_size: dict[int, int] = {}
for i in range(len(docs)):
    if i in seen:
        continue
    members = {int(k) for k in lsh.query(hashes[i])} | {i}
    members -= seen
    seen |= members
    for m_ in members:
        cluster_of[m_] = i
    cluster_size[i] = len(members)

# Rows are emitted group-by-group: multi-member groups first in plan order, then singletons.
multi = [(i, s) for i, s in enumerate(fp.group_sizes) if s >= 2]
print(f"\nINTENDED GROUPS: {len(multi)} multi-member")
print(f"{'group':>6}{'size':>6}{'clusters':>10}{'biggest':>9}{'purity':>8}")
ptr = 0
fragmented = 0
for gi, size in multi:
    idx = list(range(ptr, ptr + size))
    ptr += size
    cl = Counter(cluster_of[i] for i in idx)
    biggest = cl.most_common(1)[0][1]
    if size >= 5 or len(cl) > 1:
        print(f"{gi:>6}{size:>6}{len(cl):>10}{biggest:>9}{biggest / size:>8.2f}")
    if biggest / size < 0.5:
        fragmented += 1
print(f"fragmented groups (<0.5 purity): {fragmented} of {len(multi)}")

singles = list(range(ptr, len(rows)))
print(f"\nINTENDED SINGLETONS: {len(singles)} rows")
in_cluster = [i for i in singles if cluster_size.get(cluster_of[i], 1) >= 2]
print(
    f"singletons in a cluster of >=2: {len(in_cluster)} ({len(in_cluster) / len(singles):.1%})"
)
print("-> these are exactly the singleton band's deficit and the mid band's surplus")

bad = Counter(cluster_of[i] for i in in_cluster)
print(f"\ndistinct spurious clusters: {len(bad)}")
print("largest, with a sample title:")
for cid, n in bad.most_common(12):
    print(f"  {n:>3} rows  |  {rows[cid]['title'][:66]}")

print("\nHow description blanking splits the dominant group (group 0, the first rows):")
g0 = list(range(min(fp.group_sizes[0], len(rows))))  # the dominant group is emitted first
withd = [i for i in g0 if (rows[i].get("description") or "").strip()]
blank = [i for i in g0 if not (rows[i].get("description") or "").strip()]
print(f"  {len(withd)} rows with a description -> clusters {set(cluster_of[i] for i in withd)}")
print(f"  {len(blank)} rows blanked            -> clusters {set(cluster_of[i] for i in blank)}")
print("  A blanked row's token set is the TITLE ONLY, so it cannot reach 0.7 Jaccard against")
print("  title+description. Two cluster ids here means the split is still happening; after")
print("  Task 3 the dominant group should have no description at all and show ONE id.")
```
