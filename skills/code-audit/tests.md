# tests — code-audit

Scenarios for the `/code-audit` orchestrator skill.

Last verified: 2026-07-08 — rename text static-verified by `check_all.py`;
**Scenarios 1–2 live-verified (2026-07-02 typed runs, transcribed from the DEVLOG
record); Scenario 3 design-verified.** Those live runs were typed under the former
`/code-review` command name; `/code-audit` is the current renamed equivalent for
the same orchestrator pipeline. Both live runs used `low` effort with an explicit
`HEAD` baseline and path scoping; the default `high` panel-of-3 and `max`
loop-until-dry tiers have never been observed.

## Scenario 1 — Golden: real diff, full pipeline, clean bill (live-verified 2026-07-02)

**Historical input:** In a fresh session on 2026-07-02, the maintainer typed
`/code-review low HEAD DEVLOG.md TODO.md plans/2026-06-29-executor-agent.md` — an
explicit `HEAD` baseline plus path scoping, so the pinned diff was the current
uncommitted recordkeeping update only, not the whole branch.

**Current equivalent:** `/code-audit low HEAD DEVLOG.md TODO.md
plans/2026-06-29-executor-agent.md`.

**Expected output:** The slash command resolves; the baseline is pinned and stated;
five lens reviewer subagents spawn (not a solo read-through); candidate findings go
through adversarial verifier subagents; refuted candidates are dropped, never
reported; the report lands at `code-reviews/<date>-<branch-slug>.md` in the
clean-bill shape with `Verdict: No correctness issues found.` when nothing survives.

**Verify:** Observed in the 2026-07-02 run: five lens reviewers ran, three candidate
findings all refuted by verifiers, report written to
`code-reviews/2026-07-02-claude-commit-skill.md` matching the clean-bill template.
Contract checks: `code-reviews/` ignored via `.git/info/exclude` (no tracked file
touched), and `git status --untracked-files=all` showed no tracked-file changes from
the run beyond the pre-existing worktree changes.

## Scenario 2 — Edge: empty review span (live-verified 2026-07-02)

**Historical input:** Same 2026-07-02 session, the maintainer typed
`/code-review low HEAD skills/code-review/SKILL.md` — a path scope
containing no changes against the baseline.

**Current equivalent:** `/code-audit low HEAD skills/code-audit/SKILL.md`.

**Expected output:** The skill reports an empty review span and stops — no
reviewers spawn, no report is created, no work is manufactured.

**Verify:** Observed: the run reported the empty span and did not create another
report file under `code-reviews/`.

## Scenario 3 — Weird: a finding that survives verification (design-verified)

**Input:** A diff containing a real bug — e.g. an inverted condition a lens reviewer
flags with a concrete failure scenario the verifier(s) cannot refute.

**Expected output:** The finding survives the adversarial gate and is reported as a
numbered finding with the full contract (`severity`/`file`/`line`/`defect`/
`failure_scenario`/`cause`/`fix_direction`), ordered most-severe-first, in the
findings variant of `assets/report-template.md`; the chat surface shows the Verdict
line plus one line per finding. The code itself is never edited (read-only rule).

**Verify:** Design-traced only. Every recorded run's candidates were refuted, so the
surviving-finding path — the findings-variant report, severity ordering, and the
`high`-tier three-verifier panel — has never been observed live. First run on a diff
with a genuine bug should upgrade this scenario and note which tier ran.
