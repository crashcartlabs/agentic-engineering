# tests — dashboard

**Status: Scenarios 1-5 live-verified** by running the exact commands SKILL.md
documents directly (the `/dashboard` slash invocation itself wasn't triggered — these
runs prove the underlying mechanics `start`/`stop` rely on).

## Scenario 1 — Golden: start, watch runs, stop

**Input:** `/dashboard start` with `scripts/dashboard/config.json` pointing at a real
target repo; later, `/dashboard stop`.

**Expected output:** `start` launches `python3 scripts/dashboard/dashboard.py --watch`
in the background; `dashboard.pid` appears naming a live process, and
`scripts/dashboard/dashboard.html` is written. `stop` sends `SIGTERM` to that PID; the
pidfile disappears and the process exits.

**Verify:** `dashboard.pid` exists and its PID answers to `ps -p` right after `start`;
after `stop`, the pidfile is gone and the PID no longer appears in `ps`.

**Live-verified:** ran `nohup python3 scripts/dashboard/
dashboard.py --watch > /dev/null 2>&1 &` against a scratch config pointed at this
repo checkout — `dashboard.pid` appeared within 2s naming a live PID (confirmed via
`ps -p`), `dashboard.html` was written. Sent `kill <pid>`; the pidfile was gone within
2s and the PID no longer appeared in `ps`.

## Scenario 2 — Edge: `stop` with nothing running

**Input:** `/dashboard stop` when no `dashboard.pid` file exists (never started, or
already stopped).

**Expected output:** The skill reports that nothing is running — not an error, not a
crash.

**Verify:** no `kill` is attempted; no traceback; a plain "nothing is running" message.

**Live-verified:** with no `dashboard.pid` present, confirmed
there is nothing for `stop` to act on — the file genuinely does not exist, matching the
"say so, don't error" contract.

## Scenario 3 — Weird: `start` with no config

**Input:** `/dashboard start` before `scripts/dashboard/config.json` exists.

**Expected output:** The skill relays `dashboard.py`'s own config error (pointing at
`config.example.json`) rather than guessing a `repo_path` or silently defaulting.

**Verify:** no background process is launched; no pidfile is created; the error message
names `config.example.json`.

**Live-verified:** with `config.json` removed, `python3
scripts/dashboard/dashboard.py --watch` printed `dashboard: No config at
.../config.json. Copy config.example.json to config.json (next to it) and set
repo_path to your target repo.` and exited 1 — no pidfile, no background process.

## Scenario 4 — Weird: `dashboard.html`/`dashboard.pid` is a pre-planted symlink

**Input:** a symlink planted at the fixed output path (`dashboard.html` for a one-shot
render, `dashboard.pid` for `--watch`) pointing at an unrelated real file, before
running `dashboard.py`.

**Expected output:** the write is refused (`O_NOFOLLOW` -> `ELOOP`); a stderr message
names the path and says it's a symlink; the symlink and its target survive untouched;
the process does not crash. A one-shot run exits 1 with the message. A `--watch` run
whose *pidfile* path is the symlink refuses to start at all (exits 1 with the message,
never enters the loop) — a watch loop `/dashboard stop` can never find the PID for
would be an unmanageable background process, worse than refusing to start; a `--watch`
run whose *html* path is the symlink instead prints the message once per tick and
keeps looping, since the pidfile (and therefore `stop`) is unaffected.

**Verify:** the symlink's target file's content is byte-identical before and after;
the symlink itself is unchanged (`readlink` still points at the same target); a stderr
message referencing "is a symlink — refusing to write through it" appears; for the
pidfile case, no watch process is left running afterward.

**Live-verified:** planted a symlink at a scratch
`dashboard.html` pointing at a scratch file containing a marker string, then ran
`dashboard.py --config <scratch>/config.json` (one-shot) — exited 1, printed
`dashboard: <path> is a symlink — refusing to write through it` to stderr, and the
target file's marker content and the symlink itself were unchanged afterward.
Separately, planted a symlink at a scratch `dashboard.pid` and called `run_watch()`
directly with that path (the CLI has no `--pid-path` flag, so this exercised the
function directly rather than through `main()`) — the refusal message appeared once,
`run_watch` raised `SymlinkWriteRefused` without ever entering the loop, and the
pidfile symlink/target were unchanged; confirmed no `dashboard.html` was written and
no process was left running. (Amendment: an earlier version of this fix let
the watch loop keep running after the pidfile refusal — a Codex review
caught that this leaves an unmanageable, unstoppable background process; `run_watch`
now propagates the refusal instead of swallowing it, and `main()` catches it for a
clean exit-1 message.)

