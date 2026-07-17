---
name: handoff
description: "Compact the current conversation into a handoff document so a fresh session can resume the work without re-deriving context. Captures the live working state — current goal, what's half-done, the exact next action, open questions — not a permanent record. Writes to the repo-local handoffs/ directory and prints the path for you to hand to the next session. Invoke as /handoff [what the next session will focus on]. Explicit-trigger only."
---

# /handoff — Resume-here document for a fresh session

Write a handoff document that lets a fresh agent pick up exactly where this conversation left off. This captures the **hot working state** — the mental context that would otherwise die with this session.

**Boundary vs DEVLOG.md.** DEVLOG.md (§XIII) is the permanent, committed, end-of-session narrative — the cold archive. This handoff is the opposite: ephemeral, uncommitted, and about *right now* — the goal you're mid-flight on, the thing you were about to do next, the reasoning you haven't written down yet. Don't reproduce DEVLOG here; if a DEVLOG entry already covers something, reference it.

## Where to save it

Save to the repo-local **`handoffs/` directory**, never the OS temp directory. A handoff is throwaway state and does not belong in git, but it must survive OS temp cleanup long enough for a later session to resume. Put it under the workspace root recorded in the handoff:

- Resolve the workspace root with Git (`git rev-parse --show-toplevel`) or the platform equivalent; do not guess from the current directory.
- Create `<workspace>/handoffs/` if it does not exist.
- Keep the directory untracked. Add `handoffs/` to the repository's local exclude file when missing. In a linked worktree, do **not** assume `.git/info/exclude` is a real path; ask Git for it (`git rev-parse --git-path info/exclude`).

Name the file so it's identifiable later, e.g. `handoff-<repo-or-branch>-<YYYY-MM-DD>.md`. **Slugify the repo/branch component first** — replace `/` and any other path-unsafe characters with `-`. This repo's branches routinely contain slashes (`plan/<slug>`, `claude/<name>`); a raw `/` would be read as a path separator and either fail the write or scatter the file into an unintended subdirectory. Write only one file inside `handoffs/`; do not create nested paths from the branch name.

**After writing, print the absolute path on its own line, prominently.** The next session cannot find this file unless you surface where it is — closing that loop is the whole point. The user resumes by starting a fresh session and pasting: "read `<path>` and continue."

## How to resume

When a user asks you to resume from a handoff, read the requested handoff path first. For one transition period after the move from OS temp storage, support the old location as a fallback:

- If the requested file is missing and its basename starts with `handoff-`, try `<workspace>/handoffs/<basename>` first.
- If that is also missing, attempt one legacy temp lookup by the same basename: POSIX `${TMPDIR:-/tmp}`; Windows `$env:TEMP`.
- Report which path you actually read, or say that both the repo-local and legacy temp locations were missing.

Do not write new handoffs to the OS temp directory. The fallback is read-only and only exists so old `/tmp` or macOS `/var/folders/.../T/` handoff paths can survive the transition.

## What to include

Keep it lean — enough to resume, nothing more. Cover, in roughly this order:

- **Workspace (required, first)** — the **absolute** repo/worktree path, the current branch, and the commit SHA (plus dirty/clean status). The user works across several repos and worktrees (§XI); without this, every relative path below is ambiguous and a fresh session can resume in the wrong checkout while believing it's correct.
- **Goal & success criterion** — what we're trying to achieve and how we'll know it's done (§VI).
- **Current state** — what's done, what's in flight, what's untouched.
- **Next action** — the single most concrete thing the next session should do first.
- **Open questions / blockers** — decisions not yet made, things waiting on the user.
- **Key files & references** — paths touched or relevant, relative to the workspace root recorded above; link by path, don't paste.
- **Suggested skills** — which skills the next agent should invoke (e.g. `/plan`, `/execute`, `/code-audit`).

## Rules

- **Don't duplicate other artifacts.** PRDs, plans, ADRs, issues, commits, diffs — and this repo's DEVLOG.md, LESSONS.md, TODO.md — are already captured. Reference them by path or URL instead of re-summarizing.
- **Redact sensitive information** — API keys, passwords, tokens, PII. Never write a secret into the handoff.
- **Honor the argument.** If the user passed a description of what the next session will focus on, treat it as the lens and tailor the document to that — trim anything irrelevant to it.
