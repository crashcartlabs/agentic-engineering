# tests — resolving-merge-conflicts

Scenarios for the `resolving-merge-conflicts` skill. Each names the input, the expected
behavior, and how to verify it.

**Status: live-verified.** All four scenarios were driven end-to-end in a scratch repo on
2026-07-04 (dogfood record at the bottom of this file). Scenario 3's original expected-output
wording was corrected by the live run — see the note inside it.

Last traced: 2026-07-04 (live dogfood, scratch repo)

## Scenario 1 — Golden: two intents combine into one region

**Input:** A merge stops with one conflicted file — `config.ts`. Ours added a `retries`
field; theirs added a `timeoutMs` field, both in the same object literal. Both changes are
clearly purposeful and independent. (This is the exact fixture the 2026-07-04 live run used.)

**Expected output:** The skill reads both sides (`git show :2:config.ts`, `:3:config.ts`,
`git log --merge -p`), confirms this is a plain merge (so ours/theirs are not inverted),
and writes the region that keeps **both** `retries` and `timeoutMs` — not a wholesale
`--ours`/`--theirs`. It stages the file, runs `git diff --check` (clean) and
`git ls-files -u` (empty), re-runs the repo gate green, then finishes with
`git merge --continue`.

**Verify:** `config.ts` contains both new fields and no conflict markers; `git ls-files -u`
is empty; `git status` shows the merge completed; the gate passed before `--continue`.

## Scenario 2 — Edge: abort is the correct answer

**Input:** A rebase onto the wrong base: it was started against `origin/legacy` instead of
`origin/main`, and the very first commit conflicts in a file whose "theirs" side reflects
work the author cannot interpret with confidence.

**Expected output:** The skill recognizes two abort triggers at once — wrong base, and a
side whose intent is unclear (§II). It does **not** force a plausible resolution. It runs
`git rebase --abort`, confirms the pre-operation state is restored, and escalates: names the
wrong base, lays out both sides of the ambiguous hunk, and hands the decision to the human
rather than deciding it.

**Verify:** No commit was produced from a guessed resolution; `git status` shows no rebase
in progress and the branch back at its pre-rebase tip; the reply states why it aborted and
what the human must decide.

## Scenario 3 — Weird: a "resolved" file still carries markers

**Input:** A cherry-pick conflict where an earlier attempt left a `=======` and a diff3
`|||||||` base marker inside `parser.py`, and the file was already `git add`-ed as if done.
The instinct in the room is to run `git cherry-pick --continue` and move on.

**Expected output:** Before continuing, the skill checks the **staged** tree —
`git diff --cached --check` (or `git diff --check HEAD`) — which flags the leftover markers
and exits non-zero, and treats that as Step 5 catching an unresolved file, not as noise. It
cleans the region to the intended result, re-stages, re-verifies (both checks clean,
`git ls-files -u` empty), re-runs the gate, and only then `git cherry-pick --continue`.

**Corrected by the live run (2026-07-04):** this scenario originally expected plain
`git diff --check` to flag the markers and `--continue` to refuse. Both claims are false in
this state: once the file is `git add`-ed, `git diff --check` compares worktree to index and
exits **0**, `git ls-files -u` is already empty, and `git cherry-pick --continue` would
happily **commit the markers** — the index is not unmerged. Only the staged-tree check
catches it, exactly as SKILL.md Step 5 warns.

**Verify:** `parser.py` has no `<<<<<<<`/`|||||||`/`=======`/`>>>>>>>` markers; the cherry-pick
completes only after the checks pass; no commit contains a marker.

## Scenario 4 — Weird: shared-stash and worktree hygiene under pressure

**Input:** A merge conflict in a worktree that also has unrelated dirty edits. The tempting
shortcut is `git stash` to "get a clean slate," and a sibling worktree has the target branch
checked out.

**Expected output:** The skill refuses to `git stash` around the in-progress merge — the
stash is shared across worktrees and stashing deletes `MERGE_HEAD` and rewrites sequencer
state. To back out it uses `git merge --abort`, not a stash cycle. It stays in the current
worktree and never touches the sibling worktree or its branch. If a pre-existing stash was in
play, it records `git stash list` first and restores the stack afterward.

**Verify:** No `git stash` was run against the live merge; `MERGE_HEAD` survived until an
explicit `--abort` or `--continue`; the sibling worktree is untouched; `git stash list`
matches its pre-run state.

## Dogfood record (2026-07-04, live — scratch repo, macOS)

Run by the model driving the skill through the active harness (invocation-policy check: model-invocable
as intended) in a scratch TypeScript repo with a real gate (`tsc --noEmit`, later
`+ py_compile`). All four scenarios, live:

- **Scenario 1 — PASS.** Real merge conflict in `config.ts` (ours added `retries`, theirs
  added `timeoutMs`, same object literal). Steps 1–6 in order: status/`--diff-filter=U`
  orient, `:1:/:2:/:3:` + `git log --merge` read, labels confirmed non-inverted, combined
  region keeping both fields, staged, both marker checks clean, `ls-files -u` empty, gate
  green, `git merge --continue`. Merge commit contains both intents.
- **Scenario 2 — PASS.** Rebase of `feature/parser` started onto `legacy` instead of `main`;
  the replay conflicted while re-applying already-landed main commits (wrong-base symptom)
  and legacy's only commit was `"fix"` (https→http, `port + 1` — intent unreadable). Both
  abort triggers recognized; `git rebase --abort` restored the exact pre-rebase tip
  (verified by hash); no guessed commit exists.
- **Scenario 3 — PASS, and it corrected this file.** Cherry-pick conflict in `parser.py`
  with diff3 markers half-cleaned (`|||||||`/`=======` left) and the file already staged.
  Live result: `git diff --check` exits **0** (does not catch it), `git ls-files -u` empty,
  `--continue` would have committed the markers; `git diff --cached --check` exits 2 and
  names both marker lines. Region cleaned to combine both intents (trim fields + drop
  empties), re-staged, gate green, cherry-pick completed; `git grep` over the commit shows
  no markers.
- **Scenario 4 — PASS (on redo).** Merge conflict with an unrelated dirty `notes.md`, a
  pre-existing stash entry, and a sibling worktree present. No stash was touched around the
  operation (stash reflog still exactly one entry), `MERGE_HEAD` survived until the explicit
  `--continue`, dirty edit preserved, sibling worktree untouched, gate green before
  `--continue`. **Operator error caught during the run:** the first attempt piped the gate
  to `/dev/null` inside a `&&` chain under `set -e`; the gate was red, the failure was
  silent, and a broken resolution got merged before the visible re-run exposed it. The redo
  ran the gate visibly. Lesson: never suppress gate output when its exit status is the
  decision — the skill's "gate green before `--continue`" is load-bearing.
