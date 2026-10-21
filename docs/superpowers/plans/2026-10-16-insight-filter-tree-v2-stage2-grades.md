# Filter tree v2, stage 2: estimator and certainty grades — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The filter tree answers a branch from the report's joint quality cube where it can.
- A number is **exact** when the cube holds the split.
- It is **bounded** (a guaranteed range) when some cells were too small to release.
- It is **estimated** (≈) only where a step has no joint split.
- Verdicts and suggestions rank on the worst case. A report without a cube behaves exactly as today.

**Architecture:**
- The view's corpus model (`MODEL-BEGIN`…`MODEL-END` in `insight/view.py`) moves to `insight/view_model.js`, which `render()` inlines, so the page stays one offline file.
- A cube tier answers a path's cube steps (category, model, Baugruppe, the gates error code/description/serial, "has a model id", "names a Baugruppe") from the one cut that holds exactly those axes.
- Every other step keeps today's independence estimate, applied as a correction: `new = old(path) × cube(part) / old(part)`.
- Two tests pin the behaviour:
  - a golden snapshot, written before the cube tier exists, pins "no cube = unchanged"
  - a ground-truth test checks the model against true counts from the stand-in's tickets

**Tech Stack:** JavaScript (in the page), node v24 for the model harnesses, Python 3.12 and pytest. Run Python as `../../.venv/bin/python` (a worktree has no `.venv`).

**Spec:** `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md`, section 2.

**Verified before writing:** every code block below was applied in a throwaway worktree, with these results:
- the move is byte-identical: the page rendered from the real fourth-run report is unchanged
- the golden snapshot matches (2,000 answers)
- the ground-truth test passes: 198 of 321 pure-cube paths are exact, and every answer agrees with the truth within half a ticket
- the model and smoke harnesses pass on the stand-in AND on the real fourth-run report
- ruff is clean, and the full suite passes (see the final check)

## Decisions taken while prototyping (within spec section 2; record them in the spec, Task 6)

- **Swap rule.** For a path with cube steps and other steps:
  - the estimate is `old(path) × cube(part) / old(part)`
  - the range is today's guaranteed range intersected with the cube part's range (Fréchet for the lower end)
  - estimated results never rise above the step before, as today
- **A path the quality section already answers exactly keeps that answer** (e.g. a category in one year). The cube tier only adds what is new.
- **Ranges are capped by the step above**, so a finer cut's withheld slack never makes a child's upper end exceed its parent's.
- **Four constrained cube axes** (category, Baugruppe, model and a gate in one path): no cut holds them, so today's estimate is used.
- **Worst-case usable** (`q.rlo`) comes from the cube where it applies. Otherwise it is the generic guarantee `usable(all) − (tickets(all) − tickets(path).lo)`, which is often 0 for paths with a year. That is honest: such a path never wins on a guess.
- **Suggestions** are offered when their *estimate* helps and *ordered* by the worst case (estimate as tie-break). Filtering on the worst case hid every suggestion on uncertain paths.
- **Only the ticket count's grade is displayed.** The usable count carries its own range (`q.rlo`..`q.rhi`, `q.grade`), used for ranking; showing it belongs to stage 5's comparison work.
- **A union of several Baugruppen** is bounded between the largest part and the sum of parts (capped by the cut without Baugruppe). The spec's extra tightening by released pairs is not done.
- **The truth test's tolerance is half a ticket.** The model's year and field figures come from fill *shares* the report rounds to four decimals.

## Binding constraints

- **Never read anything under `local/quarantine/` or `<export-dir>/`.** `local/artifacts/report.json` (the fourth run) has passed the gate and may be read.
- A harness hook blocks any Bash command whose text contains the export file extension. Edit a file that contains the export's file name (e.g. `tests/integration/test_insight_view.py`, whose fixture names it) with the Edit tool, never with `sed`/heredocs.
- Tests: `../../.venv/bin/python -m pytest -q <files>`. Lint: `../../.venv/bin/ruff check . && ../../.venv/bin/ruff format --check .`. Full suite: add `--ignore=tests/integration/test_german_fts.py --ignore=tests/integration/test_migrate.py`. `tests/unit/test_data_guards.py::test_the_test_suite_does_not_dirty_the_quarantine` fails whenever `local/quarantine` holds anything; it is unrelated to this work.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `insight/view_model.js` | **create** | the corpus model: what survives a chain of steps; cube tier; grades; `rankOf` |
| `insight/view.py` | modify | inline `view_model.js`; `amount()`; grade-aware display; rank toggle; verdicts and suggestions via `rankOf`; lab note |
| `tests/integration/insight_view_golden.js` | **create** | records/compares the model's answers on a frozen report |
| `tests/integration/insight_view_truth.js` | **create** | checks the model against true counts |
| `tests/integration/data/insight_report_nocube.json` | **create** | frozen stand-in report, cube removed (synthetic, guarded) |
| `tests/integration/data/insight_view_golden.json` | **create** | the golden answers, written in Task 2 |
| `tests/integration/test_insight_view.py` | modify | fixture without the slow measurement; golden and truth tests |
| `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md`, `docs/STATE.md` | modify | decisions, state |

---

### Task 0: Branch

- [ ] `git switch -c feat/filter-tree-grades` (from `feat/insight-quality`).
- [ ] Baseline: `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py` → all pass.

---

### Task 1: The corpus model moves to `insight/view_model.js`

**Files:** Create `insight/view_model.js`; modify `insight/view.py`; test `tests/integration/test_insight_view.py`.

- [ ] **Step 1: Write the failing test.** Append to `tests/integration/test_insight_view.py`:

```python
def test_the_page_inlines_the_corpus_model_file_verbatim(built):
    model = Path(view.__file__).with_name("view_model.js").read_text(encoding="utf-8").rstrip("\n")
    assert "(MODEL-BEGIN)" in model and "(MODEL-END)" in model
    assert model in view.render(built)
```

- [ ] **Step 2: Run it.** `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py -k inlines` → FAIL (`FileNotFoundError` for `view_model.js`).

