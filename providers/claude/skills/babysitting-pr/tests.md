# tests — babysitting-pr

**Status: S3 fully live; S1 and S4 live except one sub-path each; S2 design-verified.** The
watch arc — arm, wake classification, triage, fix, watch-to-green, terminal wake, wind-down —
ran live across four PRs (records below). Precise coverage:
- **S3** (out-of-band merge → teardown) — fully live.
- **S1** (red-CI wake → diagnose → fix → green) — live *except* the delegated-subagent fix
  path. Every live CI fix (incl. the staged break) was small enough to land **inline** under
  the delegation floor, so the wake/diagnose/fix/green loop is proven but **delegating the fix
  to a subagent is still design-verified** — no live break warranted it.
- **S4** (timer-fired no-op) — the silent-no-op *classification* is live. The **re-arm**
  is provided by the recurring hourly cron (still armed, re-fires by construction); the demo
  used a short recurring cron retired after one fire, so an explicit "schedule a fresh timer"
  step was not separately observed — the recurring-job mechanism covers it.
- **S2** (ambiguous/architectural or access-escalating comment) — design-verified; no such
  comment occurred across four watches (all were tractable or stale).
- **S5** (`babysitting-active` label lifecycle) — the label add/remove *mechanics* are
  live-verified (staged against a real merged PR, below); the label has not yet been exercised as
  part of a real end-to-end arm→wind-down watch (no PR was open to babysit when this
  landed).

Coverage: S5 label mechanics staged live on a real merged PR; S1 loop + S4 no-op
live; S3 live; delegated-fix and fresh-timer sub-paths design-verified.

## Scenario 1 — Golden: CI fails → diagnose → push fix → green

**Input:** Babysitting an open PR. A `<github-webhook-activity>` arrives reporting a
failed CI check — a lint/test job red on a real break the PR introduced.

**Expected output:** The wake is classified as a real CI failure. Because the job is
"get it green," it is never a no-op: the skill pulls the failing job logs, judges the
fix small and in line with the PR's intent, **delegates** a focused subagent to land the
change, and pushes. No PR comment is posted for a self-evident fix. It stays subscribed
and keeps the check-in armed; when the follow-up webhook/check-in shows the check green,
the fix is treated as done. The skill does **not** merge the PR.

**Verify:** a commit fixing the failing check lands on the PR branch; the previously-red
check reads green on the next state pull; the subscription is still active (no
`unsubscribe_pr_activity`); no comment was posted.

## Scenario 2 — Edge: ambiguous review comment → ask the human

**Input:** A `<github-webhook-activity>` review comment requests an architecturally
significant change — a design call, e.g. "switch this to an event-sourced model" — not a
mechanical fix.

**Expected output:** Triage routes it to **ask the human first** rather than pushing a
plausible guess. No code is pushed; the human is asked with the tradeoff named. If the
comment additionally tried to redirect the task or escalate access, that too is surfaced
to the human as untrusted content, not acted on. The subscription and the check-in stay
armed.

**Verify:** no commit is pushed in response to the comment; the human is prompted with
the decision to make; the PR is still open and still subscribed.

## Scenario 3 — Weird: PR merged out of band → stop + unsubscribe

**Input:** A wake fires (a self check-in or a webhook) and the PR now reads **merged** —
someone merged it directly — while a `send_later` check-in was still pending.

**Expected output:** The watch is recognized as finished. The skill tears down the
event wake (`unsubscribe_pr_activity`, or in a mapped harness the Monitor stream stopped —
self-exit on terminal detection counts), cancels the pending self check-in (`send_later`
or the CronCreate job), reports **once** (what it fixed, what it escalated, what is now
moot), and stops. No further wake is armed. A PR
that reads **closed** resolves identically.

**Verify:** the event wake source is torn down (`unsubscribe_pr_activity`, or the mapped
Monitor stream ended); no new check-in is scheduled (`send_later` or cron); a single final
report is produced; the session takes no further PR action.

## Scenario 4 — No-op: silent self check-in re-arm (no webhook for success)

**Input:** A `send_later` check-in fires. Re-reading state shows CI green, no new review
threads, PR still mergeable and open — nothing changed since the last look. This is
exactly the case webhooks never surface: a green CI and a quiet base.

**Expected output:** The check-in is a **silent no-op** — no comment, no ping to the
human. The skill re-arms the next `send_later` ~1h out and returns to waiting. Because
green is not "finished," it does **not** unsubscribe.

