# tests - todo-cleanup

Scenarios captured from a real cleanup that migrated this repo's `TODO.md`
backlog to GitHub issues, plus the immediate no-op replay against the emptied backlog.

Last verified: live run of the cleanup described below.

## Scenario 1 - Golden: mixed backlog becomes issues and an empty TODO

**Input:** `TODO.md` contained completed checked items, open pipeline/security/skill
work, `/commit` review findings already listed as GitHub issues, housekeeping tasks,
external-skill evaluation notes, prior-art notes, skip decisions, and a watchlist.

**Expected output:** Completed items were removed. The `/commit` review findings
already tracked as issues were reused. Every remaining unit of work became a new issue,
one issue per work item. `TODO.md` was reduced to a header plus "No current local TODO
items." `DEVLOG.md` recorded the migration and the grouping decisions.

**Verify:** `gh issue list --repo your-org/your-repo --state all --limit 100 --json number`
shows one new issue for each migrated work item, and `TODO.md` has no checklist items.

## Scenario 2 - Edge: already tracked issue group is not duplicated

**Input:** The `/commit` skill section listed remaining review findings already
tracked as issues, plus two untracked validation gaps: a live Python
pre-commit setup run and decline near-misses.

**Expected output:** No duplicate issues were opened for the already-tracked findings. The two
untracked validation gaps each became a new issue. The `/commit` section was removed from
`TODO.md` because every remaining work item was now issue-backed.

**Verify:** `gh issue list --repo your-org/your-repo --state all` shows one issue for
each original review finding and a new issue for each of the two validation gaps.

## Scenario 3 - Weird: checked item contains residual work

**Input:** The `/handoff` resume test item was checked and described as done, but its
tail text still named untested Windows `$env:TEMP`, POSIX `$TMPDIR`, and no-argument
variants.

**Expected output:** The completed resume-test text was removed, but the residual
variant work was preserved as a new issue before deletion from `TODO.md`.

**Verify:** The new issue exists with the three residual variants in its body, and no
`/handoff` residual text remains in `TODO.md`.

## Scenario 4 - No-op: TODO already empty

**Input:** Current `TODO.md` contains only the header, AGENTS.md pointer, and the note
that deferred work is tracked in GitHub issues.

**Expected output:** No GitHub issues are created and `TODO.md` is left unchanged.

**Verify:** A scan for `- [ ]`, `- [x]`, or `- [~]` in `TODO.md` returns nothing.
