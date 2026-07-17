# tests — execute

**Status: launcher happy path + pre-flight refusals live-verified; blocker relay
design-verified; interruption-resume contract live-verified in a throwaway git
fixture.** Written from recorded real runs, then updated for the resume path: the
executor dogfood (throwaway repos, verified `a84210e`), the typed `/execute` launcher
smoke-test, the multi-phase reviewer-plan execution on a real PR, and the
interruption-resume fixture described in Scenario 4. Nothing below is upgraded past what
those records show.

Last verified via the resume fixture; a typed Claude `/execute` run was auth-blocked in
that session.

## Scenario 1 — Golden: approved plan, clean tree → executor runs it, launcher relays

**Input:** `/execute plans/<file>` typed with an existing plan whose status is
`approved`, on a clean tree (live: `plans/execute-launcher-smoke.md` in an
isolated worktree, fresh session).

**Expected output:** Pre-flight passes and says so in one line before launching. The
executor subagent (not the foreground) creates `plan/<slug>` from the current branch,
sets the plan `in-progress`, implements phase by phase, commits each phase only after
its validation is green (code + plan-file updates staged together, message referencing
the phase), finalizes the plan `done` with every task `[x]`, and writes factual
Execution Notes. It pushes nothing and opens no PR. The launcher relays the executor's
factual summary and **offers** `/review-plan <plan-file>` — an offer, never an
auto-run.

**Verify:** the `plan/<slug>` branch exists with one commit per phase plus one
finalization commit (plan status → `done` + Execution Notes — the contract's own
completion step, not a duplicate phase commit); the plan file's status went
`approved → in-progress → done` and tasks read `[x]`; the tree is clean; no remote
ref or PR was created; the foreground reply contains the pre-flight line, the
summary, and the review offer. (Live run: branch
`plan/execute-launcher-smoke`, phase committed after validation `8c51757`, finalized
`baf0140`, tree clean, nothing pushed, offer made — observed as `/review`, the
offer's name before a later rename; the current `/review-plan` wording is
design-traced only and upgrades on the next live run.)

## Scenario 2 — Edge: pre-flight refusals — no executor is ever spawned

**Input:** Three separate invocations: (a) `/execute plans/nonexistent.md` — a
supplied path that doesn't exist (distinct from no-arg `/execute`, which is not a
refusal: pre-flight step 1 lists `plans/` and asks); (b) a plan whose status is not
`approved` (live: the completed smoke plan, status `done`); (c) an `approved` plan on
a dirty worktree (live: an approved untracked temp plan with the tree dirty).

**Expected output:** Each refuses with a clear, case-specific message — path error,
"approve it first (via `/plan`'s Gate 2)", "commit or stash first" — and stops. No
executor subagent is spawned, no branch is created, nothing is committed.

**Verify:** the refusal names the actual failing gate; `git status` and the branch
list are byte-identical before/after; no agent was launched. (All three live,
separate fresh invocations.)

## Scenario 3 — Edge: executor hits a real blocker → `[!]` + Amendment, no review offer

**Input:** A plan whose execution hits something genuinely unsettled or unsatisfiable
mid-run (live at executor level: an unsatisfiable test in the executor dogfood; a
genuine Phase-4 blocker in the reviewer-plan run on a real PR).

**Expected output:** The executor stops rather than deciding for the human: marks the
task `[!]`, appends an Amendment explaining the block, commits the progress so the
branch is clean, and ends with a clear blocker report — it does not edit tests or
spoof validation to get past the block. The launcher surfaces the blocker and the
Amendment and does **not** offer `/review-plan` — there is nothing complete to review.

**Verify:** the plan file shows `[!]` with a matching Amendment; completed phases are
committed (per-phase) and the branch is clean; the tests the plan named are untouched;
the foreground reply names the blocker and contains no `/review-plan` offer.
(Executor-side live twice: the first run stopped, marked `[!]`, amended, refused to
edit the test or use a spoofing hack; the second, a reviewer-plan run on a real PR,
produced Phases 1–3 per-phase commits, a real Phase-4 blocker, plan honest across
`draft → in-progress`, commits, and Execution Notes. The **launcher's** blocker relay —
surface + no-offer — has not been observed through a typed `/execute` and stays
design-verified.)

## Scenario 4 — Weird: run interrupted mid-plan → resume

**Input:** A multi-phase run via the typed launcher, deliberately interrupted after at
least one phase has committed but before the plan is `done`. Live fixture: a throwaway
repo with `plans/resume-live.md` on `plan/resume-live`, status `in-progress`, Phase 1
`[x]`, Phase 2 `[ ]`, and exactly one existing phase commit (`c0f0b41 Phase 1: seed
file`). Negative fixture in the same repo:
`plans/missing-branch.md`, status `in-progress`, with no
`plan/missing-branch`.

**Expected output:** `/execute` accepts `in-progress` only when the matching
`plan/<slug>` branch exists; it does **not** tell the operator to reset the plan to
`approved`. It refuses `approved` + existing branch and `in-progress` + missing branch
with a clear status/branch mismatch message. On resume, the executor verifies completed
phases against the plan's phase list and branch commits, skips completed phases, and
continues from the first incomplete phase. If every phase is complete but status is
still `in-progress`, it refuses as a status/checklist mismatch.

**Verify:** after interruption, the branch and plan file match the state above; after
resume, exactly one commit per phase exists (no duplicates), the plan reaches `done`
honestly, and mismatched branch/status refuses before spawning. (Live run:
state-machine fixture asserted `in-progress` + `plan/resume-live` exists is resumable,
and `in-progress` + no `plan/missing-branch` is a refusal. Completion produced
`c0f0b41 Phase 1: seed file`, `2c5ced1 Phase 2: resume marker`, and `c66a688 Finalize
resume live plan`; the plan reached `done`, both tasks were `[x]`, and the fixture tree
was clean. A true typed Claude `/execute` attempt against the fixture was also made, but
the local CLI exited before loading skills with `Not logged in · Please run /login`, so
that exact slash-command path remained auth-blocked in that session.)
