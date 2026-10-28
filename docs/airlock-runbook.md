# Airlock runbook

**The rule.** No AI assistance between "real CSV lands on the box" and "real CSV is
deleted and verified gone". Work the checklist in order and do not improvise. If a
step fails: abort, shred the data, *then* fix the code with AI help.

**The one rule people break.** When a sealed run fails, do not paste its output
anywhere near an AI tool. The profiler prints only codes, schema paths and counts;
verbatim values go to `profiler_detail.log`, which stays on the box. Read that file
yourself, describe the problem in your own words, and shred it.

**What the exit codes mean.** `0` success. `2` safety violation — the selfcheck
refused to write an unsafe artifact; the code and schema path on stdout are safe to
read and usually enough to diagnose. `3` unexpected failure — only the exception
*type* is printed, the traceback is in the detail log. `4` (the insight report only) the
arguments or the input are wrong — refused before anything was written; the code and a count
are printed, never a value.

---

## Phase 0 — before any window (AI assistance fine, no real data present)

Everything that needs a network happens here. The window itself has none.

- [ ] `make guard-install` once per clone, then `tools/guard/airlock status` shows
      "closed". **Open the window yourself, in a normal terminal, when the real CSV lands on
      the box: `tools/guard/airlock open`.** While it is open the guard denies every AI tool
      call in this repo. Close it only after the real CSV is deleted and verified gone:
      `tools/guard/airlock close`.
- [ ] `make test lint` green on the workstation.
- [ ] `docker build -f infra/profiler/Dockerfile -t recall/profiler:pinned .` — deps
      installed with `uv sync --frozen --no-dev` against the hash-pinned lockfile,
      plus `hunspell` and `hunspell-de-de`. **Never resolve dependencies inside a
      window**: `uv run` reaches the network, and freshly-downloaded third-party code
      would execute in the same process as the real CSV.
- [ ] Verify it runs with no network at all:

      docker run --rm --network=none recall/profiler:pinned \
        python -c "import profiler.__main__; print('offline import ok')"

- [ ] **Verify the German dictionary *inside the image*** — not on the host, which
      does not have it:

      docker run --rm --network=none recall/profiler:pinned \
        hunspell -d de_DE -l </dev/null; echo rc=$?

      → `rc=0`. If it is missing, `hunspell_unrecognized_top` comes back empty, the
      §7 synonym-mining input is lost, and recovering it costs a whole extra cycle.

