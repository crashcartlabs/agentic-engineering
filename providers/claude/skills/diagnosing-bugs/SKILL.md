---
name: diagnosing-bugs
description: "Diagnose a bug by proving its cause before changing code — tighten the feedback loop, reproduce and minimise, hypothesise, instrument, then fix behind a regression test that was red first. Use when chasing a bug, a crash, a failing or flaky test, a stack trace, an unexpected null/undefined, or a regression — any \"why is this broken\", \"debug this\", \"track down\", or \"root cause\" request. Not /code-audit (that reviews a diff for defects), and not a quick fixer that skips reproduction."
---


# Diagnosing bugs — find the cause before you change anything

A bug is a **gap between what the code does and what you believe it does**; debugging closes it by investigation, never by guessing (§VII). The fast, plausible fix — wrap the crash in a `try`, drop a null check where the stack trace pointed — moves the bug somewhere quieter instead of removing it. That is exactly the code that passes a casual review and fails when it matters. The discipline below is the antidote: reproduce before you touch anything, change one thing at a time, and prove the cause with a test that was red a minute ago.

Adapted from Matt Pocock's MIT-licensed skills collection (github.com/mattpocock/skills); see `ATTRIBUTION.md`.

Detect the project's run/build story first — some projects run TypeScript, Python, or shell directly, others need a build or compile step. Give every command in a form that works on both Windows PowerShell and a POSIX shell, or give both.

## 1 — Tighten the feedback loop

Before anything else, make the bug **cheap to observe**. The biggest lever in debugging is the time between "make a change" and "see what it did" — shrink it first and every later phase gets faster. Find the smallest command that exhibits the bug and run *that*, not the whole suite: a single test by name (`node --test --test-name-pattern='parseRow quoted'`, `pytest path::test -x`), a one-file script, or a REPL with the failing input pasted in. When the loop runs in seconds you can afford to change one thing at a time; when it takes minutes you will be tempted to change five, and that is how causes get lost.

When no existing test or script reaches the bug, **build the loop** rather than settling for a slow one — spend disproportionate effort here, because every later phase just consumes it. In rough order of preference:

- a **failing test** at whatever seam reaches the bug — unit, integration, e2e;
- a **curl/HTTP script** against a running dev server, or a **CLI invocation** on a fixture input diffed against known-good output;
- a **headless browser script** (Playwright) that drives the UI and asserts on DOM, console, or network;
- a **replayed capture** — save a real request, payload, or event log to disk and replay it through the code path in isolation;
- a **throwaway harness** — a minimal script that spins up just enough of the system (one module, mocked deps) to hit the bug path with a single call, deleted once the fix lands;
- a **fuzz loop** for "sometimes wrong output" — hundreds of random inputs, looking for the failure mode;
- a **differential loop** — the same input through old vs new version (or two configs), diffing the outputs;
- last resort, a **human-in-the-loop script** — if a person must click, script *their* steps and capture the output so even that loop is structured and repeatable.

The loop must assert the user's **exact symptom** — "runs without erroring" is not a signal that goes red on *this* bug.

## 2 — Reproduce and minimise

You have not started until the bug **reproduces on demand** (§VII). Read the *whole* error and the *whole* stack trace first — the top frame is where it surfaced, not always where it broke, and the message often names the cause outright. Then drive the failure deterministically: the exact input, state, and command that trigger it, captured so you can re-run it verbatim. A bug you cannot reproduce is a bug you cannot prove you fixed — an intermittent failure is not exempt, it is a signal to pin down the hidden state (an RNG seed, an ordering, a clock, a leaked global) until it fails every time. When the hidden state resists pinning, work on the **reproduction rate** instead of demanding a clean repro: loop the trigger 100×, run it in parallel, add stress, inject sleeps to widen the timing window. A bug that fails half the time is debuggable; one that fails 1% of the time is not — keep raising the rate until the loop's verdict is trustworthy.

Now **minimise**. Strip the reproduction to the smallest input and shortest path that still fails — delete unrelated data, collapse fixtures, remove callers. Each thing you remove that keeps the failure alive is a thing that was not the cause. What survives to the minimal case is where the bug lives.

## 3 — Hypothesise

Only now form hypotheses — **three to five of them, ranked**, before testing any. A single hypothesis anchors you on the first plausible idea; generating rivals forces you to notice what else the evidence allows. Each must be a specific, falsifiable statement of what is wrong — "`parseRow` keeps the quote char because the escape branch never runs on a doubled quote," not "quoting is broken" — with the prediction it makes stated outright: "if X is the cause, then changing Y makes the failure disappear." A hypothesis with no prediction is a vibe; discard or sharpen it.

