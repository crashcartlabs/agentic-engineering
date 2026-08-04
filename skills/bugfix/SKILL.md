---
name: bugfix
description: 'Lightweight lane for small, well-understood fixes: reproduce and prove the root cause, then write a compact single-phase plan and execute it through the normal review pipeline. Invoke the `bugfix` skill with `<what-is-broken>`. Explicit-trigger only; routes anything bigger to the full `spec` → `plan` chain.'
---

# bugfix — the lightweight fix lane

The full chain (`spec` → `plan` grilling → multi-phase execution) exists for product
work. A bug fix — a known symptom, a proven cause, a surgical change — does not need a
product contract or a design interview. This lane gives it a compact plan, the same
test-first discipline, and the same mandatory review. **The review is never skipped;
what is dropped is the ceremony.**

```
bugfix <symptom> → triage → investigate (diagnosing-bugs) → compact plan → approve
→ execute → review-plan
```

## What this is / is not

- **Is:** a foreground lane that turns a small fix into an approved compact plan, then
  hands it to the normal `execute` + review-stack pipeline (`review-plan` then
  `code-audit`).
- **Is:** the *only* path that may skip `spec` and skip plan grilling.
- **Is not:** a license to skip testing, review, or the plan artifact.
- **Is not:** a substitute for the `diagnosing-bugs` skill — this lane *uses* that skill's
  investigation discipline for phase 1.

## Triage — the gate that keeps the lane honest

Qualifies for the bugfix lane **only if all** of these hold:

- [ ] Single concern — one bug, one fix
- [ ] Small blast radius — roughly 1–3 files touched
- [ ] No new dependencies
- [ ] No schema, API, or product-behavior-contract change
- [ ] The root cause is provable by a reproduction (not a guess)

**If any fails, route to the full chain** (`spec` → `plan`). When in doubt, full
chain. The lane is an explicit classification the human confirms; it is never assumed.

## Workflow

### Step 1 — Prove the cause before writing anything

Run the `diagnosing-bugs` skill's discipline with the narrowed scope of a small fix: tighten
the feedback loop, reproduce and minimise, rank hypotheses, instrument, and confirm
the *cause* — not the symptom. Do not skip to editing. A fix for a bug you cannot
trigger is a guess.

### Step 2 — Write the compact plan

Fill [assets/bugfix-template.md](assets/bugfix-template.md) and save it to:

```
plans/<YYYY-MM-DD>-fix-<kebab-topic>.md
```

`<kebab-topic>` names the *outcome* (`fix-auth-timeout`, not `working-on-auth`). The
template keeps the canonical plan shape — the reviewer and executor depend on it — but
collapses everything to a single phase and one-line sections. The `Spec` row is
`none — bugfix lane`; `Branch` is `plan/fix-<kebab-topic>`.

The plan's single phase must carry:

- **TDD:** `strict` — a bug fix is a behavioral change; the regression test comes
  first, watched red, then green, then red again on revert.
- **Validation:** the exact narrow command that proves the fix (the single test by
  name, the repro script, the curl).

### Step 3 — Approve, then execute through the normal pipeline

Present the compact plan. On approval, set `Status: approved` and `Branch:
plan/fix-<kebab-topic>` together, then offer the `execute` skill with `<plan-file>` — an offer, never
an auto-run. The existing executor, resume-integrity checks, and the `review-plan` skill work
unchanged: one phase, one commit, mandatory review stack. If the fix is
single-line and the human prefers it done in the foreground, that is acceptable —
but the review stack still runs, and the plan still records the outcome.

## Hard rules

- **Explicit-trigger only.** Never auto-start, and never *assume* the lane — propose
  it, let the human confirm.
- **Prove the cause first** — reproduce before you change anything; the compact plan
  records how the cause was proven.
- **Regression test first, and it must fail** — red for the predicted reason, then
  green; revert the fix and watch it go red again.
- **No ceremony, no shortcuts:** the review is mandatory, the diff is surgical, the
  plan file is written and honest.
- **Route up when in doubt** — triage failure is the full chain, not a "slightly
  bigger bugfix."
- **Never fix the symptom** — if the investigation shows the cause is elsewhere or
  the change is bigger than triage allowed, stop and re-triage to the full chain.