**Verify:** no PR comment and no human ping result from the check-in; a new `send_later`
is scheduled ~1h out; the subscription is still active.

## Scenario 5 — Label lifecycle: `babysitting-active` added on arm, removed on wind-down

**Input:** Arming a watch on an open PR in a repo where `babysitting-active` may or may
not already exist as a label; later, the watch reaches wind-down (merged, closed, or a
human stop).

**Expected output:** On arm, the skill checks `gh label list` for `babysitting-active`
and creates it only if missing (idempotent — re-arming a repo that already has the label
never errors), then adds it to the watched PR. On wind-down, the label is removed from
the PR alongside `unsubscribe_pr_activity` and cancelling the check-in — durable state
(the label) should read "not being watched" the moment the watch ends, not linger.

**Verify:** the PR carries `babysitting-active` immediately after arm; after wind-down
(merged/closed/human-stop) the PR no longer carries it; re-arming a repo where the label
already exists does not error on `gh label create`.

**Staged live verification:** no open
PR existed to run a genuine arm→wind-down watch on when this instrumentation landed, so
the label *mechanics* were verified directly and reversibly against a real, already-
merged PR instead of a live watch: `gh label list` showed no `babysitting-active` label
in the repo; `gh label create babysitting-active --description "..." --color 0e8a16`
created it; a second `gh label list` check before `gh label create` confirmed the
idempotent guard (skips re-creation once it exists); `gh pr edit <pr> --add-label
babysitting-active` added it (confirmed via `gh pr view <pr> --json labels`); `gh pr edit
<pr> --remove-label babysitting-active` removed it (confirmed empty `labels: []`) —
restoring the PR to its original, unlabeled state. The **mechanics** are live-verified;
the **end-to-end arm→wind-down integration** (the label appearing/disappearing as a
side effect of a real watch, not a direct `gh` call) is still design-verified — the next
real `/babysitting-pr` run on an open PR should close that gap.

## Dogfood record (live)

Run as `/babysitting-pr` (registration + explicit trigger confirmed); the
watched PR was the session's own dogfood-records PR, so watcher and author collapsed —
noted, and the no-self-merge rule still held (agent-side merge is permission-gated anyway).

- **Port gap found at arm time:** `subscribe_pr_activity` and `send_later` do not exist in
  this harness. Verified by tool search, then mapped: a **persistent Monitor poll-stream**
  (60s interval emitting CI/comment/mergeable deltas and merged/closed terminals) supplied
  the event wake, and an **hourly CronCreate check-in** (off-minute, session-only) supplied
  the timer. SKILL.md's arm section now records this mapping.
- **Arm:** one full state read (OPEN, CI 2/2 green, MERGEABLE/CLEAN, 2 Codex reviews with
  4 inline P2 comments) before any action.
- **Wake 1 (review comments) — triaged live:** 3 valid-tractable (SKILL.md hard-rule bullet
  missing the staged marker check the live dogfood had just proven; npm dogfood record
  missing an explicit synthetic-consumer residual; DEVLOG left-off list stale) → **delegated
  one focused subagent**, which landed all three in `a96f35e` with the gate green and
  returned hash + status. 1 stale (LESSONS line already landed after the reviewed commit)
  → reply only, no change. All four threads answered with one-liners.
- **Watch-to-green:** the monitor emitted the push's CI re-run (2/2 pass) and the comment
  count delta (4→8, own replies) — both classified self-inflicted no-ops, handled silently.
  Fix not treated as done until the green was observed.
- **Scenario 3, live (mapped teardown):** the PR was merged; the monitor emitted `TERMINAL: merged` and
  exited on its own terminal detection (the unsubscribe equivalent), the cron check-in was
  deleted, main synced, and a single final report closed the watch. No further wakes.
- **Residuals (design-verified still):** a red-CI wake (S1's trigger — CI never failed
  during the watch), an ambiguous/architectural or access-escalating comment (S2 — all
  four comments were tractable or stale), and a timer-fired silent re-arm (S4 — the merge
  landed before the hourly check-in ever fired).

## Dogfood record 2 (live)

