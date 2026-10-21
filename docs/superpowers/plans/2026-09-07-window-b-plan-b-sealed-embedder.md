# Window B Leakage Gate — Plan B: the sealed embedder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `profiler/gate` produce a report whose `embedder_is_a_model` is **true** — the real `intfloat/multilingual-e5-large` running inside the sealed airlock image with `--network=none`, driven by `window.sh`'s Window B command block, proven by an offline rehearsal before a real window is ever booked.

**Architecture:** No new packages. `profiler/gate/embedder.py` gains an `E5Embedder` beside the existing `HashingEmbedder`, satisfying the same `Embedder` protocol — so nothing else in the gate changes. `infra/profiler/Dockerfile` bakes torch and the model weights in at **build** time, because the window runs with no network. `infra/profiler/rehearse-window-b.sh` mirrors the existing Window A rehearsal, which has already caught six defects that would each have cost an airlock cycle.

**Tech Stack:** Python 3.12, uv, pytest, ruff, torch (**CPU-only wheels**), transformers, podman.

---

## Read this first — you have no context

This plan assumes a fresh session. Read, in order:

1. This plan, whole.
2. `docs/STATE.md` — the resume point. Read **"M2 findings"** (all twelve), and **"Decisions already made — do not relitigate"**.
3. `docs/superpowers/plans/2026-08-27-window-b-leakage-gate.md` — **Plan A**, which is complete. It built all four checks with the embedder injected precisely so this plan is the only part that needs the sealed image.
4. `docs/airlock-runbook.md` § **"Window B — leakage gate"** — the controls, which are not negotiable.
5. `PROJECT_BRIEF.md` §8 **"Leakage gate"**.

## Data handling rules — absolute

- **Never read anything under `local/quarantine/` or the client working directory.** A client's real ticket export under NDA. **Nothing in this plan needs them** — every step runs against synthetic corpora.
- **A session hook rejects any Bash command whose text contains the export file suffix** (a dot followed by `csv`). Put such paths *inside* a Python file written with the Write tool, and invoke it with a command that never names the suffix. Passing one as an argv trips the hook — verified twice. **This includes heredocs**: `cat > f <<EOF` puts the body in the command text. If you think you need such a command, STOP and ask the operator.
- **Do not commit anything under `local/`.** `git ls-files local/` must stay empty.
- **The fixture at `local/fixtures/export.csv` stays uncommitted** until this gate is green against real data.

## The rule about failing tests

**If a test fails and you believe the test is wrong, STOP and report it rather than adjusting the test. On this project a failing test has been right and the plan wrong fifteen times.**

And a second rule this project learned the hard way, which matters more here than usual:

**A test that passes for the wrong reason is worse than no test, because it reads as coverage.** Four shipped in one session before being caught — an exact-Jaccard assertion that held while the stub clustered 60% of its own singletons; a shingle test whose real-side sentence was one content word short of the window, so the intersection was empty and it could not fail; a `"shingle" not in "[]"`; and an `isinstance(value, int)` satisfiable by an all-zeros return. **If you notice one, report it — that report is worth more than the implementation.**

## Decisions already made — do not relitigate

| Decision | Choice | When |
|---|---|---|
| Embedder | `intfloat/multilingual-e5-large`, shared with M3's pgvector index | operator, 2026-08-27 |
| Check scope | all four checks in the window, one report | operator, 2026-08-27 |
| Report signing | hash manifest, no keys | operator, 2026-08-27 |
| Baseline quantile | `BASELINE_PERCENTILE = 95`, `CROSS_PERCENTILE = 99` | operator + measurement, finding 12 |
| **Compute** | **CPU only. No GPU in the window container.** The run may take hours; the operator confirmed an overnight run is acceptable. | operator, 2026-09-07 |

**That last one removes the only branch this plan would otherwise have had.** Do not add `--device nvidia.com/gpu=…` to `window.sh`. Do not install CUDA torch. The airlock contract is unchanged by this plan.

## The two constraints that shape everything here

Both are read off `infra/profiler/window.sh`'s `cmd_run`, which invokes:

