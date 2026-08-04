# Plan Review — pre-publication-polish  (cycle 1/2)

Plan:    plans/2026-08-03-pre-publication-polish.md  (status: in-progress: blocker-scoped)
Branch:  plan/pre-publication-polish vs origin/main  (176 files, +2174/−627)
Verdict: APPROVE (blocker-scoped) — completed phases conform with evidence; 6.3–6.5 blocker genuine (executor never pushes/PRs; human launcher completes post-review).

## Deterministic checks
- Validation re-run:   PASS — full gate `python3 scripts/ci/check_all.py` green (CI_VERDICT: PASS; one mid-run ERROR traced to the documented pre-existing `run_eval.py` TOCTOU flake, passes on rerun); grep gates fresh: slash-invocation 0 matches, §-citation 0 matches (canonical text only); lint_skills/lint_sediment/janitor/cmux selftests all OK (run fresh by checkers).
- Repo gate:           PASS — check_all.py green on the branch tip 78cdcd5; generated-tree drift checks included and clean.
- Diff → plan mapping: PASS — every non-generated file across the six phase commits maps to a plan task or the Relevant-files table; carve-outs held (tests.md touched only in skills/todo-cleanup/tests.md; README only in Phase 5; no .gitignore/AGENTS.md/DEVLOG.md/LESSONS.md edits).
- Plan-file integrity: PASS — status in-progress with blocker; all phase tasks [x] except 6.3–6.5 [!] carrying a matching Amendment; one commit per phase (23fd37d, ef8fe4c, f21c4bb, c3aeacc, 911b07c, 78cdcd5); Execution Notes factual; Spec row `none — maintenance/polish` consistent with non-product work.

## Success criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | `agentic gate` green incl. lint_plans on this plan | PASS | check_all.py CI_VERDICT: PASS run fresh; lint_plans part of the gate. |
| 2 | Slash-invocation grep (canonical) = 0 | PASS | fresh grep: 0 matches for /code-audit\|/execute\|/review-plan\|/ship in SKILL.md/references/assets/templates. |
| 3 | openai.yaml interface blocks equal derivation; lint fails on divergence | PASS | lint_skills.py derived_interface_strings + interface_divergence wired into main(); `--selftest` OK with in-memory diverging fixture (RED→GREEN pinned); 4 blocks spot-checked (TDD, cmux, Babysitting PR casing; first-sentence short_description; `Use $name…` prompt); --fix regen applied. |
| 4 | 6 delegation skills link byte-identical degraded-delegation.md; lint_sediment enforces | PASS | md5 024a6629… identical across all 6 copies; lint_sediment SHARED_BASENAMES + diverged-copy selftest OK; one-line links present in all 6. |
| 5 | capabilities.md skill×provider table + Pi limitation; no Pi policy artifact | PASS | docs/capabilities.md:24 table, :39 Pi footnote; git diff shows no providers/pi enforcement changes. |
| 6 | §-citations in canonical text = 0 | PASS | fresh grep: 0 matches in SKILL.md/references/assets/templates. |
| 7 | todo-cleanup maturity truthful + literal marker | PASS | toolbelt.json `"todo-cleanup": "live-verified"`; tests.md literal `live-verified`; skill_catalog.py:54-55 requires exact string. |
| 8 | janitor no-follow+size-bound+escaping; cmux mkdtemp; justfile vars; README list | PASS | weekly_janitor_report.py lstat/O_NOFOLLOW + 1 MiB bound + md_code_span escaping, selftest OK (symlink/oversized/hostile title); spawn_fleet/send_task mkdtemp (inert assertion strings kept), selftests OK; justfile vars codex_model/glm_model/minimax_model; README has docs/ (link), plans/, security-reviews/, .github/, justfile, .pre-commit-config.yaml. |
| 9 | providers/ + docs/skills.md regenerated, no drift | PASS | gate generated-docs check OK; providers/claude/skills/todo-cleanup/tests.md carries the marker (generated copy). |
| 10 | Version 0.2.1 across 4 manifests + CHANGELOG | PASS (local half) | 0.2.1 in toolbelt.json, package.json, .claude-plugin/plugin.json, .codex-plugin/plugin.json; CHANGELOG [0.2.1] - 2026-08-04. Tag + publish half: pending 6.3 (outside reviewed span — blocker). |
| 11 | PR lands; #2–#7 closed; #7 triage comment | PENDING | 6.4 — human launcher step post-review; not yet possible to evidence. Blocker genuine (executor never opens PRs). |
| 12 | Definition-of-Done checklist | PASS (local half) | gate green; behavioral changes selftest-verified RED→GREEN; diff surgical (mapping PASS); v0.2.1 shipped/public verified pending 6.3–6.5. |

## Findings  (most severe first)

None — completed phases satisfy the plan. Blocker (6.3–6.5) confirmed genuine: executor.md hard rules forbid push/PR/publish; Amendment records it; branch is publish-ready and gate-green.

## Notes
- Cycle 1 of 2. Blocker-scoped review: criteria 10–11 (and the publish halves of 1/12) become fully evidenced after the human launcher completes 6.3–6.5.
- Pre-existing observation, out of scope: `scripts/eval/run_eval.py --selftest` TOCTOU flake (child_survived() misses ProcessLookupError from /proc/<pid>/stat); documented in the plan's Execution Notes; a related FileNotFoundError fix landed in the harness-upgrades plan.
- Recommend /code-audit for general correctness — out of scope here.