- [ ] **Step 3: Move the block.** Run this from the worktree root. It cuts the block from `/* ---------- filter model: what survives a chain of steps (MODEL-BEGIN) ---------- */` through `/* ---------- (MODEL-END) ---------- */` (inclusive) out of `view.py` into `insight/view_model.js`, puts `__MODEL__` in its place, and makes `render()` inline it:

```bash
../../.venv/bin/python - <<'EOF'
p = "insight/view.py"; s = open(p).read()
a = s.index("/* ---------- filter model: what survives a chain of steps (MODEL-BEGIN) ---------- */")
end = "/* ---------- (MODEL-END) ---------- */"; b = s.index(end) + len(end)
open("insight/view_model.js", "w").write(s[a:b] + "\n")
s = s[:a] + "__MODEL__" + s[b:]
s = s.replace('    return _PAGE.replace("__CSP__", _CSP).replace("__DATA__", data)',
              '    return _PAGE.replace("__MODEL__", _MODEL).replace("__CSP__", _CSP).replace("__DATA__", data)')
s = s.replace('_PAGE = r"""<!doctype html>', '''# The corpus model (what survives a chain of filter steps) lives in its own file so it can be read,
# tested and changed on its own; render() inlines it, so the page stays one offline file.
_MODEL = (Path(__file__).with_name("view_model.js")).read_text(encoding="utf-8").rstrip("\\n")

_PAGE = r"""<!doctype html>''')
open(p, "w").write(s)
EOF
```

- [ ] **Step 4: Prove nothing changed.** Render the real report with this branch and with the parent commit; the pages must be identical:

```bash
git show HEAD:insight/view.py > /tmp/view_old.py
../../.venv/bin/python -c "
import json, importlib.util, sys; sys.path.insert(0, '.')
from insight import view as new
spec = importlib.util.spec_from_file_location('view_old', '/tmp/view_old.py'); old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
r = json.load(open('local/artifacts/report.json')); print('identical:', new.render(r) == old.render(r))"
```
Expected: `identical: True`. Then `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py` → all pass.

- [ ] **Step 5: Commit** `refactor(view): the corpus model moves to insight/view_model.js, inlined at render (byte-identical page)`.

---

### Task 2: The golden snapshot: no cube, no change

Written now, while the model knows nothing of the cube.

**Files:** Create `tests/integration/insight_view_golden.js`, `tests/integration/data/insight_report_nocube.json`, `tests/integration/data/insight_view_golden.json`. Modify `tests/integration/test_insight_view.py`.

- [ ] **Step 1: The harness.** Create `tests/integration/insight_view_golden.js`:

```javascript
// The corpus model's answers for a fixed report and fixed chains of steps, written once and then
// compared: without a quality cube the model must answer exactly as it did before the cube tier.
// usage: node insight_view_golden.js PAGE.js REPORT.json (write|check) GOLDEN.json
const fs = require("fs");
const [, , pagejs, reportjson, mode, golden] = process.argv;
const R = JSON.parse(fs.readFileSync(reportjson, "utf8"));
const src = fs.readFileSync(pagejs, "utf8");
const a = src.indexOf("(MODEL-BEGIN)"), b = src.indexOf("(MODEL-END)");
const block = src.slice(src.lastIndexOf("/*", a), src.indexOf("*/", b) + 2);
const get = (o, p) => p.split(".").reduce((x, k) => (x == null ? undefined : x[k]), o);
const L = p => { const v = get(R, p); return Array.isArray(v) ? v : []; };
const N = p => { const v = get(R, p); return typeof v === "number" ? v : undefined; };
const sum = (arr, f) => arr.reduce((s, x) => s + f(x), 0);
const TOTAL = get(R, "source.row_count");
const api = new Function("R", "get", "L", "N", "sum", "TOTAL", block + "; return {M, DIMS, DIM_KEYS, BOOL, TERMS_ALL, profile, QLADDER, setMinWords};")(R, get, L, N, sum, TOTAL);
const { M, DIMS, DIM_KEYS, BOOL, TERMS_ALL, profile, QLADDER, setMinWords } = api;

const steps = [];
DIM_KEYS.forEach(k => DIMS[k].values.slice(0, 4).forEach(v => { steps.push({ t: "d", dim: k, mode: "i", vals: [v.v] }); steps.push({ t: "d", dim: k, mode: "o", vals: [v.v] }); }));
M.yearKeys.forEach(y => steps.push({ t: "y", vals: [y] }));
BOOL.forEach((_, id) => { steps.push({ t: "g", f: id, neg: false }); steps.push({ t: "g", f: id, neg: true }); });
TERMS_ALL.slice(0, 6).forEach(t => steps.push({ t: "x", src: t.src, term: t.term, neg: false }));
let seed = 7; const rnd = () => (seed = (seed * 48271) % 2147483647) / 2147483647;
const chains = [];
for (let i = 0; i < 500; i++) { const c = [], len = 1 + Math.floor(rnd() * 5); for (let j = 0; j < len; j++) c.push(steps[Math.floor(rnd() * steps.length)]); chains.push(c); }

const out = [];
QLADDER.forEach(nw => {
  setMinWords(nw);
  chains.forEach(c => {
    const p = profile(c);
    out.push({ nw, n: [p.n.lo, p.n.est, p.n.hi], grade: p.grade, q: p.q ? [p.q.p, p.q.r, p.q.kept, p.q.exact, p.q.known] : null, fields: p.fields });
  });
});
if (mode === "write") { fs.writeFileSync(golden, JSON.stringify(out)); console.log("GOLDEN-WRITTEN " + out.length); process.exit(0); }
const want = JSON.parse(fs.readFileSync(golden, "utf8"));
const close = (x, y) => (typeof x === "number" && typeof y === "number" ? Math.abs(x - y) <= 1e-9 * Math.max(1, Math.abs(y)) : x === y);
const same = (x, y) => (Array.isArray(x) && Array.isArray(y) ? x.length === y.length && x.every((v, i) => same(v, y[i]))
  : x && y && typeof x === "object" ? Object.keys(y).every(k => same(x[k], y[k])) && Object.keys(x).length === Object.keys(y).length : close(x, y));
const bad = [];
if (want.length !== out.length) bad.push("count " + out.length + " vs " + want.length);
out.forEach((o, i) => { if (!same(o, want[i])) bad.push(i + " " + JSON.stringify(o) + " != " + JSON.stringify(want[i])); });
if (bad.length) { console.log("GOLDEN-DIFF " + bad.length + "\n" + bad.slice(0, 5).join("\n")); process.exit(1); }
console.log("GOLDEN-OK " + out.length);
```

