# Contributing

This repository is a public snapshot of a privately developed toolbelt (see the
"Public snapshot posture" section in [README.md](README.md)). Issues and pull
requests are read and appreciated, but changes land in the private repository first
and reach public `main` with the next snapshot, so a public PR may be ported rather
than merged in place.

## Before proposing a change

Run the repository gate and make it green:

```bash
python3 scripts/ci/check_all.py
```

CI runs the same entry plus a secret-scan job, on Linux, macOS, and Windows, with
Python pinned at the declared 3.9 floor — so 3.10+-only syntax fails the build.

## Ground rules the gate enforces

- **Pure stdlib.** Scripts use only the Python standard library; no third-party
  imports.
- **Generated files are never hand-edited.** `providers/claude/skills/` and
  `providers/codex/agents/` are generated from the canonical `skills/` and
  `agents/` trees; `docs/skills.md` is generated from skill frontmatter. After
  editing canonical content, regenerate:

  ```bash
  python3 scripts/toolbelt.py generate
  python3 scripts/ci/skill_catalog.py --generate
  ```

- **LF line endings** everywhere (`.gitattributes` enforces this).
- **Skills stay provider-neutral and machine-neutral.** The sediment lint
  (`scripts/ci/lint_sediment.py`) fails the build on personal paths, private
  namespaces, or this-repo-specific commands inside shared `skills/` or `agents/`
  content.
- **Every skill is a directory** under `skills/` with a `SKILL.md` (frontmatter
  `name` matching the directory and a trigger-bearing `description`), a `tests.md`
  with at least three scenarios and a verification marker, and an
  `agents/openai.yaml` whose invocation policy matches `toolbelt.json`.

## Commit hygiene

The pre-commit hook runs a quick gate (`check_all.py --index --quick`: all lint
modules plus the generated-adapter drift check) against the staged bytes. The full
gate, including the installer and script selftests, runs in CI and via
`agentic gate` — run it locally before proposing anything substantial.
