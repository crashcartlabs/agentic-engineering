---
name: ship
description: "Open an evidence-bearing PR for the current branch — re-runs the repo's gate and self-review at the exact HEAD being shipped, refuses on red/stale/self-caught findings, creates the PR with per-command proof in the body, and requests the Codex review. Invoke as /ship after /commit lands the work. Not /commit (landing changesets) and not /babysitting-pr (watching a PR that already exists). Launched on request: invoke it when the user explicitly asks to ship, open a PR, or chains it after /commit in the same message — never on your own initiative."
---

# /ship — Open a PR whose body proves the gate ran

Turn the current branch into an open, review-requested PR whose Verification section
is **evidence, not decoration**: captured command output, exit codes, and the exact
SHA they were produced at. The invariant the whole skill defends: **the SHA the gate
and self-review ran against is the SHA that gets pushed and PR'd** — an amend or
commit between gate and push rots the evidence, and rotted evidence is refused,
never shipped.

Ship is the middle of the pipeline: `/commit` lands changesets, `/ship` opens the
evidence-bearing PR, `/babysitting-pr` keeps it merge-ready. Stay in lane.

## Step 1 — Preconditions: refuse early, by name

Resolve the git review base once, before any checks: run `agentic resolve-base` and
call its output `<base-ref>`. Reuse that exact ref for the ahead-count, self-review
scope, and PR summary/diff. Resolve `<github-base-branch>` with `agentic resolve-base
--github-branch`; use that branch name for `gh pr create --base`, never the
remote-tracking ref. These commands are the shared fallback policy; do not reimplement
it in this skill.

Then check these things; any failure is a named refusal with the fix, and the run stops
unless the existing-PR check explicitly enters `refresh-existing-PR` mode:

- **No branch, or the default branch** — `git branch --show-current` empty means
  detached HEAD (live case: it prints nothing, so a naive not-main check passes and
  the push later fails on an empty refspec) → refuse: check out a branch. Equal to
  the repo's default → refuse: ship ships a feature branch; branch first.
- **Dirty tree** (`git status --porcelain -uall` non-empty) → refuse: ship ships
  commits — evidence captured at HEAD cannot cover uncommitted work. `/commit` first.
  (`-uall`: repos with `status.showUntrackedFiles=no` otherwise hide untracked files
  that a gate or build may read)
- **Nothing to ship** (`git rev-list --count <base-ref>..HEAD` = 0) → refuse: no
  commits ahead of base.
- **A PR already exists for this branch** (`gh pr view --json state,url,number,body`
  returns an OPEN one) → inspect the body before refusing. If its Verification
  section contains the exact blocker marker `BLOCKED: evidence stale; not shipped`,
  enter **`refresh-existing-PR` mode** with that PR number/URL: continue through the
  same gate, self-review, freshness, and push checks, then edit the existing PR body
  in Step 6 instead of creating a second PR. Otherwise refuse and print its URL:
  pushing to the branch updates that PR; watching it is `/babysitting-pr`'s job, not
  a second create.

**Completion criterion:** all preconditions ran; either every one passed, the run
entered `refresh-existing-PR` mode with a concrete PR number/URL, or the run ended in
a refusal that names the failed check and the fix.

## Step 2 — Discover the gate

Discover the repo's gate the way `/commit` does — hook manager, manifest scripts
(`lint` / `typecheck` / `test`), CONTRIBUTING, CI config. CI is the ground truth —
in this meta-repo `.github/workflows/ci.yml` runs two jobs, so the gate is
`python3 scripts/ci/check_all.py` **plus** the secret scan (`trufflehog filesystem`
over a `git archive HEAD` extract, `--no-update --no-verification --fail`, stdout suppressed and
the exit code gating), not the lint script alone. If every source comes up empty, ask the user for
the command(s) once — do not ship an evidence PR with no evidence to put in it.

**Completion criterion:** a written list of gate commands (≥1), each runnable as-is.

## Step 3 — Capture evidence at a recorded SHA

Record `git rev-parse HEAD` first — evidence is *of* a SHA, so pin it before anything
runs. Then run every gate command **visibly** (never pipe a gate to `/dev/null`; the
output is the evidence and the exit code is the decision), and
capture per command: the exit code and a trimmed output tail.

**Exception — a secret scan's output is never shown or quoted.** Its stdout may
contain the very credential it found (this repo's CI suppresses trufflehog stdout for
exactly that reason, and a raw secret must never be persisted into any
report or comment). Run it with `--no-update`, stdout suppressed, and gate on the **exit code** — the
silent-gate lesson forbids masking exit codes, not redacting secret-bearing output.
On failure, report only that the scan failed and how to inspect locally (re-run the
scanner directly in a private terminal); the finding itself stays out of chat, PR
bodies, and refusal text.

**Any non-zero exit → refuse.** Report the failing command and its actual output
verbatim (secret scan excepted — see above), state plainly that nothing was pushed
and no PR was opened, and stop — the fix cycle belongs to `/commit` (or
`diagnosing-bugs`), after which `/ship` is re-run from Step 1.

**Completion criterion:** every gate command has exit 0 with captured output, or the
run ended in a refusal quoting the red command's output.

