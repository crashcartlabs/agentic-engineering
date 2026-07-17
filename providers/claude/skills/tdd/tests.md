# tests — tdd

Scenarios for `/tdd`. These are design-verified against the current `SKILL.md`; the
first real strict-TDD implementation should add live evidence.

## Scenario 1 — Golden: one planned behavior slice

**Input:** The user says `/tdd implement the approved email-validation phase`, and
the active plan names the HTTP request/response boundary as the seam.

**Expected process:** The agent reads the plan and route/service code, writes down the
single behavior and approved seam, writes one request-level test for a malformed email,
runs the narrow test and observes it fail for the expected validation reason, then adds
the minimal validation code and reruns the same test to green before running the
containing check named by the plan.

**Verify:** `SKILL.md` requires loading the contract, using the approved seam, one
vertical slice, red before production code, minimal green implementation, and evidence
of the command sequence.

## Scenario 2 — Edge: no agreed seam

**Input:** The user asks for TDD on a feature, but the plan/spec does not say whether
the behavior should be tested through the CLI, HTTP route, service API, or UI.

**Expected process:** The agent does not guess or start writing tests against internals.
It identifies the candidate seams from the codebase and asks for the material seam
decision, or stops if the design has no public testable boundary.

**Verify:** `SKILL.md` says no test is written until one public seam is named, and that
a missing valid seam is surfaced as a design problem.

## Scenario 3 — Weird: proposed test is tautological or implementation-coupled

**Input:** The user suggests testing a total by computing the expected total with the
same reduction logic, or asks to mock an owned helper and assert that it was called.

**Expected process:** The agent refuses the test shape, replaces it with a behavior
test whose expected value comes from an independent literal/spec/example, and mocks
only a true system boundary if one is involved.

**Verify:** `SKILL.md` lists tautological tests, implementation-coupled tests, and
mocking owned modules as anti-patterns; `references/mocking.md` limits mocks to system
boundaries.

## Scenario 4 — Boundary: bug report without a proven cause

**Input:** The user says "use TDD to fix this crash" but the failure has not been
reproduced or diagnosed.

**Expected process:** The agent routes the investigation through the repo's
cause-first debugging discipline before using `/tdd` for the regression test. It does
not write a speculative test around a guessed cause.

**Verify:** `SKILL.md` is scoped to the implementation loop, while
`diagnosing-bugs/SKILL.md` owns reproduction, minimization, hypothesis, and proof of
cause before the red regression test.