**Show the ranked list to the user before testing it.** They often hold re-ranking knowledge you cannot see ("we deployed a change to #3 yesterday") or have already ruled candidates out — a cheap checkpoint (§IX). Do not block on a reply; proceed down your own ranking if none comes.

When the code is large or the regression is new, **isolate by binary search** instead of reading everything:

- **`git bisect`** when the bug is a regression — mark a known-good and known-bad commit, let it halve the history, and land on the exact commit that introduced it. Automate it with `git bisect run <your minimal command>` so every step runs the identical check and the exit code decides good/bad.
- **Binary-search the code path** when there is no bad commit — short-circuit or comment out half the pipeline, see which half keeps the failure, repeat. The half that still fails contains the cause.

## 4 — Instrument

Test the hypothesis by **observing**, not by editing behavior. Add logging at the boundary your hypothesis names — the value going in, the value coming out — and confirm the state is what you predicted. `console.error(...)` / `print(..., file=sys.stderr)` to **stderr** (so it never pollutes a stdout that a caller may parse), a debugger breakpoint, or a temporary assert all work; pick the one that shows the state fastest. **Tag every debug log with one unique prefix** — e.g. `[DEBUG-a4f2]` — so cleanup in phase 5 is a single grep; untagged logs are the ones that survive into the commit. Confirm the *cause*, not just the symptom: if you predicted a doubled quote and the log shows a single one, the hypothesis holds; if the value is already correct at that boundary, the bug is upstream — return to phase 3 with a new hypothesis. **Change one thing at a time** (§VII) so each observation has exactly one cause.

Never let an unexpected `null`/`undefined` stand: when a value is missing where you did not expect it, the answer is to find *why* it is missing, not to guard it (§VII). A null check over an unexplained null just relocates the bug to the first place that actually needs the value.

## 5 — Fix, cause-first, with a regression test

Write the **failing test first** (§V) — at a seam that exercises the real bug pattern as it occurs at the call site. If the only available seam is too shallow to replicate the failure (a unit test that cannot reproduce the chain that triggered it), a test there gives false confidence — and the absence of a correct seam is itself a finding about the design (§V): say so in the post-mortem instead of shipping a hollow test. Encode the minimal reproduction from phase 2 as a test, run it, and **watch it fail** for the reason your hypothesis names — a test you never saw fail proves nothing, and a test that fails for a *different* reason means you are about to fix the wrong thing. Then fix the **cause** you confirmed in phase 4, not the symptom the stack trace pointed at, and watch the same test go green. Revert the fix and confirm the test goes red again: that red → green → (revert) → red loop is the only proof the fix addresses the cause and not a coincidence.

Keep the fix **surgical** (§IV): the diff touches only what the cause requires. Remove every log line, temporary assert, throwaway harness, and `git bisect` artifact you added while investigating — grep for your `[DEBUG-...]` tag to catch the logs — instrumentation is scaffolding, not the fix.

## 6 — Post-mortem

Before you call it done, close the loop (§XII). State plainly what the cause was, why the fix addresses it, and what you are still unsure of (§IX). Then ask the cheap question: **where else does this cause live?** The same mistake often repeats in a sibling function, and the minimal reproduction you built is the probe for it. If the bug came from a correction or a mistaken assumption worth not repeating, add its one line to **LESSONS.md** (§X); if the investigation was a substantial session, its narrative belongs in **DEVLOG.md** (§XIII), not here.

## Hard rules

- **Reproduce before you change anything.** A fix for a bug you cannot trigger is a guess; there is no cause-first debugging without a deterministic repro — intermittent bugs get pinned down, not fixed blind.
- **Read the whole error and stack trace before touching code** — the message often names the cause, and the top frame rarely is it.
- **Change one thing at a time.** Batching changes destroys the one-cause-per-observation that makes debugging converge.
- **Never paper over an unexpected null with a null check** (§VII) — find why it is null, or the bug just moves somewhere quieter.
- **The failing test comes first and must actually fail** (§V) — red for the predicted reason, then green; a test that was never red proves nothing.
- **Fix the cause, not the symptom** — verify by reverting the fix and watching the test go red again.
- **Leave no instrumentation behind** — logs, asserts, and bisect artifacts are scaffolding; the committed diff is the cause fix plus its test, nothing more (§IV).
- **Not `/code-audit`** (that reviews a diff for defects) and **not a fixer that skips reproduction** — this skill's whole value is refusing the plausible fix until the cause is proven.
