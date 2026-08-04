# Testing seams — pre-agreement and anti-patterns

Doctrine for the plan's testing strategy, ported from Matt Pocock's `tdd` skill. It
complements the repo's testing doctrine and the local `tdd` skill (which owns the
red-green loop);
this file covers *where* tests go and which test shapes to refuse.
Vocabulary (**seam**, **interface**, **adapter**) is defined in the
`codebase-design` skill.

## Pre-agreed seams

A **seam** is the public boundary a test exercises: the interface where behavior is
observed without reaching inside. Tests live at seams, never against internals.

**Test only at pre-agreed seams.** Before any test is written, the seams under test
are written down and confirmed with the human — no test at an unconfirmed seam. You
can't test everything; agreeing the seams up front is how testing effort lands on
critical paths and complex logic instead of every edge case. The question to settle
during planning: *"What's the public interface, and which seams should we test?"*
Prefer existing seams at the highest point possible — the ideal number of seams is one.

## Anti-patterns to refuse

- **Implementation-coupled** — mocks internal collaborators, tests private methods, or
  verifies through a side channel (querying the database instead of using the
  interface). The tell: the test breaks when you refactor but behavior hasn't changed.
- **Tautological** — the assertion recomputes the expected value the way the code does
  (`expect(add(a, b)).toBe(a + b)`, a snapshot derived by hand the same way, a constant
  asserted equal to itself), so it passes by construction and can never disagree with
  the code. Expected values must come from an independent source of truth — a
  known-good literal, a worked example, the spec.
- **Horizontal slicing** — writing all tests first, then all implementation. Bulk tests
  verify *imagined* behavior: they test the shape of things rather than user-facing
  behavior, go insensitive to real changes, and commit to test structure before the
  implementation is understood. Plan **vertical slices** instead — one test → one
  implementation → repeat, each test a **tracer bullet** that responds to what the last
  cycle taught you.

## Mocking, briefly

Mock at system boundaries only (third-party APIs, time/randomness, sometimes DB and
filesystem — prefer real test stand-ins where they exist). Never mock your own modules
or internal collaborators. At boundaries, inject the dependency rather than
constructing it inside, so the test adapter slots in at the seam.
