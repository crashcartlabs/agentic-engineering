# tests — commit

Scenarios captured from the real runs that built this skill, in a scratch TS repo
(`acme-parser`) and a private skill-testing repo.

Verification status: Scenarios 1–2 live; Scenario 3's concurrent-vanish path live but
its Step-3 offer-on-decline sub-path design-verified — added after the run, never
replayed live; Scenario 4 live.

## Scenario 1 — Golden: no gate → set one up → two clean commits

**Input:** A TS repo with a committed baseline, an uncommitted feature (quoted-cell
support in `parseRow` + its test), a `test` script, and no hook manager or typecheck.

**Expected output:** Gate discovery reports "test script only, no hooks"; the setup
branch fires (user approved): husky + lint-staged + prettier installed, typecheck
script added, and the new gate made green on existing code (`@types/node`,
`"types": ["node"]` in tsconfig). Two commits, setup first ("Add pre-commit hooks
(husky + lint-staged + prettier)"), then the feature — with the hook visibly running
lint-staged, `tsc --noEmit`, and `node --test` on the feature commit.

**Verify:** `git log` shows both commits in that order; the feature commit's output
shows all three checks; `git status --porcelain` is empty.

## Scenario 2 — Edge: the work breaks a check → fix the cause, then commit

**Input:** Same repo, now hook-guarded. New work: doubled-quote escape support with
a real bug (the literal `"` never emitted), plus the test that catches it.

**Expected output:** The gate runs *before* any commit attempt and fails
(`✖ doubled quotes escape to a literal "`); the fix lands in the implementation
(`current += '"'`), not the test; the gate reruns green; one commit lands and the
hook re-verifies it.

**Verify:** No commit exists from the failing state; final `git log -1` shows the
fix commit; test count went 2→3 passing.

## Scenario 3 — Weird: oversized mixed tree that vanishes mid-run

**Input:** A live repo with 72 dirty files (mixed: skill moves, deletions, harness
changes, new fixtures), partially staged state, no hook manager — and a concurrent
session that commits everything while the skill is mid-inventory.

**Expected output:** The gate is discovered from CONTRIBUTING.md and CI (self-tests,
pytest, check-skill sweeps). No hook manager is wired, so Step 3 offers pre-commit
setup once despite the runnable scripts; on decline the discovered gate commands
still run in Step 4 (the original live run predates Step 3 — a compliant replay
must include this offer). The missing `pytest` is installed per the repo's setup
docs (venv, PEP 668); the full gate runs green (29/29 self-tests, 67 pytest,
0 FAIL / 0 WARN sweeps). At commit time the skill re-checks `git status`, finds the
tree clean, and reports "nothing to commit — a concurrent session landed it
(commit 3dc9dc5)" instead of committing anything. Stat-dirty files (status `M`,
empty diff) are ignored, staged renames are read as intent.

**Status:** Split — the concurrent-vanish path (72-file tree, `pytest` via venv, gate green,
clean-tree re-check → "nothing to commit, commit 3dc9dc5") was **live**; the Step-3
offer-on-decline sub-path is **design-verified only** (it was added to the skill after this run
and never replayed through a live run — the parenthetical below says so).

**Verify:** No new commit is created; the report names the concurrent commit and the
gate results.

## Scenario 4 — Decline near-misses: message-only, amend, rebase (live-verified)

**Input (three variants):** (a) "write me a commit message for this" (message only);
(b) "amend the last commit"; (c) "rebase these onto main" / "squash the last 3".

**Expected output:** None runs the commit workflow. The skill's scope (frontmatter — "Not
for writing a commit message alone, rewriting history (amend, rebase), or pushing and PR
creation") excludes all three, so it declines or redirects **without touching git state**:
no staging, no commit, no `git add`, no history rewrite. A message-only request yields a
message (or a pointer), not a commit; amend/rebase are redirected to the user or the
appropriate tool, with the working tree and index left exactly as found.

**Verify:** `git status --porcelain` and `git reflog` are unchanged after the request; no
new commit exists; the reply states the boundary rather than silently doing a partial
commit.

**Status:** Live-verified. Scratch repo with two
commits, a staged edit, and an unstaged edit; before-state pinned (HEAD hash, porcelain,
reflog count, stash count). (a) yielded a composed message from the read-only staged diff
plus a "/commit to land it" pointer — no commit created; (b) and (c) were redirected with
the scope line quoted, amend/squash named as history rewrites the user drives explicitly.
After all three: HEAD, `git status --porcelain`, reflog line count, and stash list
byte-identical to the before-state. The commit workflow (gate discovery, staging, commit)
never started.
