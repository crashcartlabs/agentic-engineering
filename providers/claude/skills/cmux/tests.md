# Tests for the `cmux` skill

Mark each scenario **live-verified** (actually run, output observed) once
run, or **design-verified** (traced by inspection only) if not yet run live
— do not mark something live-verified without having actually run it.

## Golden: fan-out two features — **live-verified**

1. In a scratch git repo, run:
   ```
   /cmux deploy 2 workspaces of pi agents to build features "add a health
   endpoint" and "add a version endpoint" in <scratch-repo-path>
   ```
2. Expect: two worktrees created under `<scratch-repo>-worktrees/`, two cmux
   workspaces visible (siblings in one window), a manifest at
   `.cmux/fleet/<slug>.json` listing both entries with real refs, and the
   response returns immediately (does not block).
3. `/cmux check <fleet>` shows both agents' current screen output.
4. `/cmux teardown <fleet>` closes both workspaces; worktrees remain on disk.

Verified by invoking `scripts/cmux/spawn_fleet.py --arrange tabs` directly
against a real scratch repo with two `pi` entries (not by asking a live
Claude Code session to parse the natural-language `/cmux deploy ...`
request into that invocation — the underlying mechanism this skill drives
is confirmed, but the skill's own natural-language-to-CLI translation step
was not separately exercised). Confirmed under the historical unsafe-launch
implementation: two real worktrees, two real cmux
workspaces, correct manifest, both `pi` agents actually launched (via
`read-screen`) with the right model in the right cwd. Also live-verified the
grid arrangement (`--arrange grid`, entries mixing `claude`+`pi`) and a full
`just build` run. Safe launch construction is now covered by the script's
selftest; the older live run used permission-bypass flags and is not evidence
for the new safe default. Two real bugs were found and fixed during this verification — see
below.

**`codex` substitution note:** `codex` was not installed in the verification
environment (`which codex` finds nothing). Every scenario
here that calls for "any agent" or an agent mix instead substitutes `pi`
and/or `claude`, both of which were actually run and observed. The one place
`codex` appears is the real 4-entry `just build` run, where its pane's
command was constructed and executed exactly as designed (`cd <worktree> &&
codex --dangerously-bypass-approvals-and-sandbox -m gpt-5.5 '<task>'`) but
the shell reported `bash: codex: command not found` — this confirms the
command-construction and per-pane `cd` mechanics are correct, but `codex`'s
own actual runtime behavior (does it authenticate, does it honor these
flags, does it actually build anything) has not been observed and remains
unverified.

## Edge: cmux not running and socket not yet open — **live-verified**

1. Quit cmux (`osascript -e 'tell application "cmux" to quit'`).
2. Repeat the golden scenario.
3. Expect: the skill/script notices `cmux ping` failing, runs `open -a
   cmux`, polls until the socket is up, and proceeds — without asking for
   confirmation partway through.

Confirmed: quit cmux, ran `spawn_fleet.py` against a scratch repo, it
auto-launched cmux and bootstrapped the fleet in under 2 seconds.

## Edge: socketControlMode still `cmuxOnly` — **design-verified**

1. Manually reset `~/.config/cmux/cmux.json`'s `automation.socketControlMode`
   to `cmuxOnly` (or remove the `automation` key) and fully restart cmux.
2. Repeat the golden scenario.
3. Expect: when invoked outside cmux, the script refuses with instructions to
   run inside a cmux pane. It must not edit `cmux.json` unless the caller also
   supplied the explicit `--allow-all-socket` override.

The older implementation automatically raised the policy and was live-tested;
that history is retained below, but it is not the current safety contract. The
current refusal and explicit-override branches are covered by `--selftest`.

**Bug found and fixed during this test:** `ensure_cmux_running()` originally
used `cmux ping` as its only "is cmux running" signal. Under `cmuxOnly`,
`ping` itself is refused from outside a cmux pane *even when the app is
fully running* — so the function could never tell "not running" apart from
"running but policy-blocked," and spun for 20 seconds before dying, even
though cmux was up the whole time. Fixed by falling back to process
liveness (`pgrep -f "Contents/MacOS/cmux"`) when `ping` fails.

**Second bug found during task review (not live-testing) and fixed:** the
first fix above introduced a subtler, self-healing race: since
`_cmux_process_alive()` can return true the instant the OS forks the
process — before cmux's own socket server has finished initializing —
`ensure_cmux_running` could return just ahead of the socket actually being
ready. `ensure_socket_allowall`'s *first* `capabilities` check was a single,
un-polled call at that point, so it could misread "socket not ready yet" as
"still cmuxOnly" and trigger an unnecessary backup/restart cycle even when
nothing was actually wrong (it would still reach the correct end state, just
after wasted seconds and an extra `cmux.json.bak.*` file). Fixed by making
that first check a short bounded poll too (`_capabilities_allowall()`,
shared with the post-restart check), symmetric with the fix already applied
for the post-restart case. This closes the race by construction (the first
check now retries instead of trusting a single sample), but the exact
timing window that would trigger it wasn't independently reproduced —
`--selftest` and a fresh grid-mode run were re-confirmed passing after the
change, which rules out a regression but doesn't prove the race was ever
actually hit in the runs performed.