```
ulimit -c 0; podman run --rm --network=none \
  -v $QUARANTINE:/q \
  -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
  $IMAGE $WINDOW_CMD
```

1. **`--network=none`.** Nothing resolves at run time. The model weights and the tokenizer must be **inside the image**, and `transformers` must be told not to try reaching out — otherwise it fails with a network error inside a sealed window, where there is no AI to debug it.
2. **No `--device`.** CPU only, per the decision above.

`ulimit -c 0` is a data-safety control, not tidiness: a core dump would contain ticket text straight out of memory and outlive the window. Leave it.

## Where Plan A left things

- `profiler/gate/` holds `embedder.py`, `shingles.py`, `sweep.py`, `neighbours.py`, `report.py`, `__main__.py`.
- `python -m profiler.gate --synthetic X --real Y --out Z` works today with `HashingEmbedder`, exits 0 on green and 3 on red, and writes the report either way.
- `Embedder` is a `Protocol` with `identity: str` and `encode(list[str]) -> np.ndarray` returning **unit-norm row vectors**.
- `E5_DOCUMENT_PREFIX = "passage: "` and `MAX_TOKENS = 512` already exist in `embedder.py` and are already recorded in the report manifest.
- `report.embedder_is_a_model` is `not embedder.startswith("hashing:")`.
- `window.sh`'s window-b `WINDOW_CMD` is `''` and the script correctly refuses: *"window 'b' has no command block yet"*.

## File structure

| File | Change |
|---|---|
| `pyproject.toml` | add torch (CPU index) + transformers; `needs_model` marker |
| `uv.lock` | regenerated — the Dockerfile uses `--frozen` and fails loudly if stale |
| `profiler/gate/embedder.py` | add `E5_MODEL`, `E5_REVISION`, `E5Embedder` |
| `profiler/gate/__main__.py` | `--embedder` accepts `e5`; `--model-revision` |
| `infra/profiler/Dockerfile` | bake weights, set offline env, extend the offline self-check |
| `infra/profiler/window.sh` | window-b `WINDOW_CMD` |
| `infra/profiler/rehearse-window-b.sh` | new, mirrors `rehearse-window-a.sh` |
| `tests/unit/test_gate_embedder_e5.py` | new, marked `needs_model` |
| `docs/STATE.md` | record the outcome |

## Pre-flight

```bash
cd <repo-root>
git status --short && git log --oneline -1
make test; make lint
```

Expected: clean tree. `make lint` silent. `make test` **`1 failed, 338 passed, 1 skipped, 2 xfailed`** — the single failure is `tests/unit/test_data_guards.py::test_the_test_suite_does_not_dirty_the_quarantine`, from a stray `profiler_detail.log` in the quarantine directory that **only the operator may shred** (`make check-clean` says to inspect and shred it without an AI tool, and the session hook denies the assistant that path). **That failure is expected, is not yours, and must remain the only one.**

If the operator has shredded it, the baseline is `339 passed` with no failures. **Take the count you observe as your baseline and check each task adds the number of tests it says** — the delta is what matters, not the absolute.

---

### Task 1: torch and transformers, CPU-only

The default `torch` wheel pulls CUDA and is gigabytes larger for no benefit — the window has no GPU by decision. uv needs an explicit index for the CPU build.

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `uv.lock`

- [ ] **Step 1: Add the dependencies and the CPU index**

In `pyproject.toml`, add to `dependencies`:

```toml
  "torch>=2.4",
  "transformers>=4.44",
```

and add these blocks at the end of the file:

```toml
# torch's default wheels carry CUDA. The airlock window has no GPU by decision
# (operator, 2026-09-07: CPU is acceptable, the run may go overnight), so the CPU build is
# both smaller and the only one that will ever be exercised. `explicit = true` keeps every
# other package on PyPI - without it uv would try to resolve the whole tree against
# download.pytorch.org.
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cpu" }
```

Also add to `[tool.pytest.ini_options]`'s `markers`:

```toml
  "needs_model: requires the e5 weights (skipped unless they are present locally)",
```

- [ ] **Step 2: Regenerate the lock and verify CPU-only**

