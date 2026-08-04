# Agentic Engineering — Setup Guide

This is the full setup, update, and troubleshooting reference. For the quick path,
run `agentic setup` (or `python3 scripts/toolbelt.py setup` from this repository)
and follow the prompts — this document explains what that does and how to control it.

## What the toolbelt installs

The installer is **idempotent** (safe to re-run) and **ownership-aware**: every file
or directory it writes carries a hidden marker recording that agentic-engineering
owns it, plus a content hash. It refuses to overwrite anything it does not own, and
refuses to update or remove anything you have edited since install unless you pass
`--force` explicitly.

| Provider | What gets installed | Where |
|---|---|---|
| All | `agentic` launcher | `~/.local/bin/agentic` (POSIX) or `%LOCALAPPDATA%\AgenticEngineering\bin\agentic.cmd` (Windows) |
| Codex + Pi (shared) | canonical skills | `~/.agents/skills/<name>/` |
| Claude | generated skill adapters + agent prompts | `~/.claude/skills/<name>/`, `~/.claude/agents/*.md` |
| Codex | generated executor agent | `~/.codex/agents/executor.toml` |
| Pi | subagent extension + executor definition | `~/.pi/agent/extensions/agentic-engineering/`, `~/.pi/agent/agents/` |
| Hermes | skills + workflow router | `$HERMES_HOME/skills/` (default `~/.hermes/skills/`) |

Install state (ownership, hashes, which providers are installed) lives in
`~/.agentic-engineering/install-state.json`.

## The setup wizard

```bash
python3 scripts/toolbelt.py setup          # POSIX (Linux, macOS, WSL)
py -3 scripts\toolbelt.py setup           # Windows PowerShell (no python3 alias)
```

Windows uses the `py` launcher rather than a `python3` executable; the generated
`agentic.cmd` launcher relies on the same `py -3` convention. After installation,
`agentic setup` works identically on every platform.

Four steps:

1. **Doctor** — reports Python/Git/CLI availability, provider CLIs, optional
   capabilities (Docker, cmux), credentials, and source health. Missing things get a
   one-line `hint:` with the remedy.
2. **Plan** — states exactly which provider integrations will be installed and asks
   for confirmation (skipped with `--yes`).
3. **Install** — runs the same idempotent install as `agentic install`.
4. **Verify + next steps** — re-runs doctor and prints the entry points
   (`agentic init-app`, `/spec`, `/bugfix`, `agentic doctor`).

Flags:

| Flag | Effect |
|---|---|
| `--providers claude,codex` | install a subset instead of all |
| `--yes` | skip the confirmation prompt (CI, scripts) |
| `--dry-run` | show what would be written, write nothing |
| `--force` | overwrite managed files even if edited since install |
| `--home <path>` | use a different home root (testing, staging) |

## Doctor and hints

```bash
agentic doctor
```

Reports the same machine state the wizard uses. Every missing capability carries a
`hint:` line with the consequence and the fix:

- `docker: missing` → `hint: install Docker to enable the disposable sandbox (...)`
- `cmux: missing` → `hint: cmux is macOS-only; fleet orchestration is not available on this OS`
- `launcher: missing` → `hint: run agentic setup (or python3 scripts/toolbelt.py install)`
- a missing provider CLI (claude/codex/pi) → its install command

`doctor` exits non-zero when something required (Git, source validity, at least one
provider) is missing, so scripts can gate on it.

## Provider selection

```bash
python3 scripts/toolbelt.py install --providers claude,codex,pi,hermes
python3 scripts/toolbelt.py install --providers hermes        # Hermes only
```

The default is `all`. Uninstalling a provider removes only its managed artifacts;
shared `~/.agents/skills/` survive while any of Codex/Pi still use them:

```bash
python3 scripts/toolbelt.py uninstall --providers codex
python3 scripts/toolbelt.py uninstall              # everything
```

## Updating

After pulling toolbelt changes, re-run the installer. Managed files are replaced only
when they still match the previous installation; local edits cause a refusal instead
of being silently lost.

```bash
git pull
python3 scripts/toolbelt.py install
```

The Hermes provider copies the canonical skills at install time, so a re-install is
also how you refresh `~/.hermes/skills/` after skill updates in the repo.

## Hermes specifics

- Skills land at `~/.hermes/skills/<name>/`, plus the `agentic-engineering` router
  skill that maps workflow steps to skills and documents the four exclusions.
- Four toolbelt skills are **not** installed because Hermes bundles its own under the
  same names or namespace: `plan`, `tdd`, `dogfood`, and `research`. The router tells
  the Hermes agent to load those from the repo instead.
- The executor agent prompt is installed inside the `execute` skill as
  `references/executor.md`.
- `$HERMES_HOME`, when set, overrides `~/.hermes` as the skills root.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `refusing to replace unmanaged file/directory` | The path exists but agentic-engineering does not own it (e.g. a Hermes category dir collides with a skill name). Inspect the path; if the toolbelt should own it, `--force`; otherwise the exclusion list is the answer. |
| `managed file was edited since installation` | You edited an installed file. Re-run with `--force` to replace it, or edit the canonical copy in the repo and re-install. |
| `install state` errors | `~/.agentic-engineering/install-state.json` is corrupt or foreign. Move it aside and re-install. |
| `agentic: command not found` | `~/.local/bin` is not on `PATH`. Add it, or call `python3 scripts/toolbelt.py ...` from the repo. |
| Doctor shows `docker: missing` | Install Docker (see hint) if you want the disposable sandbox; the rest of the toolbelt works without it. |
| Doctor shows `cmux: missing` | Not applicable on Windows/Linux; cmux fleet orchestration is macOS-only. |
| Upstream check reports CHANGED | Matt Pocock (or another pinned upstream) moved a skill you adapted. Review the diff and decide whether to port anything; the weekly GitHub Action opens an issue automatically. |

## Platform notes

- **Windows:** the launcher is `agentic.cmd`; commands in this guide assume a POSIX
  shell, but every toolbelt script is cross-platform and works under PowerShell.
- **macOS:** cmux fleet orchestration is available; the sandbox needs Docker.
- **Linux:** full capability except cmux; the sandbox needs Docker.

## Related

- [capabilities.md](capabilities.md) — honest per-OS capability matrix
- [artifacts.md](artifacts.md) — the workflow artifacts and their owners
- [app-build-workflow.html](app-build-workflow.html) — the visual workflow map
