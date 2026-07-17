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
| GitHub-backed workflows | Yes | Yes | Yes | `gh`, network, authentication |
| Dashboard rendering | Portable tests | Yes | Yes | Watch mode requires POSIX process control |
| cmux orchestration | No | Yes | No | cmux and supported terminal environment |
| Disposable sandbox | Docker-dependent | Yes | Yes | Docker/Compose |

Skills may require external write authority—for example, opening an issue or pull
request—even when the core workflow is available. Those actions remain explicit and use
the active provider's permission model.
