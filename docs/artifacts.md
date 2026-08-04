# Artifact registry

| Artifact | Owner | Location | Tracked | Retention and consumers |
|---|---|---|---:|---|
| Product specification | `spec` | `specs/<date>-<topic>.md` | Yes | Product contract consumed by `plan` and `review-plan` |
| Implementation plan | `plan`, then `execute` | `plans/<date>-<topic>.md` | Yes | Living execution state and validation contract |
| Plan-conformance review | `review-plan` | `reviews/<date>-<plan>.md` | Yes | Release evidence; links back to plan and spec |
| Correctness audit | `code-audit` | `code-reviews/<date>-<topic>.md` | Local by default | Embed actionable evidence in a PR; do not cite an inaccessible local path |
| Security audit | `security-audit` | `security-reviews/<date>-<topic>.md` | Yes | Risk evidence for release and follow-up |
| Skill safety scan | `skill-safety-scan` | `skill-scans/<date>-<skill>.md` | Yes | Promotion evidence for the scanned skill |
| Skill-eval evidence | `agentic eval` (`scripts/eval/run_eval.py`) | `eval-results/<date>-<skill>-<scenario>.json` | Local | Evidence for a manual `skillMaturity` promotion in `toolbelt.json`; cite the record in the skill's `tests.md` when promoting |
| Handoff | `handoff` | `handoffs/` | Local | Short-lived conversation state; never replaces the plan |
| Development narrative | Foreground session | `DEVLOG.md` | Yes | Newest-first session record |
| Lessons queue | Foreground session | `LESSONS.md` | Yes | Temporary correction-to-rule queue |
| Deferred work | Human/foreground session | GitHub issues | Remote | Durable backlog; `TODO.md` is only unfiled scratch |
| Release evidence | Application repository | PR, CI, tags, deployment records | Remote | Source of truth for what shipped and what is live |

Every plan should link its source specification, and every conformance review should map
both plan success criteria and specification acceptance behavior. A report cited in a
pull request must be reachable by remote reviewers or summarized with enough evidence in
the pull request itself.