Run: `uv lock`
Then: `uv sync`

Verify the wheel really is CPU-only — a CUDA build would bloat the sealed image and pull an nvidia toolchain into it:

```bash
uv run python -c "import torch; print(torch.__version__); print('cuda build:', torch.version.cuda)"
```

Expected: a version ending `+cpu`, and `cuda build: None`. **If `torch.version.cuda` is not `None`, STOP and report** — the index override did not take, and baking a CUDA torch into the sealed image is a change to the airlock's footprint that the operator has not agreed to.

- [ ] **Step 3: Confirm nothing regressed**

Run: `make test; make lint`
Expected: the same baseline you measured in pre-flight. Adding a dependency must not change a single test.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -F - <<'MSG'
build: add torch (CPU-only) and transformers for the sealed embedder

<write a real body: the airlock window has no GPU by decision, so the CPU wheel is the only
one that will be exercised and the default CUDA build would bloat the sealed image for
nothing; explicit index keeps everything else on PyPI; uv.lock regenerated because the
Dockerfile uses --frozen and fails loudly on a stale lock>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: `E5Embedder`

The one piece of real logic in this plan. It satisfies the existing `Embedder` protocol, so `neighbours.py`, `report.py` and the CLI need no change beyond selecting it.

**Three things are easy to get wrong and each is pinned by a test:**

1. **Pooling.** e5 requires **mean pooling over the last hidden state, masked by the attention mask**. CLS pooling is wrong for this model family and produces plausible-looking but degraded vectors — the kind of defect that yields a green gate for the wrong reason. Pinned by comparing against a hand-computed mean.
2. **Normalisation.** `neighbours.py` treats a dot product as a cosine, which is only true for unit-norm rows. Pinned.
3. **The prefix.** `E5_DOCUMENT_PREFIX` is applied by `neighbours._encode`, **not** by the embedder — do not apply it twice. Pinned by asserting the embedder does not add it itself.

**Files:**
- Modify: `profiler/gate/embedder.py`
- Create: `tests/unit/test_gate_embedder_e5.py`

- [ ] **Step 1: Capture the revision you are pinning**

The identity must name a revision, so the report says exactly which weights produced the verdict — finding 1's lesson, and the manifest exists to make a run reproducible.

```bash
uv run python - <<'PY'
from huggingface_hub import model_info
info = model_info("intfloat/multilingual-e5-large")
print("sha:", info.sha)
PY
```

Record the printed sha. Use it verbatim as `E5_REVISION` below. **If this command needs network and you have none, STOP and ask the operator to run it** — do not substitute `"main"`, because an unpinned revision makes the manifest a claim about nothing.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_gate_embedder_e5.py`:

```python
import numpy as np
import pytest

from profiler.gate import embedder

pytestmark = pytest.mark.needs_model


def _model():
    try:
        return embedder.E5Embedder()
    except Exception as exc:  # noqa: BLE001 - weights absent is the only expected cause
        pytest.skip(f"e5 weights not available locally: {exc}")


def test_the_identity_names_the_model_and_its_revision():
    """Finding 1: a stub answered for the model for two rounds because nothing recorded who
    answered. A gate report asserting a cosine bound is worthless if the vectors came from
    somewhere else, and the manifest exists to make the run reproducible - which needs the
    revision, not just the name."""
    model = _model()
    assert model.identity.startswith("e5:intfloat/multilingual-e5-large@")
    assert not model.identity.startswith("hashing:"), (
        "report.embedder_is_a_model keys off this prefix"
    )
    assert len(model.identity.split("@")[-1]) >= 7, "the revision must be pinned, not 'main'"