- [ ] **Step 2: The frozen report.** Build it in memory from the stand-in's planned rows, with no export file:

```bash
mkdir -p tests/integration/data
../../.venv/bin/python - <<'EOF'
import json, re, sys
sys.path.insert(0, ".")
from insight import report, view
from tests import insight_standin as standin
rows = [{c: str(v) for c, v in standin._csv_row(r).items()} for r in standin.planned_rows()]
src = {"filename": "export" + chr(46) + "csv", "sha256": "0" * 64, "bytes": 1, "row_count": len(rows)}
prov = {"code_commit": "abc1234", "image_digest": "sha256:" + "a" * 64}
built = report.build(rows, source=src, provenance=prov, k=standin.K_TEST, cube_budget=0)
del built["quality"]["cube"]
open("tests/integration/data/insight_report_nocube.json", "w").write(json.dumps(built, sort_keys=True, ensure_ascii=False))
open("/tmp/page_nocube.js", "w").write(re.search(r"<script>\n(.*?)</script>\n</body>", view.render(built), re.S).group(1))
EOF
node tests/integration/insight_view_golden.js /tmp/page_nocube.js tests/integration/data/insight_report_nocube.json write tests/integration/data/insight_view_golden.json
```
Expected: `GOLDEN-WRITTEN 2000`.

- [ ] **Step 3: The test.**
  - The view fixture must not run the slow measurement, and the truth test (Task 3) needs the rows. With the **Edit tool**, change the `built` fixture of `tests/integration/test_insight_view.py` into these two fixtures (the `standin.build(...)` line keeps its existing argument):

```python
@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    return extract.read_rows(standin.build(tmp_path_factory.mktemp("view") / <the existing file name>))


@pytest.fixture(scope="module")
def built(rows):
    return report.build(
        rows,
        source=SOURCE,
        provenance=PROVENANCE,
        k=standin.K_TEST,
        serial_prefixes=False,
        cube_budget=0,
    )
```

  - Append the helpers and the golden test, which are the first part of the block below. The truth test lands in Task 3:

```python
DATA = Path(__file__).with_name("data")


def page_script(report_dict, tmp_path, name="page.js"):
    script = re.search(r"<script>\n(.*?)</script>\n</body>", view.render(report_dict), re.S).group(
        1
    )
    (tmp_path / name).write_text(script, encoding="utf-8")
    return tmp_path / name


def node(harness, *args):
    done = subprocess.run(
        ["node", str(Path(__file__).with_name(harness)), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return done.returncode, done.stdout + done.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_without_a_cube_the_model_answers_exactly_as_before(tmp_path):
    """The golden answers were written by the model before it knew about the cube (spec 2026-10-16,
    section 2: a report without a cube keeps today's behaviour). The report is a frozen stand-in
    report with its cube removed, so only a change to the model can move these numbers."""
    frozen = json.loads((DATA / "insight_report_nocube.json").read_text(encoding="utf-8"))
    code, out = node(
        "insight_view_golden.js",
        page_script(frozen, tmp_path),
        DATA / "insight_report_nocube.json",
        "check",
        DATA / "insight_view_golden.json",
    )
    assert code == 0 and "GOLDEN-OK" in out, out
```

- [ ] **Step 4: Run.** `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py` → all pass, including `test_without_a_cube_the_model_answers_exactly_as_before`.
- [ ] **Step 5: Mutation check (do not commit).** Change `const clamp01 = v => Math.max(0, Math.min(1, v));` in `view_model.js` to `Math.min(0.99, v)` → the golden test FAILS. Revert.
- [ ] **Step 6: Commit** `test(view): a golden snapshot of the corpus model's answers, written before the cube tier`.

---

### Task 3: The cube tier

**Files:** Modify `insight/view_model.js`; create `tests/integration/insight_view_truth.js`; modify `tests/integration/test_insight_view.py`.

- [ ] **Step 1: The truth harness and test (red first).** Create `tests/integration/insight_view_truth.js`:

```javascript
// Checks the corpus model against the true counts of the stand-in's tickets: an exact answer must be the
// truth, any other answer's range must hold it, and the cube must make most pure-cube paths exact.
// usage: node insight_view_truth.js PAGE.js REPORT.json TRUTH.json
const fs = require("fs");
const [, , pagejs, reportjson, truthjson] = process.argv;
const R = JSON.parse(fs.readFileSync(reportjson, "utf8"));
const src = fs.readFileSync(pagejs, "utf8");
const a = src.indexOf("(MODEL-BEGIN)"), b = src.indexOf("(MODEL-END)");
const block = src.slice(src.lastIndexOf("/*", a), src.indexOf("*/", b) + 2);
const get = (o, p) => p.split(".").reduce((x, k) => (x == null ? undefined : x[k]), o);
const L = p => { const v = get(R, p); return Array.isArray(v) ? v : []; };
const N = p => { const v = get(R, p); return typeof v === "number" ? v : undefined; };
const sum = (arr, f) => arr.reduce((s, x) => s + f(x), 0);
const TOTAL = get(R, "source.row_count");
const { profile, setMinWords, CUBE } = new Function("R", "get", "L", "N", "sum", "TOTAL", block + "; return {profile, setMinWords, CUBE};")(R, get, L, N, sum, TOTAL);
const truth = JSON.parse(fs.readFileSync(truthjson, "utf8"));
if (!CUBE) { console.log("FAIL the report has no cube"); process.exit(1); }
setMinWords(truth.min_words);
const bad = [], tally = { exact: 0, bounded: 0, estimated: 0, pureExact: 0, pure: 0 };
/* Counts are whole tickets. The model's year and field figures come from fill SHARES the report rounds to
   four decimals, so an answer can sit a few hundredths off a whole number: half a ticket is the tolerance. */
const eps = 0.5;
truth.paths.forEach(({ steps, n, r, pure }) => {
  const p = profile(steps), tag = JSON.stringify(steps);
  tally[p.grade] = (tally[p.grade] || 0) + 1;
  if (pure) { tally.pure += 1; if (p.grade === "exact") tally.pureExact += 1; }
  if (p.grade === "exact") {
    if (Math.abs(p.n.est - n) >= eps) bad.push("exact count " + p.n.est + " != " + n + " " + tag);
    if (p.q && p.q.exact && Math.abs(p.q.r - r) >= eps) bad.push("exact usable " + p.q.r + " != " + r + " " + tag);
  }
  if (n < p.n.lo - eps || n > p.n.hi + eps) bad.push("count " + n + " outside " + p.n.lo + ".." + p.n.hi + " (" + p.grade + ") " + tag);
  if (p.q && (r < p.q.rlo - eps || r > p.q.rhi + eps)) bad.push("usable " + r + " outside " + p.q.rlo + ".." + p.q.rhi + " (" + p.grade + ") " + tag);
});
if (tally.pure && tally.pureExact / tally.pure < 0.3) bad.push("only " + tally.pureExact + " of " + tally.pure + " pure-cube paths are exact");
console.log(JSON.stringify(tally));
if (bad.length) { console.log("TRUTH-FAIL " + bad.length + "\n" + bad.slice(0, 8).join("\n")); process.exit(1); }
console.log("TRUTH-OK " + truth.paths.length);
```

