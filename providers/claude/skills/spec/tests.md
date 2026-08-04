# tests - spec

Scenarios for `/spec`. These are design-verified against the current `SKILL.md` and
template; the first real spec session should add live evidence.

Last verified: 2026-07-09

## Scenario 1 - Golden: rough idea to approved product spec

**Input:** `/spec build a lightweight habit tracker for runners who want streaks and
weekly mileage goals`.

**Expected process:** The skill reads repo instructions and any existing domain docs,
presents a context brief, interviews one question at a time with recommended answers,
settles users, goals, acceptance behavior, edge cases, non-goals, and success metrics,
then writes `specs/<date>-runner-habit-tracker.md` from the template. It does not write
code or create a technical plan.

**Verify:** `SKILL.md` requires context loading, recommendation-first questions,
Gate 1 teach-back, the product-alignment checklist, saving under `specs/`, and no
implementation planning.

## Scenario 2 - Conversation synthesis

**Input:** `/spec --from-conversation` after a long discussion where product behavior,
edge cases, and out-of-scope decisions are already settled.

**Expected process:** The skill synthesizes what is already known, asks only for a
missing product-changing fact if one exists, writes the spec, and asks for approval.
It does not restart the interview from zero.

**Verify:** `SKILL.md` defines `--from-conversation` as synthesize-first and only asks
when a missing fact would materially change the spec.

## Scenario 3 - Wayfinder handoff

**Input:** `/spec --from-wayfinder <issue>` for a resolved wayfinder ticket that names
the destination and product decisions.

**Expected process:** The skill reads the map/ticket, preserves the resolved decisions,
turns them into a product spec, links back to the source issue, and leaves open any
planning-only implementation questions for `/plan`.

**Verify:** `SKILL.md` names the wayfinder mode, requires reading related maps/tickets,
and keeps implementation details out of the spec.

## Scenario 4 - Too foggy to specify

**Input:** `/spec make a social app for local communities` with no clear audience,
outcome, product boundary, or first behavior.

**Expected process:** The skill refuses to fabricate a spec and routes to `/wayfinder`
to map the destination and open decisions first.

**Verify:** `SKILL.md` says to stop and recommend `/wayfinder` when the idea has no
clear user, outcome, or product boundary.

## Scenario 5 - Boundary: user asks for implementation plan

**Input:** During `/spec`, the user asks for exact files, database migration order,
test commands, and implementation phases.

**Expected process:** The skill captures any product-level constraints but defers
technical architecture, sequencing, exact seams, and validation commands to `/plan`.

**Verify:** `SKILL.md` explicitly says those details belong to `/plan`; the template
contains plan handoff notes but no implementation phase section.