def test_vectors_are_unit_norm():
    """neighbours.py treats a dot product as a cosine, which is only true for unit-norm rows.
    Without this every threshold in the gate means something else."""
    vectors = _model().encode(["Hydraulikpumpe verliert Druck", "Klimaanlage kuehlt nicht"])
    assert vectors.shape[0] == 2
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_pooling_is_masked_mean_not_cls():
    """e5 requires mean pooling over the last hidden state, masked by the attention mask. CLS
    pooling is wrong for this family and yields plausible-looking but degraded vectors - a
    green gate for the wrong reason.

    Padding must not shift the result: the same text embedded alone and alongside a much
    longer sibling gets different padding, and a mean that ignores the mask would differ.
    """
    model = _model()
    alone = model.encode(["Pumpe undicht"])[0]
    padded = model.encode(["Pumpe undicht", "Ein deutlich laengerer Satz " * 20])[0]
    np.testing.assert_allclose(alone, padded, atol=1e-4)


def test_identical_text_reaches_cosine_one_and_unrelated_text_does_not():
    """The gate must be able to see what it exists to catch, and to tell it from ordinary
    German. Both halves, because a model that scored everything near 1.0 would pass the first
    assertion alone."""
    model = _model()
    vectors = model.encode(
        [
            "Hydraulikpumpe verliert Druck an der Vorderachse",
            "Hydraulikpumpe verliert Druck an der Vorderachse",
            "Klimaanlage kuehlt nicht ausreichend im Sommerbetrieb",
        ]
    )
    assert float(vectors[0] @ vectors[1]) > 0.999
    assert float(vectors[0] @ vectors[2]) < 0.95


def test_the_embedder_does_not_add_the_passage_prefix_itself():
    """`neighbours._encode` prepends E5_DOCUMENT_PREFIX. If the embedder did it too the text
    would carry it twice, which is a silent shift in every cosine in the report."""
    model = _model()
    plain = model.encode(["Pumpe undicht"])[0]
    prefixed = model.encode([embedder.E5_DOCUMENT_PREFIX + "Pumpe undicht"])[0]
    assert float(plain @ prefixed) < 0.9999, (
        "the two must differ, or the embedder is stripping or adding the prefix on its own"
    )
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_gate_embedder_e5.py`
Expected: FAIL — `module 'profiler.gate.embedder' has no attribute 'E5Embedder'`.

(`pyproject.toml` sets `addopts = "-q --strict-markers"`, so adding `-q` yourself suppresses the count line. Run without `-q` when you want a count.)

- [ ] **Step 4: Implement**

Append to `profiler/gate/embedder.py`:

```python
# The operator's choice on 2026-08-27, shared with M3's pgvector index so the gate's cosine
# bound applies to the vectors M3 actually stores. Pinned by revision: the manifest exists to
# make a run reproducible, and "multilingual-e5-large" without a revision is a claim about
# whatever the hub served that day.
E5_MODEL = "intfloat/multilingual-e5-large"
E5_REVISION = "<paste the sha from Task 2 Step 1>"


class E5Embedder:
    """`intfloat/multilingual-e5-large` on CPU, offline.

    Loads from the local cache only. The airlock window runs with `--network=none`, so a hub
    lookup there fails inside a sealed window with no AI available to debug it - the weights are
    baked into the image at build time and `local_files_only=True` makes an attempt to reach out
    a loud failure here rather than a mystery there.

    CPU by decision (operator, 2026-09-07): the window container gets no `--device`, and an
    overnight run is acceptable.

    Pooling is a MASKED MEAN over the last hidden state, which is what this model family
    requires. CLS pooling would produce plausible-looking but degraded vectors, and a gate that
    is green for the wrong reason is the failure mode this whole project keeps hitting.
    """

    def __init__(self, model: str = E5_MODEL, revision: str = E5_REVISION) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            model, revision=revision, local_files_only=True
        )
        self._model = AutoModel.from_pretrained(
            model, revision=revision, local_files_only=True
        ).eval()
        self.identity = f"e5:{model}@{revision}"

    def encode(self, documents: list[str], batch_size: int = 16) -> np.ndarray:
        torch = self._torch
        out: list[np.ndarray] = []
        for start in range(0, len(documents), batch_size):
            batch = [d or "" for d in documents[start : start + batch_size]]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=MAX_TOKENS,
                return_tensors="pt",
            )
            with torch.no_grad():
                hidden = self._model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.cpu().numpy().astype(np.float64))
        return np.vstack(out) if out else np.zeros((0, 1))
