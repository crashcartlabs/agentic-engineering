# Plan Review — pre-publication-polish  (cycle 2/2)

Plan:    plans/2026-08-03-pre-publication-polish.md  (status: in-progress: blocker-scoped)
Branch:  plan/pre-publication-polish vs origin/main  (25 commits, +2200/−650)
Verdict: APPROVE (blocker-scoped) — re-review after three fix rounds and the security audit; all completed-phase criteria evidenced, blocker 6.3–6.5 genuine. Cycle cap reached (2/2).

## Deterministic checks
- Validation re-run:   PASS — `python3 scripts/ci/check_all.py` green at HEAD 3d0b119 (CI_VERDICT: PASS, run fresh this cycle); grep gates (slash / §) 0 matches; lint_skills/lint_sediment/janitor/cmux/skill_catalog/links/plans/records selftests all green.
- Repo gate:           PASS — including generated-tree drift checks.
- Diff → plan mapping: PASS — every non-generated file maps to a plan task, a fix-round finding (code-reviews/…-2.md, cycle-3 findings), or the security MEDIUM; carve-outs held.
- Plan-file integrity: PASS — status in-progress with blocker; every phase task `[x]` except 6.3–6.5 `[!]` with matching Amendments; one commit per phase (23fd37d, ef8fe4c, f21c4bb, c3aeacc, 911b07c, 78cdcd5); fix rounds committed per round (A–I: ed73615…ca498ec; round 2: a4c3632; round 3: b0dbe7b + fb8b29f; security: 40e080b); Execution Notes and four Amendments factual and matching the diffs; Review verdict (cycle 1) and Audit outcome rows link their reports.

## Success criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | `agentic gate` green incl. lint_plans | PASS | CI_VERDICT: PASS at every commit and at HEAD (fresh run). |
| 2 | Slash-invocation grep (canonical) = 0 | PASS | 0 matches; gate widened and case/fence/span-hardened (cycle-2 findings 3–5) with 22+ adversarial variants re-verified NOT re-triggered. |
| 3 | openai.yaml blocks equal derivation; lint fails on divergence | PASS | derivation + syntactic fixed-point check (cycle-2 finding 8); 32/32 files lint clean; --fix idempotent and self-healing (findings A, 9, comment-headed). |
| 4 | degraded-delegation ×6 byte-identical + lint_sediment enforces | PASS | md5-identical; selftest green; cycle-2/3 re-audits clean. |
| 5 | capabilities table + Pi limitation; no Pi artifact | PASS | docs/capabilities.md:24/:39; no providers/pi enforcement (verified twice). |
| 6 | §-citations = 0 | PASS | 0 matches. |
| 7 | todo-cleanup maturity truthful + literal marker | PASS | toolbelt.json `live-verified` + tests.md literal; catalog check exact-string. |
| 8 | janitor/cmux/justfile/README | PASS | janitor read path hardened through cycle-3 + security (O_NONBLOCK/fstat, preview guard, clutter escaping); cmux mkdtemp leak-free; justfile vars; README structure now includes reviews/ + security-reviews/. |
| 9 | providers/ + docs/skills.md regenerated, no drift | PASS | generated checks green at HEAD. |
| 10 | Version 0.2.1 ×4 + CHANGELOG | PASS (local half) | 0.2.1 everywhere + `[0.2.1]` entry; tag/publish pending 6.3 (blocker). |
| 11 | PR lands; #2–#7 closed; #7 triage comment | PENDING | 6.4 — human launcher step post-review. |
| 12 | Definition of Done | PASS (local half) | gate green; every finding has a regression test (selftest fixtures); diff surgical; publish halves pending 6.3–6.5. |

## Findings  (most severe first)

None — completed phases satisfy the plan. The blocker (6.3–6.5: export/tag/publish, PR, public-tree verification) is genuine: the executor never pushes or opens PRs (executor.md hard rule); the branch is publish-ready and gate-green. Cycle cap reached (2/2) — the remaining steps are handed to the human launcher.

## Notes
- Cycle 2 of 2 — cap reached; no further automated review pass.
- Verification trail this session: code-audit cycle 1 (9 findings A–I, all fixed) → cycle 2 (9 findings, all fixed) → cycle 3 (3 findings + 2 partial closures, all fixed) → security-audit (1 MEDIUM, fixed) → adversarial re-trigger passes at every round. Round-2/3 findings verified closed against reproductions; security MEDIUM e2e-verified.
- Remaining before ship: Phase 6.3 (export branch + tag v0.2.1 + publish_public.py snapshot flow), 6.4 (PR closing #2–#7 + #7 triage comment), 6.5 (public-tree verification).
