# tests — handoff

Scenarios for the `/handoff` skill. The core end-to-end resume test was done in the
2026-07-01 session (see DEVLOG "handoff resume loop closed"). This file now tracks the
repo-local handoff location, the one-transition legacy temp fallback, and the older slug /
no-argument variants.

Last verified: 2026-07-07 — repo-local write/read, local exclude, slug, and legacy temp
fallback exercised live on macOS in the M3-07 candidate worktree. Windows `$env:TEMP`
fallback remains design-verified (not run on a Windows host).

## Scenario 1 — Repo-local save directory is untracked — live

**Input:** From the worktree root, resolve the workspace with `git rev-parse --show-toplevel`,
create `handoffs/`, and write `handoff-<slug>-<date>.md`.

**Expected:** The handoff path is `<workspace>/handoffs/<filename>`, not `$TMPDIR`, and
`handoffs/` in the repository's local exclude keeps the file out of `git status`.

**Verify (exercised 2026-07-07, macOS):**
- `git rev-parse --show-toplevel` →
  `/Users/<you>/code/app-worktrees/m3-07-codex55-xhigh-20260707-225523-b`
- live file written to
  `handoffs/handoff-cmux-m3-07-codex55-xhigh-20260707-225523-b-2026-07-07.md`
- `git check-ignore handoffs/handoff-cmux-m3-07-codex55-xhigh-20260707-225523-b-2026-07-07.md`
  reported the file ignored by `handoffs/`
- `git status --short` did not list `handoffs/`

## Scenario 2 — Slugify the repo/branch component — live

**Input:** Branch names with `/`, spaces, and `:` — this repo's branches routinely carry
slashes (`plan/<slug>`, `claude/<name>`).

**Expected:** Every path-unsafe character becomes `-`, so the name is one filename segment,
never a nested path, and the write lands as a single file in `handoffs/`.

**Verify (exercised 2026-07-07):** `printf '%s' "$b" | tr '/ :' '-'`
- `cmux/m3-07-codex55-xhigh-20260707-225523-b` →
  `cmux-m3-07-codex55-xhigh-20260707-225523-b`
- `plan/reviewer-agent` → `plan-reviewer-agent`
- `feature/a b:c` → `feature-a-b-c`

The live file appeared under `handoffs/` as one filename segment, not scattered into a
`cmux/` subdirectory.

## Scenario 3 — Missing handoff is reported, never hunted in OS temp — design-verified

**Input:** A requested handoff path is missing, and no file with that basename exists
under `<workspace>/handoffs/` either.

**Expected:** Resume attempts the requested path, then `<workspace>/handoffs/<basename>`
for a `handoff-` basename, then reports the file missing. No OS temp directory is
searched and nothing is ever written there.

**Verify:** `SKILL.md`'s resume section names exactly those two lookups and ends in a
missing-file report; it contains no temp-directory fallback.

*History:* an earlier revision carried a transition-period read-only fallback to
`${TMPDIR:-/tmp}` / `$env:TEMP` for pre-repo-local handoffs, live-verified on POSIX at
the time. That transition ended and the fallback was removed; the old live evidence
describes retired behavior and no longer applies to the shipped skill.

## Scenario 4 — Resume reads repo-local handoff first — live

**Input:** A fresh resume step reads the repo-local handoff path printed by the live write
from Scenario 1.

**Expected:** The first read succeeds from `handoffs/`, so no legacy temp fallback is needed.
The document starts with the required Workspace section and includes the current branch,
commit SHA, dirty/clean status, goal, current state, and next action.

**Verify (exercised 2026-07-07, macOS):** Reading
`handoffs/handoff-cmux-m3-07-codex55-xhigh-20260707-225523-b-2026-07-07.md` succeeded from the
repo-local path. The file's first section was `## Workspace`, and the Workspace line contained
the absolute worktree path, branch `cmux/m3-07-codex55-xhigh-20260707-225523-b`, and the then-
current commit SHA.

## Scenario 5 — No-argument default lens — live (macOS)

**Input:** `/handoff` invoked with no focus argument.

**Expected:** With no lens to tailor to, the **full** document is written (Workspace, Goal,
Current state, Next action, Open questions, Key files, Suggested skills) — nothing trimmed.
With an argument, the "Honor the argument" rule trims to that lens.

**Status:** Live-verified on macOS before the storage move — the 2026-07-04 session-close
no-arg run produced the full general-resume document (no lens trim). The maintainer ruled the
prose-triggered invocation counts as the typed no-arg variant (#40). The with-argument trim
was separately exercised the same day (the earlier `-evening` lens run). The save location has
since moved to repo-local `handoffs/`; the lens behavior is unchanged.
