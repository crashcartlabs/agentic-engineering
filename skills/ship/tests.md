# tests — ship

Scenarios captured from **real pre-codification runs**: four live ships
in this repo (the /build-skill practice corpus) and staged
refusal runs in a scratch repo (`shiplab`). The first **typed** `/ship` run followed
in a fresh session: Scenario 1's legacy gate/push/Codex path
is live-verified through the registered command; its self-review extension is covered
by Scenario 6 until the next full `/ship` PR exercises it end to end. Scenarios 2–5
remain verified by the manual/staged runs.

Last verified: S1 typed-run live; S2–S5 manual/staged runs; S6
self-review gate dogfooded on the bake-off branches.

## Scenario 1 — Golden: green gate → self-reviewed evidence PR → Codex request

**Input:** A feature branch with committed work ahead of `main`, clean tree, no
existing PR (live: `claude/item9-friction-cuts` → a real PR, and three more alongside it).

**Expected output:** Gate discovered (`python3 scripts/ci/check_all.py` plus the CI
secret scan — trufflehog, stdout suppressed, exit-code gated) and run at a recorded
SHA; exit 0; `/code-audit` runs on the branch diff; `/security-audit` either runs
on security-relevant diffs or is explicitly skipped for passive docs-only diffs;
`/skill-safety-scan` runs when a skill changed; branch pushed with tip == evidence
SHA; `gh pr create` with a body whose Verification section carries the captured
output, the self-review report verdicts, `<N> findings caught internally`, and
"Verified at commit `<sha>`"; `@codex - Please review PR` comment posted; PR URL +
`/babysitting-pr <n>` pointer printed; the word **shipped** stated.

**Verify:** the PR body's Verification section carries BOTH gate rows — check_all
with its captured output, and the secret-scan row showing pass/fail and exit code
only, never scanner output; the self-review rows name the `/code-audit` report, the
optional `/skill-safety-scan` report, the `/security-audit` report or passive
docs-only skip, and `<N> findings caught internally`; the PR's head SHA equals the
SHA named in the body; the Codex comment exists; the reply says shipped.

**Status:** Live-verified via the first typed run — a real PR (evidence SHA
`843fcd6`, merged `9ec38d6`): all four preconditions checked, both gate rows in the
body, freshness held end-to-end (post-gate tree re-check, `ls-remote` tip, and the
`--jq` headRefOid check all at the evidence SHA), @codex comment posted,
`/babysitting-pr <n>` pointer printed, **shipped** stated. One deviation, recorded at
the time: the local scanner was missing → installed by a named route (brew, same version
CI uses) rather than CI's pipe-to-shell installer. The internal self-review fields
did not exist yet and are not claimed as verified by that run.

## Scenario 2 — Edge: red gate → refuse, nothing pushed

**Input:** A branch where the gate fails (live scratch run: `npm test` exit 1 —
`'Usb Cable' != 'USB Cable'`, a lowercase-normalization commit flattening acronyms).

**Expected output:** The refusal quotes the failing command's actual output, states
**not shipped** — no push, no PR — and routes the fix to `/commit` /
`diagnosing-bugs`, with `/ship` re-run from Step 1 afterward.

**Verify:** no new remote ref and no PR exist; the failing assertion appears verbatim
in the refusal; the reply says not shipped.

## Scenario 3 — Weird: evidence goes stale between gate and push

**Input:** Gate green at SHA A, then a last-second `--amend` moves HEAD to SHA B
before the push (live scratch run: `3b5340d` → `d05b432`).

**Expected output:** The Step 5 SHA comparison catches the divergence; the run
refuses to push, returns to Step 3, re-captures evidence at SHA B, reruns Step 4
self-review for SHA B, re-checks freshness, and only then proceeds. No PR ever
carries evidence or self-review from a SHA it doesn't ship. If the divergence is
only discovered after `gh pr create` (a concurrent push during create), the recovery
is in place: evidence and self-review are both re-run at the tip, and the existing
PR's body is refreshed via `gh pr edit` — never a second PR, never a stranded
stale-evidence or stale-self-review body. If that recovery first writes
`BLOCKED: evidence stale; not shipped` to the existing PR, the next `/ship` Step 1
recognizes the marker and enters `refresh-existing-PR` mode instead of hitting the
generic existing-PR refusal (design-traced; the concurrent-push race was not staged
live).

**Verify:** the recorded-vs-HEAD mismatch is named in the run log; the gate ran twice
(once per SHA); self-review ran for the shipped SHA or a ledgered reviewed-content
SHA when the only later commit is tracked evidence; the pushed tip equals the
*second* SHA; a blocked stale-evidence PR is edited in place and no duplicate PR is
created.

## Scenario 4 — Boundary: precondition refusals, each by name