```

- [ ] **Step 5: Fetch the weights locally so the tests can run**

```bash
uv run python - <<'PY'
from transformers import AutoModel, AutoTokenizer
from profiler.gate.embedder import E5_MODEL, E5_REVISION
AutoTokenizer.from_pretrained(E5_MODEL, revision=E5_REVISION)
AutoModel.from_pretrained(E5_MODEL, revision=E5_REVISION)
print("weights cached")
PY
```

This needs network. It is a **local** fetch, not the sealed image — the image gets its own copy in Task 4.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_gate_embedder_e5.py`
Expected: 5 passed.

**If `test_pooling_is_masked_mean_not_cls` fails, STOP and report the two vectors' cosine.** It failing means padding is shifting the result, which means the mask is not being applied — and every cosine in every report would then depend on what else happened to be in the batch.

**If `test_identical_text_reaches_cosine_one_and_unrelated_text_does_not` fails on its second assertion**, report the measured cosine. e5 scores unrelated German fairly high, so if it comes in just above 0.95 the threshold may be wrong rather than the model — but that is the operator's call, not yours, because it interacts with finding 12's calibration.

- [ ] **Step 7: Full suite and lint, then commit**

Run: `make test; make lint`
Expected: baseline + 5.

```bash
git add profiler/gate/embedder.py tests/unit/test_gate_embedder_e5.py
git commit -F - <<'MSG'
feat(gate): the real e5 embedder, CPU and offline

<write a real body: satisfies the existing Embedder protocol so nothing else in the gate
changes; identity names model AND revision because the manifest exists to make a run
reproducible and finding 1 cost two rounds to a stub nobody could see; local_files_only makes
a hub lookup a loud failure here rather than a mystery inside a sealed --network=none window;
masked mean pooling not CLS, pinned by a padding-invariance test, because degraded vectors
would make the gate green for the wrong reason>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: Select it from the CLI

**Files:**
- Modify: `profiler/gate/__main__.py`
- Modify: `tests/unit/test_gate_report.py` (append one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_gate_report.py`:

```python
def test_the_cli_rejects_an_unknown_embedder_rather_than_defaulting(tmp_path):
    """A typo must not silently fall back to the stub. A report whose embedder_is_a_model is
    false because of a misspelt flag looks exactly like one produced on purpose."""
    import pytest

    from profiler.gate.__main__ import main

    synthetic, real = _unrelated_corpora(tmp_path)
    with pytest.raises(SystemExit):
        main(
            [
                "--synthetic", str(synthetic),
                "--real", str(real),
                "--out", str(tmp_path / "r.json"),
                "--embedder", "e5-large",
            ]
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_gate_report.py`
Expected: FAIL — argparse currently accepts only `hashing`, so `e5-large` already raises `SystemExit` and **this test may PASS immediately.** If it does, that is fine and expected: it is a guard against a future regression, not a driver for this change. Note it in your report and move on.

- [ ] **Step 3: Wire the choice**

In `profiler/gate/__main__.py`, change:

```python
    parser.add_argument("--embedder", choices=["hashing"], default="hashing")
```

to:

```python
    parser.add_argument("--embedder", choices=["hashing", "e5"], default="hashing")
    # Overridable so the operator can pin a different revision in the window without a code
    # change. Defaults to the pinned one; a mismatch shows up in the manifest either way.
    parser.add_argument("--model-revision", default=None)
```

and replace `model = HashingEmbedder()` with:

```python
    if args.embedder == "e5":
        from profiler.gate.embedder import E5_REVISION, E5Embedder

        model = E5Embedder(revision=args.model_revision or E5_REVISION)
    else:
        model = HashingEmbedder()
```

**`hashing` stays the default deliberately.** Every test in the suite must keep running on a machine with no weights, and the CLI already prints a NOTE when the stand-in produced the verdict.

- [ ] **Step 4: Run everything and commit**

Run: `make test; make lint`
Expected: baseline + 5 + 1.

