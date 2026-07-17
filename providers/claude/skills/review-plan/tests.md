# tests - review-plan

Scenarios for the `/review-plan` plan-conformance reviewer (born `/review`; renamed during a
dogfood run when the slash menu showed both it and the harness built-in). Each names
the input, the expected verdict/behavior, and how to verify it.

**Status: live-verified** (full record at the end of this
file), with these named exceptions still design-verified only: Scenario 2's exact
unmapped-hunk input, Scenario 3's cannot-run-validation arm, Scenario 4's missing-branch
variant (c), and Scenario 5's third-pass cap refusal.

Last verified: live dogfood on a real `/execute` product, with a design trace for the named exceptions.

## Scenario 1 — Golden: a satisfied `done` plan → APPROVE

**Input:** A plan with status `done`, all tasks `[x]`, one commit per phase, Execution
Notes present. Its `plan/<slug>` branch exists; the diff is entirely mapped to plan tasks;
every phase's validation and the repo gate pass when re-run fresh; each success criterion is
backed by a test that goes red when the change is reverted.

**Expected:** `/review-plan` re-runs validation itself (never citing the executor's logs), maps
every hunk, confirms plan-file integrity, spawns one checker per criterion + the intent/scope
lens, and every criterion returns `PASS` with concrete evidence. Verdict **APPROVE**. Report
written to `reviews/<date>-<slug>.md`; chat shows the verdict line, one PASS line per
criterion, and the path. The report remains visible to git, and the plan metadata is stamped
with a `Review verdict` link to that report.

**Verify:** report header reads `Verdict: APPROVE`; every criterion row has a PASS with a
named test or observed behavior; the plan metadata table has a `Review verdict` row whose
value is `APPROVE` plus a real Markdown link from the plan to `../reviews/<date>-<slug>.md`;
`git status --porcelain -uall` shows the report file and plan metadata change until they are
committed.

## Scenario 2 — Edge: one criterion unmet + one unmapped hunk → REVISE

**Input:** A `done` plan where the tests pass, but (a) one success criterion has no test or
observable proof, and (b) one diff hunk (e.g. an unrelated logger tweak) maps to no plan task
and no Execution Note.

**Expected:** The per-criterion checker returns `FAIL` for the unproven criterion (a criterion
with no evidence is a FAIL, never a PASS); diff→plan mapping flags the unmapped hunk. Verdict
**REVISE**, with findings most-severe-first: the `[FAIL]` criterion above the `[SCOPE]`
unmapped hunk. The skill does not edit code, does not fix either issue, and hands both to the user.

**Verify:** report `Verdict: REVISE`; finding 1 is `[FAIL]` naming success criterion N; finding
2 is `[SCOPE]` naming the unmapped `file:line`; no code was modified
(`git status --porcelain -uall` clean of tracked changes).

## Scenario 3 — Weird: validation cannot run at all → BLOCKED

**Input:** A `done` plan whose validation command cannot execute in the environment (missing
tool / unreachable service), distinct from a command that runs and fails.

**Expected:** Verdict **BLOCKED**, not APPROVE and not REVISE. The report states the cause
(environment cannot run it vs the command itself is broken), evaluates no success criteria on
unrun tests, and fabricates no evidence. The empty-span case resolves the same way — BLOCKED,
never a manufactured PASS — with the cause split per the skill: a branch whose tip is an
ancestor of the base ref reports "fully merged — nothing left to diff; reviews run pre-merge
by design"; any other empty span on a `done` plan reports "nothing was built."

**Verify:** report `Verdict: BLOCKED`; the deterministic-check block shows `BLOCKED` on the
validation line with the cause; the success-criteria section says "not evaluated," with no
invented PASS/FAIL rows.

## Scenario 4 — Refusal: bad input spawns nothing

**Input (three variants):** (a) no/'missing' plan path; (b) a plan whose status is `draft`
or `approved` or plain `in-progress` with no `[!]` blocker task; (c) a plan with no
`plan/<slug>` branch.

**Expected:** Each is refused at pre-flight with a clear one-line message, and **no subagent
is spawned and no report is written** — a bad input never costs a fan-out. The blocker-scoped
exception: `in-progress` *with* a `[!]` task carrying a matching Amendment is accepted as a
blocker-scoped review, not refused.

**Verify:** the run ends at pre-flight with the refusal message; no `reviews/` file is created;
no checker subagent is launched.

## Scenario 5 — Evidence persistence + feedback-cap contract

**Input:** Any valid review run, then a second `/review-plan` of the same plan on the same day.

**Expected:** The only filesystem writes are the report under `reviews/`, the reviewed
plan's metadata rows (`Review verdict`, plus `Audit outcome` if existing audit evidence
matches the branch/slug), and removal of an exact stale local-exclude line (`reviews/` or
`/reviews/`) left by the old untracked-report flow. `.gitignore` is never edited;
code is never edited. If a broader local exclude would still hide `reviews/`, the run
refuses before writing a metadata link to a hidden report. The same-day re-review appends
`-2` to the filename and increments the cycle count in the header; a third pass at the cap
says "cap reached — handed to the user" rather than running a third automated review.

