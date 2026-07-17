---
name: commit
description: "Commit the current work only after the repo's own checks pass. Use when asked to commit, check in, or save work to git, when a finished task needs committing, or when asked to add pre-commit hooks (husky, pre-commit) to a repo. Discovers the repo's gate (hooks, package scripts, CONTRIBUTING, CI), runs it, fixes failures the work caused, and splits unrelated changesets into separate commits. Not for writing a commit message alone, rewriting history (amend, rebase), or pushing and PR creation (that's /ship)."
---


# Commit

Land the work like a careful maintainer: nothing commits until the repo's **gate** —
every check the repo itself expects — is green, and each commit is one coherent
changeset. Never `--no-verify`.

Two requests reach this skill: **committing work** and **setting up hooks**. Read
which one you got before Step 1. A setup-only request runs the same steps but
touches only the setup changeset — every other dirty file is left exactly as found
and reported, never fixed to satisfy the gate and never committed.

## Step 1 — Inventory from a fresh snapshot

Run `git status --porcelain -uall` (`-uall` — a bare `??  dir/` hides the files
inside it), `git diff --stat`, and `git diff --cached --stat` **now**;
any status from earlier in the conversation is stale — the tree can change under you
(a concurrent session may have already committed it).

Also probe for an operation in progress **now** — porcelain output never shows it:
`git rev-parse -q --verify MERGE_HEAD`, the same for `CHERRY_PICK_HEAD`, and test
for `rebase-merge`/`rebase-apply` dirs under `$(git rev-parse --git-path .)`. A
live sequencer changes Step 5's rules (finish with the operation's own
`--continue`, never a stash cycle) — miss it and a cherry-pick lands with you as
author and its remaining picks silently dropped.

- The staged/unstaged split expresses intent — preserve it unless it is wrong.
- Stat-dirty means empty in **both** `git diff` and `git diff --cached` for that
  file — a staged-only change (`M ` in the first porcelain column) is empty in the
  plain diff by design. A mode-only diff (`old mode`/`new mode`) is a real change —
  it travels with its changeset.
- Group every dirty file into a named changeset (feature, hook setup, docs, …).

**Completion criterion:** every dirty file is assigned to a changeset or explicitly
excluded, judged from output run just now. A clean tree → report "nothing to commit"
and stop — unless the request is hook setup, which needs no dirty files: continue to
Step 2. A file you cannot explain → ask before it goes anywhere near a commit.

## Step 2 — Discover the gate

Check all five sources, in order:

1. `git config core.hooksPath` — **any** value is a first-class gate source,
   whoever set it. Read the hooks it points at; if no known manager owns them (a
   hand-rolled `.githooks/`), those hooks are still the gate — and Step 3 must
   never let an installer repoint it.
2. Hook manager — `.husky/`, `.pre-commit-config.yaml`, `lefthook.yml` — and
   confirm it is *wired*: `core.hooksPath` points at it, or the resolved hook
   `$(git rev-parse --git-path hooks/pre-commit)` exists **and its content is that
   manager's**. Never test the literal `.git/hooks/pre-commit` path — `.git` is a
   file in linked worktrees, so a shared hook that demonstrably fires would read
   as missing; conversely, a hand-written hook sitting next to an uninstalled
   config is not wiring. A config file whose `install` never ran guards nothing;
   treat it as a gate to run, and Step 3 as the place to wire it.
3. Manifest scripts — package.json `lint` / `typecheck` / `test`, Makefile targets,
   pyproject tool config
4. Repo docs — the pre-PR gate CONTRIBUTING or README states
5. CI — `.github/workflows`: what CI runs is the ground truth of what must pass

The gate includes the **message**, not just the tree: a `commit-msg`-stage hook
(`.husky/commit-msg`, a commitlint config) or message conventions stated in
CONTRIBUTING / visible in the repo's `git log` style are gate items too — discover
them now so Step 5 composes a conforming message instead of having the commit
rejected mid-flow.

**Completion criterion:** a written list of gate commands and message rules; an
empty list counts only after all five sources came up empty.

## Step 3 — If no hook manager is wired, offer to install one

Scripts alone don't guard commits: when Step 2 found no hook manager — even if
lint/test scripts exist — offer hook setup once: husky for a JS/TS repo, pre-commit
for Python — steps and pitfalls in
[references/setup-hooks.md](references/setup-hooks.md).

One hard stop first: a foreign `core.hooksPath` (Step 2, source 1) blocks setup —
`husky init` would repoint it and silently disable the repo's real gate, and
`pre-commit install` refuses outright. Surface it and either fold the existing
hooks into the new manager with the user's say-so, or leave setup declined; never
overwrite.