**Amendment (second round):** a later Codex review round caught
two more ordering issues in the same function, both fixed together since they pull in
opposite directions — checked with the real CLI's default pidfile path (the only path
`--watch` actually uses):
- The pidfile-symlink check ran *after* the first render, so a pre-planted pidfile
  symlink would let a fresh `dashboard.html` get written before the refusal — `gh
  /dashboard start`'s own success check (pidfile exists + names a live process) could
  be fooled by the symlink's pre-existing target. Fixed: `pid_path.is_symlink()` is
  now checked first, before anything else runs. Live-verified: with a pidfile symlink
  planted, `run_watch()` raised immediately and `dashboard.html` was confirmed never
  written.
- Requiring the first render to succeed (the round-5 fix above) had made an
  *html-only* symlink fatal on startup too, contradicting this same scenario's own
  documented non-fatal, per-tick behavior. Fixed: the initial render only treats a
  bare `SymlinkWriteRefused` as non-fatal (logged, startup continues); any other
  `DashboardError` (a genuinely broken `repo_path`) still refuses to start. Live-
  verified via the real CLI with `dashboard.html` symlinked: the watch process stayed
  alive, `scripts/dashboard/dashboard.pid` was written naming the live PID, stderr
  showed the per-tick refusal, the symlink's target was untouched, and stopping the
  process removed the pidfile normally.

## Scenario 5 — Weird: `stop` with a pidfile naming an unrelated process

**Input:** `scripts/dashboard/dashboard.pid` manually pointed at the PID of some other,
unrelated running process (not `dashboard.py --watch`).

**Expected output:** `stop` runs `ps -p <pid> -o command=`, sees it doesn't reference
`dashboard.py --watch`, reports "pidfile names a PID that isn't the dashboard process —
not sending SIGTERM", and does **not** send any signal.

**Verify:** the unrelated process is still alive and unaffected after `stop` runs; no
`kill` is issued against it.

