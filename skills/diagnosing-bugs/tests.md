# tests — diagnosing-bugs

Verification scenarios for the `diagnosing-bugs` workflow. Each names the input, the
expected behavior traced against the SKILL.md phases, and how to verify it.

**Status: live-verified.** All four scenarios were driven end-to-end in a scratch repo on
2026-07-04 (dogfood record at the bottom of this file). The exact wrong values and flake
rates in the scenario texts are illustrative; the live run's actuals are in the record.

Last traced: 2026-07-04 (live dogfood, scratch repo). Scenarios 1 and 3 were extended on
2026-07-08 for behavior backported from mattpocock/skills (ranked hypotheses shown to the user,
tagged debug logs, reproduction-rate raising); those additions are traced against SKILL.md but
not yet re-verified live.

## Scenario 1 — Golden: a bisected regression, fixed cause-first

**Input:** A TS row parser where a recent commit broke doubled-quote escaping — `parseRow('"a""b"')`
returns `a"b"` instead of `a"b`. A known-good commit and a known-bad commit both exist, and a single
named test can exercise the case.

**Expected:** Phase 1 shrinks the loop to that one test (`node --test --test-name-pattern=...`), not
the suite. Phase 2 reproduces deterministically and reads the whole trace. Phase 3 generates **3–5 ranked
falsifiable hypotheses** (top-ranked: the escape branch never fires on a doubled quote), each with its
prediction stated, shows the ranked list to the user without blocking, and runs
`git bisect run <minimal command>` to land on the introducing commit. Phase 4 logs the value at the escape
boundary to **stderr** with a unique `[DEBUG-...]` tag and confirms the single-vs-doubled quote. Phase 5 writes the failing test **first**, watches it fail for that
reason, fixes the cause, watches it pass, reverts the fix to confirm it goes red again, and strips the log
and bisect artifacts (a grep for the debug tag comes back empty). Phase 6 checks the sibling writer for the same bug.

**Verify:** `git bisect` names exactly one commit; the committed diff contains only the cause fix plus the
new test — no log lines, asserts, or bisect leftovers; reverting the fix turns the new test red.

## Scenario 2 — Edge: the crash site is not the cause; refuse the null check

**Input:** A Python script throws `AttributeError: 'NoneType' object has no attribute 'strip'` at a known
line; the tempting one-liner is a `if val is not None:` guard at that line.

**Expected:** Phase 2 reproduces and reads the *whole* trace rather than patching the top frame. The guard
is **refused** (§VII); instead the value is traced upstream to why it is `None` — an earlier lookup returned
nothing / a key was absent — and that cause is fixed. Phase 5's regression test asserts the upstream value is
now present, and fails without the upstream fix.

**Verify:** the diff contains no `is not None` / optional-guard added at the crash site; the regression test
fails when the upstream fix is reverted; the `None` no longer reaches `.strip()`.

## Scenario 3 — Weird: an intermittent failure — no fix until it reproduces

**Input:** A flaky test that fails roughly 1 run in 20 on an ordering- or seed-dependent assertion, with no
deterministic reproduction yet.

**Expected:** No speculative fix ships. Phase 2 is treated as a gate: the skill makes the failure
deterministic first — seed the RNG, force the ordering, or loop the minimal command until it fails and
capture that exact state — and reports "not reproduced yet" rather than editing code until then. If the hidden
state resists pinning, the skill raises the **reproduction rate** (loop the trigger 100×, parallelise, inject
sleeps) until the loop's verdict is trustworthy, rather than demanding a clean repro or giving up. Only once
the captured seed/state re-fails verbatim (or the rate is high enough to debug against) do phases 3–5 begin.

**Verify:** no code change is proposed while the bug is non-deterministic; the captured seed/state reproduces
the failure verbatim on re-run (or a rate-raising loop is shown with its failure count); phase 5 starts only
after that repro exists.

## Scenario 4 — Boundary/refusal: "just wrap it in a try/catch"

**Input:** "This throws sometimes — just wrap it in a try/catch so it stops crashing." No reproduction, cause
unknown.

**Expected:** The blanket catch is **pushed back on**: swallowing an unexplained failure hides the cause and
moves the bug somewhere quieter (§VII). The skill offers the reproduce-then-cause path instead, and treats a
narrow catch of an *expected, explained* error as the only acceptable form. It does not silently add a broad
handler. This is also where the `/code-audit` boundary holds: the skill diagnoses a live failure, it does not
review a diff.

**Verify:** no broad `catch {}` / bare `except:` is added over an unexplained failure; the response names the
missing reproduction and routes to the cause-first workflow.

## Dogfood record (2026-07-04, live — scratch repo, macOS)

Run by the model driving the skill through the active harness (invocation-policy check: model-invocable
as intended) in a scratch repo (`parse.ts`/`write.ts` + `py/`), staged so every bug was real and
committed history existed where a scenario needed it.

- **Scenario 1 — PASS.** TS parser regression staged so the existing suite passed at HEAD (the
  bug landed unnoticed — the doubled-quote case was untested). Live actuals: `parseRow('"a""b"')`
  → `a""b` (escape branch appended `line.slice(i, i+2)`, both quote chars). Phase 1: loop = one
  untracked repro script. Phase 2: deterministic, minimised further to `'""""'`. Phase 3:
  `git bisect run node repro.mjs` named exactly the "Simplify quote handling" commit. Phase 4:
  stderr log at the escape branch showed `""` appended — hypothesis confirmed. Phase 5: test
  first, red for the predicted reason, cause fix, green, revert→red (after a first attempt used
  `git stash -q push` — wrong flag order, no stash created — caught because the "red" count came
  back 0; redone with `git stash push -q --`), re-apply→green; committed diff = fix + test only,
  instrumentation and repro script gone. Phase 6: `writeRow` sibling probed by roundtrip, clean.
- **Scenario 2 — PASS, with a two-layer live find.** Python `AttributeError: 'NoneType'…strip`
  reproduced; guard at the crash site refused; upstream instrumentation showed
  `lookup key='titel' present=False available=['owner','title']` — a key typo, the None fully
  explained; red-first test, upstream fix, revert→red, committed diff has zero `is not None`.
  **The live find:** the post-fix "green" check stayed red, and diagnosing *that* with the same
  phases proved the interpreter was executing stale bytecode — Apple's CommandLineTools Python
  redirects caches via `sys.pycache_prefix` to `~/Library/Caches/com.apple.python` (so
  `rm -rf __pycache__` is a no-op), and a same-second, same-size edit (`titel`→`title`) keeps
  the stale pyc "valid" under the mtime+size check. Proof: loaded `render.__code__.co_consts`
  contained `'titel'` while the source said `'title'`; `touch report.py` invalidated the cache
  and the suite went green. Guard against this when editing Python mid-session: bump mtime or
  check `importlib.util.cache_from_source()`.
- **Scenario 3 — PASS.** Flaky leaderboard test (4-way score tie ordered by set iteration):
  12 fresh runs showed mixed P/F (higher rate than the illustrative 1-in-20; intermittency is
  the contract). The gate held — zero code edits before determinism: `PYTHONHASHSEED=1` fails
  verbatim ×3, `PYTHONHASHSEED=0` passes ×3. Then hypothesis (no deterministic tie-break), fix
  (secondary sort key = name), green under both pinned seeds and 12/12 unseeded runs,
  revert→red under the pinned seed, 1-line commit.
- **Scenario 4 — PASS.** "Just wrap parseRow in try/catch" refused: response names the missing
  reproduction, routes to capture-the-row → minimise → cause-first-fix, allows only a narrow
  catch of an expected, explained error; `git status` clean — no code change shipped.