```bash
git add profiler/gate/__main__.py tests/unit/test_gate_report.py
git commit -F - <<'MSG'
feat(gate): --embedder e5 selects the real model

<write a real body: hashing stays the default so the suite runs with no weights present; the
import is lazy so a machine without torch can still run the other three checks; revision
overridable for the window without a code change; a typo raises rather than falling back,
because a report whose embedder_is_a_model is false by accident looks exactly like one that
is false on purpose>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: Bake the weights into the sealed image

The load-bearing task. Build time has network; run time does not.

**Files:**
- Modify: `infra/profiler/Dockerfile`

- [ ] **Step 1: Read the current Dockerfile**

`cat infra/profiler/Dockerfile`. Note what it already does and preserve all of it: hunspell + the German dictionary, `uv sync --frozen --no-dev`, `COPY src` and `COPY profiler` (**not** `fixtures` — the gate lives under `profiler/` for exactly this reason), `HF_HUB_DISABLE_TELEMETRY=1`, and a final offline self-check.

- [ ] **Step 2: Bake the weights and force offline at run time**

Add **after** the existing `COPY profiler ./profiler` / `uv sync` lines and **before** the final self-check:

```dockerfile
# The model weights, fetched at BUILD time because the window runs with --network=none and
# nothing resolves there. ~2.2 GB. HF_HOME is set before the fetch so the cache lands inside
# the image rather than in a layer that gets discarded.
ENV HF_HOME=/opt/hf
RUN python -c "\
from transformers import AutoModel, AutoTokenizer; \
from profiler.gate.embedder import E5_MODEL, E5_REVISION; \
AutoTokenizer.from_pretrained(E5_MODEL, revision=E5_REVISION); \
AutoModel.from_pretrained(E5_MODEL, revision=E5_REVISION); \
print('weights baked')"

# Belt and braces on --network=none. Without these, transformers may still attempt a hub
# lookup and fail with a network error INSIDE a sealed window, where there is no AI available
# to work out why. local_files_only in E5Embedder is the first guard; these are the second.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
```

- [ ] **Step 3: Extend the offline self-check**

The existing final `RUN python -c "import profiler.__main__, recall.clean.pipeline; print('sealed image ok')"` proves the image imports offline. Extend it to prove the **model** loads offline too — this is the single most valuable line in the file, because it turns "the weights are missing from the image" from a sealed-window failure into a build failure:

```dockerfile
RUN python -c "\
import profiler.__main__, recall.clean.pipeline; \
from profiler.gate.embedder import E5Embedder; \
v = E5Embedder().encode(['passage: Pumpe undicht']); \
assert v.shape[0] == 1, v.shape; \
print('sealed image ok, model loads offline, dim', v.shape[1])"
```

- [ ] **Step 4: Build and verify offline operation**

```bash
podman build -t recall/profiler:pinned -f infra/profiler/Dockerfile .
```

Then prove it works with **no network at all**, which is the actual window condition:

```bash
podman run --rm --network=none recall/profiler:pinned python -c "\
from profiler.gate.embedder import E5Embedder; \
m = E5Embedder(); print(m.identity); \
print('dim', m.encode(['passage: test']).shape)"
```

Expected: the identity with its pinned revision, and a dimension of 1024.

**If this fails with a network or cache error, STOP.** Do not add a network to the run — that would break the one control the airlock actually guarantees. The fix belongs in the build.

- [ ] **Step 5: Commit**

```bash
git add infra/profiler/Dockerfile
git commit -F - <<'MSG'
build: bake the e5 weights into the sealed image

<write a real body: the window runs --network=none so nothing resolves there and the weights
must be inside the image; HF_HOME set before the fetch so the cache lands in the image;
HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE as the second guard behind local_files_only; the
offline self-check now loads the MODEL, which turns a missing-weights bug from a sealed-window
failure into a build failure - the whole point, since a window has no AI to debug it>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: `window.sh`'s Window B command block

**Files:**
- Modify: `infra/profiler/window.sh`

- [ ] **Step 1: Read the window-b block**

`sed -n '40,64p' infra/profiler/window.sh`. It already carries:

