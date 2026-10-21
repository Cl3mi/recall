# Prompt for the next session

Copy everything in the fenced block below into a fresh Claude Code session started in
`~/mci/recall`.

Why it is shaped this way: the binding data constraint is stated first and in the operator's
own voice, because a constraint buried mid-prompt gets treated as background. The "escalate,
don't adjust" rule keeps earning its place — it has now been right fifteen times. New in this
handoff, and the reason it is worth re-reading: a **"tests that pass for the wrong reason"**
block. The last session shipped four of them before they were caught, and every one read as
coverage while asserting nothing. That failure mode cost more than any bug did.

---

```
Continue M2 on the branch feat/m2-fixture-generator, which is already checked out, 146 commits.
The tree is clean and lint is silent. `make test` reports 338 passed with ONE failure:
tests/unit/test_data_guards.py::test_the_test_suite_does_not_dirty_the_quarantine, caused by a
stray profiler_detail.log I have not shredded yet. That failure is MINE to clear, not yours -
never touch that test and never touch anything under local/quarantine/.

Implement docs/superpowers/plans/2026-09-07-window-b-plan-b-sealed-embedder.md with
superpowers:subagent-driven-development, one subagent per task. Give each subagent the full
task text rather than a file to read, and list explicitly which test edits that task is
authorised to make. Verify each task's result yourself against the tree rather than trusting
the subagent's report - run `make test` and `make lint` after each task, and if a subagent
reports a number, re-run the command that produced it. Last session three subagents went idle
without reporting at all and one left a broken tree; in that last case the failing tests were
right and my spec was wrong.

Read first, in this order:
1. docs/superpowers/plans/2026-09-07-window-b-plan-b-sealed-embedder.md - the plan. Read it
   whole, including "The two constraints that shape everything here" and "Out of scope".
2. docs/STATE.md - the resume point. Read "M2 findings" (all twelve) and "Decisions already
   made - do not relitigate".
3. docs/superpowers/plans/2026-08-27-window-b-leakage-gate.md - Plan A, complete. It built all
   four gate checks with the embedder INJECTED, specifically so Plan B is the only part that
   needs the sealed image.
4. docs/airlock-runbook.md, the "Window B" section - the controls, which are not negotiable.

Never read anything under local/quarantine/ or ~/work/<client-dir>/. Those hold a client's
real ticket export under NDA. local/artifacts/profile.json IS readable - it passed the safety
gate. Nothing in this plan needs the real export; every step runs against synthetic corpora.

A session hook rejects any Bash command whose text contains ".csv". Do not work around it with
globs, variables, a different filename or any other obfuscation - ask me to run that command
instead. This includes heredocs: `cat > f <<EOF` puts the body into the command text, which
tripped the hook twice last session. The sanctioned route is the Write tool: the path goes
INSIDE the Python file and the command that runs it never names the suffix.

Tell every subagent, in these words: if a test fails and you believe the test is wrong, STOP
and report it rather than adjusting the test. On this project a failing test has been right and
the plan wrong fifteen times.

And tell them this too, because it cost more than any bug did: A TEST THAT PASSES FOR THE WRONG
REASON IS WORSE THAN NO TEST, because it reads as coverage. Four shipped in one session before
being caught:
- an exact-Jaccard assertion that held while llm.Fake clustered 60% of its own singletons
- a shingle test whose real-side sentence was one content word short of the window, so the
  intersection was empty and it could not fail
- `assert "shingle" not in json.dumps(checks["shingles"].get("examples", []))`, which evaluates
  `"shingle" not in "[]"`
- an `isinstance(value, int)` check satisfiable by an all-zeros return
If a subagent notices one, that report is worth more than the implementation. One did, and it
was.

Do not retry these. They are measured, not suspected:
- The gate's baseline percentile is settled at 95 (CROSS_PERCENTILE 99). p99 saturates at
  1.000000 on this fixture and the check cannot fail; p75 and p50 sit BELOW a clean comparison
  and would fire on fixtures that are fine. See finding 12.
- Do not use rounds 4, 5 or 6 as a "clean comparison" corpus. They share 71-87% of their
  documents with round 7, because round 7 reused 413 cached model responses written during
  them. Only round 3 is independent, at 0.1% overlap.
- Do not add --device to window.sh. CPU is my decision and an overnight run is acceptable.
- Do not install CUDA torch. The CPU wheel is the only one that will ever be exercised.

For the model work:
- The window runs with --network=none, so the weights MUST be baked into the image at build
  time. Build has network; run does not.
- e5 needs the "passage: " prefix, and neighbours._encode already applies it - do not apply it
  twice. Both corpora are documents, so both get "passage: ", never "query: ".
- Pooling is a MASKED MEAN over the last hidden state. CLS pooling is wrong for this model
  family and produces plausible-looking but degraded vectors, which is a green gate for the
  wrong reason.
- Pin E5_REVISION to a real sha. "main" makes the report's manifest a claim about whatever the
  hub served that day.

The rehearsal in Task 6 is the most valuable part of the plan. rehearse-window-a.sh has already
caught six defects that would each have cost a full airlock cycle. A sealed window has no AI
available. Every failure the rehearsal catches is a cycle saved, so do not weaken an assertion
to get a green rehearsal.

Then show me: that `podman run --rm --network=none recall/profiler:pinned` loads the model
offline, the rehearsal's PASS/FAIL summary, whether embedder_is_a_model came out true, the
measured throughput in documents per second and what that implies for a corpus of tens of thousands of documents, and any
defect the rehearsal caught. State which command produced each number.

Do not commit anything under local/, and do not commit the fixture at local/fixtures/export.csv.
It stays uncommitted until this gate is green against REAL data, which needs a window I have to
book. `git ls-files local/` must stay empty.

If a hypothesis of yours turns out wrong, record it in docs/STATE.md with its numbers the way
finding 12 records the 1.000000 baseline. A wrong hypothesis written down is worth more than a
vague one left out, because it stops the session after you repeating it.
```

---

## What changed in this handoff, and why

**Added the "passes for the wrong reason" block.** Four such tests shipped in one session. One
was caught by a subagent that reported a concern instead of adjusting anything, and that report
was worth more than its implementation — so the prompt now asks for it explicitly rather than
hoping for it.

**Added the round-overlap warning.** Rounds 4–6 share 71–87% of their documents with round 7
because of the response cache. A session that used them as a "clean comparison" baseline would
measure 1.000000 and conclude the gate was broken.

**Stated the CPU decision as a decision.** Otherwise a session will spend a task measuring
throughput to decide something already decided, or worse, add `--device` to `window.sh` and
change the airlock's footprint.

**Kept the escalate-don't-adjust rule, with the count updated.** It is the single highest-value
line in this file.
