# Shared audit pipeline mechanics

Common mechanics for the audit orchestrators (`/code-audit`, `/security-audit`). The
skill that carries this file defines *what* its lenses look for and *what* a finding
must prove to survive; this file defines the shared *how*: pinning the scope, scaling
effort, deduplication, adversarial verification, and report-file naming. This file is
intentionally byte-identical in every skill that carries it — the repository gate
enforces that, so edit every copy together or none.

## Pin the baseline — before reading any code

Everything runs from the current worktree's directory, so sibling worktrees and the
main repo stay invisible.

- **Resolve the base ref.** Run `agentic resolve-base` from the target worktree and use
  its output as `<base-ref>`. This shared resolver prefers `origin/HEAD`, then existing
  remote-tracking `origin/main`/`origin/master`, then local `main`/`master`; do not
  reimplement or reorder that policy inside the skill.
- **Compute the merge-base:** `git merge-base <base-ref> HEAD`.
- **Capture the review span** — everything this branch changed vs the base, *committed
  or not*:
  - committed branch work: `git diff <base-ref>...HEAD` (three-dot, from the merge-base)
  - uncommitted tracked changes: `git diff HEAD`
  - untracked new files: `git status --porcelain --untracked-files=all` — the
    `--untracked-files=all` is essential, since the default mode collapses a newly
    added directory to a single `dir/` entry and would hide every file inside it.
    Include the full contents of each new (`??`) file.
- **Honor the args:** a `baseline` arg (SHA / branch / tag) overrides `<base-ref>`;
  `paths...` scope the diff to those files. A skill-level flag may override the diff
  scope entirely; the skill says so where it applies.
- **If the span is empty, stop** and say so — there is nothing to review. Do not
  manufacture work.
- **State plainly what is under review:** branch, base ref, file count, `+`/`−` line
  counts. This assembled diff is the **pinned scope** — every lens subagent sees
  exactly this and nothing else changes underneath it.

## Effort tiers

| Tier | Verification | Discovery | Thoroughness |
|------|--------------|-----------|--------------|
| `low` | 1 skeptic per finding | single pass | high-confidence findings only |
| `medium` | 1 skeptic per finding | single pass | standard sweep |
| **`high`** (default) | panel of 3, majority-kills | single pass | standard sweep |
| `max` | panel of 3, majority-kills | loop-until-dry | exhaustive sweep |

Effort scales *verification rigor + discovery persistence + how hard each lens looks*
— never the lens set. All of the skill's lenses always run at every tier; dropping
lenses to "go faster" is the wrong economy.

## Barrier, then dedupe

Wait for every lens subagent to return. Merge duplicates — two lenses will land on the
same defect; collapse them into one finding, keeping the clearest supporting scenario.
This dedupe happens *before* verification so skeptics are never spent on the same
finding twice.

## Adversarial verification — the gate

For each deduped finding, spawn verifier subagent(s). A verifier's **only** job is to
**refute** the finding — its default verdict is that the finding does not hold. A
finding **survives only if the verifier confirms the skill's survival bar** (the
concrete failure scenario or exploit path the skill defines). No confirmed scenario,
no survival.

- `low` / `medium`: one verifier per finding.
- `high` / `max`: a **panel of three** verifiers per finding; the finding dies unless
  a majority confirm it.
- `max` only — **loop-until-dry:** after verifying, re-run the full lens fan-out on
  the same pinned scope; keep going until a full round surfaces nothing new, then stop.

## Report file naming

Write the report to the skill's report directory as `<YYYY-MM-DD>-<slug>.md`. Get
today's date at runtime — `Get-Date -Format yyyy-MM-dd` on Windows, `date +%F` on
POSIX. `<slug>` is the current branch lowercased with `/` and non-kebab characters
replaced by `-` (the skill may define additional slugs for special modes). If the file
already exists (a same-day re-review), append `-2`, `-3`, ….
