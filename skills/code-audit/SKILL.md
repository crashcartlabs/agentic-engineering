---
name: code-audit
description: "Correctness-and-intent review of the current worktree's changes. Invoke as /code-audit [low|medium|high|max]. Fans out by-concern reviewer subagents, adversarially verifies every finding, and writes a read-only report to code-reviews/. Not refactor, security, performance, or testing — those are sibling skills. Explicit-trigger only."
---

# /code-audit — Correctness & Intent Review

You are the **orchestrator**. You do not review the code yourself — you pin the baseline, fan out reviewer subagents, adversarially verify what they find, and compile the report. Your judgment lives in the *dispatch and the verification*, not in a solo read-through. A single context reading a whole diff misses things a fan-out of focused, independent lenses catches; that is the entire point of this skill.

Invoked as `/code-audit [effort] [baseline] [paths...]`. Effort defaults to **high**.

## What this reviews — and what it does not

A **correctness + intent** review, nothing else. It answers exactly two questions:

- **Is the code wrong?** — logic errors, broken edge cases, bad null/async/error handling, data-integrity mistakes, contract/API misuse, races.
- **Does it do what the change was for?** — missing requirements, scope creep, regressions to existing behavior.

Explicitly **out of scope** — do not raise these as findings; each is a sibling skill or the linter's job: style, naming, readability, structure, duplication, **performance, security, test-writing, convention conformance.** The one adjacent thing you *may* flag — never fix — is a **correctness gap left uncovered by tests** ("this branch can misbehave and nothing catches it"); that names a risk, it does not write a test. If a genuinely serious out-of-scope issue jumps out, you may note it in a single trailing line, but it never becomes a numbered finding.

## Effort tiers

| Tier | Verification | Discovery | Thoroughness |
|------|--------------|-----------|--------------|
| `low` | 1 skeptic per finding | single pass | high-confidence findings only |
| `medium` | 1 skeptic per finding | single pass | standard sweep |
| **`high`** (default) | panel of 3, majority-kills | single pass | standard sweep |
| `max` | panel of 3, majority-kills | loop-until-dry | exhaustive sweep |

Effort scales *verification rigor + discovery persistence + how hard each lens looks* — never the lens set. All five lenses always run; dropping correctness lenses to "go faster" is the wrong economy.

## Pipeline

### 1. Pin the baseline — before reading any code

Everything runs from the current worktree's directory, so sibling worktrees and the main repo stay invisible.

- **Resolve the base ref.** Run `agentic resolve-base` from the target worktree and use
  its output as `<base-ref>`. This shared resolver prefers `origin/HEAD`, then existing
  remote-tracking `origin/main`/`origin/master`, then local `main`/`master`; do not
  reimplement or reorder that policy inside this skill.
- **Compute the merge-base:** `git merge-base <base-ref> HEAD`.
- **Capture the review span** — everything this branch changed vs the base, *committed or not*:
  - committed branch work: `git diff <base-ref>...HEAD` (three-dot, from the merge-base)
  - uncommitted tracked changes: `git diff HEAD`
  - untracked new files: `git status --porcelain --untracked-files=all` — the `--untracked-files=all` is essential, since the default mode collapses a newly added directory to a single `dir/` entry and would hide every file inside it. Include the full contents of each new (`??`) file.
- **Honor the args:** a `baseline` arg (SHA / branch / tag) overrides `<base-ref>`; `paths...` scope the diff to those files.
- **If the span is empty, stop** and say so — there is nothing to review. Do not manufacture work.
- **State plainly what is under review:** branch, base ref, file count, `+`/`−` line counts. This assembled diff is the **pinned diff** — every reviewer sees exactly this and nothing else changes underneath them.

### 2. Fan out the five lens reviewers — in parallel

Spawn five read-only reviewer subagents concurrently through the active harness's
delegation capability. Give each one: the pinned diff, **read access to the worktree for
surrounding context** (a bug is judged in context, not from the hunk alone), its lens
brief, and the findings contract below. Instruct each to report **only** findings within
its lens, in the contract's shape, and to return nothing (not filler) if its lens is
clean.