```
WINDOW_NAME="Window B - leakage gate"
WINDOW_IN="export.csv"
WINDOW_OUT=(gate_report.json)
WINDOW_SHRED=(export.csv profiler_detail.log shingles.bin neighbours.bin)
WINDOW_CMD=''
```

**Leave `WINDOW_OUT` and `WINDOW_SHRED` exactly as they are.** They were decided when the runbook was written. `shingles.bin` and `neighbours.bin` are on the shred list from an earlier design that wrote intermediates; the current gate writes none, and a shred list naming a file that does not exist is harmless while removing an entry is a change to a safety control.

- [ ] **Step 2: Write the command**

Replace window b's `WINDOW_CMD=''` with:

```bash
      # Plan B, 2026-09-07. The synthetic corpus is shipped in beside the real export; both
      # are read from /q, and only gate_report.json comes back out - counts, thresholds and
      # verdicts, no shingle set and no vectors, per docs/airlock-runbook.md.
      #
      # --embedder e5 is explicit rather than defaulted: the CLI defaults to the hashing
      # stand-in so the test suite runs without weights, and a window that silently used the
      # stand-in would produce a report whose embedder_is_a_model is false - indistinguishable
      # from one produced deliberately.
      #
      # CPU, no --device, by decision (operator, 2026-09-07). Expect hours, not minutes.
      WINDOW_CMD='python -m profiler.gate --synthetic /q/synthetic.csv --real /q/export.csv --out /q/gate_report.json --embedder e5 --roster /q/roster.txt'
```

**Note for whoever runs the window:** `WINDOW_IN` is `export.csv` only, so the synthetic corpus and the roster must be placed in the quarantine directory alongside it as part of Phase 0. The rehearsal in Task 6 exercises exactly that, which is where the omission would otherwise be discovered.

- [ ] **Step 3: Verify the refusal is gone and a dry run is sane**

```bash
./infra/profiler/window.sh --help 2>&1 | head -20
./infra/profiler/window.sh b run --dry-run 2>&1 | tail -20
```

Expected: no *"window 'b' has no command block yet"*. Read the printed command and confirm it names the three `/q` inputs and the one `/q` output. If `--dry-run` is not a supported flag, read the script's own usage rather than guessing, and report what it offers.

- [ ] **Step 4: Commit**

```bash
git add infra/profiler/window.sh
git commit -F - <<'MSG'
feat(airlock): write Window B's command block

<write a real body: --embedder e5 explicit rather than defaulted, because the CLI defaults to
the stand-in so the suite runs without weights and a window that silently used it would
produce a report indistinguishable from a deliberate stub run; WINDOW_OUT and WINDOW_SHRED
left untouched as decided safety controls; the synthetic corpus and roster must be staged into
quarantine in Phase 0, which the rehearsal exercises>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 6: `rehearse-window-b.sh`

**The most valuable task in this plan.** `rehearse-window-a.sh` has already caught six defects that would each have cost a full airlock cycle. A sealed window has no AI available and every failure costs a cycle; this is where the failures are supposed to happen instead.

**Files:**
- Create: `infra/profiler/rehearse-window-b.sh`
- Modify: `Makefile` (add a `window-b-rehearsal` target beside the existing `window-a-rehearsal`)

- [ ] **Step 1: Read the Window A rehearsal end to end**

`cat infra/profiler/rehearse-window-a.sh`. **Mirror its structure exactly** — same scratch-directory discipline, same `pass`/`fail` counters, same PASS/FAIL-per-step reporting, same `--quick` flag to skip the image rebuild, same refusal to run against anything outside its own scratch directory. Do not invent a new shape; the point is that a reader who knows one knows the other.

- [ ] **Step 2: Write the rehearsal**

It must, using **synthetic data only** and the **exact image, flags and mounts the real window uses**:

1. Create a scratch quarantine directory and refuse to proceed if it is outside `${TMPDIR:-/tmp}`.
2. Generate two stand-in corpora with `--fake` — one as the "synthetic" input, one standing in for the real export. **`llm.Fake` is lexically distinct under the profiler's tokenizer** (that was fixed after it clustered 60% of its own singletons), so two `--fake` runs with different seeds are genuinely different corpora.
3. Stage `synthetic.csv`, `export.csv` and `roster.txt` into the scratch quarantine, exactly as Phase 0 must.
4. Run the sealed image with `--network=none` and no `--device`, invoking the same `WINDOW_CMD` window b now carries.
5. Assert `gate_report.json` appears, is valid JSON, and that **`embedder_is_a_model` is `true`** — the single most important assertion in the file, and the thing Plan A could not prove.
6. Assert the report contains no text from either corpus: grep it for a distinctive token from each stand-in and require zero hits.
7. **Measure and print wall-clock time and documents-per-second.** Not a pass/fail gate — the operator has accepted an overnight run — but the number belongs in `docs/STATE.md` so whoever books the window knows what to expect.
8. Verify the shred list: after the run, assert every `WINDOW_SHRED` entry that exists can be removed and that `gate_report.json` is the only thing left.
9. Print a PASS/FAIL summary and exit non-zero on any failure.

- [ ] **Step 3: Add the Makefile target**

Beside the existing `window-a-rehearsal`:

```make
window-b-rehearsal:
	./infra/profiler/rehearse-window-b.sh
