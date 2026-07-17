---
name: tdd
description: "Run a strict test-driven development loop for implementation work. Use when the user asks to build or fix something test-first, mentions TDD or red-green-refactor, wants integration-style behavior tests, or an approved plan marks a phase as strict TDD. Not a planning or review skill; it is the execution loop for one behavior slice at a time."
---


# Test-driven development

This skill owns the red -> green implementation loop. `/plan` chooses the success
criteria, seams, and validation strategy; `/execute` builds the approved plan; this
skill is the discipline used inside a behavioral implementation slice when the work
is explicitly test-first.

Adapted from Matt Pocock's MIT-licensed `tdd` skill, with this repo's stricter
pre-agreed seam and Definition-of-Done rules folded in.

## 1. Load the contract

Read the active plan/spec/issue and the code around the target behavior before
writing any test. If the project has `CONTEXT.md` or ADRs for the area, read them
so test names and domain terms match the project.

Identify the public seam under test: the interface where behavior is observed
without reaching into internals. If the seam is already approved in the plan, use it.
If no seam is approved and the choice is material, ask before writing tests. If no
valid seam exists, stop and report that the design lacks a testable boundary.

Completion criterion: one named behavior and one public seam are written down.

## 2. Take one vertical slice

Work one behavior at a time. The slice should be small enough that one failing test
can drive one minimal implementation step.

Do not write all tests first. Bulk test-writing commits to imagined behavior and
locks in test structure before the implementation teaches you anything.

Completion criterion: one behavior is selected, with explicit input, action, and
observable result.

## 3. Red

Write the smallest behavior test at the agreed seam. A good test reads like a
specification of capability, not implementation structure.

The expected value must come from an independent source of truth: the spec, a
known-good literal, a worked example, or a fixture. Do not compute the expected value
with the same logic the production code should contain.

Run the narrowest command that executes this test and watch it fail for the intended
reason. If it passes before the implementation, or fails for an unrelated reason,
fix the test or the setup before changing production code.

Completion criterion: the new test is red for the expected reason.

## 4. Green

Write only enough production code to pass the red test. Do not anticipate later
tests, add speculative options, or widen scope because the next behavior is obvious.

Run the same narrow test until it passes. Then run the next relevant containing check
named by the plan or local conventions.

Completion criterion: the test that was red is now green, and the relevant containing
check still passes.

## 5. Refactor only after green

After the test is green, make only cleanup that is required to keep the current slice
clear, local, and maintainable. Larger structural changes are separate plan work, not
an excuse to expand the TDD slice.

Rerun the narrow test after any cleanup.

Completion criterion: no behavior changed during cleanup and the slice remains green.

## 6. Repeat or stop

Repeat the loop for the next vertical slice only when it is still inside the approved
scope. If the next behavior requires a new seam, a new dependency, or a decision the
plan did not settle, stop and surface that instead of improvising.

At the end, report the evidence: the behavior slices covered, the red/green command
sequence, and any behavior deliberately left out of scope.

## Test shape rules

- Test behavior through public interfaces, not private methods or internal
  collaborators.
- Mock only system boundaries: third-party APIs, time/randomness, and sometimes
  database or filesystem boundaries. See [references/mocking.md](references/mocking.md)
  when a mock is needed.
- Do not mock modules the project owns just to make a test easier.
- Prefer the highest existing seam that proves the behavior. The ideal number of
  seams for a small feature is one.
- Avoid side-channel verification when the public interface can prove the behavior.
  For example, prefer "created user can be retrieved" over "row exists in table."
- Keep each test focused on one logical behavior. Multiple assertions are fine when
  they are all part of the same observable outcome.

## Refuse these anti-patterns

- **Implementation-coupled tests:** tests that break on refactor while behavior is
  unchanged.
- **Tautological tests:** assertions that recompute the expected value using the same
  algorithm as the production code.
- **Horizontal slicing:** all tests first, then all implementation.
- **Green-only tests:** tests added after the code works without ever observing red.
- **Hollow coverage:** a shallow unit test that cannot reproduce or prove the behavior
  the user cares about.

## Hard rules

- Red before green. A test that never failed proves little.
- One seam, one behavior slice, one minimal implementation step.
- If the seam is unclear, settle the seam before writing tests.
- If the test fails for the wrong reason, fix the test/setup before production code.
- If strict TDD conflicts with the approved plan, stop and surface the conflict.
