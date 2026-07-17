# tests — build-skill

Verification scenarios for `/build-skill`. These three are **design-verified** — each
checked against the current `SKILL.md` by inspection — and are the plan to exercise
live when `/build-skill` is first dogfooded on a real skill (first live capture
pending).

## Scenario 1 — Golden: new skill from a real task

**Input:** `/build-skill notify-on-deploy`, no existing skill of that name, user wants
a skill that posts a deploy summary to Slack.

**Expected process:** the guide scopes one task (Step 1), does the task live ≥3×
(golden/edge/weird) on real inputs before writing any file (Step 2), and only then
codifies `SKILL.md` + `tests.md` from those runs (Step 3). No `SKILL.md` is written
before the practice runs.

**Verify:** Steps 1→3 enforce practice-before-codify; Step 3 says "from the runs, not
theory"; Step 2's completion criterion requires ≥3 captured runs (one per archetype).

## Scenario 2 — Edge: user demands imagination-first

**Input:** "Skip the practice, just write me the SKILL.md now."

**Expected process:** the guide pushes back **once** (the practice runs are where the
skill gets real), and proceeds to imagination-first authoring only if the user insists
after that push.

**Verify:** the "push back once … proceed only if they insist" instruction is present
under *The spine*.

## Scenario 3 — Routing: existing skill, not a new one

**Input:** "Improve my code-audit skill — it over-triggers."

**Expected process:** recognized as a *sharpen an existing skill* job, not a fresh
build — re-enter this workflow at Step 2 to re-run the task and re-codify what broke,
per Step 8 and the description's closing clause.

**Verify:** Step 8 names the existing-skill path; the description ends by routing
existing-skill sharpening back to this workflow's practice step.

## Notes

- These are structural/behavioral checks of the guide's own instructions. A real
  end-to-end run (task scoped → practice runs captured → files written → checklist
  clean) should be captured here the first time `/build-skill` authors a real skill.
- The scaffold in `assets/skill-skeleton/` ships its own `tests.md.template` so skills
  built with this workflow start with a tests sidecar.
