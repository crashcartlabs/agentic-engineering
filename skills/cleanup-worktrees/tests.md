# tests — cleanup-worktrees

Manual verification scenarios for the `cleanup-worktrees` skill. Run these in a
scratch repo, not this repo, since the skill deletes worktree directories.

Status: design-verified; the scenarios below still require a fresh
live scratch-repository run after the provider-neutral migration.

## Setup

```bash
mkdir /tmp/cleanup-worktrees-test && cd /tmp/cleanup-worktrees-test
git init -q repo && cd repo
git commit --allow-empty -q -m "init"
git checkout -b main -q 2>/dev/null || git branch -m main

# merged + clean worktree -> should be removed
git worktree add -q -b merged-clean ../wt-merged-clean
git -C ../wt-merged-clean commit --allow-empty -q -m "work"
git merge -q merged-clean

# merged + dirty worktree -> should be skipped
git worktree add -q -b merged-dirty ../wt-merged-dirty
git -C ../wt-merged-dirty commit --allow-empty -q -m "work"
git merge -q merged-dirty
echo "uncommitted" >> ../wt-merged-dirty/scratch.txt

# unmerged + clean worktree -> should be skipped
git worktree add -q -b unmerged-clean ../wt-unmerged-clean
git -C ../wt-unmerged-clean commit --allow-empty -q -m "work not yet merged"

# merged, but with an ignored .env file -> should be skipped, not removed
echo ".env" >> .gitignore
git add .gitignore
git commit -q -m "ignore .env"
git worktree add -q -b merged-ignored-content ../wt-merged-ignored-content
git -C ../wt-merged-ignored-content commit --allow-empty -q -m "work"
git merge -q merged-ignored-content
echo "SECRET=abc123" > ../wt-merged-ignored-content/.env
```

## Scenario 1 — Golden: sweep with no argument

**Input:** `/cleanup-worktrees` run with no argument in `repo`, with the four
worktrees set up above plus the main worktree.

**Expected output:** `wt-merged-clean` is reported clean=yes merged=yes and
removed (`git worktree list` no longer shows it, and
`/tmp/cleanup-worktrees-test/wt-merged-clean` no longer exists).
`wt-merged-dirty` is reported clean=no and left untouched. `wt-unmerged-clean`
is reported merged=no and left untouched. `wt-merged-ignored-content` is
reported clean=no (skipped — contains ignored files: `.env`) and left
untouched, even though it is merged and `git status --short` (without
`--ignored`) on it alone would report nothing. The main worktree is never
considered. No local branch is deleted — `git branch` still lists
`merged-clean`, `merged-dirty`, `unmerged-clean`, and
`merged-ignored-content`.

**Verify:** `git worktree list` shows only the main worktree and the three
skipped worktrees; `git branch` still lists all four feature branches;
`../wt-merged-ignored-content/.env` still exists with its original content.

## Scenario 2 — Edge: targeted single-worktree invocation

**Input:** `/cleanup-worktrees ../wt-merged-dirty` (or the branch name
`merged-dirty`), invoked directly instead of a full sweep.

**Expected output:** Only that worktree is evaluated. Since it's dirty, it's
reported skipped with reason "uncommitted changes" and nothing is removed.

**Verify:** `wt-merged-dirty` directory and branch both still exist; no other
worktree is touched.

## Scenario 3 — Weird: no `origin` remote

**Input:** Run the golden sweep (Scenario 1) in a repo with no `origin`
remote configured (the scratch repo above has none by default).

**Expected output:** The `git fetch origin main --quiet` step fails
gracefully — the run continues using the local `main`, and the rest of the
sweep produces the same results as Scenario 1 rather than aborting entirely.

**Verify:** The run completes and reports all four worktrees' outcomes
instead of stopping on the fetch failure.

## Scenario 4 — Known limitation: squash-merged branch is not detected

**Input:** Set up one more worktree the same way as the others, but land its
work via a squash merge instead of a regular merge:

```bash
git worktree add -q -b squash-merged ../wt-squash-merged
echo "content" > ../wt-squash-merged/file.txt
git -C ../wt-squash-merged add file.txt
git -C ../wt-squash-merged commit -q -m "work"
git merge --squash squash-merged -q
git commit -q -m "squashed work"
```

(Note: the branch's commit must actually change a file — `--allow-empty`
produces no diff, so `git merge --squash` has nothing to stage and the
squash commit never happens.)

Then run `/cleanup-worktrees` with no argument.

**Expected output:** `wt-squash-merged` is reported clean=yes merged=no and
left untouched — per the documented "Known limitations" caveat, neither
merge check can see the ancestry link (the squash commit on `main` has no
parent relationship to `squash-merged`'s tip), so this worktree is
(safely) never cleaned up automatically.

**Verify:** `git worktree list` still shows `wt-squash-merged`; the
directory and the `squash-merged` branch are untouched.

## Scenario 5 — Data loss regression: ignored content must not be silently deleted

**Input:** `/cleanup-worktrees ../wt-merged-ignored-content` (or the branch
name `merged-ignored-content`), invoked directly instead of a full sweep.
This worktree is merged and reports empty from `git status --short`, so a
clean check that doesn't also look for ignored files would treat it as
removable.

**Expected output:** The worktree is reported clean=no (skipped — contains
ignored files: `.env`) and nothing is removed, even though it is merged.

**Verify:** `git -C ../wt-merged-ignored-content status --short` prints
nothing (confirming this worktree would have looked "clean" under the old,
narrower check), but `git -C ../wt-merged-ignored-content status --short
--ignored` prints `!! .env`. After running the skill,
`../wt-merged-ignored-content/.env` still exists and still contains
`SECRET=abc123`, and `git worktree list` still shows
`wt-merged-ignored-content`.

## Teardown

```bash
cd /tmp && rm -rf cleanup-worktrees-test
```