Append to `tests/integration/test_insight_view.py`:

```python
def _truth_paths(report_dict, tickets, count=400, seed=3):
    """Random paths of cube steps (and a year step in a fifth of them), with the true number of
    tickets and of usable tickets each one keeps, counted from the tickets themselves."""
    graded = quality.grades(tickets, standin.K_TEST)
    words = report_dict["quality"]["default_min_words"]
    values = {
        "cat": [e["value"] for e in report_dict["dimensions"]["categoryId"]["values"]],
        "model": [e["model"] for e in report_dict["origin"]["vehicles"]["models"]],
        "baug": [e["value"] for e in report_dict["origin"]["baugruppe"]["top"]],
    }
    years = sorted({t.created_year for t in tickets if t.created_year})
    gates = ("fehlercode", "description", "serial", "model_id", "baugruppe")
    has = {
        "cat": lambda t, v: t.category == v,
        "model": lambda t, v: t.model == v,
        "baug": lambda t, v: v in t.baugruppe,
    }
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        steps, tests = [], []
        for _ in range(rng.randint(1, 3)):
            kind = rng.choice(["cat", "model", "baug", "gate", "gate"])
            if kind == "gate":
                f, neg = rng.choice(gates), rng.random() < 0.4
                steps.append({"t": "g", "f": f, "neg": neg})
                tests.append(lambda t, f=f, neg=neg: quality.FIELDS[f](t) != neg)
            else:
                v, mode = rng.choice(values[kind]), rng.choice("io")
                steps.append({"t": "d", "dim": kind, "mode": mode, "vals": [v]})
                tests.append(lambda t, k=kind, v=v, m=mode: has[k](t, v) == (m == "i"))
        pure = rng.random() >= 0.2
        if not pure:
            y = rng.choice(years)
            steps.append({"t": "y", "vals": [y]})
            tests.append(lambda t, y=y: t.created_year == y)
        kept = [g for t, g in zip(tickets, graded, strict=True) if all(test(t) for test in tests)]
        usable = sum(1 for g in kept if g.retrievable(words))
        out.append({"steps": steps, "n": len(kept), "r": usable, "pure": pure})
    return {"min_words": words, "paths": out}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_model_with_a_cube_agrees_with_the_true_counts(built, rows, tmp_path):
    truth = _truth_paths(built, extract.tickets(rows))
    (tmp_path / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    code, out = node(
        "insight_view_truth.js",
        page_script(built, tmp_path),
        write(tmp_path, built),
        tmp_path / "truth.json",
    )
    assert code == 0 and "TRUTH-OK" in out, out
```

Also add `import random` to the imports and `quality` to `from insight import extract, quality, report, view`. The truth test uses both.

- [ ] **Step 2: Run it.** `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py -k true_counts` → FAIL. The harness stops with `ReferenceError: CUBE is not defined`, because the model has no cube tier yet.

- [ ] **Step 3: The cube lookup.** In `insight/view_model.js`, insert directly before `/* ---------- (MODEL-END) ---------- */`:

