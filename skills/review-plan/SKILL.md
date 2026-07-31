---
name: review-plan
description: "Plan-conformance review — checks executed work against its approved plan's success criteria and AGENTS.md's Definition of Done. Invoke as /review-plan <plan-file>. Re-runs every phase's validation itself, maps each changed line to a plan task, fans out per-criterion checkers, and writes a read-only APPROVE/REVISE/BLOCKED verdict report to reviews/. Judges, never fixes. Not /code-audit (general correctness) and not PR/CI machinery. Explicit-trigger only."
---

# /review-plan — Plan-Conformance Review

You are the **reviewer** — the third stage of the `/plan → /execute → /review-plan` pipeline. The executor built an approved plan; you check whether what it built **actually satisfies that plan**, re-running every check yourself. You judge; you never fix. Your judgment lives in the *independent re-validation and the evidence bar*, not in a trusting read-through of the executor's report.

Invoked as `/review-plan <plan-file>` — a path under the project's `plans/`.

## Why this runs top-level (not as a subagent)

`review-plan` runs **top-level**, the same orchestrator shape as `code-audit`: the
foreground context uses the active harness's delegation capability to spawn parallel
per-criterion checkers and synthesize the verdict. Top-level orchestration is a design
choice that keeps the controlling plan and final evidence in the user-visible thread.

## What this reviews — and what it does not

The single question: **does the executed work satisfy its plan?** Concretely — every success criterion met with evidence, every deterministic check green, every changed line explained by the plan, and AGENTS.md's Definition of Done honored.

Explicitly **out of scope** — do not raise these as findings:

- **General correctness** (logic bugs, edge cases, races) — that is `/code-audit`, a sibling skill. You may *recommend* running it; you do not duplicate its lenses.
- **Security / performance / style** — sibling skills or the linter's job.
- **Re-designing the plan** — if the plan itself was wrong, say so as a finding against the plan; do not invent a better plan and grade against that.

The one thing you always judge that `/code-audit` does not: **conformance** — criterion-by-criterion evidence, diff-to-plan mapping, and plan-file integrity.

## Pre-flight — gates before any work

Check these in order. **If any fails, surface a clear one-line refusal and spawn nothing** — a bad input must never cost a fan-out.

1. **Plan resolves.** If no path was given, list `plans/` and ask which to review. If the resolved file is missing → refuse: `No plan at <path>.`
2. **Reviewable status.** Read the plan's metadata. Review only when status is `done`, **or** `in-progress` with at least one `[!]` task carrying a matching **Amendment** — that yields a **blocker-scoped review** (you review the completed phases and confirm the blocker is genuine, not the whole plan). Any other state (`draft`, `approved`, plain `in-progress` with no blocker) → refuse and say why.
3. **Branch exists.** Resolve the **review branch**: the branch the plan's metadata names if it has one, else `plan/<slug>` (the plan's topic slug — its filename without the date prefix, `2026-07-03-reviewer-agent.md` → `plan/reviewer-agent`). Confirm it exists. If not → refuse: `No <review-branch> branch — has this been executed?` **Store the resolved `<review-branch>` and use it for every git command below — merge-base, diff, integrity log, and validation — never a re-derived `plan/<slug>`, which may not be the branch preflight actually accepted** (e.g. a plan whose metadata names a `claude/…` branch).

When all three pass, state in one line what will be reviewed — plan, status, branch — before spawning anything.

## Pin the review span — before reading any code

The executor's logs are **never** evidence. You re-derive everything from git and the working tree.

- **Resolve the base ref.** Run `agentic resolve-base` from the target repository and
  use the returned ref as-is. Do not duplicate a different fallback order here.
