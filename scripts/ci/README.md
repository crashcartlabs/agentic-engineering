# scripts/ci — the meta-repo's own gate

This repo prescribes a green gate for every other repo (see the `/commit` skill) but had
none of its own. These checks close that gap — run by `.github/workflows/ci.yml` on every
push to `main` and every pull request, and runnable locally with the same command CI uses:

```sh
scripts/ci/run_gate
```

Green locally == green in the lint job. The aggregate gate runs four repository lints
plus the embedded selftests for the dashboard, plan lint, and record-file lint. Pure
stdlib, cross-platform, no network.

## Checks

| Script | What it enforces |
|---|---|
| `lint_records.py` | DEVLOG entries are newest-first with no empty (orphaned-heading) sections, and each entry is structurally sound — opens with `**Focus:**` and holds at most one each of `**Focus:**`/`**Done:**`/`**Left off:**` (a duplicate label is the merged-entry signature from the PR #70 orphan, issue #71); LESSONS entries are newest-first, contiguous, real dates, and not in the future. `--selftest` covers both directions, including a reproduction of the PR #70 merge. |
| `lint_plans.py` | No plan-template residue in `plans/`: metadata rows are filled (valid `Status`, real dates, no template tokens) and no unfilled `<placeholder>`-style tokens remain in the body. `--selftest` covers both directions. |
| `lint_skills.py` | Every skill has a `SKILL.md` with a `name`/`description`, `name` matches its directory, every `assets/`/`references/` file it points at exists, and every skill has `tests.md`. |
| `lint_links.py` | Relative Markdown links resolve to a real file. External URL liveness is out of scope (network-flaky). |
| `scripts/dashboard/dashboard.py --selftest` | Embedded dashboard fixtures cover config validation, plan/status parsing, review badge parsing, PR state parsing, attention classification, dirty/staleness helpers, and watcher pidfile guards. |

The secret scan runs only in CI. It installs trufflehog `v3.95.8` from the matching
released installer tag, then scans the **committed source** — a `git archive HEAD` export
— not `.git/` history (out of scope for this gate, and a false-positive source: a plain
`trufflehog filesystem .` walks `.git` and flags things like commit-message URLs).
`--no-verification` is the safe flag from LESSONS 2026-07-01 (never verify a hit against a
provider). trufflehog's `filesystem` command has no `--redact` flag, so a matched secret is
kept out of the logs by suppressing stdout and gating on the exit code instead.

## Known follow-ups

- Bump the pinned trufflehog version in CI when a release update is needed.
- External-URL link liveness, if the need recurs (see issue #50).