```javascript
/* ---------- the joint quality cube (spec 2026-10-16, stage 2) ----------
   The report's quality.cube holds every combination of up to three of category, Baugruppe, model and a
   gate pattern (error code, description, serial present), each cell floored at k. The steps of a path
   that are cube axes (category, model, Baugruppe, those three gates, "has a model id", "names a
   Baugruppe") are answered from the one cut that holds exactly those axes: exact when every matching
   cell was released (or the cut withheld nothing), otherwise a guaranteed range. Every other step keeps
   the independence estimate, applied as a correction: new = old(path) * cube(part) / old(part).
   Grades: "exact", "bounded" (a range from withheld cells, no independence assumption) or "estimated".
   A report without a cube gets none of this: the model answers exactly as it did before. */
const AXES = ["cat", "baug", "model", "gates"], GATE_BIT = { fehlercode: 0, description: 1, serial: 2 };
const CUBE = (() => {
  const c = Q && Q.cube;
  if (!c || !Array.isArray(c.cuts)) return null;
  const cuts = new Map();
  c.cuts.forEach(cut => {
    const axes = String(cut.axes).split("+"), w = cut.withheld || {};
    const hidden = ((w.below_floor || {}).rows || 0) + ((w.entity_like || {}).rows || 0);
    cuts.set(cut.axes, { axes, hidden, cells: new Map((cut.cells || []).map(g => [axes.map(a => String(g[a])).join("|"), g])) });
  });
  const released = s => (((Q.by_dimension || {})[s] || {}).values || []).map(e => String(e.value)).concat(["_other", "_none"]);
  const U = { cat: released("categoryId"), baug: released("baugruppe"), model: released("model_id"), gates: [] };
  for (let i = 0; i < 8; i++) U.gates.push([4, 2, 1].map(b => (i & b ? "1" : "0")).join(""));
  return { cuts, U, k: Math.max(1, N("provenance.min_frequency") || 1) };
})();
const CUBE_DIMS = new Set(["cat", "model", "baug"]), CUBE_GATES = new Set(["fehlercode", "description", "serial", "model_id", "baugruppe"]);
const cubeStep = s => (s.t === "c" || (s.t === "d" && CUBE_DIMS.has(s.dim)) || (s.t === "g" && CUBE_GATES.has(s.f)));
/* the scope's cube constraints, per axis a set of axis values; null when the scope is not a cube question */
function cubeCon(sc) {
  const con = {}, toAxis = (k, vals) => {
    const out = new Set();
    for (const v of vals) {
      if (v === "__rest") { const named = new Set(DIMS[k].values.map(x => x.v)); CUBE.U[k].forEach(a => { if (!named.has(a)) out.add(a); }); }
      else if (CUBE.U[k].includes(v)) out.add(v); else return null;
    }
    return out;
  };
  for (const k of ["cat", "model"]) if (sc.dims[k]) { con[k] = toAxis(k, [...sc.dims[k]]); if (!con[k]) return null; }
  let pats = CUBE.U.gates;
  for (const g of sc.gates) {
    if (g.id in GATE_BIT) pats = pats.filter(p => (p[GATE_BIT[g.id]] === "1") !== g.neg);
    else if (g.id === "model_id") { const m = con.model || new Set(CUBE.U.model); con.model = new Set([...m].filter(v => (v === "_none") === g.neg)); }
  }
  if (pats.length < CUBE.U.gates.length) con.gates = new Set(pats);
  const inc = [], exc = new Set();
  for (const m of sc.multis) {
    if (m.key !== "baug") continue;
    const vals = toAxis("baug", m.vals); if (!vals) return null;
    if (m.neg) vals.forEach(v => exc.add(v)); else inc.push(vals);
  }
  const bg = sc.gates.find(g => g.id === "baugruppe");
  if (bg) { if (bg.neg) inc.push(new Set(["_none"])); else exc.add("_none"); }
  if (inc.length > 1 || (inc.length && exc.size)) return null;
  if (inc.length) con.baug = { inc: inc[0] }; else if (exc.size) con.baug = { exc };
  return con;
}
/* an interval vector: lo and hi per component (tickets, usable at N, noise, field fills) */
const ivZero = () => ({ lo: Object.fromEntries(QK.map(k => [k, 0])), hi: Object.fromEntries(QK.map(k => [k, 0])) });
const ivOf = v => ({ lo: { ...v }, hi: { ...v } });
const ivAdd = (a, b) => ({ lo: Object.fromEntries(QK.map(k => [k, a.lo[k] + b.lo[k]])), hi: Object.fromEntries(QK.map(k => [k, a.hi[k] + b.hi[k]])) });
/* the sum over every combination of the given axis-value sets in one cut; a missing combination is empty
   when the cut withheld nothing, otherwise anything below k, and all of them together at most what the
   cut withheld */
function cutSum(axes, sets) {
  if (!axes.length) return ivOf(qv(Q.overall));
  const cut = CUBE.cuts.get(axes.join("+")); if (!cut) return null;
  let iv = ivZero(), missing = 0;
  const walk = (i, key) => {
    if (i === axes.length) { const g = cut.cells.get(key.join("|")); if (g) iv = ivAdd(iv, ivOf(qv(g))); else missing += 1; return; }
    sets[i].forEach(v => walk(i + 1, key.concat(v)));
  };
  walk(0, []);
  const slack = Math.min(missing * (CUBE.k - 1), cut.hidden);
  if (slack > 0) QK.forEach(k => { iv.hi[k] += slack; });
  return iv;
}
/* the cube's answer for a set of constraints, or null when no cut holds them (four axes) */
function cubeAnswer(con) {
  const plain = AXES.filter(a => a !== "baug" && con[a]), sets = a => [...con[a]];
  if (!con.baug) return plain.length ? cutSum(plain, plain.map(sets)) : null;
  const axes = AXES.filter(a => con[a]); if (axes.length > 3) return null;
  const withB = v => cutSum(axes, axes.map(a => (a === "baug" ? [v] : sets(a))));
  if (con.baug.inc) {
    const parts = [...con.baug.inc].map(withB); if (parts.some(p => !p)) return null;
    if (parts.length === 1) return parts[0];
    /* a ticket can carry several Baugruppen: the union is at least the largest part and at most their sum */
    const cap = cutSum(plain, plain.map(sets)), lo = {}, hi = {};
    QK.forEach(k => { lo[k] = Math.max(...parts.map(p => p.lo[k])); hi[k] = Math.min(sum(parts, p => p.hi[k]), cap ? cap.hi[k] : Infinity); });
    return { lo, hi };
  }
  const all = cutSum(plain, plain.map(sets)), gone = [...con.baug.exc].map(withB); if (!all || gone.some(p => !p)) return null;
  const lo = {}, hi = {};
  QK.forEach(k => { lo[k] = Math.max(0, all.lo[k] - sum(gone, p => p.hi[k])); hi[k] = Math.max(lo[k], all.hi[k] - Math.max(0, ...gone.map(p => p.lo[k]))); });
  return { lo, hi };
}
const RANK = { low: true };
function setRank(low) { RANK.low = !!low; }
/* what verdicts and suggestions rank on: the worst case while there is a cube, the estimate otherwise */
function rankOf(pr) {
  const low = CUBE && RANK.low;
  const n = low ? pr.n.lo : pr.n.est, r = pr.q ? (low ? pr.q.rlo : pr.q.r) : 0;
  return { n, r, p: n > 0 ? r / n : 0 };
}
```

- [ ] **Step 4: Wire it into `profile`.** Replace everything from `const PCACHE = new Map();` up to (not including) `const clone = s => JSON.parse(JSON.stringify(s));` with:

```javascript
const PCACHE = new Map();
function profile(steps) {
  const key = JSON.stringify(steps) + "|" + QSET.n;
  if (PCACHE.has(key)) return PCACHE.get(key);
  if (PCACHE.size > 100000) PCACHE.clear();
  /* a cached entry outlives the tree's step objects, which are edited in place: it keeps its own copy */
  const own = JSON.parse(JSON.stringify(steps)), sc = scopeOf(own), ev = evalScope(sc), fields = {}, known = {};
  const qq = Q ? (sc.empty ? qEmpty() : qOf(sc)) : null;
  GATES.forEach(([f]) => {
    const g = sc.gates.find(x => x.id === f);
    if (qq && QF.includes(f) && !g) { fields[f] = qq.f[f]; known[f] = qq.known; return; }
    fields[f] = g ? (g.neg ? 0 : 1) : (ev.sz.est > 0 ? filledOf(f, sc, ev.sz, false).p : 0);
    known[f] = !!g || (!sc.C && !sc.Y) || (!!sc.Y && f !== "boiler") || (!!sc.C && (f === "solutions" || f === "description"));
  });
  const cb = CUBE && !sc.empty ? cubeOf(own, sc, ev, qq) : null;
  if (cb) {
    const out = { n: cb.n, grade: cb.grade, fields: { ...fields, ...cb.fields }, known, sc, q: cb.q, steps: own, guessed: cb.guessed };
    PCACHE.set(key, out); return out;
  }
  const n = { ...ev.n };
  const upPr = steps.length ? profile(steps.slice(0, -1)) : null;
  if (upPr) { const up = upPr.n; n.hi = Math.min(n.hi, up.hi); n.est = Math.max(Math.min(n.lo, n.hi), Math.min(n.est, up.est, n.hi)); n.lo = Math.min(n.lo, n.est); }
  let q = null;
  if (qq) {
    /* a step can only remove usable tickets, so the estimate never rises above the step before */
    const r = Math.min(n.est * qq.p, upPr && upPr.q ? upPr.q.r : Infinity), all = qRootR();
    q = { p: n.est > 0 ? r / n.est : 0, r, kept: all > 0 ? Math.min(1, r / all) : 0, exact: qq.exact && n.hi - n.lo < 0.5, known: qq.known };
  }
  const grade = n.hi - n.lo < 0.5 ? "exact" : CUBE ? "estimated" : "estimate";
  if (q && CUBE) {
    if (q.exact) { q.rlo = q.r; q.rhi = q.r; }
    else { q.rlo = Math.max(0, qRootR() - (TOTAL - n.lo)); q.rhi = Math.max(q.rlo, Math.min(n.hi, qRootR())); }
  }
  const out = { n, grade, fields, known, sc, q, steps: own, guessed: CUBE ? own.filter(s => !cubeStep(s)) : [] };
  PCACHE.set(key, out); return out;
}
/* a path with cube steps: the cube answers its cube part, the old model corrects for the rest */
function cubeOf(own, sc, ev, qq) {
  const part = own.filter(cubeStep), rest = own.filter(s => !cubeStep(s));
  if (!part.length) return null;
  /* the quality section already answers some paths exactly (a category by year): keep that answer */
  if (ev.n.hi - ev.n.lo < 0.5 && (!qq || qq.exact)) return null;
  const scS = scopeOf(part); if (scS.empty) return null;
  const con = cubeCon(scS); if (!con) return null;
  const iv = cubeAnswer(con); if (!iv) return null;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v)), all = qRootR();
  /* the step above holds every ticket this path holds, and the old model's range is guaranteed too */
  const up = own.length > 1 ? profile(own.slice(0, -1)) : null, cap = Math.min(ev.n.hi, up ? up.n.hi : Infinity);
  const evS = evalScope(scS), cl = Math.max(iv.lo.n, ev.n.lo), ch = Math.max(cl, Math.min(iv.hi.n, cap));
  const cEst = ch - cl < 0.5 ? cl : clamp(evS.n.est, cl, ch);
  let n, grade, rlo, rhi, rEst;
  const rcap = Math.min(ch, up && up.q && up.q.rhi !== undefined ? up.q.rhi : Infinity);
  const rl = Math.min(iv.lo.r, ch), rh = Math.max(rl, Math.min(iv.hi.r, rcap)), cR = rh - rl < 0.5 ? rl : clamp(cEst * (qq ? qOf(scS).p : 0), rl, rh);
  if (!rest.length) {
    n = { lo: cl, est: cEst, hi: ch }; grade = ch - cl < 0.5 ? "exact" : "bounded";
    rlo = rl; rhi = rh; rEst = cR;
  } else {
    /* the rest keeps the independence estimate: swap the old guess for the cube's part by its true value */
    const restLo = evalScope(scopeOf(rest)).n.lo, ratio = evS.n.est > 0 ? ev.n.est / evS.n.est : 0;
    const lo = Math.max(ev.n.lo, cl + restLo - TOTAL, 0), hi = Math.max(lo, Math.min(ev.n.hi, ch));
    n = { lo, est: clamp(cEst * ratio, lo, hi), hi }; grade = hi - lo < 0.5 ? "exact" : "estimated";
    const qS = qq ? qOf(scS) : null, cP = cEst > 0 ? cR / cEst : 0;
    const p = qq && qS && qS.p > 0 ? clamp(qq.p * cP / qS.p, 0, 1) : cP;
    rlo = Math.max(0, rl + restLo - TOTAL); rhi = Math.max(rlo, Math.min(rh, hi)); rEst = clamp(n.est * p, rlo, rhi);
    /* an estimate never rises above the step before, as in the model without a cube */
    if (up && grade !== "exact") {
      n.est = Math.max(n.lo, Math.min(n.est, up.n.est));
      if (up.q) rEst = Math.max(rlo, Math.min(rEst, up.q.r));
    }
  }
  rlo = Math.max(rlo, all - (TOTAL - n.lo), 0);
  const fields = {};
  if (qq) QF.forEach(f => { const cf = cEst > 0 ? clamp((iv.lo[f] + iv.hi[f]) / 2 / cEst, 0, 1) : 0; const qS = rest.length ? qOf(scS) : null; fields[f] = rest.length && qS && qS.f[f] > 0 ? clamp(qq.f[f] * cf / qS.f[f], 0, 1) : cf; });
  sc.gates.forEach(g => { fields[g.id] = g.neg ? 0 : 1; });
  const q = qq ? { p: n.est > 0 ? rEst / n.est : 0, r: rEst, rlo, rhi, kept: all > 0 ? Math.min(1, rEst / all) : 0, exact: grade === "exact" && rhi - rlo < 0.5, known: !rest.length || qq.known, grade: grade === "exact" && rhi - rlo >= 0.5 ? "bounded" : grade } : null;
  return { n, grade, fields, q, guessed: rest };
}
```