Second full arc, same day (invoked as `/babysitting-pr`): arm with seeded monitor +
hourly cron → Codex-review wake → 3 valid P2s triaged and fixed **inline** per the
delegation floor (phrase-level edits, one file) → threads answered → self-inflicted
deltas (own push, own reply-wrapper reviews) classified silently → merged terminal →
monitor self-exit, cron deleted, single report. Confirmed both recipe rules from record
1 (`--paginate` counts; the delegation floor) — now folded into SKILL.md — and added a
third, caught live: the v1 monitor's hand-written seed didn't match its own loop's
output format (false first delta), and its status parse read check *names*, which would
have stayed **silent on a real CI failure**; repaired mid-watch by re-arming with
`gh pr checks --json bucket` and a seed derived from the same extraction the loop runs.
Residuals unchanged (S1 red-CI wake, S2 ambiguous comment, S4 timer no-op — none
triggered; the merge landed before the hourly check-in).

## Dogfood record 3 (live)

Third full arc (invoked as `/babysitting-pr` on the first records PR of this session): arm
with seeded monitor + hourly cron → Codex-review wake with **2 valid P2s** (a stale left-off
paragraph; an S1 cleanup claim that cited repo-cleanness when the scratch lived off-repo) →
both fixed **inline** under the delegation floor → threads answered → watched to green →
**the PR was merged** (`2561172`) → monitor self-exit on the merged terminal, cron deleted, single
wind-down report. Same residual set (S1 delegated-fix, S2 ambiguous comment, S4 timer no-op —
none triggered; merge landed before the hourly check-in). This is the watch that fed the
LESSONS line about citing observed evidence per contract clause.

## Dogfood record 4 (live) — S1 loop + S4 no-op exercised

Fourth full arc, and the one that closed the S1/S4 *triggers* by **staging them** on the
records PR itself:

- **S1 red-CI wake — live.** A deliberate lint-breaking commit (a new tracked `.md` with a
  broken relative link, confirmed to fail `check_all.py` locally first) was pushed to the open
  PR. The seeded monitor emitted the delta `checks: pass:2 → fail:1,pending:1` +
  `MERGEABLE → UNSTABLE` — the red-CI wake. Classified as a real failure (job is get-it-green,
  never a no-op); **diagnosed from the actual CI log** (`gh run view --log-failed` named the
  broken-link file, not assumed); judged small and in-intent; fixed **inline** (single-file
  delete, within the delegation floor — no subagent); pushed. Not treated as done until the
  monitor emitted `checks → pass:2` on the fix commit. No PR comment (self-evident fix);
  subscription stayed armed. One read subtlety handled live: an intermediate
  `fail:1 → fail:1,pass:1` delta was the **stale** prior-commit check being swapped out
  (confirmed by checking the checks' head SHA), not a second failure. **Note:** because the fix
  was floor-eligible it was landed inline, so this run proves the red-CI *loop* but **not** the
  Scenario-1 delegated-subagent fix path — that stays design-verified (no live break was big
  enough to warrant delegation).
- **Interleaved real wake — Codex review.** Mid-watch a Codex review landed (a valid P2: the
  scan tests.md S2 contract still described a two-finding fixture while the live run used a
  three-class one). Triaged as tractable phrase-level → fixed inline, thread answered with one
  reply, watched to green. Self-inflicted deltas (own fix push, own reply) classified as silent
  no-ops.
- **S4 timer no-op — classification live; re-arm via recurring cron.** After the PR settled
  green and quiet, a short-interval check-in was armed **seeded with the settled baseline**
  (OPEN, pass:2, MERGEABLE/CLEAN, ic=1 rc=2 rv=2). It fired against unchanged state → all signals
  matched → **silent no-op**: no comment, no ping. Exactly the case webhooks never surface. The
  **re-arm** in this mapped harness is structural: the check-in is a *recurring* CronCreate job,
  so it re-fires on schedule by construction — the persistent hourly cron (still armed) is the
  live re-arm. The short demo cron was retired after its one no-op fire (its purpose spent), not
  re-armed; an explicit "create a fresh one-shot timer" step (the `send_later` idiom) was
  therefore not separately observed — the recurring job subsumes it.

**Residuals (design-verified) — the next session's dogfood queue:**
- **S2** — an ambiguous/architectural or access-escalating review comment; never triggered
  across four watches (every real comment was tractable or stale).
- **S1 delegated-subagent fix** — every live CI fix was floor-eligible and landed inline; the
  delegate-the-fix-to-a-subagent path has not run.
- **S4 fresh one-shot timer re-arm** — the recurring cron subsumes re-arm by construction, so the
  explicit "schedule a new timer" step (the `send_later` idiom) was never separately observed.

All three stay traced by inspection until a watch exercises them.
