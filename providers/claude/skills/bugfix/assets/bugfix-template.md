<!--
BUGFIX PLAN TEMPLATE — the lightweight lane. Rules:
- Keep the canonical plan section order; reviewers (human and agent) rely on it.
- Replace every <placeholder>. Collapse conditional sections to "N/A — <reason>".
- Exactly ONE "### Phase 1 — Fix" phase: the executor, resume-integrity check, and
  review-plan all depend on the canonical shape.
- Checkbox legend: - [ ] todo   - [x] done   - [~] wip   - [!] blocked
-->

# <Fix title>

| | |
|---|---|
| **Status** | draft <!-- draft → approved → in-progress → done --> |
| **Created** | <YYYY-MM-DD> |
| **Modified** | <YYYY-MM-DD> |
| **Spec** | none — bugfix lane |
| **Branch** | plan/fix-<kebab-topic> |
| **Related plans** | none |
| **Review verdict** | not run |
| **Audit outcome** | not run |

## Summary

<!-- One or two sentences: the symptom, the proven cause, the fix. -->

## Problem

- **Symptom:** <what the user sees / what fails>
- **Reproduction:** <the exact command, input, or steps that trigger it>

## Solution

<!-- The surgical fix. How the cause was proven (diagnosing-bugs discipline):
reproduced, minimised, hypothesised, instrumented. -->

## Success criteria

- [ ] <the failing behavior is fixed, phrased as a testable assertion>
- [ ] <no regression: the surrounding behavior still works>

## Non-goals / out of scope

- <anything the fix deliberately does not touch>

## Threat model & hardening boundary

**Security relevance assessment** (do not pre-fill N/A): does this fix touch
authentication, authorization, secrets, input handling, or a trust boundary?

- [ ] No — not a hardening/security change: <one-line reason>
- [ ] Yes — this is security-relevant: the `security-audit` skill is required, and the fix
  may still ride this lane if it passes triage; when in doubt, route to the full chain.

## Assumptions & open questions

- **Assumption:** <or "none">

## Research findings

N/A — fixed-stack/internal change; no ecosystem research needed.

## Dependencies

none

## Relevant files

**Existing (to change):**

| File | Why |
|---|---|
| `<path>` | <reason> |

**New (to create):**

| File | Why |
|---|---|
| `<path>` | <reason> |

## Implementation phases

### Phase 1 — Fix

- [ ] 1.1 Write the regression test that fails on the bug (red for the predicted reason)
- [ ] 1.2 Apply the surgical fix; watch the same test go green
- [ ] 1.3 Revert the fix; confirm the test goes red again, then re-apply
- [ ] 1.4 Run the narrow validation below and the surrounding test scope

**TDD:** strict
**Validation:** <the exact narrow command(s): single test by name, repro script, curl>

## Test / validation strategy

The regression test encodes the minimal reproduction from the investigation and
fails without the fix. A behavioral change with no failing-first test is not done.

## Risks & rollback

N/A — small, reversible change (single phase, one commit on a feature branch).

## Decisions & tradeoffs

- **<Decision>** — <why>; tradeoff: <what it costs>.

## Definition of Done

- [ ] Root cause proven, not assumed
- [ ] Regression test written first and seen red
- [ ] Fix surgical — every changed line justified by this plan
- [ ] Validation command green
- [ ] Reviewed via the review stack — the `review-plan` skill (conformance) then the `code-audit` skill
  (correctness) — before merge; the `security-audit` skill when the security assessment above
  says the fix is security-relevant

## References

none

## Notes

none

## Execution Notes

_Not started._

## Amendments

_None yet._
