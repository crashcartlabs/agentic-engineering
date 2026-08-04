# Changelog

All notable changes to this toolbelt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow semver
while the project is pre-1.0 (minor bumps may break). Public `main` is a snapshot,
so this file is the only cross-release diff public consumers have — every snapshot
ships with its version's entry.

## [0.2.1] - 2026-08-04

### Changed

- Canonical skill text no longer hardcodes Claude-style `/name` invocation —
  commands now read "invoke the `name` skill", so they hold on Codex and Pi too.
  `tests.md` evidence prose (literal typed-command records) was left untouched.
- Codex `agents/openai.yaml` interface strings (`display_name`,
  `short_description`, `default_prompt`) are now generator-derived from canonical
  metadata and lint-checked for drift; `new-app` and `bugfix` are overwritten by
  the derivation like every other skill.
- The six skills that require subagent delegation link a shared, byte-identity-
  linted `references/degraded-delegation.md` covering both fan-out and
  single-subagent harnesses, including the sequential fresh-context fallback.
  `docs/capabilities.md` gains a skill × provider support table and documents
  that Pi does not enforce explicit skill invocation.
- Remaining §I–§XIII citations in canonical skill text were inlined or dropped so
  skills stand alone outside this toolbelt.
- `weekly_janitor_report.py` reads DEVLOG.md/LESSONS.md with symlink no-follow
  and a size bound, and escapes repo-controlled strings in the Actions summary.
- The pre-commit gate hook uses `language: system` + `python3` so it also works
  on native Windows.
- cmux `spawn_fleet.py`/`send_task.py` selftests use `tempfile.mkdtemp()` roots
  instead of fixed `/tmp` paths.
- justfile hoists the bake-off model IDs into top-of-file variables.

### Added

- README repository-structure list now covers `docs/` (including the generated
  `docs/skills.md` catalog link), `plans/`, `security-reviews/`, `.github/`,
  `justfile`, and `.pre-commit-config.yaml`.

### Fixed

- `todo-cleanup` maturity corrected to `live-verified` — its tests.md documents a
  real live migration run, matching the catalog's promotion contract.

## [0.2.0] - 2026-07-31

### Added

- `agentic eval` — provider-pluggable skill-eval harness v1: JSON scenarios under
  `skills/<name>/evals/`, deterministic fixture checks plus an optional LLM-judge
  rubric pass, evidence records under gitignored `eval-results/`, and a hermetic
  fake-provider selftest wired into the gate. Pilot scenarios for `commit`,
  `new-app`, and `resolving-merge-conflicts`.
- `scripts/ci/lint_sediment.py` — fails the gate when personal or repo-specific
  sediment (private namespaces, machine paths, this-repo commands, internal
  milestones) appears in shared `skills/` or `agents/` content; also enforces
  byte-identity of the duplicated `shared-pipeline.md` reference.
- `check_all.py --quick` — lint modules plus the generated-adapter drift check
  without the slow selftests; now used by the pre-commit hook.
- `scripts/ci/test_toolbelt.py` — unit tests for previously selftest-only
  installer paths (`resolve_base`, `parse_frontmatter`, forwarded commands,
  `doctor` probing).
- `CONTRIBUTING.md`, `SECURITY.md`, and a README section describing the
  public-snapshot posture.

### Changed

- `code-audit` and `security-audit` share their pipeline mechanics via a
  byte-identical `references/shared-pipeline.md` instead of duplicated prose.
- `plan` phases carry an explicit `TDD: strict` / `TDD: none` marker; the
  executor builds strict-TDD phases through the `/tdd` discipline; `build-skill`
  verifies via `/dogfood` and cites its verdict as promotion evidence.
- `grilling` rewritten in agent voice with concrete triggers; `new-app` gained a
  real command-discovery procedure; `codebase-design` dropped its generic
  testability section.
- Shared skills are now machine- and repo-neutral: repo-local facts moved to
  AGENTS.md, `opensrc` became a conditional capability, dated anecdotes moved to
  DEVLOG.md, attribution reduced to one canonical line per derived skill.
- `weekly_janitor_report.py` repo-specific callouts are env-configured
  (`AGENTIC_JANITOR_*`) and disabled by default.

### Fixed

- `publish_public.py` no longer embeds the private namespace string in its own
  leak check and uses `shutil` instead of POSIX-only `rm -rf`/`cp -r`.
- Removed dead code from `toolbelt.py` (phantom `shutil.IgnorePattern` type,
  unreachable dispatch branches, hand-rolled quoting).
- `babysitting-pr` no longer asserts a dated, now-wrong claim about harness
  capabilities; `ship`/`babysitting-pr` invocation prose matches actual policy.

## [0.1.0] - 2026-07-17

### Added

- Initial public snapshot: 31 provider-neutral skills, the executor agent, the
  installer/doctor/generator (`scripts/toolbelt.py`), the CI gate, the disposable
  Docker sandbox, and provider adapters for Claude Code, Codex, and Pi.