## Step 4 — Internal self-review before external review

Before any push or PR create, run the repo's own review skills on the branch diff
while the work is still local and cheap to fix.

Track the ship-cycle count in a local ignored ledger so a fix/commit/rerun cycle
does not lose what was caught. Find the git dir with `git rev-parse --git-common-dir`
and write `<git-common-dir>/ship-self-review/<branch-slug>.md`. Record each run's
SHA, report paths, surviving findings, fixed-in commit, and the cumulative
`N findings caught internally` value. The final PR count comes from this ledger and
the named reports, not from memory or from the final clean run alone. If the count
is missing or ambiguous after a rerun, refuse instead of silently writing `0`.

Before launching a new self-review command, inspect the ledger and named report
paths. Reuse an existing clean report-backed self-review when it already covers the
current HEAD and all required report files are present. For tracked evidence
directories (`reviews/`, `security-reviews/`, `skill-scans/`), the report files must
also be visible to `git status`; `code-reviews/` remains a local-only `/code-audit`
report directory, so verify those paths exist in the worktree and ledger but do not
require them to be visible as tracked artifacts. Also reuse the clean report set
after an evidence-artifact-only commit: if the
previous reviewed SHA differs from current HEAD only by committed tracked reports
under `reviews/`, `security-reviews/`, or `skill-scans/` (and metadata rows those
reports update), record the current HEAD as the shipped evidence SHA but keep the
reviewed-content SHA and report paths in the ledger. Do **not** rerun the same
review solely because its tracked report was committed; that creates an endless
same-day `-2`, `-3`, … report loop.

- Always require `/code-audit high <base-ref>` on the merge-base branch diff
  (`git diff <base-ref>...HEAD`). If the runtime can run that explicit-trigger
  slash workflow as part of the user-requested `/ship`, run it exactly. If it
  cannot, pause before any push/PR, print the exact command for the user to run in
  this same worktree, and resume only after the report exists.
- Run `/security-audit high <base-ref>` on the same diff when changed files touch
  subprocess/shell execution, command construction, parsing/deserialization, file
  reads/writes/deletes/path handling, uploads, generated-file writers, secrets/auth,
  network boundaries, dependency manifests/lockfiles, runtime/deploy/CI config, or
  review/audit/gate control flow that routes untrusted input toward those surfaces.
- Docs-only passive prose diffs skip the `/security-audit` half explicitly. Record
  `security audit skipped: docs-only diff`. File extension alone is not enough:
  `.claude` skill/agent Markdown is operational when it changes commands, file/path
  behavior, secrets, permissions, or review/audit control flow.
- If any `skills/<name>/` skill changed, require `/skill-safety-scan <name>`
  and record its verdict before treating the security audit as skipped. A skill
  prose change can alter agent behavior even when it is Markdown.

Any surviving finding blocks shipping. State **not shipped**, fix each finding
before opening the PR, add a regression test or focused `tests.md` scenario for each
fix, land the fixes with `/commit`, then rerun `/ship` from Step 1 so gate evidence
and self-review both cover the final HEAD. Do not push or create a PR while an
internal finding is unfixed.

If Step 4 produces tracked report artifacts and there are no surviving findings,
do not fall through to Step 5 with a dirty tree. State **not shipped yet**: commit
only those report artifacts (and any report metadata rows) with `/commit`, then
rerun `/ship` from Step 1. On that rerun, the reuse rule above must recognize the
committed report-backed clean self-review and continue without generating a fresh
same-day report.

Success metric: external Codex review should average **under 3 findings per PR**
after this self-gate. If that is not true after roughly 5 shipped PRs, revisit the
M2-07 checklist instead of accepting external-review fix commits as normal.

**Completion criterion:** `/code-audit` produced a report for this branch diff;
`/security-audit` either produced a report or has the explicit docs-only skip
reason; `/skill-safety-scan` ran for any changed skill; every surviving finding is
fixed with regression coverage and re-verified, or the count is zero; and the
internal-catch count is ready for the PR body.

## Step 5 — Freshness check, then push

First re-check the tree: `git status --porcelain -uall` must be empty. A gate that
*writes* tracked files (a formatter, a regenerated snapshot, a lockfile) leaves HEAD
unchanged — the SHA comparison below cannot see it — yet the evidence now describes a
state that is not committed (live case: a post-gate write left the tree dirty at an
unchanged HEAD). Dirty self-review report artifacts should already have been handled
by Step 4's report-commit-and-reuse path; if they reach this point, return to that
Step 4 handling. Any other dirty path → refuse and route to `/commit`; re-run `/ship`
after the writes land.

Re-read `git rev-parse HEAD`. If it differs from the recorded SHA, the evidence is
**stale** — something amended or committed while the gate ran. Do not push; return to
Step 3 and re-capture at the new HEAD (live case 2026-07-04: a last-second `--amend`
moved HEAD between gate and push; the SHA comparison caught it).

