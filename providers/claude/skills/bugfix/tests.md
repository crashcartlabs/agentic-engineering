# tests — bugfix

Scenarios for the `/bugfix` skill. Each names the input, the expected behavior, and
how to verify it.

**Status: design-verified — scenarios drafted; not yet live-run.** Promotion to
`partially-live` requires a typed live run per the repo's promotion convention.

## Scenario 1 — Golden: small well-understood fix → compact plan → review

**Input:** `/bugfix the dashboard 500s when a user's name contains an apostrophe`
where reproduction is a one-line command, the root cause is provable in minutes
(e.g. an unescaped quote in a query), and the fix touches one file plus its test.

**Expected output:** The skill triages into the bugfix lane (single concern, small
blast radius, no new deps, no contract change, reproducible cause), runs the
diagnosing-bugs discipline to *prove* the cause, writes a compact single-phase plan
under `plans/<date>-fix-<slug>.md` with `TDD: strict` and a named validation command,
gets human approval, and offers `/execute` — it never auto-runs. The resulting plan
passes the plan lint and `/review-plan` reviews it like any other plan.

**Verify:** the plan is written, approved, and lint-clean; the executor completes it
in one phase/one commit; review-plan runs; no `/spec` was produced; no grilling
happened.

## Scenario 2 — Edge: triage fails → routed to the full chain

**Input:** `/bugfix users can't log in` where the investigation shows the cause spans
four files, a schema change, or an API contract change — or where the cause cannot be
reproduced.

**Expected output:** The skill refuses the lightweight lane. It either routes to
`/spec` + `/plan` (bigger change) or continues investigation under `/diagnosing-bugs`
until the bug reproduces (unproven cause). It does not write a compact plan around a
guess, and it does not silently expand the lane.

**Verify:** no bugfix-lane plan is written; the transcript names the failing triage
criterion and the route taken.

## Scenario 3 — Weird: fix turns out bigger than triage allowed

**Input:** mid-execution, the real cause is found elsewhere (a second call site, a
shared helper), so the surgical fix grows beyond the triage box.

**Expected output:** The skill stops and re-triages: the change is either split (the
small fix proceeds; the larger issue is filed as a backlog item — "noticed, not
done" goes to Execution Notes) or the lane is escalated to the full chain. It never
finishes a "bugfix" that actually shipped a feature or a refactor.

**Verify:** the plan records the deviation in Execution Notes/Amendments; no scope
creep lands silently; the larger work is deferred, not absorbed.

## Scenario 4 — Hard rule: review is never skipped

**Input:** a one-line fix where the human says "just fix it, skip the review."

**Expected output:** The skill holds the line: the review is mandatory in this lane.
It may propose the *foreground* path (plan written, fix applied and verified, then a
scoped review) but never ships un-reviewed. The reason is stated: the review is what
makes the lane trustworthy — dropping it for small fixes is exactly how small bugs
become production incidents.

**Verify:** no un-reviewed merge; the transcript shows the refusal and the scoped
review that did run.
