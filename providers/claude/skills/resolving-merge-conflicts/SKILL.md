---
name: resolving-merge-conflicts
description: "Resolve git merge, rebase, or cherry-pick conflicts safely — reconstruct the result that honors both sides' intent, or abort when that isn't possible. Use when a merge/rebase/cherry-pick stops with conflicts, when `git status` shows unmerged paths, or when a pull leaves conflict markers in files. Works only in the current worktree and hands ambiguous conflicts to the human. Not for blindly force-resolving to one side, teaching git basics, or resolving a conflict whose correct outcome is genuinely unclear — those get aborted or handed back."
---


# Resolving merge conflicts

A conflict is git refusing to guess: two changes touched the same region and it will
not pick for you. Your job is to reconstruct the **one correct result that honors both
intents** — or to recognize this conflict is not yours to resolve and **abort**.
Low-risk means: touch only the conflicted regions, keep the operation recoverable, and
never invent a resolution when a side's intent is unclear (§II — plausible-looking code
is exactly the code that passes review and fails when it matters).

## 1. Orient — before touching a single file

Conflict state (`MERGE_HEAD`, an in-progress rebase, the unmerged index) is
**per-worktree** — it lives in *this* worktree's git dir. Read it here; resolve it here.
Never reach into a sibling worktree or the main checkout to "help" — you would be editing
a tree whose owner is mid-operation.

- **Which operation?** `git status` names it — "You are currently rebasing", "…merging",
  "…cherry-picking" — and lists the unmerged paths. That state word decides which
  `--continue` / `--abort` you finish with; using the wrong one is its own failure.
- **Which files?** `git diff --name-only --diff-filter=U` is the exact conflicted set.
  `git ls-files -u` shows the unmerged index entries behind them.

## 2. Understand both sides — read before you write (§I)

You cannot preserve an intent you have not read. For each conflicted file:

- The three inputs are addressable: `git show :1:<file>` is the **common base**,
  `:2:<file>` is **ours**, `:3:<file>` is **theirs**.
- `git log --merge -p -- <file>` shows the commits on each side that touched this file —
  *why* each change exists, not just what it says.
- When the log alone doesn't explain a side, follow it upstream: the PRs and the original
  issues/tickets behind each side's commits state the intent the diff only implies.
- **The ours/theirs labels invert during a rebase and cherry-pick.** In a merge, "ours"
  is your branch. In a rebase, "ours" (`:2:`, `--ours`) is the upstream you are replaying
  *onto*, and "theirs" (`:3:`, `--theirs`) is your own commit being replayed. Confirm
  which operation you are in (Step 1) before trusting either label, or you will keep the
  wrong side with full confidence.

## 3. Decide — resolve or abort

Aborting is not failure. `git merge --abort` / `git rebase --abort` /
`git cherry-pick --abort` restore the **exact** pre-operation state — it is recoverable,
low-risk, and often the *correct* answer. Stop and abort (or escalate) when:

- **Wrong operation** — wrong branch, wrong rebase base, or the wrong commit cherry-picked.
  Nothing downstream is worth resolving; abort, fix the target, restart.
- **A side's intent is unclear** — you cannot tell what one change was *for*, so you cannot
  preserve it. Do not fill the gap with a plausible merge (§II). Lay out both sides and
  hand the decision to the human.
- **Too large or tangled to resolve safely** — many files, deeply interleaved semantic
  changes, or **generated artifacts** (lockfiles, bundles, snapshots) that diverged.
  Regenerate those from source rather than hand-merging line noise; if the *semantic*
  conflict is beyond confident resolution, abort and escalate.
- **A rebase where the same conflict recurs commit after commit** — a signal the base or
  the approach is wrong. Stop and reconsider strategy instead of re-resolving the same
  clash ten times.

Only when you can state what both sides intended and how they combine do you proceed to
resolve.

## 4. Resolve — hunk by hunk, intent preserved

Work one conflicted region at a time. For each, write the code that achieves **both**
sides' purpose — not merely whichever half you deleted last.

- Picking a whole side wholesale (`git checkout --ours` / `--theirs <file>`) is right only
  when you *know* one side genuinely supersedes the other. Blind side-picking is the exact
  failure this skill exists to prevent — most real conflicts need a combined region.
- Change only what is inside the conflict; leave the rest of the file alone (§IV — a
  surgical diff). Do not reformat or "tidy while I'm here."
- Stage each file as you finish it: `git add <file>` (or `git rm` for a delete/modify
  conflict you resolve as a delete). Staging is how you tell git the region is settled.

## 5. Verify — markers gone, gate green

Two independent checks, both cross-platform because they are git's own tools:

- **No markers survive — staged *and* unstaged.** `git diff --check` only inspects the
  working tree, so once you `git add` a resolved file (Step 4) a marker in the *staged*
  content slips past it — a staged file containing `<<<<<<<` returns 0 from
  `git diff --check`, and `git ls-files -u` is empty too (git already considers it merged).
  So check the staged tree explicitly: **`git diff --cached --check`** (plus `git diff --check`
  for anything still unstaged), or equivalently `git diff --check HEAD`. All must exit
  clean, and `git ls-files -u` must come back **empty**. A marker committed into a file is a
  broken build shipped as "resolved."
- **Re-run the repo's gate.** A conflict resolution is a behavioral change (§V) — run the
  checks the repo itself expects and make them green before continuing. Discover the gate
  the same way `/commit` does (hooks, package scripts, CONTRIBUTING, CI); don't duplicate
  that logic here.

## 6. Finish — with the operation's own tool

- Complete with the matching continuation: `git merge --continue`,
  `git rebase --continue`, or `git cherry-pick --continue`. `git status` from Step 1 told
  you which. `--continue` refuses while anything is still unmerged — that refusal is Step 5
  catching an unresolved file, not an error to work around.
- **Never `git stash` to escape a conflict.** The stash stack is **shared across every
  worktree** (it lives in the common git dir), and stashing around an in-progress operation
  destroys its sequencer state — it deletes `MERGE_HEAD`/`CHERRY_PICK_HEAD`, rewrites a
  picked commit's authorship to you, and silently drops the remaining rebase steps. To back
  out, use `--abort`, never a stash cycle. If unrelated dirty work was stashed *before* the
  operation began, record `git stash list` first and restore it after, leaving the shared
  stack exactly as you found it.

## Hard rules

- **Read both sides before editing; preserve both intents.** Never resolve a conflict you
  cannot explain — no blind `--ours`/`--theirs`, no plausible-looking guess.
- **Aborting is a valid resolution.** Wrong base, unclear intent, or a conflict too large to
  resolve safely → `--abort` and escalate. Do not force a resolution to look finished.
- **Escalate ambiguity to the human.** When a side's purpose is genuinely unclear, hand it
  over with both sides laid out — do not decide it for them.
- **Current worktree only.** Never reach into a sibling worktree or the main checkout, and
  never `git stash` around an in-progress operation — the stash is shared and it eats the
  sequencer state.
- **Not done until markers are gone and the gate is green.** `git diff --cached --check`
  (staged) and `git diff --check` (unstaged) clean — equivalently `git diff --check HEAD` —
  `git ls-files -u` empty, the repo's checks passing — then `--continue`.