**Verify:** after a run, `git status --porcelain -uall` shows only the new review report and
the plan metadata row changes; `git diff -- .gitignore` is empty; `<git-common-dir>/info/exclude`
contains no active line that hides `reviews/` after the run; the second report is
`reviews/<date>-<slug>-2.md` with `cycle 2/2` in its header.

## Phase 4 dogfood — LIVE RECORD (fresh session)

Vehicle: a real `/plan → /execute → /review-plan` pipeline run on
`plans/<date>-plans-placeholder-lint.md` (the plan was approved; an executor agent built it
on `plan/plans-placeholder-lint` with per-phase commits). Three review runs total.

**Probe A — nested fan-out (assumption falsified).** A delegated subagent had access to
the harness's delegation capability and successfully spawned a nested agent ("pong" round-trip observed). The
harness gained nested fan-out since the plan was written; top-level stays as a design
choice (the `/code-audit` precedent) — SKILL.md's rationale paragraph updated to say so.

**Probe B — name shadowing (assumption falsified → rename).** Model-side `Skill("review")`
loaded the harness built-in GitHub-PR review (it treated the plan path as a PR ref); the slash
menu was confirmed to show BOTH entries. Per the skill's own contingency: renamed
`review` → `review-plan` (dir, frontmatter, cross-references in `/execute` and
`executor.md`). The new name registers next session.

**Scenario 4 (refusals) — live, variants (a)+(b).** (a) missing path
`plans/<date>-nonexistent.md` → one-line refusal at gate 1; (b) the lint plan while
genuinely `draft` → refusal at gate 2. Both: no `reviews/` file written, no subagent
spawned. Variant (c) (missing branch) remains design-verified. The blocker-scoped
*acceptance* arm also ran live: `in-progress` + 4 `[!]` + matching Amendment was accepted,
not refused (see the BLOCKED run below).

**Scenario 2-shaped REVISE — live (cycle 1/2).** Report
`reviews/<date>-plans-placeholder-lint.md`. All 5 criteria PASS (checker fan-out: 5
per-criterion + intent/scope lens, single message, read-only, scratch-copy experiments
only); verdict REVISE on three findings most-severe-first: `[FAIL]` missing-row rule had
no red-when-removed test (lens proved it by deleting the rule on a scratch copy —
selftest stayed green), `[PLAN]` the plan's own allowlist missed two live template tokens
(finding against the plan, per the skill), `[INTEGRITY]` disclosed deviation with
`Amendments: _None yet._`. Reviewer fixed nothing; fix + re-review was chosen. Note: the
scenario's exact input (unmapped hunk) did not occur — that variant stays design-verified;
the REVISE mechanics (ordering, no-fix, hand-to-the-user) are live-verified.

**Scenario 1 (golden APPROVE) — live (cycle 2/2).** After the executor's fix commit
(`b21a110`) against the re-approved plan: fresh re-validation (lint corpus exit 0,
`--selftest` exit 0 incl. missing-row fixture, `check_all.py` PASS), full-span re-pin
(+473/−2 over 6 commits), 7/7 criteria PASS with independent evidence (every lint rule
mutation-verified red by a checker), Amendments ↔ deviations matched both ways, verdict
APPROVE with findings "None", one low residual in Notes. Report
`reviews/<date>-plans-placeholder-lint-2.md`.

**Scenario 5 (old read-only + cycle cap) — historical live record.** Same-day re-review correctly wrote the
`-2` suffix and `cycle 2/2` header with explicit cap language ("no further automated
pass"). `git status --porcelain -uall` after every run: zero tracked changes; reports
excluded via a `reviews/` line in `$(git rev-parse --git-common-dir)/info/exclude`;
`.gitignore` untouched. The third-pass refusal itself was not exercised (no third pass
was requested) — design-verified. A later change intentionally supersedes the local-exclude part:
future reports are tracked and the plan carries the verdict row.

**Scenario 3 (BLOCKED) — empty-span arm live.** `/review-plan` on
`plans/<date>-reviewer-agent.md` (blocker-scoped acceptance) found its metadata branch
fully merged into origin/main → merge-base == tip → empty span → BLOCKED, criteria "not
evaluated", nothing spawned, no fabricated evidence
(`reviews/<date>-reviewer-agent.md`). A design note surfaced for the user was resolved
as by-design (option 1): reviews run pre-merge; the skill's
empty-span rule now splits the BLOCKED cause into "fully merged — nothing left to diff"
vs "nothing was built." The cannot-run-validation arm stays design-verified.

Reports live under `reviews/`; that directory is now tracked evidence, so future
clones keep the full reports as well as the plan-metadata verdict summary.
