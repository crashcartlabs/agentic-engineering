# Capability matrix

The toolbelt promises an honest tested boundary, not identical functionality on every
operating system.

| Capability | Windows | macOS | Linux | Additional requirement |
|---|---:|---:|---:|---|
| Instructions, skills, specs, and plans | Yes | Yes | Yes | Python 3.9+ for automation |
| Installer, doctor, generator, app bootstrap | Yes | Yes | Yes | Python 3.9+ |
| Structural gate and portable selftests | Yes | Yes | Yes | Git |
| Claude Code adapter | Yes | Yes | Yes | Claude Code |
| Codex adapter and custom executor | Yes | Yes | Yes | Codex |
| Pi skills and executor extension | Yes | Yes | Yes | Pi |
| Hermes skills and workflow router | Yes | Yes | Yes | Hermes |
| GitHub-backed workflows | Yes | Yes | Yes | `gh`, network, authentication |
| Dashboard rendering | Portable tests | Yes | Yes | Watch mode requires POSIX process control |
| cmux orchestration | No | Yes | No | cmux and supported terminal environment |
| Disposable sandbox | Docker-dependent | Yes | Yes | Docker/Compose |

Skills may require external write authority—for example, opening an issue or pull
request—even when the core workflow is available. Those actions remain explicit and use
the active provider's permission model.

## Skill × provider support

Every skill in `skills/` installs to all four providers, but the invocation and
delegation experience differs. The gate enforces the per-provider policy artifacts
(`skillPolicy.explicit` for Claude and Codex); where a provider has no policy mechanism,
the limitation is documented here instead of enforced.

| Skill | Claude | Codex | Pi | Hermes |
|---|---|---|---|---|
| Workflow skills (spec, plan, execute, bugfix, commit, ship) | explicit-trigger enforced | explicit-trigger enforced | implicitly invocable¹ | explicit-trigger via router |
| Review skills (review-plan, code-audit, security-audit) | explicit-trigger enforced; delegation via markdown agents | explicit-trigger enforced; delegation via generated TOML | implicitly invocable¹; delegation 1-at-a-time via subagent extension | delegation via `delegate_task` |
| Research, improve-codebase-architecture | delegation via markdown agents | delegation via generated TOML | delegation 1-at-a-time via subagent extension | delegation via `delegate_task` |
| cmux, dashboard | machine-specific skills, installed as-is | machine-specific skills, installed as-is | machine-specific skills, installed as-is | machine-specific skills, installed as-is |
| Everything else | installed and invocable | installed and invocable | installed and invocable | installed and invocable |

¹ **Pi limitation:** `skillPolicy.explicit` is **not enforced on Pi** — mutating skills
are implicitly invocable there. The Pi `package.json` block and
`providers/pi/extensions/subagent.ts` carry no policy artifact, so this is documented,
not enforced; see degraded-delegation.md.
