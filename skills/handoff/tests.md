# tests — handoff

Scenarios for the `/handoff` skill. The core end-to-end resume test was done in an
earlier session. This file now tracks the repo-local handoff location, the
one-transition legacy temp fallback, and the older slug / no-argument variants.

Repo-local write/read, local exclude, slug, and legacy temp fallback were exercised
live on macOS in a candidate worktree. Windows `$env:TEMP` fallback remains
design-verified (not run on a Windows host).

## Scenario 1 — Repo-local save directory is untracked — live

**Input:** From the worktree root, resolve the workspace with `git rev-parse --show-toplevel`,
create `handoffs/`, and write `handoff-<slug>-<date>.md`.

**Expected:** The handoff path is `<workspace>/handoffs/<filename>`, not `$TMPDIR`, and
`handoffs/` in the repository's local exclude keeps the file out of `git status`.

**Verify (exercised on macOS):**
- `git rev-parse --show-toplevel` →
  `/Users/you/code/app-worktrees/session-worktree-b`
- live file written to
  `handoffs/handoff-cmux-session-worktree-b-<date>.md`
- `git check-ignore handoffs/handoff-cmux-session-worktree-b-<date>.md`
  reported the file ignored by `handoffs/`
- `git status --short` did not list `handoffs/`

## Scenario 2 — Slugify the repo/branch component — live

**Input:** Branch names with `/`, spaces, and `:` — this repo's branches routinely carry
slashes (`plan/<slug>`, `claude/<name>`).

**Expected:** Every path-unsafe character becomes `-`, so the name is one filename segment,
never a nested path, and the write lands as a single file in `handoffs/`.

**Verify (exercised):** `printf '%s' "$b" | tr '/ :' '-'`
- `cmux/session-worktree-b` →
  `cmux-session-worktree-b`
- `plan/reviewer-agent` → `plan-reviewer-agent`
- `feature/a b:c` → `feature-a-b-c`

The live file appeared under `handoffs/` as one filename segment, not scattered into a
`cmux/` subdirectory.

## Scenario 3 — Legacy temp fallback read — live on POSIX, design-verified on Windows

**Input:** A requested repo-local path is missing, but a legacy temp handoff with the same
basename exists in the POSIX temp directory.

**Expected:** Resume attempts `<workspace>/handoffs/<basename>` first, then attempts one
read-only legacy lookup by basename in `${TMPDIR:-/tmp}` on POSIX or `$env:TEMP` on Windows.

**Verify (exercised on macOS/POSIX):** With the repo-local file absent and a same-
basename file planted in a temporary legacy directory, the fallback read returned the legacy
file contents and reported the legacy path. The Windows branch was traced against the skill's
`$env:TEMP` rule but not run on a Windows host.

## Scenario 4 — Resume reads repo-local handoff first — live

**Input:** A fresh resume step reads the repo-local handoff path printed by the live write
from Scenario 1.

**Expected:** The first read succeeds from `handoffs/`, so no legacy temp fallback is needed.
The document starts with the required Workspace section and includes the current branch,
commit SHA, dirty/clean status, goal, current state, and next action.

**Verify (exercised on macOS):** Reading
`handoffs/handoff-cmux-session-worktree-b-<date>.md` succeeded from the
repo-local path. The file's first section was `## Workspace`, and the Workspace line contained
the absolute worktree path, branch `cmux/session-worktree-b`, and the then-
current commit SHA.

## Scenario 5 — No-argument default lens — live (macOS)

**Input:** `/handoff` invoked with no focus argument.

**Expected:** With no lens to tailor to, the **full** document is written (Workspace, Goal,
Current state, Next action, Open questions, Key files, Suggested skills) — nothing trimmed.
With an argument, the "Honor the argument" rule trims to that lens.

**Status:** Live-verified on macOS before the storage move — the session-close
no-arg run produced the full general-resume document (no lens trim). The
prose-triggered invocation was ruled to count as the typed no-arg variant. The
with-argument trim was separately exercised in an earlier `-evening` lens run. The
save location has since moved to repo-local `handoffs/`; the lens behavior is unchanged.