**Input (five variants, live scratch runs except d):** (a) invoked on `main`;
(b) dirty tree (1 uncommitted edit); (c) branch 0 commits ahead of base;
(d) branch already has an OPEN PR whose body is not marked
`BLOCKED: evidence stale; not shipped` (traced from a real ship flow, where
follow-up pushes updated the open PR and no second create was attempted);
(e) detached HEAD (live-staged: `git checkout $(git rev-parse HEAD)`,
then `git branch --show-current` printed nothing with exit 0 — a naive not-main
check passes wrongly).

**Expected output:** Each refuses before any gate run or network action, naming the
failed check and the fix: branch first / `/commit` first / nothing to ship / here's
the existing PR URL, watch it with `/babysitting-pr` / check out a branch (empty
`--show-current` is not "not main", it is no branch at all).

**Verify:** `git status`, refs, and the PR list are unchanged after each refusal; the
named fix matches the failed check; for (e), the refusal names detached HEAD rather
than passing the default-branch check on the empty string.

## Scenario 5 — Weird: the gate itself writes tracked files

**Input:** Gate green at a recorded SHA, but a gate command wrote a tracked file
(formatter, regenerated snapshot, lockfile) during the run (live-staged:
post-gate append to `lib.js` at `d05b432` — `git rev-parse HEAD` unchanged while
`git status --porcelain -uall` showed ` M lib.js`).

**Expected output:** Step 5's tree re-check catches it before the SHA comparison,
which alone cannot — HEAD never moved. The run refuses to push, states **not
shipped**, and routes to `/commit` to land the writes; `/ship` re-runs from Step 1
afterward.

**Verify:** no push and no PR happened; the refusal names the dirty paths at the
unchanged SHA; after `/commit`, the re-run's evidence SHA is the new HEAD.

## Scenario 6 — Gate: internal self-review before PR open

**Input:** A feature branch with committed work ahead of the pinned `<base-ref>`,
clean tree, green repo gate, and no existing PR. Variants: (a) passive docs-only
prose, (b) code or config touching subprocess/parsing/file-writing/secret-handling
surfaces, (c) `skills/<name>/` skill-instruction changes.

**Expected output:** After Step 3 captures gate evidence and before any push or PR
creation, `/ship` gets report-backed results from `/code-audit high <base-ref>` on
`git diff <base-ref>...HEAD`. For variant (a), the security row records
`skipped: docs-only diff`. For variant (b), `/security-audit high <base-ref>` runs
on the same diff. For variant (c), `/skill-safety-scan <name>` runs before any
security-audit skip is accepted, because skill prose is operational agent
instruction. If the runtime cannot nest explicit-trigger slash commands, `/ship`
prints the exact commands, waits for the user-run reports, and resumes only after
those reports exist.

Any surviving internal finding states **not shipped**, blocks the PR, and requires a
fix plus a regression test or focused `tests.md` scenario before `/ship` is rerun.
The cumulative count is stored in the local
`<git-common-dir>/ship-self-review/<branch-slug>.md` ledger so a required
`/commit` restart cannot reset `N` to zero. The eventual PR body records
`<N> findings caught internally` plus the `/code-audit`, optional
`/skill-safety-scan`, and `/security-audit` verdict/report path or skip reason.
If `/security-audit` or `/skill-safety-scan` writes tracked report artifacts and no
findings survive, `/ship` stops before Step 5, commits only the report artifacts (and
report metadata rows) via `/commit`, then reruns and reuses the clean report-backed
self-review instead of generating a new same-day report loop. `/code-audit` reports
under `code-reviews/` are local-only evidence: the ledger must name an existing file,
but reuse must not require that path to be visible to `git status`.
Success metric: external Codex review should stay under 3 findings per PR; if not
after roughly 5 shipped PRs, revisit the checklist.

**Verify:** no `gh pr create` happens before `/code-audit` completes and any
required `/security-audit` or `/skill-safety-scan` pass/skip is recorded; the same
`<base-ref>` is used for ahead-count, review scope, summary, and diff evidence while
`<github-base-branch>` (for example `main`, not `origin/main`) is used for
`gh pr create --base`; skill Markdown is not treated as inert docs just because its
extension is `.md`; PR-head mismatch recovery reruns both gate evidence and
self-review before editing the existing PR body; after committing tracked
clean-report artifacts, the next run does not create `-2`/`-3` replacement reports
solely because the first reports were committed, and it does not reject an existing
`code-reviews/` report merely because that local-only directory is excluded from git
status.

**Status:** Dogfooded on the cmux bake-off branches. The internal
review passes caught 7 issues before PR open: slash-command nesting/report handoff,
pinned base-ref reuse, passive-only docs skip, skill Markdown as operational input,
durable catch-count handoff, PR-body report-backed verdicts, and stale-PR recovery
rerunning self-review at the refreshed SHA. This scenario is the focused regression
record, and the future PR evidence block should report `7 findings caught internally`.