```

and add `window-b-rehearsal` to the `.PHONY` line.

- [ ] **Step 4: Run it**

Run: `make window-b-rehearsal`

Expected: every step PASS, `embedder_is_a_model: true`, and a printed throughput figure.

**Every failure here is a defect you have just saved an airlock cycle on.** Report each one with its step name and the actual output. Do not weaken an assertion to get a green rehearsal — the rehearsal exists precisely to be harder than the window.

- [ ] **Step 5: Commit**

```bash
git add infra/profiler/rehearse-window-b.sh Makefile
git commit -F - <<'MSG'
feat(airlock): a Window B dress rehearsal

<write a real body: mirrors rehearse-window-a.sh, which has caught six defects that would
each have cost an airlock cycle; synthetic data only, same image and flags and mounts as the
real window, --network=none and no --device; asserts embedder_is_a_model is true, which is
the thing Plan A could not prove; asserts no corpus text reaches the report; measures
throughput so whoever books the window knows what to expect; exercises the Phase 0 staging of
the synthetic corpus and roster, which window.sh's WINDOW_IN does not cover>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 7: Record the outcome

- [ ] **Step 1: Update `docs/STATE.md`**

Add, under the M2 findings:

- Plan B's completion, with the **measured throughput** from Task 6 and the resulting estimate for the real corpus (tens of thousands of documents) plus 1,500 synthetic ones.
- The **pinned revision** in `E5_REVISION`, so a later session can tell whether the weights changed.
- That the gate is now capable of a real verdict but **has not been run against real data** — that needs a booked window and is the operator's call.
- Any defect the rehearsal caught, with its numbers. A rehearsal that caught nothing is itself worth recording, because it means the next failure will be in the window.

Then update the summary near the top: Window B is ready to book.

- [ ] **Step 2: Commit `docs/STATE.md` alone**

---

## After the last task

- [ ] `make lint` silent; `make test` shows only the quarantine guard (or nothing, if the operator shredded it).
- [ ] Tree clean; `git ls-files local/` empty.
- [ ] `make window-b-rehearsal` green, with `embedder_is_a_model: true`.
- [ ] `podman run --rm --network=none recall/profiler:pinned …` loads the model offline.
- [ ] The fixture at `local/fixtures/export.csv` is **still uncommitted**.

## Out of scope

- **Booking and running the real window.** That is a manual, AI-free procedure in `docs/airlock-runbook.md` and the operator's decision.
- **Committing the fixture.** It waits for a green gate against real data.
- **Finding 11's seed study.** The operator deferred it until the gate is green.
- **Section 8's remaining three PII pattern families** — plates, surnames, addresses. Recorded with reasons in `profiler/gate/sweep.py`; plates need the roster to disambiguate the invented product line.
- **Programmatic noise injection** (§8: signatures, quoted chains, corrupted casing, HTML). Still unimplemented, will move the cluster bands, wants its own measurement pass.
