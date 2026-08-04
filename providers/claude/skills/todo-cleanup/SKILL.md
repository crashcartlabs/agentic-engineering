---
name: todo-cleanup
description: "Reviews and clears a repository TODO/backlog file by removing completed entries and converting every remaining untracked work item into GitHub issues before deleting it. Use when the user asks to clean TODO.md, migrate backlog items to GitHub issues, remove done TODOs, or ensure TODO entries are issue-tracked before deletion."
---


# TODO cleanup

Clean a backlog file without losing work. The invariant: unfinished work leaves the
target backlog file only after a matching GitHub issue is confirmed or created.

## Workflow

### Step 1 - Pin the context

Resolve the target backlog file from the request; default to `TODO.md` when the user
does not name one. Read the repo instructions, the target backlog file, the git remote,
and the existing GitHub issues for the repository. Search all issue states, not just
open issues. If the repo, target file, or issue tracker cannot be resolved, stop before
deleting unfinished items.

**Completion criterion:** the original backlog text is captured, the target repository
and backlog path are known, and the existing issue inventory is available.

### Step 2 - Classify every backlog item

Treat a parent bullet and its indented children as one item unless the children are
independent work. Assign each item exactly one classification:

- **Done:** checked off or clearly completed, with no remaining action.
- **Residual:** mostly done, but the text still names untested variants, follow-ups,
  or caveats that require work.
- **Already tracked:** the item names an issue or an issue search finds a matching
  work item.
- **Untracked work:** real remaining work with no matching issue.
- **Settled context:** an explicit skip/decision/reference note with no remaining
  action.

A checked item with residual work is not done; create or confirm an issue for the
residual, then remove the checked note.

**Completion criterion:** every backlog item has a classification and a planned action:
remove, create issue then remove, or keep because tracking is blocked.

### Step 3 - Create only missing issues

Before creating an issue, search by exact issue number if present, then by the item's
distinctive title and keywords. Do not duplicate an existing issue. Create one issue per
coherent work item; split unrelated work, and fold prior-art notes or caveats into the
same body when they serve the same deliverable.

Each issue body should preserve enough context to act without reopening the deleted
backlog entry: source heading, relevant constraints, and checkable acceptance criteria.
If the user has already asked to create issues, proceed after dedupe. Otherwise, list
the planned titles before writing to GitHub.

**Completion criterion:** every untracked or residual item has a new issue URL, or the
item remains in the target backlog file with the blocker stated.

### Step 4 - Edit the backlog

Remove only items that are done, settled context, already issue-tracked, or newly
issue-tracked. Do not remove unfinished work when issue creation failed. If the backlog
is empty, leave the file as a short pointer, for example:

```markdown
# TODO

Work identified but deliberately deferred - see AGENTS.md section XIV.

No current local TODO items. Deferred work is tracked in GitHub issues.
```

**Completion criterion:** the target backlog file contains no completed items and no
issue-tracked items; any remaining item is there because it still needs tracking.

### Step 5 - Record the cleanup

For a substantive cleanup, add a newest-first `DEVLOG.md` entry summarizing what was
removed, which issue numbers were created or reused, and any grouping decisions. Add a
`LESSONS.md` entry only if the cleanup exposed a correction or reusable process mistake.
Do not close pre-existing issues unless the user explicitly asked for issue hygiene.

**Completion criterion:** durable repo records explain where the backlog went without
duplicating each issue body.

### Step 6 - Verify

Run a final check before reporting:

- `git diff -- "$BACKLOG_FILE" DEVLOG.md` plus any other files intentionally touched,
- scan the target backlog file for leftover checkbox or backlog markers,
- list the created issue numbers and titles,
- `git status --short`.

**Completion criterion:** the diff matches the cleanup scope, issue-backed work is
accounted for, and only intended files are modified.