## Error: branch/worktree name collision — **live-verified**

1. Run the golden scenario once, then run it again with an identical feature
   description (so it derives the same slug) without tearing down or
   removing the first run's worktree/branch.
2. Expect: a clear error naming the exact colliding worktree path — not a
   silent overwrite, and not an unrelated stack trace.

Confirmed: second run with the same `--run-slug`/entry produced `error:
worktree already exists: <exact path>` and exit code 1 — no overwrite, no
stack trace.

## Bug found and fixed: grid mode only saw one pane's surface

While live-testing the grid/bake-off arrangement (2 entries), `spawn_grid`
failed with `expected 2 panes in grid workspace workspace:9, found 1`. Root
cause: `cmux list-pane-surfaces --workspace <ref>` (with no `--pane`)
silently returns only the *focused* pane's surfaces, not every pane in the
workspace — confirmed via `cmux tree --workspace <ref>`, which showed both
panes and both surfaces actually existed. Fixed by enumerating panes first
(`cmux list-panes --workspace <ref>`) and reading each pane's surface
individually (`list-pane-surfaces --workspace <ref> --pane <pane-ref>`).
Re-tested after the fix: both panes correctly resolved, correct labels
attached to the correct surfaces.

**Follow-up fix from task review:** the initial fix above still matched
each pane's surface to an entry positionally (`zip(entries, worktrees,
surface_refs)`, relying on `list-panes`' enumeration order matching the
order entries were submitted in) — an assumption never actually confirmed
by cmux's own documentation. Since each surface is already named
`entry.label` at creation time, and `list-pane-surfaces`' output includes
that name, the fix was tightened to match surfaces to entries **by name**
instead of position — eliminating the ordering assumption entirely. Live
re-verified with 3 entries (`alpha`/`pi`, `beta`/`pi`, `gamma`/`claude`):
each surface's cwd and model, read back via `read-screen`, matched its
entry's label correctly.

**Second follow-up fix, found by task review (not live-testing):** the
name-keyed match above broke the single-entry grid path
(`--arrange grid` with exactly one `--entry`), which creates its surface via
a plain `--command` with no per-surface name set anywhere (unlike the
multi-entry `--layout` path, whose leaves are named `entry.label`) — so the
new lookup would always fail to find a name match and `die()`, a regression
in a previously-working, still-reachable path that the 3-entry
re-verification above didn't exercise. Fixed by special-casing
`len(entries) == 1` to use the surface ref the `workspace create --json`
response already names directly, skipping the name-lookup path entirely for
that case. Live re-verified: a real single-entry `--arrange grid` run
correctly created one worktree/workspace/surface with the right cwd and
model, confirmed via `read-screen`.

## Known caveat (not fixed, out of scope): Claude Code's folder-trust prompt

Live-testing the grid arrangement with a `claude` entry showed Claude Code
stop at a "Quick safety check: Is this a project you created or one you
trust?" prompt on first launch in a brand-new worktree directory —
`--dangerously-skip-permissions` does not bypass this; it's a separate,
per-directory trust gate. This only appears in a real interactive terminal
(a cmux pane); `claude`'s own `--help` notes the dialog is skipped when
stdout isn't a TTY (e.g. the orchestrator's own `exec_orchestrator` launch,
which is not itself a fresh cmux pane). Net effect: a `claude`-agent entry
in a fleet may need one manual "yes, trust this folder" click the first
time a given worktree path is used. This is a Claude Code behavior, not a
bug in this project's tooling, and fixing it (e.g. pre-seeding trust for
generated worktree paths) is out of scope for this tooling — flagged here for
awareness rather than silently worked around.

## Bug found and fixed (whole-branch review): manifest stored positional refs, not UUIDs

The final whole-branch review (after the per-task reviews individually passed) caught
something no single task's reviewer had context to see: `spawn_tabs` stored
`workspace_ref`/`surface_ref` straight from `workspace create --json`'s
default output — which are **positional** refs (`workspace:5`,
`surface:7`), not UUIDs — into the manifest, while
`references/events-and-waiting.md` documents matching notification events
on a `workspace_id` **UUID**. Since the manifest never actually contained a
UUID form, that documented wait pattern could never match against a
fan-out-created fleet's real workspace. Separately, `SKILL.md` itself warns
"anchor to the UUID form" for anything long-lived — the manifest, read back
by `check`/`collect`/`teardown` potentially hours later, is exactly that,
so a positional ref risked drifting to the wrong surface if unrelated panes
opened/closed in between.

Confirmed live: `cmux workspace create --json` (no extra flags) returns only
`workspace_ref`/`surface_ref` in positional form; `--id-format both --json`
returns both the positional refs *and* `workspace_id`/`surface_id` UUIDs in
the same response, and those UUIDs work as direct drop-in values for any
later `--workspace`/`--surface` flag (confirmed via `read-screen` using the
UUIDs directly). `list-pane-surfaces` also accepts `--id-format both`,
adding the UUID as a second token before the name in its output
(`surface:13 <uuid>  <name>`).

Fixed: `spawn_tabs` and `spawn_grid` now pass `--id-format both` on every
`workspace create` call and store the UUID fields (`workspace_id`,
`surface_id`) as the manifest's `workspace_ref`/`surface_ref` values (field
*names* unchanged, so nothing downstream needed to change its manifest
schema — only the *values* are now UUIDs instead of positional refs). The
grid path's name-keyed pane matching now captures the UUID from
`list-pane-surfaces --id-format both`'s output instead of the positional
ref. `SKILL.md` and `references/socket-policy.md` were also updated to
recommend `--id-format both` for ad-hoc driving of anything long-lived, and
to note that `cmux ping` alone can't distinguish "cmux is down" from
"cmux is up but `cmuxOnly` refuses us" (the same lesson already applied
inside `spawn_fleet.py`, now propagated to the hand-driving instructions).

Live re-verified all three code paths after the fix (tabs, single-entry
grid, multi-entry grid): each produced a UUID-form manifest, and
`read-screen` using those UUIDs directly (not the positional refs cmux also
returned) correctly reached the right surface with the right cwd/model in
every case.

## Bugs found and fixed (Codex PR review)

This repo's own automated Codex review flagged 6 real issues on the PR. Five
were tractable and fixed directly; one (colon-containing model IDs) needed a
human design decision first.

- **Subdirectory `--repo` rejected.** `main()` only checked `(repo /
  ".git").exists()`, which fails for a normal subdirectory of a repo (e.g.
  `repo/packages/app`) even though `just build`/`debug` are documented to
  target wherever they were invoked from. Fixed with `resolve_repo_root()`
  (`git -C <path> rev-parse --show-toplevel`). Live re-verified: invoking
  with `--repo <scratch-repo>/packages/app` correctly wrote the manifest at
  the real repo root, not the subdirectory.
- **Colon-containing model IDs silently mis-parsed.** `parse_entry`'s
  `split(":", 3)` structurally cannot represent a model ID with its own
  colon (e.g. pi's `sonnet:high` thinking-level shorthand) — colons beyond
  the 3rd position always become part of `description`, with no error and
  no way to detect after the fact that truncation happened (the 3rd split
  segment is colon-free by construction, so a runtime "reject if the model
  needed a colon" check isn't actually implementable without changing the
  delimiter). Asked the human: keep the current colon-delimited format (no
  breaking change to already-shipped docs/justfile) and treat
  colon-containing models as unsupported by this format for now, revisiting
  the delimiter only if a real need comes up. Implemented the one concretely
  fixable part of this: `parse_entry` now rejects a genuinely **empty**
  model field (`x:pi::description`), which was a separate, real,
  detectable bug (see next item) — the colon-truncation case itself is
  now documented (in code comments) as a known constraint of this format,
  not silently mis-parsed without any signal at all.
- **Empty model field accepted.** `x:pi::reply ready` parsed with
  `model == ""`, so the launch line became `--model <task-text>` — the
  agent's own task got passed as its model argument. `parse_entry` now
  rejects an empty model with a clear `ValueError`.
- **Tabs mode could leave orphaned, untracked workspaces on a later
  collision.** `spawn_tabs` created each entry's worktree and cmux workspace
  in sequence; if a later entry hit a worktree collision, the script died
  before writing any manifest, leaving earlier entries' agents running with
  no record to check or tear them down. Fixed with
  `preflight_worktree_paths()`, called before anything is created. Live
  re-verified: a 2-entry run where only the *second* entry's worktree path
  already existed failed immediately with `worktree(s) already exist: ...`
  and `git worktree list` confirmed **zero** worktrees were created (not
  even the first, non-colliding entry).
- **Grid-mode notification events don't identify which pane finished.** All
  panes in a `grid` fleet share one `workspace_id`, so the documented
  `notification.requested` wait pattern fires when *any* agent in the grid
  finishes a turn — not a specific one, and `surface_id` is usually `null`.
  `references/events-and-waiting.md` now says explicitly: treat the event as
  a wakeup only, then `read-screen` every entry's own `surface_ref`
  individually to learn real per-entry status.
- **Model values interpolated unquoted into the launch command.** Only
  `task` was wrapped in `shlex.quote()`; a model string with shell
  metacharacters would inject into the command cmux runs. All three
  `YOLO_LAUNCH` lambdas now quote `model` too. Added a selftest asserting
  (via `shlex.split()`, simulating real shell tokenizing) that an unsafe
  model string like `m; touch /tmp/pwned` survives as a single argument
  rather than becoming a second command.

## Bugs found and fixed (Codex PR review, round 2)

A fresh Codex review on the fixes above found 4 more real gaps, all in the
same preflight/robustness family. Fixed and live-verified against the real
installed cmux:

- **Duplicate labels weren't rejected.** Two entries slugifying to the same
  label (e.g. `API!` and `API?`, both → `api`) would let the first worktree
  and cmux workspace get created before the second's `create_worktree` died
  on the now-existing path — same orphaned-resource shape as the original
  worktree-collision bug, just triggered a different way.
  `preflight_worktree_paths` now checks for duplicate labels first, before
  touching the filesystem or git at all. Live re-verified: two entries
  slugifying to `api` are rejected immediately with `duplicate entry
  label(s) after slugifying: ['api']`.
- **Pre-existing branches weren't preflighted.** Only the worktree
  *directory* was checked for collisions; a stale `cmux/<run>-<label>`
  branch (e.g. left over from `git worktree remove` without deleting the
  branch) would still fail `git worktree add -b` — same partial-fleet risk,
  just for branches instead of directories.
  `preflight_worktree_paths` now also checks every entry's target branch
  name (`git show-ref --verify --quiet refs/heads/<branch>`) up front. Live
  re-verified: a pre-existing branch is rejected immediately with
  `branch(es) already exist: ...`, before any worktree is created.
- **Fleet manifests could be silently overwritten.** Reusing an explicit
  `--run-slug` (or an unlucky one-second timestamp collision on the
  auto-derived slug) would overwrite `.cmux/fleet/<slug>.json`, losing the
  only recorded refs for the earlier fleet — its cmux surfaces/worktrees
  become unreachable via `/cmux check`/`/cmux teardown`. `main()` now checks
  for an existing manifest at the very start (before any preflight or cmux
  work) and refuses to proceed if one is already there. Live re-verified:
  running the same `--run-slug` twice fails the second time with a clear
  error naming the existing manifest path; confirmed no new worktree was
  created by the rejected second run.
- **`cmux hooks setup --yes`'s exit code was discarded.** If it failed, the
  fleet was still reported bootstrapped even though notification-based
  waiting (`references/events-and-waiting.md`) silently wouldn't work.
  `main()` now checks the exit code and prints a warning naming what still
  works (read-screen-based checking) if it fails, rather than staying
  silent. The non-failure path is unaffected — confirmed no warning printed
  across all the passing runs in this round of testing.

## Bug found and fixed (Codex PR review, round 3)

`branch_exists()`'s exact-ref probe (`git show-ref --verify`) missed that
git's ref namespace is hierarchical (`refs/heads/` is a tree, not a flat
list), so two real collision shapes could still make `git worktree add -b
<branch>` fail even after the "preflighted" check passed: (a) a ref already
existing *nested under* the target name, and (b) an ancestor path component
of the target already being a ref itself. Both were confirmed live in a
scratch repo before fixing, not assumed:

```
$ git branch cmux/run-x-api/sub && git branch cmux/run-x-api
fatal: cannot lock ref 'refs/heads/cmux/run-x-api': 'refs/heads/cmux/run-x-api/sub' exists; cannot create 'refs/heads/cmux/run-x-api'
$ git show-ref --verify --quiet refs/heads/cmux/run-x-api; echo $?
1   # exact-match probe says "doesn't exist" -- wrong

$ git branch cmux && git branch cmux/run-x-api
fatal: cannot lock ref 'refs/heads/cmux/run-x-api': 'refs/heads/cmux' exists; cannot create 'refs/heads/cmux/run-x-api'
$ git show-ref --verify --quiet refs/heads/cmux/run-x-api; echo $?
1   # same false negative
```

Fixed: `branch_exists()` now also probes for any child ref under the target
(`git for-each-ref "refs/heads/<branch>/"`) and walks every ancestor path
component checking for an exact ref there too. Live re-verified against the
real CLI: both collision shapes are now correctly rejected before any
worktree is created, and a clean run with neither collision still succeeds
(no false positive).