Declined: the Step 2 gate commands still run in Step 4 — declining hooks does not
waive the checks. Only a repo with nothing runnable (docs/meta repo) downgrades to
**review-only diligence** — a concrete procedure, not a waiver: the Step 5
cached-diff read is the *entire* verification, so read each changeset's full diff
line by line before its commit, and the Step 6 report must state plainly that no
gate exists.

**Completion criterion:** a hook manager guards commits, or you noted the decline or
that nothing is runnable.

## Step 4 — Run the gate before any commit attempt

Run every gate command on the work now — direct feedback beats a failed hook mid-commit.

- Missing tool (pytest, etc.): name the tool and the exact install command before
  running it — an install is never silent — and install it the way the repo's setup
  docs say, preferring project-local (a venv, a dev-dependency) to global; on an
  externally-managed Python, use a venv.
- Failure the work caused → fix the cause (not the test), re-run until green.
- Failure that pre-dates the work → do not fix it silently and do not bypass the
  hook; surface it and let the user decide.
- In a setup-only run, "the work" is the setup changeset alone: a failure that
  traces to the user's uncommitted WIP is surfaced, not fixed — prove the hook
  fires and leave the WIP untouched.

**Completion criterion:** every gate command has run; each is green or its failure is
classified pre-existing and surfaced.

## Step 5 — Commit one changeset at a time

- **Re-inventory first:** open Step 5 with a fresh `git status --porcelain -uall`.
  A clean tree → report "nothing to commit" (a concurrent session may have landed
  it) and stop; any delta from Step 1's snapshot → back to Step 1. The gate run
  can be long — never stage from a stale picture.
- An in-progress operation (detected in Step 1) overrides splitting: finish it
  with its own tool — `git cherry-pick --continue`, `git merge --continue`,
  `git rebase --continue` — or stop and ask. Never stash around sequencer state:
  the stash deletes it, which rewrites a picked commit's authorship to you and
  silently drops the remaining picks.
- Stage by explicit path — never `git add -A` into a mixed tree; when one file
  mixes changesets, split hunks. Bare `git add -p` without a TTY is a silent
  no-op (prints the hunk prompt, stages nothing, exits 0) — pipe the answers
  (`printf 'y\nn\n' | git add -p -- <file>`) or write the changeset's hunks to a
  patch file and `git apply --cached` it.
- Before each commit, read the **full** `git diff --cached` — not just `--stat`:
  it must contain exactly the current changeset, every line reviewed *now* (a
  live-edited tree makes any earlier review stale). Pre-staged entries from other
  changesets ride into the commit otherwise — record the user's staged/unstaged
  split, `git restore --staged` what doesn't belong, and restore the split
  afterwards.
- Compose the message to the conventions Step 2 discovered (commitlint rules,
  CONTRIBUTING style, the repo's `git log` shape) — a `commit-msg` hook rejects a
  free-form message as surely as a failing test, and retrying the same shape
  fails identically.
- Coupled files travel together (a behavior change ships with its test/fixture);
  unrelated changesets get separate commits.
- The gate already ran green on the full tree (Step 4), and after the last commit
  the branch tip *is* that gated state — so committing sequentially needs no
  isolation. Isolate an intermediate commit (stash the rest, re-run the gate,
  commit, pop) only when it could depend on files from a changeset it leaves
  behind **and** standalone greenness matters. When you do, follow
  `references/stash-isolation.md` for the guardrails: never during an in-progress
  operation or unborn HEAD, format staged files first, record `git stash list`, and
  `git stash pop` first on any failure inside the isolation window.
- If Step 3 installed hooks, commit that setup first so the hook guards the rest.
- Capture the commit's full output — piping it through `head` can SIGPIPE the hook
  and silently abort the commit. Hooks rewriting staged files (prettier) is normal.
- Verify each commit landed **and is yours**: capture the abbreviated hash
  `git commit` prints and require it to be a **prefix** of `git rev-parse HEAD`
  (commit prints a short id; an exact-match check would fail every time) —
  `git log -1` plus a clean status can both pass on a *concurrent session's*
  commit while yours was aborted by a hook.

**Completion criterion:** every planned commit exists in `git log`; `git stash list`
matches what it was when Step 5 began; the remaining tree state is exactly what you
deliberately left uncommitted.

## Step 6 — Report

Commit hashes and messages, the gate commands run with results, and everything
surfaced along the way: pre-existing failures left unfixed, files excluded and why,
surprises in the diff.