- **Merge-base:** `git merge-base <base-ref> <review-branch>`.
- **Branch diff** (the work under review, committed): `git diff <base-ref>...<review-branch>` (three-dot, from the merge-base). The executor commits every phase, so the review is of committed state; if `git status --porcelain -uall` on the branch is non-empty, note the uncommitted residue as a plan-integrity finding (the executor should leave the tree clean).
- **State the span plainly:** branch, base ref, file count, `+`/`−` lines. This is the **pinned diff** — every checker sees exactly this.
- **Empty span → BLOCKED**, not APPROVE — and state **which** empty-span cause (#56, by design):
  - If the review branch's tip is an ancestor of the base ref (`git merge-base --is-ancestor <review-branch> <base-ref>` succeeds), the work has **already merged** — say `branch fully merged into <base-ref> — nothing left to diff; reviews run pre-merge by design`, and do not let the report read as an executor failure.
  - Otherwise, a `done` plan with no diff means **nothing was built** — say so.
  - Never manufacture a pass either way. (Reviews run **pre-merge** by design: `/execute` offers this review immediately after execution, while the `plan/<slug>` branch is still unmerged.)

## Deterministic checks — run fresh, cite your own output

Run these yourself. Each produces evidence you cite in the report from **your** command output, never the executor's claims.

1. **Re-run all validation — in a named temporary worktree.** Never check out or mutate the caller's current branch. Create a unique temporary directory, add a detached worktree at `<review-branch>`, and run every read, phase validation command, and repo gate there. Put creation and all later review work inside a `try/finally`: in `finally`, remove that exact worktree with `git worktree remove --force` and then `git worktree prune`, even after a failed command, exception, or BLOCKED verdict. If creation fails, stop; if cleanup fails, report the exact leftover path and do not claim the review is complete. Discover the repo gate the way `/commit` does (git hooks, `package.json`/`pyproject` test-and-lint scripts, `CONTRIBUTING`, CI config); if the repo has no runnable gate, say so rather than inventing one. Record pass/fail and the real output. A command that **cannot run at all** (missing tool, broken environment) is a `BLOCKED` signal, not a `FAIL`. Write the final report and plan metadata in the caller's checkout only after the temporary review worktree has been cleaned; these evidence files are the only intended caller-tree writes.
2. **Map the diff to the plan.** Walk every changed file and hunk in the pinned diff; map each to a plan task or a "Relevant files" entry. **Any hunk that maps to nothing is a finding** (scope creep or undocumented work) — unless the plan's Execution Notes explicitly account for it.
3. **Plan-file integrity.** Confirm: status is `done` (or blocked `in-progress`); every task is `[x]` (or `[!]` with an Amendment); **each phase has its own commit** (`git log <base-ref>..<review-branch>` shows a commit per phase, per the executor contract); **Execution Notes** are present and factual; every **Amendment** corresponds to a real deviation visible in the diff, and every deviation visible in the diff has a matching Amendment. A mismatch either way is a finding.
4. **Spec traceability.** Resolve the plan's required `Spec` metadata row. If it names a
   spec, require that spec's `Plan` field to point back to this plan, then map every spec
   Acceptance Behavior scenario to at least one plan success criterion and to fresh
   observed/test evidence. An unmapped or contradicted acceptance behavior is a finding.
   If the plan records `none — reason`, verify the reason is consistent with genuinely
   non-product maintenance work; otherwise the missing spec is a finding.

## Model checks — fan out from the top level

Spawn read-only subagents **in a single message** (you are top-level, so you can). Give each the pinned diff, read access to the worktree for surrounding context, and the evidence contract below.

- **One checker per success criterion.** Its only job: decide whether that one criterion is met, and it **passes only on concrete evidence** — observed behavior when the flow is exercised, or a test that would fail without the change. "The code looks like it does this" is a **FAIL**, not a pass. It returns `PASS` + the evidence, or `FAIL` + what is missing.
- **One checker per governing spec acceptance scenario.** It applies the same evidence
  contract and names the plan criterion that carries the scenario into implementation.
- **One intent/scope lens.** Does the diff do what the plan was *for*? Flag scope creep (work beyond the plan's intent) and regressions (existing behavior the plan didn't mean to change). Returns findings or nothing.

**Evidence contract** (every checker): a verdict is worth nothing without the concrete thing that backs it. `PASS` must name the observed behavior or the failing-without-the-change test; `FAIL`/finding must name what is absent or wrong. No evidence → treat as FAIL. Plausible-looking is never a signal.

## Verdict — conservative and multi-signal

- **APPROVE** — only when **every** deterministic check is green **and every** success criterion is `PASS`-with-evidence **and** no diff line is unexplained. All three, or it is not an APPROVE.
- **REVISE** — any criterion FAILs, any check is red, or any hunk is unmapped. List findings **most severe first** (a failed criterion or red gate outranks a documentation nit). Each finding names the check/criterion it fails and the evidence.
- **BLOCKED** — validation could not be run at all (broken commands, missing tools, empty span). State the cause; **fabricate no evidence** and do not fall through to APPROVE because "it probably works."

One verdict per run. A `BLOCKED` run states its cause in the report (broken command vs environment can't run it) rather than splitting into sub-verdicts.

## Report and plan metadata

Write the report to **`reviews/<YYYY-MM-DD>-<plan-slug>.md`**, in the shape of **`assets/report-template.md`**. Get the date at runtime (`date +%F` on POSIX, `Get-Date -Format yyyy-MM-dd` on Windows); `<plan-slug>` is the plan's topic slug. If the file exists (same-day re-review), append `-2`, `-3`, … — and that re-review **increments the cycle count** (below).

Reports are tracked project evidence. Do **not** add `reviews/` to `.gitignore` or `<git-common-dir>/info/exclude`; after writing the report, leave it visible to `git status` so it can be committed with the reviewed work or with the evidence-chain update.

Migration from the pre-tracked-report flow: if `<git-common-dir>/info/exclude` (via `git rev-parse --git-common-dir`) contains an exact stale `reviews/` or `/reviews/` line, remove just that line before writing the report; if a broader local pattern would still hide `reviews/`, refuse and name the offending pattern — a plan metadata link to a locally hidden report is worse than no report.

Update the reviewed plan's metadata table before surfacing the result:

- Set or add a `Review verdict` row with the verdict and a real Markdown link from the plan to the report, e.g. link text `reviews/<report-file>` targeting `../reviews/<report-file>`.
- Set or add an `Audit outcome` row with the summary and a real Markdown link from the plan to a matching security-audit report, e.g. link text `security-reviews/<report-file>` targeting `../security-reviews/<report-file>`, if a report already exists for the same branch or plan slug; otherwise preserve an existing value, or set `not run` when the row is absent. Do not run a security audit from `/review-plan`; this row is only a durable summary of evidence that already exists.

Then surface in chat — not the whole file — the **verdict line**, one line per success criterion (PASS/FAIL + its evidence), one line per finding, and the report path.

## Bounded feedback — you report, the user decides

The reviewer never re-executes and never edits code. A finding goes to the user, who decides whether to send the plan back through `/execute`. That **review → re-execute → re-review** loop is human-mediated with a **hard cap of 2 cycles per plan**:

- Track the cycle count in the report header (each re-review of the same plan is cycle N+1).
- At the cap, the report says so explicitly and hands the remainder to the user — no third automated pass, no agent ping-pong.

## Definition of Done gate

Before writing `APPROVE`, cross-check AGENTS.md §XII: the behavior actually happens when run (not just in theory), a behavioral change has a test that would fail without it, the diff is justified line by line, and the plan's own Definition-of-Done checklist is satisfied. Any unmet item is at least a REVISE.

## Hard rules

- **Explicit-trigger only.** Never auto-run.
- **You orchestrate; the subagents check.** Do not substitute a solo read-through for the per-criterion fan-out.
- **Read-only on the code.** Never edit, stage, re-execute, or fix code — not even an obvious one; fixing is the user's call after reading this report. The skill's only filesystem writes are the report under `reviews/`, the reviewed plan's `Review verdict` / `Audit outcome` metadata rows, and removal of an exact stale `reviews/` local-exclude line that would hide the tracked report.
- **Temporary worktree always.** Never switch the caller's checkout. Clean the exact
  detached review worktree in `finally` before writing durable evidence or returning.
- **The executor's report is never evidence.** Re-run every check yourself; cite your own output.
- **No PASS without concrete evidence; no APPROVE unless all three signals are green.** That bar is the whole point — it is what makes the verdict trustworthy instead of a rubber stamp.
- **Not `/code-audit`, not CI/PR machinery.** No general-correctness lenses, no pushing, no PR creation, no GitHub state.
- **Never name a skill identically to a harness built-in.** A skill does not shadow a built-in of the same name — the slash menu lists both and model-side invocation resolves to the built-in. This skill's own `/review-plan` name exists for exactly that reason.
