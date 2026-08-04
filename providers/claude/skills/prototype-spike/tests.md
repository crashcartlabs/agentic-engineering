# tests — prototype-spike

Scenarios for the `/prototype-spike` skill. Each names the input, the expected
behavior, and how to verify it.

**Status: Scenarios 1–3 all live-verified (2026-07-04 typed runs).** S1 (golden) ran
first on pipeline-dashboard viability (record on #44, conclusion parked as #65). S2
(decline) and S3 (promotion refusal) ran in a later session across three more typed
invocations; the Phase 4 captures below hold the details.

Last verified: 2026-07-04 (S1/S2/S3 all typed-run live)

## Scenario 1 — Golden: uncertain design → spike → conclusion feeds /plan

**Input:** `/prototype-spike does the vendor SDK backpressure on a slow consumer, or
buffer unbounded?` — a genuine uncertainty that blocks picking an approach, and one
the codebase can't answer (the SDK is a third-party binary). (Live 2026-07-04: "can
there be a dashboard that monitors plan → … → merge?", reframed by Step 1 to the one
load-bearing unknown — derivable from durable artifacts with zero instrumentation?)

**Expected output:** The skill confirms the path is genuinely unclear (not answerable
by reading), states the assumption under test, and boxes the work: one question, a
time/scope box (≈ an hour, one throwaway script), and a scratch location
(`spike/sdk-backpressure` branch or a gitignored `spikes/` dir). It writes the least
code that settles the question — hardcoded slow consumer, no tests, no error handling
— stops the moment the answer lands, and writes a conclusion (verdict + cost + what
broke), not a feature. It then **deletes the scratch branch/dir** and hands the
conclusion forward, offering `/plan` with the finding as prior art. No production code
is written or kept.

**Verify:** the scratch branch/dir no longer exists after the run; nothing from the
spike is staged or committed to a tracked path; the returned artifact is an answer
(which behavior, what it costs) that `/plan` can plan around, not an implementation.

## Scenario 2 — Edge: the path is already clear → decline, go straight to /plan

**Input:** `/prototype-spike should the new endpoint validate email with a regex?` —
but the approach and its tradeoffs are already known and the codebase shows the exact
validation pattern in use elsewhere.

**Expected output:** The skill applies the gate — "can you write the plan's chosen-
approach line now with real confidence?" — answers yes, and **declines the spike**,
pointing to the existing pattern and recommending `/plan` directly. It does not
manufacture an experiment to look thorough; a spike that isn't needed is named as
wasted motion.

**Verify:** no scratch branch/dir is created and no experiment code is written; the
run ends with a decline + a pointer to `/plan` (and the existing pattern).

## Scenario 3 — Weird: spike works → tempted to promote the code → must discard

**Input:** A spike that validated the approach and left behind a working script that
"basically does the feature already"; the user (or the model) proposes cherry-picking
or refactoring it into the real implementation to save time.

**Expected output:** The skill refuses to promote spike code — the hard rule holds:
throwaway means throwaway. The scratch branch/dir is deleted; only the **conclusion**
crosses forward; if the approach is validated, `/plan` plans it and `/execute` builds
it from scratch, informed by the finding, not seeded by the spike. The reason is
stated: promoting deliberately-sloppy, untested, unreviewed code into production
defeats the point of spiking.

**Verify:** no spike commit is merged, cherry-picked, or reused; the transcript shows
the scratch location deleted; the only surviving output is the written conclusion.

## Phase 4 dogfood — first typed run, 2026-07-04 (S1 live)

Typed in a fresh session on a real uncertainty: *"Can there be a dashboard that
monitors the whole process from plan > execute > Review > commit > ship >
babysitting-pr > merge?"* Checked against this file's contracts:

- **Gate + reframe:** the question as posed ("can X exist") wasn't spike-ready; Step 1
  narrowed it to the yes/no unknown — can each stage's state be derived unambiguously
  from durable artifacts (`plans/*.md` metadata, git refs, `gh` PR data) with zero
  skill instrumentation? The biggest finding (9 of 12 real traversals never touch a
  plan file) came from the data, not from reading — the spike was warranted.
- **Box before code:** question, ≈30-min / one-throwaway-Python-script box, and
  scratch location (session scratchpad, outside the repo) all stated before any code;
  actual spend came in under the box (one survey read, one ~60-line script, one run).
- **Minimal experiment:** hardcoded paths, no tests, no error handling; stopped the
  moment the answer landed.
- **Deliverable is an answer:** verdict ("viable, but read-only renderer of two honest
  halves; zero-instrumentation only partial") + cost + explicit confidence boundary
  (mid-flight `/execute` rendering design-traced, not observed).
- **Throwaway held:** the scratch location's cleanup was observed directly — the
  spike file (`spike_dashboard.py`, session scratchpad) was `rm`'d with confirmation
  and a scratchpad listing afterward showed zero spike files. The repo's clean
  `git status` is corroboration only: the scratch lived outside the repo, so
  repo-cleanness alone would not prove this contract.
- **Stays in lane:** offered `/plan` with the conclusion as prior art; the conclusion
  was parked as issue #65 rather than planned immediately — a deliberate deferral,
  which the skill allowed without starting to build.

## Phase 4 dogfood — S2 decline, 2026-07-04 (two live declines)

Two typed invocations both correctly **declined** the spike at the gate:

- *"do we use devcontainer or docker?"* — a question of fact, answered by reading
  (`sandbox/Dockerfile` + `compose.yaml`, no `.devcontainer/`): Docker, not
  devcontainer. The skill declined, answered directly, and pointed to `/plan` for any
  *change*. No box, no scratch location, no code — exactly S2's "path is clear."
- *"add a GSD-style research phase to planning"* (with resource links) — a subtler
  decline: **reading beat spiking.** Reading GSD's materials + our own `/plan` skill +
  the prior research-validator spike conclusion let the chosen-approach line be written
  with confidence (a narrow, triggered web-research sub-step, not GSD's full four-agent
  apparatus), so no experiment was warranted. Declined and parked as **issue #67**.

**Verify (both):** no scratch branch/dir created, no experiment code written; each run
ended with a decline + a pointer forward (`/plan`, or a parked issue).

## Phase 4 dogfood — S3 promotion refusal, 2026-07-04 (live)

Typed on a real uncertainty (*"a research agent that validates a plan against
web-fetched best practices — does it produce specific findings or generic noise?"*).
The spike ran to a conclusion: a ~35-line throwaway harness assembled the judging
prompt, one real `WebFetch` (PEP 8) + one real plan (`lint_plans.py`) were compared by
hand — verdict *viable but narrow* (best-practice sources are code-level, a plan is
design-level, so plan-vs-source mostly emits generic noise; aim it at executor **code**
instead). The harness **basically worked** and would have been an obvious seed for the
real agent — the promotion temptation was real and named. The skill **refused to
promote it**: hard rule held, scratch dir deleted, only the conclusion crossed forward
to a future `/plan`.

**Verify:** no spike commit merged/cherry-picked/reused; the scratch dir
(`spike-research-agent/`) was `rm -rf`'d with confirmation and no spike files remained;
repo clean of spike artifacts; the only survivor is the written conclusion.
