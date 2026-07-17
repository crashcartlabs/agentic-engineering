---
name: prototype-spike
description: "Run a bounded, throwaway experiment that answers one design question before planning — \"does this approach even work?\", \"which of these two actually holds up?\", \"what does this really cost?\". Invoke as /prototype-spike <the design question> when a genuine design uncertainty blocks /plan and reading the codebase won't settle it. The deliverable is a conclusion, not a feature. Not production code, not /plan (it precedes it), not /execute. Explicit-trigger only."
---

# /prototype-spike — Throwaway experiment to answer a design question

A spike is a **question with a deadline**, not a head start on the build. You write the least code that will tell you whether an approach works or what it costs, you read the answer, and you **throw the code away**. What survives is the conclusion — which approach, what it costs, what broke — and that conclusion is what `/plan` then plans around. The spike de-risks the design; it never becomes the design.

Run this only when a real uncertainty is in the way. Most tasks don't need one: if you can already name the approach and its tradeoffs, you are ready to plan, and a spike is wasted motion plus a standing temptation to keep code you swore was throwaway.

## What this is / is not

- **Is:** one bounded experiment that answers one design question, run in a scratch location and discarded, whose output is an **answer** handed to the human (and, when `/plan` runs, folded into its context brief).
- **Is not:** production code, a plan, or an implementation. It does not scaffold the feature, and its code is never promoted, cherry-picked, or "cleaned up" into the real thing. `/plan` decides *what* to build; `/execute` builds it; this decides *whether the approach is even viable* so `/plan` isn't guessing.

## When to spike vs. plan directly

The gate is a single honest question: **can you write the plan's "chosen approach" line right now with real confidence?**

- **Path is clear → skip the spike, go straight to `/plan`.** You can name the approach and its tradeoffs from what you already know or can read in the codebase. Reading beats spiking — never build an experiment to answer what a file would answer (this is `/plan`'s "explore, don't ask" applied one level up).
- **A design uncertainty blocks planning → spike it.** The honest answer is "I'd be guessing": you can't pick between two approaches, or you don't know whether one works at all, or you can't estimate its cost — and no amount of reading settles it. Spike *only* that specific unknown.

State the assumption behind the uncertainty out loud before you start (§II) — "I'm assuming the streaming API backpressures; the spike checks that." If you can't phrase the uncertainty as something an experiment could resolve, you are not ready to spike; keep reading or ask.

## Workflow

### 1. Frame the question

Reduce the uncertainty to **one** question the experiment can actually answer — a yes/no ("does library X handle Y?") or an A/B ("does the queue or the poll hold up under Z?"). This is the spike's success criterion (§VI): the spike is done when this question is answered, not when the code looks finished. If you have three questions, you have three spikes — do the one that unblocks planning most and defer the rest.

### 2. Box it — before any code

Fix all three, and say them to the human:

- **The question** (from step 1), phrased so the answer is unambiguous.
- **A time/scope box** — e.g. "≈ an hour, one file, hardcoded input." The box is the commitment that this is throwaway; work that outgrows its box is a plan trying to happen, so stop and plan.
- **A scratch location that cannot leak into production** — a scratch branch (`spike/<slug>`) you will delete, or a scratch dir (a gitignored `spikes/`, or the OS temp dir). §XI: don't assume a shell — resolve temp per platform (`$TMPDIR` or `/tmp` on POSIX, `$env:TEMP` on Windows) and mind path differences.

### 3. Run the minimal experiment — the logic-validation branch

Answer "**does this approach even work?**" with the least code that settles it (§III). Hardcode the inputs, skip error handling for errors that can't occur here, write no tests, build no abstraction — none of this survives, so none of it has to be good. Change one variable at a time so the result is attributable (§VII). **Stop the instant the question is answered** — or the instant the box is spent. A box that runs out with the question still open is itself a finding ("inconclusive in an hour → the uncertainty is bigger than we thought"), not a reason to keep digging.

### 4. Read the result, write the conclusion

The deliverable is an **answer, not an artifact**. Capture, tersely:

- **The verdict** — which approach, or works / doesn't.
- **What it costs** — performance, added complexity, any new dependency the approach would drag in.
- **What broke or surprised you** — the sharp edges the real implementation will hit.

Write it where `/plan` will read it: hand it to the human, and if `/plan` runs next it becomes prior art in the context brief. Be precise about confidence (§IX) — "validated for the happy path; concurrency untested" tells `/plan` what still to pin down.

### 5. Discard the spike, feed the conclusion forward

**Delete the scratch branch or dir.** The experiment's code is thrown away on purpose: promoting it smuggles unreviewed, untested, deliberately-sloppy code into production and defeats the entire point. If the approach was validated, `/plan` plans it and `/execute` builds it **properly, from scratch** — informed by the conclusion, not seeded by the spike. The only thing that crosses the line from spike to plan is the answer.

## Hard rules

- **Explicit-trigger only; never auto-run.** The human decides an uncertainty is worth a spike — the model does not spin one up whenever it feels unsure (that is the "in case we need to" over-building §III warns against).
- **One question, one box.** No question you can state, no spike. No box, no spike. Work that outgrows the box stops and becomes a `/plan`.
- **Throwaway means throwaway.** Scratch branch or scratch dir, discarded after. Spike code is never merged, cherry-picked, or refactored into production. The conclusion is the only survivor.
- **It precedes `/plan`; it is not `/plan` and not `/execute`.** The output is a conclusion that informs the plan — not a plan, not an implementation.
- **If the path is already clear, decline and go straight to `/plan`.** A spike you didn't need is wasted motion and a temptation to keep the code.