Fresh → `git push -u <remote> <branch>` (the repo's push remote: `remote.pushDefault`
if configured, else `origin`), then confirm against the **live remote**, not the
local tracking ref — `git rev-parse @{u}` only reads `refs/remotes/...` and can be
stale under a concurrent push: the first field of
`git ls-remote <remote> "refs/heads/<branch>"` (the full ref, not the bare name —
`--heads <name>` tail-matches cousins like `team/<name>`; output is `<oid> TAB <ref>`,
take the oid, e.g. `| cut -f1`) must equal the evidence SHA.

**Completion criterion:** remote branch tip == evidence SHA, byte-for-byte.

## Step 6 — Create the PR with the evidence body

Compose the body from the template below — Summary and Changes from
`git log <base-ref>..HEAD` and the diff stat, Verification from Step 3's captured
evidence plus Step 4's internal self-review record, the SHA line from Step 5. Then
`gh pr create --base <github-base-branch> --title "..." --body-file
<file>`, appending the repo's PR attribution footer if one is conventional.

In `refresh-existing-PR` mode, do not create a PR: use the same body template and
run `gh pr edit <n> --body-file <file>` against the PR recorded in Step 1. The
refreshed body replaces the stale `BLOCKED: evidence stale; not shipped` marker with
current gate evidence and the reused or rerun self-review records.

````markdown
## Summary
<what changed and why, 1–3 sentences>

## Changes
- <one bullet per logical change, from the commit log>

## Verification
**<gate command>** — ✅ (exit 0)
```
<trimmed captured output>
```
<one block per gate command>

**Internal self-review** — ✅
- `<N> findings caught internally`
- `/code-audit high <base-ref>`: <verdict and report path>
- Code-audit evidence available to remote reviewers: <one bullet per surviving finding,
  including severity, file:line, failure scenario, and fix direction; or "No correctness
  issues found">. The local `code-reviews/` path is provenance, not a remote link.
- `/skill-safety-scan <name>`: <verdict and report path, if a skill changed>
- `/security-audit high <base-ref>`: <verdict and report path, or `skipped: docs-only diff`>

Verified at commit `<evidence SHA>`

## Risk / Rollback
<what breaks if this is wrong; how to undo it>
````

**Completion criterion:** the PR exists and its body's Verification section contains
only output captured in Step 3 at the shipped SHA plus the Step 4 report-backed
self-review verdicts and internal-catch count from that same SHA, or a ledgered
reviewed-content SHA when the shipped SHA is an evidence-artifact-only report commit
— nothing pasted from memory.

## Step 7 — Request review and hand off to the watcher

- Verify the created PR's head against the evidence: `gh pr view <n> --json
  headRefOid --jq .headRefOid` (the `--jq` matters — without it the output is a JSON
  object, not a bare SHA, and every valid ship would falsely enter recovery) must
  equal the evidence SHA. A mismatch means the branch moved during
  create — the open PR is now showing **stale evidence to reviewers**, which is worse
  than no PR: do not stop at 'not shipped'. Recover in place: return to Step 3 at the
  current tip, re-capture evidence, rerun Step 4 self-review, re-verify freshness
  and the live remote, then `gh pr edit <n> --body-file` the refreshed Verification
  — never a second PR, and never a refusal that strands the stale one. If the
  recovery gate or self-review finds a blocker after the PR already exists,
  immediately edit the existing PR body so its Verification section says
  `BLOCKED: evidence stale; not shipped`, names the failing command/report without
  leaking secret-scan output, and omits any Codex review request. After fixes land,
  resume in refresh-existing-PR mode: Step 1 recognizes that blocked stale-evidence
  marker on the existing PR instead of refusing, rerun Steps 3-5 at the current tip,
  reuse or rerun Step 4 self-review per its ledger rules, then `gh pr edit <n>
  --body-file` the refreshed body. Do not create a second PR. **Shipped** is declared
  only when the PR's head equals the SHA its body names and the self-review rows name
  reports that cover that SHA, including an artifact-only report commit when recorded.
- If the repository uses an automated PR reviewer, request it as part of shipping, not
  as an afterthought — e.g. for Codex, `gh pr comment <n> --body "@codex - Please review PR"`.
  In `refresh-existing-PR` mode, post the request after the body is refreshed unless an
  equivalent request already exists for the current head. Skip this when the repository
  has no such reviewer configured.
- Print the PR URL and close with the pointer: run `/babysitting-pr <n>` to keep it
  merge-ready — a suggestion for the human, never an auto-invoke.

**Completion criterion:** PR URL and review-request comment URL both printed, and the
run stated explicitly that the PR was **shipped** (vs. every refusal above, which
states **not shipped**).

## Hard rules

- **Red or stale evidence never ships.** No PR on a failing gate; no push when the
  evidence SHA and HEAD diverge. Fix, re-verify, re-ship.
- **External review is not the first review.** Run the internal self-review gate,
  fix every surviving finding with regression coverage, and record
  `<N> findings caught internally` before requesting Codex review.
- **Evidence is captured output, never prose.** If it wasn't produced by this run at
  the shipped SHA, it does not go in the Verification section.
- **One branch, one PR.** Never force-push, never merge, never open a duplicate PR
  for a branch that has one.
- **State shipped vs. not shipped in so many words** — the user never guesses whether
  a PR now exists.
