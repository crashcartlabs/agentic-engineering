# Agentic Engineering

Agentic Engineering is a personal, provider-neutral software-engineering toolbelt. It
packages a disciplined workflow—product specification, technical planning, test-first
execution, conformance review, risk-based auditing, release, and operations—so the same
process is available in Claude Code, Codex, and Pi.

This repository is not an application template and application code does not belong
here. Keep it installed as a toolbelt and start the agent from the application repository
being developed.

## Workflow

```text
create app repo
  -> map when needed
  -> spec
  -> plan
  -> execute with TDD
  -> verify against plan and spec
  -> audit according to risk
  -> commit and release
  -> operate and clean up
```

Small, well-understood fixes skip the product ceremony: `/bugfix` produces a compact
single-phase plan and runs the same review pipeline.

The specification is mandatory for product work; `/bugfix` is the explicit exception
for small, proven fixes. Mapping is optional when the product boundary is already
clear, and deeper audits are selected according to risk. See the visual
[app build workflow](docs/app-build-workflow.html) for the artifact and skill map.

## Requirements

- Python 3.9 or newer
- Git
- At least one supported agent CLI: Claude Code, Codex, or Pi
- Optional: `gh` for GitHub workflows, Docker for the disposable sandbox, and cmux on
  macOS for fleet orchestration

Run `python3 scripts/toolbelt.py doctor` for the exact capabilities available on the
current machine. Platform boundaries are listed in [docs/capabilities.md](docs/capabilities.md).

## Setup

The fastest path is the guided wizard. From this repository:

```bash
python3 scripts/toolbelt.py setup          # POSIX (Linux, macOS, WSL)
py -3 scripts\toolbelt.py setup           # Windows PowerShell
```

`setup` checks the machine (same report as `doctor`), tells you which provider
integrations it will install, confirms with you, installs, re-checks, and prints
next steps. Add `--yes` to skip the confirmation (CI), `--dry-run` to preview
without writing, and `--providers claude,codex` to install a subset.

If you prefer the manual install, from this repository:

```bash
python3 scripts/toolbelt.py generate --check
python3 scripts/toolbelt.py install --dry-run
python3 scripts/toolbelt.py install
```

The installer is idempotent and refuses to replace files it does not manage. It installs:

- canonical skills for Codex and Pi under the shared Agent Skills location;
- generated Claude skill adapters (with Claude invocation policy restored) and canonical
  agents under the provider's personal directories;
- the generated Codex executor agent;
- the Pi subagent extension and executor definition;
- Hermes skills and the `agentic-engineering` workflow router under `~/.hermes/skills/`
  (four toolbelt skills — `plan`, `tdd`, `dogfood`, `research` — are deliberately
  excluded because Hermes ships its own under those names; the router points at the
  repo copies);
- an `agentic` launcher under `~/.local/bin` on POSIX systems or the reported local bin
  directory on Windows.

The installer records provider ownership and content hashes in
`~/.agentic-engineering/install-state.json`. That inventory lets updates remove obsolete
managed artifacts, preserves shared skills while another provider still uses them, and
refuses to overwrite edited managed directories unless `--force` is explicit.

Ensure the launcher's directory is on `PATH`, then verify the installation:

```bash
agentic doctor
```

`doctor` reports capabilities and, when something is missing, a one-line hint for how
to fix it (`agentic doctor --hints` behavior is built in).

To install only selected adapters:

```bash
python3 scripts/toolbelt.py install --providers claude,codex
```

See [docs/setup.md](docs/setup.md) for the full setup, update, and uninstall guide.

## Start work in an application

Bootstrap a new application repository:

```bash
agentic init-app ~/code/my-app --create
```

`--create` initializes the directory as a Git repository. Commit the bootstrap files
before beginning the spec/plan workflow so later branches have a durable base.

Then start the agent with that application as its working directory:

```bash
codex -C ~/code/my-app
```

For Claude Code or Pi, change into the application repository first:

```bash
cd ~/code/my-app
claude
```

```bash
cd ~/code/my-app
pi
```

Provider-native explicit skill syntax differs:

| Provider | Example |
|---|---|
| Claude Code | `/spec` (personal install) or `/agentic-engineering:spec` (plugin install) |
| Codex | `$spec` |
| Pi | `/skill:spec` |
| Hermes | Natural language — "spec this idea", "plan this spec"; the installed `agentic-engineering` router skill loads the matching workflow skill |

The skill names, workflow order, artifacts, and behavior remain the same.

Operational helpers are also available from any application repository through the
launcher: `agentic dashboard`, `agentic cmux-fleet`, `agentic cmux-send`,
`agentic cmux-manifest`, and `agentic sandbox`. They resolve the toolbelt's own scripts
and assets instead of assuming the application contains this repository's `scripts/` or
`justfile`.

## Update and uninstall

After pulling toolbelt changes, rerun the installer. Managed files are replaced only
when they still match the previous installation; local edits cause a refusal instead of
being silently lost.

```bash
git pull
python3 scripts/toolbelt.py install
```

Remove only files owned by the installer with:

```bash
python3 scripts/toolbelt.py uninstall
```

Selective uninstall is supported (`--providers codex`, for example); shared artifacts
and the launcher remain until their last installed provider is removed.

Use `--dry-run` to preview either operation. If `doctor` reports a stale or partial
installation, rerun `install`; use `--force` only after inspecting the conflicting path
and deciding that the toolbelt should own it.

## Repository structure

- `AGENTS.md` — canonical engineering policy
- `CLAUDE.md` — thin Claude adapter
- `skills/` — canonical Agent Skills
- `agents/` — canonical agent prompts
- `providers/` — generated or executable provider adapters
- `.claude-plugin/`, `.codex-plugin/`, `package.json` — provider entry manifests
- `toolbelt.json` — workflow and invocation-policy registry
- `scripts/toolbelt.py` — installer, doctor, generator, and app bootstrap
- `scripts/` and `sandbox/` — supporting automation
- `docs/` — guides and the generated skill catalog ([docs/skills.md](docs/skills.md))
- `plans/` — approved implementation plans and execution records
- `reviews/` — plan-conformance review reports
- `security-reviews/` — security-audit reports
- `.github/` — CI workflows
- `justfile` — just-command shortcuts for the common toolbelt recipes
- `.pre-commit-config.yaml` — pre-commit hook running the gate

Provider-generated files are not a second source of truth. Regenerate them from the
canonical prompt or skill metadata and verify with `agentic check`.

## Public snapshot posture

This public repository is a curated snapshot: development happens in a private
repository, and public `main` is periodically replaced by a single squashed
"public snapshot" commit (see [docs/publishing.md](docs/publishing.md)). Issues and
pull requests are welcome as feedback, but be aware that fixes land in the private
repository first and arrive here with the next snapshot — a public PR may be ported
rather than merged directly, and public branch history should not be treated as
durable. See [CONTRIBUTING.md](CONTRIBUTING.md) for the gate to run before proposing
changes and [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Safety model

Git worktrees provide concurrency isolation, not host security. Agent bypass flags,
environment injection, destructive cleanup, and relaxed control sockets must be explicit
unsafe choices. The Docker sandbox protects the host checkout only within the threat
model documented in `sandbox/README.md`; Docker and any enabled network access remain
trusted boundaries.

Run the repository gate before shipping toolbelt changes:

```bash
agentic gate
```

Artifact ownership and retention are documented in [docs/artifacts.md](docs/artifacts.md).
