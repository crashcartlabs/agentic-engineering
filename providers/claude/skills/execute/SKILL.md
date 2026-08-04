---
name: execute
description: "Launches or resumes the executor on an approved or in-progress plan. Invoke the `execute` skill with `<plan-file>`. Pre-flights the plan, spawns the executor subagent to implement it autonomously, then relays the result and offers the review stack — `review-plan` plus `code-audit`. Explicit-trigger only."
disable-model-invocation: true
argument-hint: "<plan-file>"
---


# execute — Launch or resume the executor

A thin launcher. Your job is **pre-flight, spawn, relay** — not to do the implementation yourself. The executor subagent does the work autonomously.

Invoke the `execute` skill with `<plan-file>` (a path under the project's `plans/`).

## Pre-flight — check before launching

1. **Resolve the plan.** If no path was given, list `plans/` and ask which to run. Otherwise resolve the given path.
2. **Exists?** If the file is missing, stop and say so.
3. **Status + branch agree?** Read the plan's metadata and compute the plan branch:
   `plan/<slug>`, where `<slug>` is the plan filename without its leading
   `YYYY-MM-DD-` date prefix and without `.md`. Then check local branches.
   Require the plan's Branch row to equal the computed branch for both modes.
   - `approved` + matching Branch row + no `plan/<slug>` branch = start a new execution.
   - `in-progress` + matching `plan/<slug>` branch = resume the interrupted execution.
   - `approved` + existing `plan/<slug>` branch = stop: the plan says it has not
     started, but execution state already exists.
   - `in-progress` + no matching `plan/<slug>` branch = stop: the plan says execution
     started, but there is no branch to resume.
   - Any other status = stop with a status-specific message. For `draft`, tell the human
     to approve it first (via the `plan` skill's Gate 2). For `done`, say it is already complete.
4. **Tree safe for the mode?** Run `git status`.
   - For a new `approved` execution, the working tree must be clean before spawning.
   - For an `in-progress` resume, do not reject merely because the matching `plan/<slug>`
     branch has WIP; that is the interrupted state being resumed. If the current branch is
     not `plan/<slug>`, require a clean tree before the executor checks out the plan
     branch.

If any check fails, surface a clear message and do not spawn anything.

When all checks pass, say so in one line before launching — e.g.
`Pre-flight passed: plans/<file> approved, tree clean — launching executor.` or
`Pre-flight passed: plans/<file> in-progress with plan/<slug> present — resuming executor.` —
so the human sees the gate cleared before the handoff.

## Launch

Use the active harness's delegation capability to launch the installed **executor**
agent with the resolved plan-file path and pre-flight mode (`start` or `resume`) as its
brief. Claude loads the Markdown agent from the plugin, Codex loads the generated TOML
agent, and Pi exposes it through the installed `subagent` extension. **Hermes** loads
the executor prompt from the canonical `agents/executor.md` in the toolbelt repo (the
`hermes` provider installs a copy as a linked reference inside this skill) and
delegates through its delegation capability with that prompt as the agent brief. If the named agent
or delegation capability is unavailable, stop and run `agentic doctor`; do not silently
execute in the foreground. The executor runs autonomously on its own `plan/<slug>`
branch and returns a factual summary.

## After it returns

1. Relay the executor's factual summary to the human — what got built, anything that deviated, anything blocked.
2. **If it completed:** offer the review stack — the plan-conformance reviewer first
   (invoke the `review-plan` skill with `<plan-file>`), then the correctness audit (the `code-audit` skill) once the
   conformance review passes. Both run by default on every completed execution; the
   offer names both so the human knows the change is not review-complete after only
   one of them. An offer, never an auto-run; both are explicit-trigger only.
3. **If it stopped on a blocker:** surface the blocker and the relevant Amendment, then
   offer the supported blocker-scoped `review-plan <plan-file>` review as an explicit
   choice. Explain that it validates completed phases and whether the blocker is genuine;
   it does not approve the unfinished plan or restart execution.

## Hard rules

- Explicit-trigger only; never auto-launch.
- The pre-flight gates are not optional — no executing an unapproved plan, no starting
  against a dirty tree, and no resuming when plan status and branch state disagree.
- Never tell the human to reset an interrupted plan from `in-progress` back to
  `approved`. `in-progress` + matching `plan/<slug>` is the supported resume path.
- On a new run the executor writes `Status: in-progress` and the concrete Branch row in
  one atomic plan-file replacement, verifies both, and rolls back the newly created branch
  if that metadata transition fails.
- You are the launcher, not the worker. The executor subagent does the coding.
