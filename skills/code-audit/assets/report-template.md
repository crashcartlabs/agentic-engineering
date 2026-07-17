# Code Review Report — structure & worked example

The orchestrator writes every review in this shape. Findings are ordered **most-severe-first** — every `[BUG]` before any `[RISK]`. Each finding must carry a verified `What breaks` scenario; if it has no concrete trigger path, it should never have reached the report.

## Structure

```
# Code Review — <branch> vs <base>  (<N files, +X/−Y lines>)

Verdict: <M> confirmed findings (<b> bugs, <r> risks)

## Findings  (most severe first)

### <n>. [BUG|RISK] <one-line defect>
`<path>:<line>`
What breaks: <the verified failure scenario — concrete inputs/state → wrong behavior>
Why:        <the actual cause in the code>
Fix direction: <one sentence; diagnosis only, never applied>
```

## Worked example

This is the bar to hit — specific inputs, a traced cause, a one-line fix direction:

```
# Code Review — sync-pager vs main  (4 files, +212/−37 lines)

Verdict: 2 confirmed findings (1 bug, 1 risk)

## Findings  (most severe first)

### 1. [BUG] Off-by-one drops the last page when total is a multiple of pageSize
`src/sync/pager.ts:142`
What breaks: with total=200, pageSize=50, the loop `while (page < ceil(total/size))`
            with a 1-indexed `page` stops after page 3 → the 4th page (records 151–200)
            is never fetched, so the last 50 records never sync.
Why:        the loop is written for a 0-indexed page but `page` is initialised to 1.
Fix direction: start at page 1 with `page <= totalPages`, or 0-index the counter.

### 2. [RISK] Unhandled rejection if the token refresh itself returns 401
`src/auth/client.ts:88`
What breaks: only when a refresh call 401s (expired refresh token) — the awaited
            `refresh()` throws outside the surrounding try, escapes the retry handler,
            and crashes the worker instead of forcing re-auth.
Why:        the refresh call was added just below the try/catch that wraps the request,
            not inside it.
Fix direction: move the refresh inside the guarded block so a 401 there routes to re-auth.
```

## Clean bill of health

When nothing survives verification, the report body is exactly this — stated plainly, never padded with speculative findings:

```
# Code Review — <branch> vs <base>  (<N files, +X/−Y lines>)

Verdict: No correctness issues found.
```
