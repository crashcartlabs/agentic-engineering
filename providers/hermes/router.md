---
name: agentic-engineering
description: 'Router for the agentic-engineering workflow in Hermes: spec -> plan -> execute -> review stack -> ship. Use when the user starts spec/plan/execute/review/ship/bugfix work — load the matching skill from this toolbelt and follow it.'
---

# agentic-engineering — workflow router (Hermes adapter)

This is the Hermes adapter for the agentic-engineering toolbelt. The canonical
skills live in the toolbelt repo (`skills/`); this router tells you which one to
load and when. Hermes loads skills by name, so four toolbelt skills are NOT
installed here because Hermes ships its own under the same names or namespace:
`plan`, `tdd`, `dogfood`, and `research`. When the workflow needs one of those,
load it from the repo instead.

## The workflow

```
wayfinder (foggy idea) -> spec -> plan -> execute + tdd -> review-plan + code-audit
-> security-audit (risk-gated) -> commit -> ship -> operate
```

| Step | Skill | How to invoke |
|---|---|---|
| Map a foggy idea | wayfinder | "/wayfinder <idea>" |
| Product contract | spec | "/spec <idea>" (mandatory for product work) |
| Technical plan | plan | "/plan <spec-file>" — **load from repo: skills/plan/SKILL.md** (Hermes has its own plan; use the toolbelt's) |
| Test-first discipline | tdd | **load from repo: skills/tdd/SKILL.md** |
| Execute an approved plan | execute | "/execute <plan-file>" (uses agents/executor.md → installed as execute/references/executor.md) |
| Small fixes | bugfix | "/bugfix <what-is-broken>" — lightweight lane, review still mandatory |
| Conformance review | review-plan | "/review-plan <plan-file>" |
| Correctness audit | code-audit | "/code-audit <low\|medium\|high\|max>" — on by default with review-plan |
| Security audit | security-audit | "/security-audit <risk-level>" |
| Commit + ship | commit, ship | "/commit", "/ship" |
| Operations | diagnosing-bugs, babysitting-pr, handoff, todo-cleanup | natural language |

## Rules for the Hermes agent

1. When the user invokes a workflow step, load that skill's SKILL.md from the
   toolbelt repo (`__TOOLBELT_REPO__`) or from this installed copy, and follow it —
   the skill is the authority, not this summary. `__TOOLBELT_REPO__` is rendered at
   install time to the actual toolbelt checkout the installer ran from; if that
   checkout has moved, ask the user where the toolbelt lives and use that path.
2. The four excluded skills (plan, tdd, dogfood, research) are read from the repo's
   `skills/<name>/SKILL.md` — never substitute Hermes's bundled plan/tdd/dogfood/
   research for the toolbelt's; the toolbelt's carry this repo's doctrine.
3. Follow the working repo's own rules: read its local `AGENTS.md` (Hermes reads it
   natively), match its patterns, and run **that repository's** gate before calling
   work done (discover it the way the commit skill does: hooks, package scripts,
   CONTRIBUTING, CI config). The toolbelt's own `python3 scripts/ci/check_all.py`
   applies only when working on the toolbelt meta-repository itself — never assume it
   exists in an application repo.
4. Artifacts live in the working repo: `specs/`, `plans/`, `reviews/`,
   `DEVLOG.md`, `LESSONS.md`. Keep them honest and current.
5. Reviews are the quality gate: run review-plan + code-audit on every change;
   security-audit when the change's risk warrants it. Never skip the review for
   speed.