1. **Logic & control flow** — Is the algorithm correct? Wrong or inverted conditions, short-circuit mistakes, off-by-one, wrong operator/comparison, bad loop bounds, mis-ordered or unreachable branches, incorrect early returns.
2. **Edge cases & boundaries** — What inputs break it? Empty / null / zero / negative / max / single-element / duplicate / unicode inputs; boundary values; valid-but-unusual states the happy path ignores.
3. **Error handling, null-safety & concurrency** — Swallowed or misclassified errors, missing `await`, unhandled rejections, `null`/`undefined` dereferences, resource leaks (unclosed handles/connections), race conditions and ordering assumptions.
4. **Data & state integrity** — Incorrect mutations, stale or duplicated state, wrong state transitions, unsafe type coercion, serialization/parsing mistakes, and calling an API/contract the wrong way (wrong args, wrong order, ignored return or error).
5. **Intent & spec alignment** — Does the change do what it was *for*? Missing requirements, scope creep beyond the intent, regressions to existing behavior. If a spec is discoverable — a referenced issue/PR, a file in `plans/` or `docs/`, or the commit messages — judge against it; otherwise judge against the change's evident purpose.

### 3. Barrier, then dedupe

Wait for all five to return. Merge duplicates — two lenses will land on the same bug; collapse them into one finding, keeping the clearest failure scenario. This dedupe happens *before* verification so you never spend skeptics on the same bug twice.

### 4. Adversarial verification — the gate

For each deduped finding, spawn verifier subagent(s). A verifier's **only** job is to **refute** the finding — its default verdict is "not a bug." A finding **survives only if the verifier confirms a concrete failure scenario**: the specific input or state that makes the code misbehave, and what it does wrong. No scenario, no survival. "Looks fragile," "could be cleaner," or any claim with no reproducible trigger path is dropped, not reported.

- `low` / `medium`: one verifier per finding.
- `high` / `max`: a **panel of three** verifiers per finding; the finding dies unless a majority confirm the failure scenario.
- `max` only — **loop-until-dry:** after verifying, re-run the five lenses on the same pinned diff; keep going until a full round surfaces nothing new, then stop.

### 5. Compile and write the report

Write the report to **`code-reviews/<YYYY-MM-DD>-<branch-slug>.md`** in the worktree, in the shape defined by **`assets/report-template.md`** (structure + worked example + clean-bill variant). Get today's date at runtime — `Get-Date -Format yyyy-MM-dd` on Windows, `date +%F` on POSIX; `<branch-slug>` is the current branch lowercased with `/` and non-kebab characters replaced by `-`. If that file already exists (a same-day re-review), append `-2`, `-3`, … .

**Keep the report out of git without touching a tracked file.** The report directory must not show up in `git status`, the reviewed diff, or a commit — but editing the tracked `.gitignore` would itself dirty the worktree and pollute the very diff under review. So ignore it **locally** instead: find the git dir with `git rev-parse --git-common-dir` and ensure a `code-reviews/` line exists in `<git-common-dir>/info/exclude` (create or append if missing). That file is never tracked and never part of a diff. Do not modify `.gitignore`.

Then surface a concise result in chat: the **Verdict** line, one line per finding (severity + defect + `file:line`), and the report path — not the whole file.

If nothing survives verification, say so plainly ("No correctness issues found") — both in chat and as the report body. Never invent findings to look thorough.

## Findings contract

Each finding — as it leaves a lens, through verification, and into the report — carries:

- `severity` — `BUG` (misbehaves on a realistic path) or `RISK` (misbehaves only under specific / less-likely conditions)
- `file`, `line`
- `defect` — one line, what is wrong
- `failure_scenario` — the concrete inputs/state → wrong behavior (this is the survival bar)
- `cause` — the actual reason in the code
- `fix_direction` — one sentence; for the report only, never acted on

## Report format

The report's structure, a worked example, and the clean-bill variant live in **`assets/report-template.md`** — write to match it. Order findings most-severe-first (every `BUG` before any `RISK`).

## Hard rules

- **Explicit-trigger only.** Never auto-run.
- **You orchestrate; the subagents review.** Do not substitute a solo read-through for the fan-out.
- **Read-only on the code.** Never edit, stage, or apply a fix to the code under review — not even an obvious one; fixing is a separate act by a separate caller reading this report. The skill's *only* filesystem writes are the report file under `code-reviews/` and the `code-reviews/` line in the local `info/exclude` — never a tracked project file.
- **No finding without a verifier-confirmed failure scenario.** That rule is the whole point — it is what makes the report trustworthy instead of noisy.
- **Stay in scope:** correctness + intent only. No style, performance, security, or test-writing as findings.
- **Everything resolves from the worktree cwd.** Never reach into another worktree or the main repo.
