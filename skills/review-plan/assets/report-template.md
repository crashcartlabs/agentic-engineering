# Plan Review Report — structure & worked examples

The reviewer writes every review in this shape. The header carries the verdict and the
cycle count; the body proves it — deterministic checks with real output, a criterion table
where every PASS names concrete evidence, and findings ordered **most severe first**
(`[FAIL]` a red check or unmet criterion, then `[SCOPE]` unmapped/creeping diff, then
`[INTEGRITY]` plan-file bookkeeping). A criterion with no evidence is a FAIL, never a PASS.

## Structure

```
# Plan Review — <plan-slug>  (cycle <n>/2)

Plan:    plans/<file>  (status: <done | in-progress: blocker-scoped>)
Branch:  plan/<slug> vs <base-ref>  (<N files, +X/−Y lines>)
Verdict: <APPROVE | REVISE | BLOCKED> — <one-line reason>

## Deterministic checks
- Validation re-run:   <PASS | FAIL | BLOCKED> — <what ran, the real result>
- Repo gate:           <PASS | FAIL | BLOCKED | none> — <result>
- Diff → plan mapping: <PASS | FAIL> — <N hunks; all mapped | M unmapped>
- Plan-file integrity: <PASS | FAIL> — <status / checkboxes / per-phase commits / notes / amendments>

## Success criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | <text> | PASS | <observed behavior, or the test that fails without the change> |
| 2 | <text> | FAIL | <what is missing> |

## Findings  (most severe first)

### <n>. [FAIL|SCOPE|INTEGRITY] <one-line>
Fails: <the check or criterion this violates>
Evidence: <concrete — command output, the unmapped hunk, the missing test>
Fix direction: <one sentence; diagnosis only, never applied>

## Notes
- Cycle <n> of 2.<  at cap: cap reached — remaining findings handed to the user, no further automated pass.>
- <optional> Recommend /code-audit for general correctness — out of scope here.
```

## Worked example — REVISE

The bar to hit: real command output, per-criterion evidence, findings that name the exact
check they fail.

```
# Plan Review — add-rate-limiter  (cycle 1/2)

Plan:    plans/2026-07-02-add-rate-limiter.md  (status: done)
Branch:  plan/add-rate-limiter vs origin/main  (5 files, +214/−12 lines)
Verdict: REVISE — one criterion unproven, one unmapped hunk.

## Deterministic checks
- Validation re-run:   PASS — `npm test` 41 passing; `npm run lint` clean (ran fresh).
- Repo gate:           PASS — pre-commit hook (lint + test) green.
- Diff → plan mapping: FAIL — 1 of 9 hunks unmapped (see finding 2).
- Plan-file integrity: PASS — status done, all tasks [x], 3 phase commits, Execution Notes present.

## Success criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Rejects the 101st request in a 60s window with 429 | PASS | limiter.test.ts:88 sends 101 reqs, asserts 429; fails without the change (reverted → test red). |
| 2 | The 429 body names the retry-after seconds | FAIL | No test exercises the body; the handler sets the header but the response body is `{}` — criterion unproven. |

## Findings  (most severe first)

### 1. [FAIL] Retry-after criterion has no evidence
Fails: success criterion 2.
Evidence: no test asserts the body; manual read shows `res.json({})` at limiter.ts:57 — the retry-after is only in the header, not the body the criterion names.
Fix direction: either add the field to the body and a test, or renegotiate the criterion with the user.

### 2. [SCOPE] Unmapped edit to the logger
Fails: diff → plan mapping.
Evidence: src/log.ts:12 switches the log level to `debug`; no plan task or Execution Note covers it.
Fix direction: revert it, or record it as a deliberate deviation with an Amendment.

## Notes
- Cycle 1 of 2.
- Recommend /code-audit for general correctness — out of scope here.
```

## Clean bill — APPROVE

When every check is green and every criterion has evidence, the body stays complete but the
findings section is a single line — never padded with speculative nits.

```
# Plan Review — add-rate-limiter  (cycle 2/2)

Plan:    plans/2026-07-02-add-rate-limiter.md  (status: done)
Branch:  plan/add-rate-limiter vs origin/main  (5 files, +231/−12 lines)
Verdict: APPROVE — all checks green, every criterion evidenced, every line mapped.

## Deterministic checks
- Validation re-run:   PASS — `npm test` 43 passing; `npm run lint` clean.
- Repo gate:           PASS — pre-commit hook green.
- Diff → plan mapping: PASS — all 10 hunks mapped to a plan task.
- Plan-file integrity: PASS — status done, all tasks [x], 3 phase commits, Execution Notes + Amendment (logger revert) present.

## Success criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Rejects the 101st request in a 60s window with 429 | PASS | limiter.test.ts:88, red when reverted. |
| 2 | The 429 body names the retry-after seconds | PASS | limiter.test.ts:104 asserts `body.retryAfter === 60`, red when reverted. |

## Findings  (most severe first)

None — plan satisfied.

## Notes
- Cycle 2 of 2.
```

## BLOCKED

When validation cannot be run at all, the verdict is BLOCKED — state the cause, fabricate no
evidence, and do not fall through to APPROVE.

```
# Plan Review — add-rate-limiter  (cycle 1/2)

Plan:    plans/2026-07-02-add-rate-limiter.md  (status: done)
Branch:  plan/add-rate-limiter vs origin/main  (5 files, +214/−12 lines)
Verdict: BLOCKED — validation cannot run in this environment.

## Deterministic checks
- Validation re-run:   BLOCKED — `npm test` exits: `redis` not reachable (ECONNREFUSED 6379); the suite needs a Redis the environment does not provide.
- Repo gate:           BLOCKED — same dependency.
- Diff → plan mapping: PASS — all 9 hunks mapped.
- Plan-file integrity: PASS — status done, all tasks [x], 3 phase commits.

## Success criteria
Not evaluated — validation could not run; grading criteria on unrun tests would be fabricated evidence.

## Findings  (most severe first)

None assessed — see verdict cause.

## Notes
- Cycle 1 of 2.
- Cause is environment, not broken commands: re-run /review-plan where Redis is available.
```
