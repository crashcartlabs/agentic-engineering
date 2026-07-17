# Stash Isolation

The gate already ran on the full tree in Step 4, and after the final commit the branch
tip is that gated state. Sequential commits do not need isolation by default.

Use a stash-isolated intermediate commit only when both conditions are true:

- the commit could depend on files from a changeset it leaves behind;
- standalone greenness for that intermediate commit matters.

When isolation is necessary, use these guardrails:

- Never isolate during an in-progress operation detected in Step 1 (`MERGE_HEAD`,
  `CHERRY_PICK_HEAD`, `rebase-merge`, or `rebase-apply`). Finish with the operation's
  own `--continue` flow or stop and ask.
- Never isolate on an unborn HEAD.
- Run the repo's formatter over the staged files before stashing, so hooks have
  nothing to rewrite. A hook rewrite can make the later stash pop conflict.
- Record `git stash list` before entering the isolation window.
- On any failure inside the window, whether from the gate, hook, or commit, run
  `git stash pop` first, before touching a single file, then reassess from a fresh
  inventory.
