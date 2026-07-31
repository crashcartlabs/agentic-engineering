# Development Log

## 2026-07-31 — Harness review: fixes, de-sediment, and neutrality lint

**Focus:** Land the four-bucket improvement pass from the external harness review:
leak/bug fixes, dedup and de-sediment of shared skills, skill quality and workflow
wiring, and the strategic additions (eval harness v1, changelog/versioning, policies).

- Extracted the audit skills' shared pipeline mechanics into a byte-identical
  `references/shared-pipeline.md` carried by `code-audit` and `security-audit`;
  identity is enforced by the new sediment lint.
- Removed dated anecdotes from normative skill text; the history lives here now:
  `/review-plan` was born `/review` and renamed after the 2026-07-03 dogfood showed a
  skill cannot shadow a harness built-in; the live-vs-design-verified mislabeling trap
  recurred seven times in one 2026-07-05 review of `build-skill`; a 2026-07-04 live
  `/ship` run caught a last-second `--amend` via the SHA freshness check; the
  2026-07-04 live `/babysitting-pr` watch caught both the self-baselining monitor gap
  and a status parse reading check names; `handoff`'s legacy OS-temp fallback served
  its transition and was removed.
- Generalized repo-specific facts out of shared skills into AGENTS.md §V ("This
  repository's gate"), made `opensrc` a conditional capability, and trimmed the
  duplicated attribution passages to one canonical line per derived skill.
- Shipped eval harness v1 (`agentic eval`): provider-pluggable adapters (claude
  live, codex/pi stubs, hermetic fake for CI), JSON scenarios with deterministic
  checks plus an optional judge rubric, local evidence records, and pilot
  scenarios for commit, new-app, and resolving-merge-conflicts. Promotion stays
  manual: the runner prints the suggested `skillMaturity` edit, never applies it.
- Bumped all four manifests to 0.2.0, started `CHANGELOG.md`, documented the
  tag-per-snapshot convention, and added unit tests for previously
  selftest-only `toolbelt.py` paths.

## 2026-07-17 — Initial public release

**Focus:** Public snapshot of the Agentic Engineering toolbelt.
