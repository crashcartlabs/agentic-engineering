# Review — 2026-08-03-harness-upgrades

| | |
|---|---|
| **Plan** | plans/2026-08-03-harness-upgrades.md |
| **Branch** | plan/harness-upgrades |
| **Base** | main |
| **Verdict** | APPROVE |
| **Cycle** | 1 of max 2 |
| **Reviewed** | 2026-08-03 |

## Scope

5 phases + verification: upstream sync registry/drift check/GitHub Action, bugfix
lightweight lane, review stack on by default, Hermes provider, setup UX + docs.

## Deterministic checks (re-run by the reviewer)

| Check | Result | Evidence |
|---|---|---|
| Full gate | PASS | `python3 scripts/ci/check_all.py` → `CI_VERDICT: PASS` (multiple runs on the branch) |
| Upstream drift selftest | PASS | wired into gate; real run: 12/12 CURRENT, exit 0 |
| Toolbelt selftest | PASS | includes hermes artifact set + exclusions + setup wizard + doctor hints cases |
| Real upstream fetch | PASS | `check_upstream.py` against live GitHub: 12 CURRENT, 0 changed, 0 unreachable |
| Real hermes install | PASS | `install --providers hermes` on this box: 28 skills + router under ~/.hermes/skills; Hermes `skills_list` indexes all 28; launcher installed; `research` category dir untouched |
| Setup wizard | PASS | `setup --yes --dry-run`: steps 1–4 + next-steps banner; doctor hints print remedy lines for docker/cmux |
| Per-phase commits | PASS | `git log main..HEAD`: Plan + Phase 1…6, one commit per phase, subjects reference the phase |

## Diff-to-plan mapping

Every changed file traces to a plan phase; no orphan hunks found:

- `.github/workflows/upstream-check.yml` → P1 (weekly action, issue on drift)
- `upstream.json`, `scripts/maintenance/check_upstream.py` → P1
- `scripts/ci/check_all.py` → P1 (selftest wiring)
- `scripts/eval/run_eval.py` → P1 Amendment (pre-existing TOCTOU fix, documented)
- `ATTRIBUTION.md` → P1 (registry pointer)
- `skills/bugfix/*`, `providers/claude/skills/bugfix/*`, `docs/skills.md` → P2 (skill, template, registration, generated adapters, catalog)
- `toolbelt.json` → P2 (bugfix registration) + P3 (verify/audit stages) + P4 (hermes provider manifest)
- `docs/app-build-workflow.html` → P2 + P3 (skill map, review-stack copy)
- `scripts/toolbelt.py` → P1 (check-upstream command) + P4 (hermes install group, extra_files, exclusions) + P5 (setup wizard, doctor hints)
- `providers/hermes/router.md` → P4
- `docs/capabilities.md` → P4 (hermes row)
- `README.md` → P2 (bugfix line) + P4 (hermes row) + P5 (Setup section)
- `docs/setup.md` → P5
- `LESSONS.md`, `DEVLOG.md`, plan file → P6

## Plan-file integrity

- Status `done`; every task `[x]` except 6.5 `[!]` with a matching Amendment
  (publish is user-invoked by design — not a blocker).
- Execution Notes present, factual, name reviewer focus areas.
- Every Amendment corresponds to a real deviation visible in the diff
  (12-skill registry, eval fix, GitHub Action instead of cron, research exclusion,
  extra_files, 6.5 deferral).

## Success criteria

1. `agentic check-upstream` reports CURRENT for all 12 and exits 0 — **PASS** (real run).
2. Stale SHA exits 1 — **PASS** (selftest pins the tier).
3. bugfix skill lint-clean, single-Phase-1 template, registered — **PASS** (gate + files).
4. toolbelt.json verify = [review-plan, code-audit] — **PASS** (file inspection).
5. hermes install artifacts correct minus exclusions; detect reports hermes — **PASS**
   (selftest + real install + real `skills_list`).
6. `agentic setup` runs end-to-end — **PASS** (selftest + real dry-run).
7. doctor --hints remedy lines — **PASS** (real output: docker + cmux hints; launcher
   hint correctly absent once installed).
8. README Setup section + docs/setup.md — **PASS** (files exist, content matches
   behavior).
9. Gate green — **PASS**.
10. Publish to public — **deferred by design** (6.5, user-invoked snapshot flow).

## Findings

- **Note (non-blocking):** plan task 4.4 said "extend the generated-provider drift
  check in check_all.py"; the hermes provider has no *generated* artifacts (it copies
  canonical skills at install time), so the equivalent guarantee was implemented as
  toolbelt-selftest assertions on the hermes artifact set instead. Intent (hermes
  install stays current and correct) is met; mechanism differs from the plan's letter.
- **Note (non-blocking):** the upstream-check GitHub Action's YAML could not be
  exercised end-to-end from this branch (it runs on push/schedule); its logic
  (script exit tiers, issue dedupe via `gh issue list --search`) is reviewed and the
  underlying script is selftested. Residual risk: low, limited to the workflow file
  itself.

## Correctness pass (code-audit scope)

- `copy_managed_dir(extra_files=...)`: injected files are written before the managed
  snapshot, so the inventory and directory agree; re-install pristine checks stay
  green (proven by selftest's double-install).
- Hermes install group: exclusions applied, `$HERMES_HOME` respected, router and
  executor.md placement match `desired_artifacts` so uninstall reconciles them.
- `check_upstream.py`: exit tiers 0/1/2 match the gate convention; UNREACHABLE ≠
  CHANGED; token honored from env for rate limits.
- Setup wizard: non-TTY safe (`--yes`), dry-run safe, doctor failures are
  informational, not fatal.
- Doctor hints: conditional on actual state; no false launcher hint after install.

## Verdict

**APPROVE** — every deterministic check green, all success criteria met with
evidence, no unexplained diff lines. The two notes are documentation-level, not
correctness. The single deferred item (public publish, 6.5) is the user's
invocation of the snapshot flow.