- [ ] **Rehearse the whole pipeline on a stand-in**, in the image, offline. This is
      what catches profiler bugs before they cost a cycle — it has already caught
      two (a `ZeroDivisionError` in the Zipf estimator, and the entity sweep
      rejecting the project's own model designations):

      python - <<'EOF'
      import pathlib, sys; sys.path.insert(0, 'tests')
      from conftest import build_standin
      build_standin(pathlib.Path('/tmp/rehearsal/export.csv'))
      EOF
      docker run --rm --network=none -v /tmp/rehearsal:/q \
        -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log recall/profiler:pinned \
        python -m profiler --csv /q/export.csv --out /q/profile.json

      → must end `selfcheck_passed=True`, and
      `jq '.vocabulary.hunspell_unrecognized_top | length' /tmp/rehearsal/profile.json`
      must be non-zero.

- [ ] `docker save recall/profiler:pinned | ssh hpc 'podman load'`
- [ ] Repeat the dictionary check *on the box*, since the transfer is where it can
      go wrong:
      `ssh hpc 'podman run --rm --network=none recall/profiler:pinned hunspell -d de_DE -l </dev/null; echo rc=$?'`
      → `rc=0`.
- [ ] `ssh hpc 'mkdir -p <data-dir>/recall-quarantine && chmod 700 <data-dir>/recall-quarantine'`
      **Note the per-user component: `<data-dir>` is `/data/<box-user>`.** `/data` itself is
      root-owned and the account cannot create directories at its root — plain
      `/data/recall-quarantine` fails with Permission denied. `<data-dir>/` is the writable per-user directory, and it
      sits on the 6.3 TB filesystem rather than the 43 GB root. Verified by rehearsing
      the whole chain there under podman before any real data was present.
- [ ] Ship the code without secrets or git history:
      `git archive --format=tar HEAD | ssh hpc 'mkdir -p <data-dir>/recall-work && tar -x -C <data-dir>/recall-work'`
      — **not** `scp -r .`, which ignores `.gitignore` and would carry `.env`.
      Same reason for the path: `/data/recall-work` (outside `<data-dir>`) is not creatable by this account.

## Preflight on the real export — AI assistance still fine

Run this **before** the window. It reads the export's shape and never its content: the
only strings it can print are column names from the published 38-column contract, fixed
literals, and character-class shapes. Its output is safe to paste into an AI tool; the
file is not.

    ./infra/profiler/preflight-export.sh /path/to/the/export.csv

It catches, without a window: renamed or missing columns, a semicolon delimiter (German
Excel exports routinely use one), a latin-1 file that would mangle every umlaut, ragged
rows, and a missing header. Each of those otherwise costs a full cycle to discover.

If line 1 does not recognisably match the contract, the tool assumes it may be a data
row and prints shapes only — it will not echo it.

### Probing a free-form column's syntax

    ./infra/profiler/preflight-export.sh /path/to/the/export.csv --syntax customData

Both run on the **workstation**, not the box, and outside any window. The export is
already on the workstation; the window exists to keep real data off machines that hold an
AI context, and neither mode reads content.

Round 2 found `customData` in nearly all rows and parsed none of it — it is neither JSON nor
`key=value`. The profiler could not show why, because shape discovery matches
`[A-Za-z0-9._/:-]` and so cannot represent `=`, `;`, `{`, `<` or whitespace: we excluded
exactly the characters that identify a syntax.

This prints two content-free views, both floored so nothing appears unless
`--min-frequency` values share it:

- the **punctuation skeleton**, every letter and digit removed. `{":,}` is JSON, `=;` is
  key-value, `<>/` is XML. It cannot carry content because it retains no character that
  could be content.
- a **40-character prefix shape** over the closed alphabet, longer than `SHAPE_MAX`
  because a format declares itself in its first few dozen characters.

Use it to identify the format, teach `profiler/stats/customdata.py::detect_format`, and
re-run the window — rather than spending a sealed window to discover a delimiter.

## Window A — profiling  🔒 AI OFF from here

- [ ] `./infra/fairuse/gpu-fairuse2.sh check` → GO (profiling is CPU-only, but the
      box must not be crowded). **Exit 1 means wait; exit 3 means the box is
      unreachable — investigate connectivity, do not proceed.**
- [ ] `scp export.csv hpc:<data-dir>/recall-quarantine/`
      **Name the file `export.csv`.** `source.filename` is emitted verbatim into
      `profile.json`, so a name like `<client-name>_Tickets_<year>.csv` would put the client's
      name into the artifact an AI later reads.
- [ ] `ssh hpc` then, in one command:

      ulimit -c 0    # no core dumps: a crash must not spill ticket text to disk
      podman run --rm --network=none \
        -v <data-dir>/recall-quarantine:/q \
        -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
        recall/profiler:pinned \
        python -m profiler --csv /q/export.csv --out /q/profile.json

      `--network=none` is the actual guarantee that nothing phones home. The
      monkeypatched-socket unit test is a smoke test; this is the control.

      **Do NOT mount anything over `/work`.** The image already contains the code and
      its virtualenv at `/work/.venv`, and `PATH` points there. Mounting
      <data-dir>/recall-work:/work:ro` over it hides the venv, `python` falls back to the
      base image's interpreter, and the run dies on `ModuleNotFoundError: datasketch`
      before reading a single row. It also defeats the point of a pinned image — you
      would be running unpinned source against pinned dependencies. The `git archive`
      shipped in Phase 0 is for **Window C only**. **Window B does not need it** — the
      leakage gate lives under `profiler/gate/`, which `COPY profiler` bakes into the
      image, and that is precisely why it was put there. (This paragraph said "Windows
      B and C" until 2026-09-14; it was written before the gate existed.)

      **`RECALL_PROFILER_DETAIL_LOG` is not optional.** The default is a path relative
      to the working directory, so without it the verbatim detail log is written inside
      the container and destroyed by `--rm` — leaving a failed sealed run with no
      diagnostic at all, and no AI available to help.
- [ ] Confirm stdout ends with `selfcheck_passed=True`. On `ABORT`, read
      `<data-dir>/recall-quarantine/profiler_detail.log` yourself — do not copy it out. If
      stdout says the detail sink could not be written, the `-e` flag above is missing.
- [ ] Read `profile_report.md` in full, on the box, before copying anything.
- [ ] Sanity-check the two things that silently cost a cycle if wrong. **These run on
      the box, not inside the container**, so use the host path — `/q` only exists
      inside the run above:

      Q=<data-dir>/recall-quarantine
      jq '.vocabulary.hunspell_unrecognized_top | length' $Q/profile.json   # non-zero
      jq '.temporal.age_years_quantiles.max'             $Q/profile.json   # non-zero

      If `jq` is not installed on the box, use the image instead — it needs no network:

      podman run --rm --network=none -v $Q:/q recall/profiler:pinned python -c "
      import json; p=json.load(open('/q/profile.json'))
      print('hunspell:', len(p['vocabulary']['hunspell_unrecognized_top']))
      print('age max :', p['temporal']['age_years_quantiles']['max'])
      print('clusters/singletons:', p['clusters']['cluster_count'], p['clusters']['singleton_count'])
      print('solutions fill_rate:', p['solutions']['fill_rate'])"

      (all-zero ages mean `timestampCreated` is not `YYYY-MM-DD` and
      `profiler/stats/temporal.py` needs its regex widened)
- [ ] `scp hpc:<data-dir>/recall-quarantine/profile.json      ./local/artifacts/`
- [ ] `scp hpc:<data-dir>/recall-quarantine/profile_report.md ./local/artifacts/`
- [ ] `ssh hpc 'shred -u <data-dir>/recall-quarantine/export.csv <data-dir>/recall-quarantine/profiler_detail.log'`
- [ ] `ssh hpc 'ls -la <data-dir>/recall-quarantine'` → only `profile*` remain
- [ ] `make check-clean` on the workstation → quarantine empty.
      **Run it unsandboxed** (a normal terminal). Under the Claude Code sandbox it
      cannot list the denied directory and reports a false `clean`.
- [ ] 🔓 Only now resume AI-assisted work

## Window B — leakage gate (command block written at the start of M2)

Controls that must be in it, decided now:

- The real CSV comes back for this window. **Real-corpus embeddings are not
  retained between windows** — inversion attacks reconstruct substantial portions
  of short texts when the embedding model is public, and ours is, so retained
  vectors are the text in a thin disguise. Paying a second cycle is the cheaper
  trade.
- The shingle intersection and the nearest-neighbour check both run **on the box**,
  against the synthetic corpus shipped in. Only counts and verdicts come out — no
  hash set, no vectors. A hash set of 8-token shingles is a membership oracle and
  does not need to exist off-box.
- Gate report crossing out contains counts, thresholds and pass/fail only.

### Phase 0 additions for Window B — do these BEFORE the window

**`WINDOW_IN` names the export only, so nothing in `window.sh` puts the other two inputs
on the box. Staging all three is yours.** This is the step the rehearsal exists to catch.

- [ ] `make window-b-rehearsal` green on the workstation. It runs the real command in the
      real image with `--network=none`, and its closing block restates these steps.
- [ ] Stage **three** files into quarantine, not one:
      - `synthetic.csv` — **the candidate fixture you are trying to clear**, i.e.
        `local/fixtures/export.csv`, renamed in transit. Note this differs from the
        rehearsal, which uses two `--fake` corpora because it has no real side.
      - `export.csv` — the client's real export, renamed as for Window A.
      - `roster.txt` — the fictional roster. See the caveat on check 4 below before
        reading anything into its contents.
- [ ] The image must be the **CUDA** build (~9.3 GB). The CPU build is ~3.5 GB and would
      run the window on CPU while `window.sh` attached a card — slow, and it looks
      accelerated. `ssh hpc 'podman images | grep recall/profiler'` to confirm.
      A ship takes about an hour at the measured link speed, so do it well before.

## Window B — leakage gate  🔒 AI OFF from here

- [ ] `./infra/fairuse/gpu-fairuse2.sh claim 0` → GO, and note the UUID it prints.
      **`claim` is itself the GO gate** — it exits non-zero when the card is busy. It
      pins by UUID rather than index so the run cannot land on another user's card, and
      it carries the 60 GB cap (e5-large needs ~2.2 GB, far inside it).
- [ ] Drive it with the script, which does the claim, the thread cap and the provenance
      flags for you:

      ./infra/profiler/window.sh --window b run

      Run `--dry-run` first and read the command it prints. It must carry
      `--network=none`, `ulimit -c 0`, `--device nvidia.com/gpu=<uuid>`, a `--cpus` cap,
      the three `/q` inputs, one `/q` output, and both `--code-commit` and
      `--image-digest`. **`--threads` defaults to 32: on this box 32 measured about
      twice as fast as 128, and uncapped takes all 256 and is slower still.**
- [ ] Expect **minutes, not hours**: measured 96 docs/s on an H100 against 4.97 on CPU,
      so the tens of thousands of encode passes land in roughly three and a half minutes.
- [ ] Read `gate_report.json` **on the box** before copying anything. Three fields decide
      whether the verdict means what it appears to:
      - `embedder_is_a_model` must be **true**. False means the hashing stand-in
        produced it and it is **not a leakage verdict** at all.
      - `checks.neighbours.baseline_saturated` must be **false**. True means the bar was
        ~1.0, which nothing can exceed, so a green there is arithmetic without meaning.
      - `checks.roster.values_traced` — **expect 0, and do not read the roster check as
        evidence.** `ROSTER_COLUMN` is `ansprechpartner`, a key inside the `customData`
        envelope rather than one of the 38 columns, so the check examines nothing and
        passes for that reason (finding 13). Three of the four checks are proven; this
        one is not.
- [ ] Only `gate_report.json` crosses out. No shingle set, no vectors — a set of 8-token
      shingles is a membership oracle and must not exist off-box.

      ./infra/profiler/window.sh --window b fetch --clean

- [ ] `ssh hpc 'ls -la <data-dir>/recall-quarantine'` → only
      `gate_report.json` remains. The shred list covers all three staged inputs as of
      2026-09-14 (finding 16); before that the synthetic corpus and roster survived.
- [ ] `make check-clean` on the workstation → quarantine empty.
- [ ] 🔓 Only now resume AI-assisted work.

**If the gate is green and `embedder_is_a_model` is true, the fixture is cleared and may
be committed.** That is the whole reason it has stayed uncommitted.

## Window D — insight report, stage 1  🔒 AI OFF from here

What comes out is `report.json`: where tickets come from (Baugruppe, vehicles, title words, one
Baugruppe × model × year table), model-free evidence about the text, and (v2) identifier formats
as shapes, volume and fill over time, vehicle hours and warranty, the categorical columns,
dealer/customer/user concentration as numbers only, title and solution n-grams, and
RAG-readiness counts. It is built to be
readable by an AI **after** you have read it. Every value in it is floored (at least 50 tickets)
and swept for names, and a separate guard refuses to write the file if anything is unaccounted
for. No model, no GPU. **Serial prefixes are OFF** (operator ruling, 2026-10-12): the report says
how repeat-prone vehicles are, as numbers, and never shows a serial. Aggregates move from the
sealed root to `local/released/` through `tools/guard/export_aggregate.py`, which refuses
anything but numbers.

### Before the window (AI assistance fine, no real data present)

- [ ] `make window-d-rehearsal` → `0 failed`. It builds the image, runs the real sealed container
      offline on a synthetic stand-in, and checks the leaks, the destructive paths and the
      teardown. If your Python needs a virtualenv: `RECALL_REHEARSAL_PYTHON=.venv/bin/python`.
- [ ] **The image changed** (the report is now baked into it), so it must be shipped again:
      `infra/profiler/window.sh ship` — about an hour at the measured 2.5 MB/s. It must print
      `offline import works on the box`, which now imports the report module too.
- [ ] `./infra/profiler/preflight-export.sh /path/to/the/export.csv` (shape only, never content).
- [ ] **Resolve `~/work/<client-dir>/` first.** A real client export must not stay on a machine that
      holds an AI context. Move it to the box or shred it.
- [ ] `make check-clean` → quarantine empty. **Run it unsandboxed**; under the Claude Code
      sandbox it cannot list the denied directory and reports a false `clean`.

### The window

- [ ] Three commands, in this order. **Not `all`:** `all` starts by shipping the image again,
      which is an hour you have already spent.

      infra/profiler/window.sh --window d --csv /path/to/the/export.csv push
      infra/profiler/window.sh --window d run
      infra/profiler/window.sh --window d verify

      `push` copies the export in **as `export.csv`** (the name goes into the artifact), `run`
      checks the box is not crowded and then runs the sealed command, and `verify` is the on-box
      check below. Nothing is copied back until you have read the report. The command `run` uses:

      ulimit -c 0    # no core dumps: a crash must not spill ticket text to disk
      podman run --rm --network=none --cpus 32 \
        -v <data-dir>/recall-quarantine:/q \
        -e RECALL_PROFILER_DETAIL_LOG=/q/profiler_detail.log \
        recall/profiler:pinned \
        python -m insight --csv /q/export.csv --out /q/report.json --min-frequency 50 \
          --cube-budget 1800 --code-commit <sha> --image-digest sha256:<digest>

      **Do NOT mount anything over `/work`**: the report is imported from there.
      `--serial-prefixes` and `--allow-weak-floor` must not appear; if you ever see them in this
      command, stop.

      `run` now also builds the **joint quality cube** and measures it. The measurement is an LP
      estimate of how many withheld cube cells subtraction newly exposes (spec amendment A1);
      `--cube-budget 1800` caps it. On synthetic data of the real shape one LP pass took about
      15 minutes, so expect the run to take up to ~40 minutes longer than before. It prints
      `cube_newly_derivable=N cube_checked=X/Y`, followed by `cube_stopped=budget` or
      `cube_stopped=solver` if it ended early. An early stop leaves the report valid and guarded
      and says so in `quality.cube.measurement`; write the numbers down, none of them stops the
      window.

      **If `run` says "the box is busy"** because the OTHER GPU is in use (the gate checks both,
      although this window uses neither), gate on GPU 0 only. The fair-use script supports it, and
      the host RAM and load limits still apply:

      FAIRUSE_GPUS=0 infra/profiler/window.sh --window d run

      A broken GPU driver on the box (`nvidia-smi` failing) also makes the gate refuse; that is
      the box's problem and the only fix is to wait for it.
- [ ] The run ends `selfcheck_passed=True`, with `columns_expected_missing=0` (or a small number
      you can explain). Exit codes: `0` fine; `2` the guard refused — the code and a schema path
      are safe to read, the value is in `profiler_detail.log` **on the box**; `3` unexpected
      failure — read the detail log yourself; `4` wrong arguments or wrong file.
      - `WRONG_INPUT` means required columns are missing: the wrong file, or a `;` delimiter.
      - `MISSING_INPUT` / `EMPTY_INPUT`: the transfer went wrong.
      - A refused run **leaves no `report.json`** — an old one is removed first, on purpose.
- [ ] The on-box check prints counts only. **`guard passed True`, `min_frequency 50`,
      `serial prefixes False`.** `baugruppe coverage` near **a quarter** is what the earlier profile
      predicts (only a minority of rows carry the field). **`0.0` means no Baugruppe was found in
      `customData`: the window is spent and the fix is in code**, not in this window. The same
      holds for `fehlercode coverage` 0.0. `usable share` 0.0 or `shapes listed` 0 means a
      section came back empty; note it, it does not make the report unsafe.
- [ ] **Read `report.json` in full, on the box:**
      `ssh hpc 'less <data-dir>/recall-quarantine/report.json'`
      This is the control the design rests on. Look for anything that is a person, a dealer, a
      customer, a serial or a phone number. Baugruppe codes, model numbers and German technical
      words are expected; a name is not. In the v2 sections: a `shape` is letters from
      `A L a D _ - . / : #` only, never a real serial or date; a solution `token` is at most three
      words; `concentration` holds numbers only, so any string there is wrong; a first name in
      `vocabulary` means the name list missed it. **If anything identifying is in it, do not fetch:**
      shred (below) and describe the problem in your own words.
- [ ] `infra/profiler/window.sh --window d fetch --clean` — copies back **only** `report.json`
      and shreds the export, the detail log and any partial `report.json.tmp`.
- [ ] `ssh hpc 'ls -la <data-dir>/recall-quarantine'` → only `report.json` remains
      (and anything from other windows you chose to keep).
- [ ] `make check-clean` on the workstation → quarantine empty.
- [ ] 🔓 Only now resume AI-assisted work. Before an AI reads `local/artifacts/report.json`, gate it:

      <the repo's virtualenv python> -c "
      import json; from insight import guard
      r = json.load(open('local/artifacts/report.json'))
      print('unaccounted:', len(guard.unaccounted(r)))"

      Run it from the repository root with the virtualenv's Python (a git worktree has no
      `.venv` of its own: use the main checkout's `.venv/bin/python`). `0` means every key and
      string is accounted for. Non-zero: stop, and print paths only.

### If it fails

Abort, shred (`infra/profiler/window.sh --window d clean`), and only then ask for help. Do not
paste any output of a sealed run that you have not read yourself first; the printed codes and
counts are safe, the detail log is not.

## Window E — catalog extraction (problem catalog from the real export)  🔒 AI OFF from here

**What it is.** A local language model reads clusters of real tickets and drafts one "recipe" per
recurring problem (a cause, a component, a remedy, written in general words). The draft is checked
by machine against the whole export, and **then by you**. What may leave the box is exactly two
files: `catalog.json` (the released recipes) and `catalog.leak_report.json` (the machine check that
vouches for them). The draft, the export and every log stay on the box and are shredded.

**Why a human reads every word.** The machine checks (below) catch names, rare words and copied
sentences. They cannot judge whether a recipe *reads like a particular customer's ticket*. You can.
The catalog is meant to be readable by an AI afterwards, so anything you let through is gone.

### Before the window (AI assistance fine, no real data present)

- [ ] `make window-e-rehearsal` → `0 failed`. It runs the real `window.sh` against a stub model on a
      workstation. It does **not** prove the vLLM image or the GPU (see "First-run things" below).
- [ ] **The image changed** (the catalog code is baked into it), so ship it again:
      `infra/profiler/window.sh --window e ship`. Look for these lines, all `ok`:
      `offline import works on the box` (it now imports the catalog CLI),
      `German dictionary present in the image`,
      `podman can create an internal network on the box`,
      `LLM image present on the box`. If the internal-network line says ABORT, stop: see
      "If it fails". A plain (non-internal) network would give the model server a route out.
- [ ] `RECALL_WINDOW_LLM_IMAGE` is set to the vLLM image **pinned by digest**, e.g.
      `export RECALL_WINDOW_LLM_IMAGE=docker.io/vllm/vllm-openai@sha256:<digest>`. A floating tag
      (`:latest`) is not acceptable: the model server must be the one you checked. The image must
      already be loaded on the box; the window has no network and cannot pull it.
- [ ] `RECALL_WINDOW_HF_CACHE` is set to the directory on the box that holds the model weights
      (`Qwen/Qwen2.5-32B-Instruct-AWQ`, about 20 GB). Weights are not data. The window runs offline,
      so the weights must already be there.
- [ ] Also exported: `RECALL_WINDOW_QUARANTINE=<data-dir>/recall-quarantine` (as for the other windows).
- [ ] GPU: the run claims GPU 0 through `gpu-fairuse2.sh` and pins it by UUID. If it says
      "fairuse refused", the card is busy: **wait**, do not crowd the box. The model is sized to
      stay under the shared 60 GB cap (`--gpu-memory-utilization 0.70`).
- [ ] **The export is on the box:**
      `infra/profiler/window.sh --window e --csv /path/to/the/export.csv push`
      (the preflight prints shape only). `make check-clean` on the workstation afterwards, unsandboxed.
- [ ] Run `infra/profiler/window.sh --window e run --dry-run` and read the script it prints. It must
      show: `podman network create --internal`, **no `-p` or `--publish` anywhere**, the model
      container with `--log-driver=none`, `--no-enable-log-requests`, a weights mount ending
      `:ro` and **no `/q` mount**, `--network=none` on the last container, and neither
      `--allow-weak-floor` nor any floor flag. If any of that is missing, stop.

### The window

- [ ] `infra/profiler/window.sh --window e run`   (`all` does ship + push + run + verify in one go and
      then stops; use it only if you want the image shipped again)

  What the box is doing, so you can tell it is healthy:
  1. It claims the GPU and creates a private network that has **no route out** (`--internal`).
  2. It starts the model server on that network. This container mounts **nothing from quarantine**
     and its logs are discarded, so ticket text reaches it only over the private network and lives
     only in memory.
  3. It polls the model server every 10 seconds, for up to 30 minutes, until it answers. Loading the
     model takes minutes; silence here is normal.
  4. It runs `catalog build` (cluster the tickets, ask the model for one recipe per cluster, check each
     one) and writes `catalog.draft.json`. This can take tens of minutes to a couple of hours.
  5. It **stops and removes the model server and the network** (also when anything above fails, on
     every exit). The GPU is freed.
  6. It runs `catalog leakcheck` with **no network at all** and writes `catalog.leak_report.json`.

  Stdout ends with `leakcheck tickets=<n> identity_tokens=<n> passed=True`. Exit codes of the catalog
  commands: `0` fine, `2` the leak check or release gate refused (the code and a schema path are safe
  to read), `3` unexpected failure, `4` wrong arguments or input.
- [ ] `infra/profiler/window.sh --window e verify` prints **counts and verdicts only**. Read it like this:
      - `recipes in draft` must be above 0. **0 means the build produced nothing:** the window is
        spent and the fix is in code, not here. Shred and stop.
      - every `check ... ok failures=0`. The four checks are `vocabulary_floor` (a word in a recipe
        that too few tickets, dealers or vehicles use), `identity_denylist` (a recipe word that is, or
        contains, something from a name, number or serial column), `verbatim_corpus` (five words in a
        row copied from any ticket) and `guard` (the structural rules of a recipe).
      - `report passed : True`.
      - `report matches draft : True`. **False means the draft changed after the check** (see below).
- [ ] **WHAT TO READ ON THE BOX: the whole draft and the whole leak report. Every recipe, every word.**

      ssh hpc 'less <data-dir>/recall-quarantine/catalog.draft.json'
      ssh hpc 'less <data-dir>/recall-quarantine/catalog.leak_report.json'

      The machine passing is **not** the review. For every recipe, ask whether it contains:
      - a surname or any person's name, or a first name
      - a dealer or a customer, or anything that points to one (a town used as a dealer's name)
      - a product-internal name, project name or tool name that only this company uses
      - a part number, serial number, ticket number, code or any identifier
      - a place, a plant or a site
      - a sentence that reads like a real ticket (a particular story, a date, "we called him on...")
      - anything that could identify a person or a company
      - anything you would not want a competitor to read

      **Any doubt means delete the recipe or edit it.** There is no cost to dropping a recipe worth
      doubting; a leaked name costs the whole release. To edit, change the draft on the box with an
      editor. **Any edit, even one comma, invalidates the report** (it is bound to the exact bytes of the
      draft), so run the check again:

      infra/profiler/window.sh --window e leakcheck
      infra/profiler/window.sh --window e verify      # report matches draft : True

      Then read the changed recipes again.
- [ ] `infra/profiler/window.sh --window e release` writes `catalog.json`, with no network, and
      **only if** the report passed for the exact draft. It refuses otherwise (see "If it fails").
- [ ] `infra/profiler/window.sh --window e fetch --clean` copies back **only** `catalog.json` and
      `catalog.leak_report.json` to `local/artifacts/` (after asking whether you read both draft and
      report), then shreds the export, the draft, every `*.tmp` and the detail log.
- [ ] `ssh hpc 'ls -la <data-dir>/recall-quarantine'` → only `catalog.json` and
      `catalog.leak_report.json` remain (plus `.sealed`, a one-line marker file that is meant to stay).
- [ ] `make check-clean` on the workstation → quarantine empty. **Run it unsandboxed**, in a normal
      terminal; under the Claude Code sandbox it cannot list the denied directory and reports a false
      `clean`.
- [ ] 🔓 Only now resume AI-assisted work.

Note: `run` first deletes any old `catalog.draft.json`, `catalog.leak_report.json` and `catalog.json`
in quarantine, so a failed run cannot leave the previous run's report or catalog to be fetched.

### First-run things to verify on the box (the rehearsal cannot)

The rehearsal replaces the model server with a stub, so two things are untested until the first real run.
If either fails, the window is spent on diagnosis, but **nothing leaks**: only the model container fails.

1. **The vLLM image's entrypoint and arguments.** The window starts the image as
   `<image> --model Qwen/Qwen2.5-32B-Instruct-AWQ --no-enable-log-requests --gpu-memory-utilization 0.70
   --max-model-len 32768 --host 0.0.0.0 --port 8000`. That is the form of the OpenAI-compatible
   `vllm/vllm-openai` image, whose entrypoint is the API server. If the pinned image instead needs
   `serve <model>` or `python -m vllm.entrypoints...`, the container exits at once and the readiness
   poll never answers. Check on the box **before** the window:
   `podman run --rm --network=none <image> --help` must list `--model`.
2. **The weights mount.** It is mounted **read-only** (`:ro`) with `HF_HUB_OFFLINE=1`. Two things can
   go wrong: (a) SELinux denies the read (symptom: the container exits with "permission denied" on the
   cache; the fix is the `:ro,Z` or `:ro,z` label on the mount), (b) the server wants to write lock
   files into the cache (symptom: "read-only file system"; the fix is to mount it read-write, `:rw`,
   because weights are not data). Either change is a change to `window.sh`, made **before** the window
   and re-checked with `make window-e-rehearsal`.

### If it fails

First, whatever fails: the model server and the network are removed automatically. Check with
`ssh hpc 'podman ps -a; podman network ls'` that nothing named `recall-e-...` is left; if something is,
`podman rm -f` it and `podman network rm -f` it by hand.

- **"the LLM server never answered within the readiness budget".** The container exited or the model
  did not load in 30 minutes. Do not wait longer. Look at the container's exit with
  `podman run` by hand for the same image (no ticket data is involved at this stage), and see the first-run
  list above. The export is untouched; shred it if you stop here.
- **"fairuse refused GPU 0".** The card is busy. Wait. Do not override.
- **"podman network create --internal does not work on the box" (from `ship`).** Window E cannot be
  isolated. **Do not run it** without an internal network, and do not replace it with a plain one.
- **`build` printed `recipes=0`** (or `verify` says 0 recipes). Every cluster was rejected: too few
  tickets, dealers or vehicles behind a cluster, or the model's answers did not parse. The window is
  spent. Shred (`clean`) and fix in code, without the data.
- **`leakcheck` failed** (exit 2, `passed=False`). The names above say which:
  - `vocabulary_floor FAILED`: a recipe uses a word that too few tickets, dealers or vehicles used
    (a rare word can be one person's habit or a name).
  - `identity_denylist FAILED`: a recipe word is, or contains, a name, number or serial from the identity
    columns. This is strict on purpose (a dealer called "Service Nord" blocks "service" and "nord").
  - `verbatim_corpus FAILED`: five words in a row were copied from a ticket.
  - `guard FAILED`: the recipe broke a structural rule.
  The report lists **recipe ids only**, never words. Open the draft, find those ids, delete or rewrite the
  recipes, run `leakcheck` again. Failures are also a good sign the model copied text: read the neighbours.
- **`release` refused.** It prints reason codes, never a value:
  - `STALE_REPORT $.draft_sha256`: the draft changed after the report. Run `leakcheck`, read, release.
  - `REPORT_NOT_PASSED $.passed`: the report says the check failed. Fix the draft, `leakcheck` again.
  - `REPORT_CHECKS`, `REPORT_SHAPE`, `REPORT_FLOORS`: the report is missing, damaged or was made with
    weaker floors. Run `leakcheck` again (never edit the report).
  - `GUARD_ERROR` / any other code from the draft's own path: a recipe is malformed (a hand edit broke
    it). Fix it, `leakcheck`, release. A refused `release` leaves **no** `catalog.json`.
- **Anything else.** Abort, `infra/profiler/window.sh --window e clean`, and describe the problem in your own
  words. Read `profiler_detail.log` yourself, on the box; it can hold ticket text.

### What NEVER to do

- **Never fetch the draft.** It is the one file that holds model output derived from real text before
  the human review. `fetch` cannot copy it, and you must not copy it by hand either.
- **Never use `--allow-weak-floor`**, or lower `--k`, `--min-vehicles` or `--min-dealers`. They exist
  for rehearsals only. If you ever see one in a command, stop.
- **Never run with an AI attached** — no assistant reading the terminal, no pasted output of the
  window. The printed codes and counts are safe; the draft and the detail log are not.
- **Never reuse a report for an edited draft.** Any edit means `leakcheck` again, then read again.
- Never publish a port, never replace `--internal` with a normal network, never mount quarantine into
  the model container, never switch off `--log-driver=none`.

## Window C — real-data eval (command block written at the start of M4)

Controls that must be in it, decided now:

- This window runs the **entire offline pipeline**: clean → enrich → embed → index
  → eval. It is an overnight unattended run, so every stage must already be proven
  on synthetic data.
- vLLM starts with `--disable-log-requests` and its logs go to
  `<data-dir>/recall-quarantine/`. Default verbosity puts prompt text in the log, and a
  log file nobody remembers to shred is a leak that outlives the window.
- Postgres for this window runs with its data directory on **tmpfs**, so real rows
  never touch disk, and is destroyed with `podman rm -v`. `DROP TABLE` leaves the
  volume and the WAL behind.
- Enrichment intermediate state — needed for resumability — lives under
  `<data-dir>/recall-quarantine/`. It is a distilled summary of real tickets and is
  arguably more sensitive than the source rows.
- The hand-written eval queries are real data. They are created on the box, used on
  the box, and shredded there. Only `eval_real.json` crosses out, keyed by **opaque
  query ids** — never by query text.
- Teardown shreds: CSV, queries, enrichment state, vLLM logs, tmpfs volume, detail log.