- [ ] **Step 5: Run everything that guards the model:**
  - `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py` → all pass, including:
    - golden: no cube, no change
    - truth: the harness prints a tally such as `{"exact":228,"bounded":102,"estimated":70,"pureExact":198,"pure":321}`
    - the model guarantees: steps never add tickets, and ranges hold their estimate
  - Also run the model harness against the real report (counts only):

```bash
../../.venv/bin/python -c "
import json, re, sys; sys.path.insert(0, '.')
from insight import view
r = json.load(open('local/artifacts/report.json'))
open('/tmp/page_real.js', 'w').write(re.search(r'<script>\n(.*?)</script>\n</body>', view.render(r), re.S).group(1))"
node tests/integration/insight_view_model.js /tmp/page_real.js local/artifacts/report.json | tail -1
```
Expected: `MODEL-OK`.

- [ ] **Step 6: Mutation check (do not commit).** In `cutSum`, replace `if (slack > 0) QK.forEach(k => { iv.hi[k] += slack; });` with nothing → the truth test FAILS (a withheld cell's tickets fall outside the range). Revert.
- [ ] **Step 7: Commit** `feat(view): the corpus model answers cube steps from the quality cube - exact, bounded or estimated`.

---

### Task 4: Show what is known

**Files:** Modify `insight/view.py`.

- [ ] **Step 1: The helpers.** After `const approx = (n, exactly) => (exactly ? "" : "≈ ") + fmt(Math.round(n));` add:

```javascript
/* a profile's ticket count as far as it is known: exact, a guaranteed range from the cube's withheld
   cells ("bounded"), or an estimate. Without a cube this is approx() exactly. */
const amount = pr => (pr.grade === "bounded" ? fmt(Math.round(pr.n.lo)) + "–" + fmt(Math.round(pr.n.hi)) : approx(pr.n.est, pr.grade === "exact"));
/* the steps of an estimated count, for the tooltip on it */
const guessNote = pr => (pr.grade !== "exact" && pr.grade !== "bounded" && pr.guessed && pr.guessed.length ? "Estimated: the report has no joint split for " + pr.guessed.map(stepLabel).join(", ") + "." : "");
```

- [ ] **Step 2: Use it everywhere a profile's count is shown.** Make each replacement once, *after* the helpers exist, and do not touch `amount`'s own body:

| replace | with |
|---|---|
| `t.append(tile("Tickets", approx(pr.n.est, ex),` | `t.append(tile("Tickets", amount(pr),` |
| `hover(bar, () => [[approx(pr.n.est, ex) + " tickets", pathText(id)]` | `hover(bar, () => [[amount(pr) + " tickets", pathText(id)]` |
| `const n1 = $("div", "tn n1"); n1.append($("b", "", approx(pr.n.est, ex)), $("span", "", pct(pr.n.est / TOTAL, 0) + " of all"));` | `const n1 = $("div", "tn n1"), nb = $("b", guessNote(pr) ? "guess" : "", amount(pr)); if (guessNote(pr)) nb.title = guessNote(pr); n1.append(nb, $("span", "", pct(pr.n.est / TOTAL, 0) + " of all"));` |
| `" Tickets: " + approx(par.n.est, par.grade === "exact") + " → " + approx(pr.n.est, pr.grade === "exact") + "."` | `" Tickets: " + amount(par) + " → " + amount(pr) + "."` |
| `$("span", "gn", approx(r.pr.n.est, r.pr.grade === "exact"))` | `$("span", "gn", amount(r.pr))` |
| each remaining `approx(pr.n.est, pr.grade === "exact")` (scatter tip, copy-as-text, scenario table: 3 places) | `amount(pr)` |
| `const left = metric("tickets left", approx(pr.n.est, ex),` | `const left = metric("tickets left", amount(pr),` |
| `tip: [[approx(pr.n.est, ex) + " of " + fmt(TOTAL)` | `tip: [[amount(pr) + " of " + fmt(TOTAL)` |
| `b.append($("small", "", approx(nx.n.est, nx.grade === "exact") + " left"));` | `b.append($("small", "", amount(nx) + " left"));` |

Afterwards `grep -c "approx(" insight/view.py` must print `1`, the call inside `amount`.

- [ ] **Step 3: Style and note.**
  - After the `.pactive2 .plab{...}` rule, add `.guess{text-decoration:underline dotted;text-underline-offset:3px;cursor:help}`.
  - In `labIntro()`'s `body`, replace `w.append(row); return w;` with:

```javascript
      w.append(row);
      if (CUBE) w.append($("p", "note", "This report has a quality cube: a count is exact where the cube holds the path's split, shown as a range (from–to) where some of its cells were too small to release, and marked ≈ where a step has no joint split. Verdicts and suggestions rank on the worst case unless you switch to the estimate."));
      else if (Q) w.append($("p", "note", "Exact branch numbers need a report with a quality cube; this one has none, so counts after several steps are estimates."));
      return w;
```

- [ ] **Step 4: Run** `../../.venv/bin/python -m pytest -q tests/integration/test_insight_view.py`, plus the smoke harness on the real report (`node tests/integration/insight_view_smoke.js /tmp/page_real.js local/artifacts/report.json` after re-rendering `/tmp/page_real.js` as in Task 3) → all pass / `SMOKE-OK`.
- [ ] **Step 5: Commit** `feat(view): counts show what is known - exact, a from-to range, or ≈ with the estimated steps named`.

---

### Task 5: Rank on the worst case

**Files:** Modify `insight/view.py`.

- [ ] **Step 1: Verdicts.** In `verdictQ`, replace its first three lines (`const dq = …`, `const keep = …`, `const junk0 = …,`) with the lines below. Keep the rest of the `junk0` line (`gone = …`) as it is:

```javascript
  /* ranked as rankOf says: the worst case while the report has a cube, the estimate otherwise */
  const B = rankOf(par), P = rankOf(pr);
  const dq = (P.p - B.p) * 100, a = Math.abs(dq).toFixed(0), lost = B.n ? 1 - P.n / B.n : 0;
  const keep = B.r > 0 ? Math.min(1, P.r / B.r) : 1, k = pct(keep, 0);
  const junk0 = B.n - B.r, junk1 = P.n - P.r,
```

- [ ] **Step 2: Suggestions.** In `suggest`, replace the `const out = cands.map(...)` statement and its `.filter(...).sort(...).slice(0, 8);` line with:

```javascript
  /* a step is offered when its estimate helps, and the list is ordered on what rankOf says (the worst case
     while there is a cube): an uncertain gain is still shown, after the certain ones */
  const B = rankOf(base), gainOf = (b, p, bq, pq) => { const keep = b.n ? p.n / b.n : 0, lose = pq && bq ? 1 - (b.r > 0 ? Math.min(1, p.r / b.r) : 1) : 1 - keep, from = bq ? b.p : qscore(base); return { keep, from, eff: ((pq ? p.p : 0) - from) / Math.max(lose, 0.02) }; };
  const out = cands.map(step => { const p = profile(steps.concat(step)), est = { n: p.n.est, r: p.q ? p.q.r : 0, p: p.q ? p.q.p : 0 }, b0 = { n: base.n.est, r: base.q ? base.q.r : 0, p: base.q ? base.q.p : 0 };
    const e = gainOf(b0, est, base.q, p.q), w = gainOf(B, rankOf(p), base.q, p.q), to = p.q ? p.q.p : qscore(p), from = base.q ? base.q.p : qscore(base);
    return { step, keep: e.keep, from, to, eff: p.q ? e.eff : (to - from) / Math.max(1 - e.keep, 0.02), rank: p.q ? w.eff : (to - from) / Math.max(1 - e.keep, 0.02), n: p.n }; })
    .filter(c => c.keep > 0.05 && c.keep < 0.995 && c.to > c.from + 0.003).sort((a, b) => b.rank - a.rank || b.eff - a.eff).slice(0, 8);
```

- [ ] **Step 3: The toggle.** In `labTree()`'s controls, directly after the `QLADDER.forEach(nw => …);` line, add:

```javascript
        if (CUBE) {
          const rk = $("span", "qdef"); rk.append(document.createTextNode("Rank on:")); rk.title = "Verdicts and suggestions compare paths on their worst case, so a path never wins on a guess. Switch to the estimate to compare point values."; q.append(rk);
          [[true, "worst case"], [false, "estimate"]].forEach(([low, label]) => { const b = $("button"); b.type = "button"; b.setAttribute("aria-pressed", String(RANK.low === low)); b.textContent = label; b.onclick = () => { setRank(low); PAL.sugg.clear(); treeChanged(); }; q.append(b); });
        }
```

- [ ] **Step 4: Keep the choice in the address.**
  - In `writeHash`, after the `qn` line, add `if (CUBE && !RANK.low) p.set("rk", "e");`.
  - In `readHash`, after `if (p.get("qn")) setMinWords(Number(p.get("qn")));`, add `if (p.get("rk") === "e") setRank(false);`.
- [ ] **Step 5: Run** the view tests and the real-report smoke harness (as in Task 4) → all pass, `SMOKE-OK`.
- [ ] **Step 6: Commit** `feat(view): verdicts and suggestions rank on the worst case while there is a cube; a toggle switches to the estimate`.

---

### Task 6: Docs and verification

- [ ] **Spec.** Append amendment **A3** to `docs/superpowers/specs/2026-10-16-insight-filter-tree-v2-design.md`. It records the nine "Decisions taken while prototyping" above, one line each.
- [ ] **STATE.md.** Add a section "Filter tree v2, stage 2 (certainty grades) — BUILT <date> on `feat/filter-tree-grades`" covering:
  - what the view now does
  - the tests that pin it (golden and truth)
  - the real-report check: `MODEL-OK`, `SMOKE-OK`, and these paths exact: drop cat-B and cat-A (exact counts and usable counts checked against the report, figures omitted)
  - next: stage 3
- [ ] **Full suite and lint** (commands under Binding constraints) → `0 failed` apart from the quarantine guard test when `local/quarantine` is not empty; ruff clean.
- [ ] **Commit** `docs: filter tree v2 stage 2 - amendment A3 and STATE`.

---

## Amendments during execution (2026-10-16)

- **Task 2 (`f0f965d`).** The frozen report and the golden JSON under `tests/integration/data/`
  are not committed. `.gitignore` lines 9-12 forbid any data file, real or synthetic. Instead:
  - `tests/integration/insight_view_model_v1.js` keeps the pre-cube model as code.
  - `insight_view_golden.js` runs both models on the same chains.
  - The test builds the report at test time and removes its cube.
- **Task 3 review (`38d1646`).** These fixes have tests that fail on the old code:
  - With no floor in the report, the cube is not used.
  - A cut with entity-like withheld cells allows its whole tally.
  - `__rest` is answered from the cube only while every named value is a cube value.
  - A bounded estimate never rises above the step before.
  - `qOf` runs once per cube answer, and a sentinel-spelled value is listed once.
  - The truth test now runs at every word threshold over 1,500 paths of up to four steps.
- **Task 3, Step 5.** `insight_view_model.js` prints `MODEL-OK` first, so `| tail -1` shows
  another line. Check the first line or the exit code.
- **Task 4, Step 2.** `grep -c "approx("` prints 2. The comment above `amount` mentions `approx()`.
- **Task 5.** `readHash` carries the `rk` line on its own line. The behaviour is the same.
- **Final review (`5eb3657`).**
  - Verdicts are computed on the estimate, and the worst case only withholds a gain ("Uncertain
    gain"). The plan's Task 5 verdict code called every unmeasured step a loss.
  - `rankOf`'s worst-case share is `rlo / n.hi`, and suggestions are ordered on it.
  - A bounded count is worded as guaranteed.
  - Page checks were added (`insight_view_checks.js`). The golden check now compares all of
    `profile()` over a wider step pool, also without a quality section.

