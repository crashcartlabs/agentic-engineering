# New App verification scenarios

Last verified: pending first live run; scenarios are design-verified against `SKILL.md` and the bootstrap selftest.

## Scenario 1 — Empty repository

Run `agentic init-app <empty-temp-repo>`. Expect missing workflow files and `specs/` and `plans/` guidance to be created, with the next gate reported as `spec` or `wayfinder`. No product code is created.

## Scenario 2 — Existing application

Run against a temporary repository that already has `AGENTS.md`. Expect a conflict report and no overwrite. After explicitly selecting a different empty target, expect bootstrap to succeed.

## Scenario 3 — Toolbelt repository refusal

Run against the Agentic Engineering source root. Expect a refusal before any file is written.

## Scenario 4 — Idempotent rerun

Run twice against the same bootstrapped temporary repository. Expect the second run to report every managed file as already present and leave all bytes unchanged.
