# Triage Recipes

## Merge conflicts

A merge conflict surfaced by a check-in is handled like a CI failure: the deliverable
is a merge-ready PR. Prefer GitHub's branch update when available:

```sh
gh pr update-branch <url>
```

The scoped form is also safe:

```sh
gh pr update-branch --repo <owner>/<repo> <number>
```

Do not use bare `update-branch` or a bare number unless the current checkout is the
watched repo and branch: bare `update-branch` targets the current branch's PR, and a
bare number resolves against the current checkout's repo.

If updating manually, fetch the base first and merge the remote-tracking branch:

```sh
git fetch <remote> <base>
git merge <remote>/<base>
```

Merging a stale local base can push a no-op merge that leaves the PR conflicted. Never
rewrite pushed history for a normal sync. Resolve mechanical conflicts; ask the human
when the conflict lands in contested code.

If the repo's conventions demand linear history, the sync itself is a design call:
escalate it. Any agreed rebase touches only the PR's own branch and is pushed with
`--force-with-lease`.

## Delegation floor

The watcher owns the decision history, not the diff. Delegate real diagnose-and-land
work to a focused subagent or matching fixer skill, then return to the loop.

A phrase-level edit, such as a few lines of prose in one file, is faster done inline
than briefed out. This floor was confirmed across two live watches. Do not delegate
wording fixes just to preserve the pattern; delegate when the task needs diagnosis,
implementation, verification, and landing.

After any push, CI re-runs and the next webhook activity or check-in tells you whether
the fix worked. A fix is not done until the watcher sees it go green.
