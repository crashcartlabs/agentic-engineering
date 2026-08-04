---
name: cleanup-worktrees
description: "Remove git worktrees that are clean and fully merged into main, and only those. Use when asked to clean up, sweep, or prune worktrees. Checks each worktree's status is empty, refreshes `origin/main`, and confirms the branch is merged via both `git branch --merged` and a merge-base ancestry check against `origin/main` (falling back to local `main` when no origin remote is available) before removing anything. Never deletes the local branch, and never touches a dirty or unmerged worktree. Invoke the `cleanup-worktrees` skill with `[path or name]` (no argument sweeps every worktree of the current repo)."
---

# cleanup-worktrees

## Purpose

Remove git worktrees whose work has already landed on `main`, so stale
worktree directories don't accumulate. This is a destructive filesystem
operation (it deletes a worktree's checkout), so it never runs on its own
initiative — it only runs when explicitly invoked — and it never removes a
worktree without first proving, independently, that the worktree is both
clean and merged.

## Scope

- No argument: sweep every worktree returned by `git worktree list` for the
  current repo, **excluding the main worktree** (the first entry listed —
  the primary checkout, not one created via `git worktree add`) **and
  excluding whatever worktree this skill is currently being invoked from**
  (compare each candidate's path against `pwd`/the current working
  directory before removing it) — these are not always the same worktree,
  and removing the one the running session is sitting in can leave its
  shell/process in a broken state (cwd no longer resolves).
- An argument: treat it as a path or branch name and resolve it to the
  matching entry in `git worktree list`. Operate on that single worktree
  only.
- All `git worktree remove` calls run from the main repo checkout (`git -C
  <main-repo-root> worktree remove <path>`), never from inside the worktree
  being removed.

## Procedure (per worktree)

Run every step below for each worktree in scope, in order. Do not skip a
check to save time — a worktree only gets removed after every check below
passes.

1. **Clean check.** `git -C <worktree> status --short --ignored` must
   produce no output. **Do not use plain `git status --short` (no
   `--ignored`) for this check** — it does not report ignored files at all,
   only untracked/modified/staged tracked content, so a worktree containing
   nothing but an ignored file (e.g. a `.env` with real secrets, matched by
   the repo's `.gitignore`) reads as completely empty from the plain form
   even though `git worktree remove` (step 6) will delete that file with it,
   without needing `--force` and without any warning. "Ignored" is not the
   same as "safe to delete" — treat any ignored file the same as a dirty
   tracked one. If `--ignored` produces any output (untracked, modified,
   staged, **or ignored**), **stop for this worktree**: do not touch it
   further. Record it as skipped with reason "uncommitted changes" (tracked
   output) or "contains ignored files: <list them>" (ignored-only output) and
   move to the next worktree. Note that the merge check (step 4) will still
   list a merged branch even when its worktree is dirty — this clean check
   is the load-bearing gate, not the merge check alone.
2. **Current branch.** `git -C <worktree> branch --show-current`. If this is
   empty (detached HEAD), skip the worktree and report "detached HEAD, no
   branch to check merge status against" — do not remove it.
3. **Refresh main.** `git -C <worktree> fetch origin main --quiet`. This
   updates the `origin/main` remote-tracking ref — **not** local `main` —
   so steps 4-5 compare against `origin/main` when it's available (see
   below). If this fails (no `origin` remote, no network, etc.), don't
   hard-fail the whole run — fall back to comparing against local `main` in
   steps 4-5 and continue.
4. **Merge check (primary).** Pick the ref to check against: `origin/main`
   if it exists (refreshed by step 3, or already present from an earlier
   fetch), otherwise local `main`. Run `git -C <worktree> branch --merged
   <ref>` and confirm the branch name from step 2 appears in that list.
5. **Merge check (corroborating).** Using the same ref chosen in step 4,
   run `git -C <worktree> merge-base --is-ancestor <branch> <ref>` (exit
   code 0 means the branch's tip is reachable from `<ref>` — true for a
   fast-forward merge just as much as a true merge commit, so this doesn't
   depend on a literal merge commit existing). This is a second,
   independent confirmation — don't skip it even when step 4 already says
   merged. Like step 4, it does not detect a squash-merged branch — see
   Known limitations below.
6. **Decide.**
   - If clean (1) **and** both merge checks (4, 5) confirm the branch is
     merged: remove it — `git -C <main-repo-root> worktree remove <path>`.
   - Otherwise: do not remove it. Leave the worktree exactly as-is.
7. **Report** this worktree's outcome (see Output below).

Branch deletion (`git branch -d <branch>`) is **never** performed by this
skill, even after a successful removal. At most, mention it in the final
summary as a follow-up step the user can do themselves.

## Known limitations

- **Squash-merged branches are not detected.** A squash merge creates a new
  commit on `main`/`origin/main` with no ancestry link back to the original
  branch's tip, and GitHub's default squash-merge commit message (the PR
  title) typically doesn't reference the branch name either. Both merge
  checks (steps 4-5) will therefore read a squash-merged branch as
  unmerged, so its worktree is left alone rather than removed. This is
  safe — nothing gets deleted that shouldn't be — but it means
  squash-merged worktrees currently require manual cleanup.

## Output

Print a per-worktree line as each one is processed, then a final summary.
For each worktree include: path, branch, merged (y/n), clean (y/n), and the
action taken (removed / skipped — reason).

Example:

```
/path/to/wt-a   branch=feature/a   clean=yes  merged=yes  -> removed
/path/to/wt-b   branch=feature/b   clean=no   merged=?    -> skipped (uncommitted changes)
/path/to/wt-c   branch=feature/c   clean=yes  merged=no   -> skipped (not merged into main)
/path/to/wt-d   branch=feature/d   clean=no   merged=?    -> skipped (contains ignored files: .env)

Removed: 1   Skipped: 3
Branches left behind (delete manually if no longer needed): feature/b, feature/c
```

## Hard rules

- **Explicit-trigger only** (declared in `toolbelt.json` and provider metadata) — this never
  fires on its own initiative.
- **Never target the main worktree, however invoked.** This applies to both
  the no-argument sweep (which excludes it explicitly, see Scope) and a
  single-argument invocation — an argument that resolves to the main
  worktree must still be refused, not just backstopped by git's own
  refusal to remove the checkout it's currently using.
- **Never target the worktree this skill is currently running from, however
  invoked.** Same reasoning as the main-worktree rule above: the no-argument
  sweep excludes it explicitly (see Scope), and a single-argument invocation
  that resolves to it must still be refused.
- **Never remove a worktree that is dirty, unmerged, or detached.** No
  shortcuts, no assuming — both merge checks (steps 4 and 5) and the clean
  check (step 1) must pass.
- **Never delete a local branch.** That's a separate, optional, user-driven
  step.
- **Always remove from the main repo checkout**, never from inside the
  worktree being removed.