**Live-verified:** started an unrelated long-running process
(`sleep 300 &`), wrote its PID into `scripts/dashboard/dashboard.pid`, then ran the
skill's documented check (`ps -p <pid> -o command=`, matched against `dashboard.py
--watch`) — the command was `sleep 300`, so the check printed the refusal message and
no signal was sent; the unrelated process was confirmed still alive immediately after
(`ps -p <pid>` still listed it) and was only stopped by an explicit cleanup `kill`
outside the test. Separately confirmed the positive case: with a real
`dashboard.py --watch` process running, the same `ps -p <pid> -o command=` check
matched and the logic would proceed to `kill`.

## Dogfood record (live — 3 real worktrees + 1 constructed stream)

`dashboard.py`'s own build/render pipeline (not the `/dashboard` slash wrapper itself)
was dogfooded end to end against this repo, configured with `repo_path` pointing at
this checkout, using real `git worktree` entries at genuinely different pipeline
stages:

- **Executing, mid-`/execute`, dirty (fully live):** this checkout's own worktree, on
  `plan/worktree-pipeline-dashboard`, with Phase 6 tasks `[~]` at the time of the run —
  rendered `Executing (Phase 6 of 6)`, the phase list with phases 1-5 marked done and 6
  current, and the `dirty` flag set (uncommitted plan/skill edits present).
- **No plan (fully live):** a temporary detached worktree
  (`.claude/worktrees/dogfood-no-plan`, `git worktree add --detach <path> 721da26`) at
  this repo's initial commit, before `plans/` existed at all — rendered `No plan` with
  the `No plan file.` placeholder and a staleness of `6d ago` (a real, old commit
  timestamp).
- **Committed + reviewed, with a review badge (fully live):** a temporary detached
  worktree (`.claude/worktrees/dogfood-reviewed`) at the commit where
  `plans/2026-07-03-reviewer-agent.md` reads `status: done`, with that plan's real
  historical `reviews/2026-07-03-reviewer-agent.md` report copied into the worktree's
  own local `reviews/` (reports are worktree-local and untracked, exactly as a live
  `/review-plan` run there would have left it) — rendered `Review badges`, all 4 phases
  done, and a `review-plan: BLOCKED` badge (matching that report's real
  `Verdict: BLOCKED`). This **also live-triggered** the needs-attention banner for the
  REVISE/BLOCKED trigger: `dogfood-reviewed — review-plan verdict is BLOCKED`.
- **PR open (babysitting) — design-verified, not live:** no PR was open anywhere to
  babysit at dogfood time, and opening one would require pushing a branch — outside the
  executor's scope for this plan. Verified instead by constructing a `StreamState` with
  a `PrState(state="OPEN", babysitting=True, ...)` directly and feeding it to
  `compute_stage`/`render_card`: correctly produced stage `PR open (babysitting)` and a
  card showing `PR #99 OPEN — mergeable: MERGEABLE, CI: passing (babysitting), 4
  comment(s), 2 review(s)`.

**Aggregate result:** the one-shot render over the 3 real worktrees produced
`3 streams, 0 open PRs, 1 needing attention` and one correctly-triggered banner entry —
matching every per-stream state by hand-inspection. The temporary worktrees were
removed (`git worktree remove --force`) after the run; nothing from this dogfood is
part of the shipped diff.

**Residual:** the `/dashboard start`/`stop` slash wrapper's *mechanics* are
live-verified (Scenarios 1-3 above, run via the exact underlying commands); an actual
`/dashboard start` typed by a user, and a `PR open (babysitting)` stream produced by a
real open PR, remain design-verified until a future session exercises them.

## Scenario 6 — Weird: a second `--watch` started while one is already running

**Input:** `python3 dashboard.py --config <config> --watch` while an earlier `--watch`
invocation against the same pidfile is still alive.

**Expected output:** the second invocation refuses (`DashboardError`, exit 1, a message
naming the existing PID) instead of overwriting the pidfile — overwriting would orphan
the original watcher, invisible to `/dashboard stop` once the second process's own
cleanup later removes the (now-second) pidfile.

**Verify:** the first watcher's pidfile is unchanged after the second invocation's
refusal; only one dashboard process is left running.

**Live-verified:** started `python3 scripts/dashboard/
dashboard.py --config <scratch-config> --watch` in the background (real CLI, real
default pidfile path), confirmed its pidfile named the live PID, then ran a second real
`--watch` invocation against the same config — it printed `dashboard: an existing
dashboard watcher is already running as pid <N>; stop it first` and exited 1; the first
watcher's pidfile was unchanged afterward. Killing the first watcher then removed the
pidfile normally. (Caught by a Codex review; a stale, dead-PID pidfile is
still correctly overwritten — not exercised live here, but covered by the
`is_live_dashboard_watcher` `--selftest` fixtures.)

## Scenario 7 — Edge: local `.git/info/exclude` isn't pre-populated

**Input:** a fresh checkout with no prior `scripts/dashboard/{config.json,dashboard.html,
dashboard.pid}` lines in `.git/info/exclude` (this file is per-clone, never committed).

**Expected output:** `dashboard.py` adds the three lines itself on a real (non-selftest)
run, so the generated files never show up in `git status` — matching the "ignore it
locally, never touch `.gitignore`" convention already used by `security-audit` and
`code-audit`.

**Verify:** after one run, `<git-common-dir>/info/exclude` contains all three lines; a
second run doesn't duplicate them; `--selftest` never touches the exclude file.

**Live-verified:** called `ensure_local_excludes()` directly
against a throwaway git repo (with `DASHBOARD_DIR` pointed inside it) — the first call
appended all three lines; a second call left the file byte-identical (idempotent, no
duplicates). Confirmed this repo's own working tree was untouched throughout (`git
status --porcelain` empty before and after).

## Scenario 8 — Weird: `--watch` started against a broken `repo_path`

**Input:** `python3 dashboard.py --config <config> --watch` where `config.json`'s
`repo_path` doesn't exist (or isn't a git repo).

**Expected output:** the watcher refuses to start at all — no pidfile is written, no
background daemon is left running — instead of writing the pidfile first and then
silently failing every render forever (which would let `/dashboard start` report
success for a watcher that can never produce a dashboard).

**Verify:** the process exits non-zero with a clear error naming the failure; no
pidfile exists afterward; `dashboard.html` is never created.

**Live-verified:** ran `python3 scripts/dashboard/dashboard.py
--config <scratch-config> --watch` with `repo_path` pointed at a nonexistent directory
— printed `dashboard: git worktree list failed for <path>: [Errno 2] No such file or
directory: ...` and exited 1; `scripts/dashboard/dashboard.pid` was never created and
the scratch `dashboard.html` was never written.

## Scenario 9 — Edge: `write_dashboard` writes atomically, not in place

**Input:** any `write_dashboard` call (one-shot or a `--watch` tick).

**Expected output:** the final `dashboard.html` never exists in a truncated/partial
state — the write goes to a same-directory temp file first, then an atomic
`Path.replace()` swaps it into place, so a browser's meta-refresh reload (or a kill
mid-write) can never observe a half-written document.

**Verify:** after a run, the output path contains a complete, valid document; no
leftover `.{name}.tmp<pid>` file remains in the directory.

**Live-verified:** ran a one-shot render against a scratch
throwaway repo — `dashboard.html` contained the complete rendered document
immediately, and no stray temp file was left in the output directory afterward.

## Scenario 10 — Weird: a genuine `gh` failure vs. a branch with no PR

**Input:** `run_gh_pr_view` called (a) against a branch that genuinely has no open PR,
and (b) against a `gh` invocation that fails for a real reason (not authenticated,
rate-limited, not a git repo, `gh` missing/timeout).

**Expected output:** case (a) returns `(None, None)` — silent, exactly as before,
since "no PR" is a normal, expected state. Case (b) returns `(None, <message>)`, which
`build_streams` threads onto `StreamState.pr_fetch_error`; `render_card` shows a
distinct "⚠ PR status unknown — <message>" line instead of silently looking like a
clean stream with no PR, and `compute_needs_attention` surfaces it in the
needs-attention banner too — a systemic `gh` outage must never look identical to
"nothing needs attention."

**Verify:** case (a) produces no visible difference in the rendered card. Case (b)'s
card shows the warning line, and the aggregate summary's needs-attention count
includes that stream.

**Live-verified:** called `run_gh_pr_view(".", "main")` (a
real branch with no PR) — returned `(None, None)`, matching prior behavior exactly.
Called `run_gh_pr_view(<a throwaway non-git temp dir>, "main")` — returned `(None,
"gh pr view failed: failed to run git: fatal: not a git repository ...")`, confirmed
distinct from the no-PR case. `compute_needs_attention`/`render_card`'s handling of
the resulting `pr_fetch_error` field is covered by `--selftest`.

## Scenario 11 — Weird: `/dashboard start`'s own success check against a broken output path

**Input:** `/dashboard start` where the configured output path is a pre-planted
symlink (or otherwise permanently unwritable) from the very first tick.

**Expected output:** the skill's own "confirm it actually started" check must not
declare success on pidfile+PID alone — `--watch` stays alive with a working pidfile
in this case (Scenario 4's non-fatal, per-tick design) but never produces
`dashboard.html` at all, and its stderr is redirected to `/dev/null` by the
documented launch command, so nothing else would surface the problem. The skill now
also confirms the HTML path exists with a recent mtime before declaring success.

**Verify:** with the output path pre-symlinked, the pidfile/process check alone
passes but the HTML file never appears; the skill's completion criterion (as
documented) requires both, so a careful run following it would report the
degraded state rather than a clean success.

**Live-verified (underlying mechanics):** this exact
pidfile-exists-but-html-never-written condition was already directly observed live
in Scenario 4's amendment (an html-symlink leaves the watcher alive with a working
pidfile while every render fails) — this scenario adds the corresponding check to
the skill's own documented success criteria so a future `/dashboard start` run
actually verifies the HTML output rather than assuming it from the pidfile alone.

**Amendment:** a further Codex review round caught that the check above
was itself insufficient — an ordinary existence/mtime check (`[ -e path ]`, `stat`)
*follows* a symlink and reports on whatever it points at, so a symlink whose target
happens to already exist with a recent mtime would pass that check even though
`write_dashboard` refused to touch it. The skill now requires confirming the HTML
path is a regular file, not a symlink itself (`[ -L path ]` must be false), before
even checking its mtime. Live-verified: planted a symlink at a scratch path to a
pre-existing, just-touched target file — a naive `[ -e path ]` reported it as
existing (would have wrongly passed), while `[ -L path ]` correctly identified it as
a symlink.

**Amendment (second round):** the same class of gap existed one step
earlier — the pidfile check itself. If `scripts/dashboard/dashboard.pid` is a
*pre-existing* symlink pointing at a file whose content happens to be some unrelated
live process's PID number, `run_watch` correctly refuses to start (Scenario 4) and
never touches it — but `/dashboard start`'s own verification, if it only reads
through the symlink and checks `ps -p <pid>`, would see that unrelated PID reported
as genuinely alive and could declare success (compounded by a stale-but-real
`dashboard.html` from a previous run passing the HTML check above). The skill now
also requires confirming `dashboard.pid` itself is a regular file, not a symlink,
and that the named PID's command line actually matches the dashboard watcher pattern
(the same tightened check `stop` uses) rather than trusting bare liveness. Live-
verified: planted a pidfile symlink pointing at a file containing a genuinely live,
unrelated process's (`sleep 300`) PID — a naive `ps -p <pid>` reported it alive
(would have wrongly passed), while `[ -L path ]` correctly flagged the symlink and
the cmdline check correctly rejected `sleep 300` as not matching the watcher pattern.

## Scenario 13 — Weird: the predictable temp path used for atomic writes is a pre-planted symlink

**Input:** `write_dashboard`'s atomic-write temp file (`.{output_path.name}.tmp<pid>`,
a predictable name once the watcher's PID is known) is a pre-planted symlink to an
arbitrary file, even though the *final* `output_path` itself is not.

**Expected output:** the write is refused before the temp file is ever opened — the
Scenario 4/9 symlink protection on the final path doesn't help here, since the
actual bytes are written to the temp path first; that write must get the same
`O_NOFOLLOW` treatment, or the attacker's chosen file gets overwritten with the
rendered dashboard content instead.

**Verify:** the attacker-chosen target file's content is byte-identical before and
after; the final `output_path` is never written at all; a stderr message names the
temp path and says it's a symlink.

**Live-verified:** planted a symlink at the exact predictable
temp path (`.dashboard.html.tmp<real pid>`) pointing at a scratch file containing a
marker string, then called `write_dashboard()` against a real throwaway repo — raised
`SymlinkWriteRefused` naming the temp path, the marker file's content was unchanged
afterward, and `dashboard.html` was never created.

**Amendment:** a further review round caught that `run_watch`'s initial
render treated *this* temp-path refusal the same as the recoverable final-output-path
case (Scenario 4) — logged and non-fatal, letting startup proceed to write a pidfile.
That's wrong specifically for the temp path: its name is fixed for the process's
entire lifetime (PID-based), so if it's symlinked now it will fail identically on
every future tick too — unlike the final path, which an operator can fix while the
watcher keeps running. `write_dashboard` now re-raises the temp-path case as a plain
`DashboardError` rather than `SymlinkWriteRefused`, so `run_watch`'s "non-fatal"
catch (which only catches `SymlinkWriteRefused`) doesn't swallow it, and the whole
watcher correctly refuses to start instead. Live-verified: planted a symlink at the
exact predictable temp path, with a stale-but-real `dashboard.html` from a prior run
already present (the scenario that could otherwise fool a naive check) — `run_watch`
raised a plain `DashboardError` (confirmed not a `SymlinkWriteRefused` instance), no
pidfile was ever written, and the target file was unchanged.

## Scenario 12 — Weird: `stop`'s PID-identity check against a contrived command line

**Input:** a pidfile naming a live process whose command line contains the literal
words "dashboard.py" and "--watch" as ordinary arguments to something else entirely
(e.g. `python3 -c '...' dashboard.py --watch`, where those two tokens are just extra
positional arguments to an inline `-c` script), rather than actually running
`scripts/dashboard/dashboard.py --watch`.

**Expected output:** `stop`'s identity check must not be fooled by a bare substring
match — it requires `scripts/dashboard/dashboard.py` (the real relative path, not
just the bare filename) to appear as a genuine argument, together with `--watch` as
its own token, before treating the PID as a confirmed match.

**Verify:** the contrived command is rejected; a real `dashboard.py --watch`
invocation (relative or absolute path) still matches.

**Live-verified:** tested the tightened pattern
(`grep -qE '(^|[[:space:]/])scripts/dashboard/dashboard\.py([[:space:]]|$)'` plus a
separate `--watch`-as-its-own-token check) against three command-line strings: a
real relative-path invocation (matched), a real absolute-path invocation (matched),
and the contrived `python3 -c '...' dashboard.py --watch` counter-example from the
review (correctly rejected, since it contains the bare filename `dashboard.py`, not
the real `scripts/dashboard/dashboard.py` path).

**Amendment:** a further review round found the tightened pattern still
matched a *second* contrived counter-example that used the real path:
`python3 -c 'import time; time.sleep(30)' scripts/dashboard/dashboard.py --watch` —
the real script path and `--watch` are still just extra, unrelated arguments to the
inline `-c` code being executed. The check now also rejects any command containing a
`-c` flag outright, since a genuine `python3 scripts/dashboard/dashboard.py --watch`
invocation never has one. This narrows but doesn't fully eliminate every possible
adversarial construction (an infinite family of `python3 -c` disguises is inherent
to what a `ps`-based text check can distinguish); the residual is bounded the same
way the original security audit framed this class of issue — a local, single-user,
self-inflicted `SIGTERM` at worst. Live-verified: the new counter-example is
correctly rejected (contains ` -c `), and the real relative-path invocation still
matches (no `-c` present).

## Scenario 14 — Edge: atomic-write temp files excluded from `git status`

**Input:** a crash or `SIGKILL` between `write_dashboard`'s temp-file write and its
atomic `replace()`, leaving `.dashboard.html.tmp<pid>` behind in `scripts/dashboard/`.

**Expected output:** the leftover temp file doesn't show up as untracked in
`git status` — `ensure_local_excludes()` now also covers the temp-file glob pattern,
not just the three fixed filenames.

**Verify:** `<git-common-dir>/info/exclude` contains a
`scripts/dashboard/.dashboard.html.tmp*` line; a real leftover temp file matching
that glob is invisible to `git status --porcelain -uall`.

**Live-verified:** wrote that exact exclude line into a
throwaway git repo's `.git/info/exclude`, created a matching temp filename inside it
— `git status --porcelain -uall` produced no output at all, confirming the glob
pattern is correctly ignored.

## Scenario 15 — Weird: a `-N`-suffix report slug that's actually a different stream

**Input:** two review reports on the same day — `2026-07-06-api.md` (the real report
for a stream whose slug is `api`) and `2026-07-06-api-2.md` (a **different**,
legitimately-named stream whose slug is `api-2`, not a same-day re-review of `api`) —
with the second one more recently modified.

**Expected output:** `find_latest_review` must not pick `api-2.md` for the `api`
stream just because its slug matches the `-N` same-day-suffix pattern — the two are
filename-indistinguishable, so the match is cross-checked against each candidate
report's own embedded identity (a `Plan:` line, or the `# Code Review`/`# Security
Audit` heading's branch) before being accepted. A report whose format doesn't embed
identity at all (`skill-safety-scan`) can't be cross-checked this way and is accepted
as before — this fix narrows the ambiguity for the three report types that do embed
identity, it doesn't (and can't) fully close it for the one that doesn't.

**Verify:** the `api` stream's card shows `api.md`'s badge, not `api-2.md`'s, even
though `api-2.md` is the more recently modified file.

**Live-verified via `--selftest`:** constructed exactly this scenario (`api.md` with
embedded branch `plan/api`, `api-2.md` — modified later — with embedded branch
`plan/api-2`) and confirmed `find_latest_review(..., ["api"], branch="plan/api")`
returns `api.md`, not the newer `api-2.md`.

## Scenario 16 — Edge: a configured `output_path` inside the repo isn't excluded

**Input:** `config.json`'s `output_path` points somewhere inside this same repo
(e.g. one of the watched worktrees) instead of the default `scripts/dashboard/`.

**Expected output:** `ensure_local_excludes` also covers the *configured* path (and
its atomic-write temp-glob sibling), not just the four fixed default lines — a
dashboard writing its own output into a repo it also monitors would otherwise mark
that stream dirty with output it created itself.

**Verify:** `<git-common-dir>/info/exclude` gains a line for the configured
`output_path` (relative to the repo root) and a matching `.{name}.tmp*` line; a
second call doesn't duplicate them; a configured path outside this repo is silently
skipped (best-effort only, never an error).

**Live-verified:** called `ensure_local_excludes({"output_path":
"<scratch>/custom/subdir/my-dashboard.html"})` against a throwaway repo with
`DASHBOARD_DIR` pointed inside it — the exclude file gained both
`custom/subdir/my-dashboard.html` and `custom/subdir/.my-dashboard.html.tmp*`
alongside the four defaults; a second call left the file unchanged (idempotent).

## Scenario 17 — Edge: default-branch resolution when only a remote-tracking ref exists

**Input:** `origin/HEAD`'s symbolic-ref is unset, and no *local* `main`/`master`
branch exists — only a `refs/remotes/origin/main` remote-tracking ref (a real,
plausible state for a feature-only checkout or a worktree that never checked out the
default branch locally).

**Expected output:** `resolve_default_branch` still returns `main` — the fallback
loop now also checks `refs/remotes/origin/<candidate>`, not just
`refs/heads/<candidate>`. Without this, a stream actually on the repo's own default
branch would never trigger the documented default-branch attention item.

**Verify:** `resolve_default_branch` returns the correct name even with no local
`main`/`master` branch present.

**Live-verified:** built a throwaway repo with a
`refs/remotes/origin/main` ref but no local `main` branch (renamed the local branch
to `feature-only`) and no `origin/HEAD` symbolic-ref — `resolve_default_branch`
correctly returned `"main"`.

## Scenario 18 — Weird: a dirty path containing a space or quote character

**Input:** `git status --porcelain -uall` output for a path git quotes (spaces,
quotes, backslashes, or non-ASCII bytes trigger C-style quoting by default), e.g.
`?? "file with space.txt"`.

**Expected output:** the returned path is unquoted (`file with space.txt`, not the
literal `"file with space.txt"` with quote characters) — a later `.stat()` against
the quoted literal would silently miss the real file (caught by the existing
degrade-to-skip pattern), understating a stream's staleness by ignoring a genuinely
current edit.

**Verify:** `parse_git_status_porcelain` output matches real filenames exactly, with
no leftover quote/escape characters.

**Live-verified via `--selftest`:** `_unquote_git_path` fixtures cover a plain
unquoted path (unchanged), a quoted path with a space, escaped quote/backslash
characters, and escaped tab/newline; `parse_git_status_porcelain` correctly unquotes
a full porcelain line end to end.

## Scenario 19 — Edge: dashboard is POSIX-only, not Windows-ported

**Input:** `/dashboard start` invoked from a PowerShell session (Windows).

**Expected output:** the skill states `POSIX-only (macOS/Linux); not supported on
Windows` near the launch instructions and provides only the POSIX `nohup ... &`
command. `dashboard.py` itself exits nonzero with the same clear message before it
can reach `O_NOFOLLOW` or `ps`, so an unsupported platform does not produce an
`AttributeError` traceback.

**Verify:** `SKILL.md` contains no PowerShell launch command; the embedded
`dashboard.py --selftest` fixtures cover missing `O_NOFOLLOW`, missing `ps`, and the
`main()` error path that returns nonzero with the POSIX-only message and no traceback.

**Live-verified via `--selftest`:** simulated the missing
platform primitives and `main()` unsupported-platform path on macOS. A real Windows
run remains unverified; the point of the check is to refuse Windows rather than port
the dashboard's POSIX worktree, `ps`, `nohup`, and signal-handling workflow.
