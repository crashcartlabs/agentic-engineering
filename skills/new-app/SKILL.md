---
name: new-app
description: "Bootstrap a new or existing application repository into the Agentic Engineering spec-to-operations workflow. Use when starting an application, preparing an empty repository for agent-assisted development, or adding the workflow artifacts and local instructions to an existing app before product work begins."
---

# Bootstrap a new application repository

Keep product code in the application repository and keep this toolbelt installed globally. Bootstrap the target before specification or implementation begins.

## 1. Resolve and inspect the target

Resolve the requested directory. If none was given, use the current working directory only after confirming it is the intended application repository.

Before writing:

- inspect existing `AGENTS.md`, `CLAUDE.md`, `DEVLOG.md`, `TODO.md`, `specs/`, and `plans/`;
- inspect the stack, package/build files, existing checks, and deployment assumptions;
- refuse to overwrite an existing file unless the user explicitly approves a merge;
- never initialize the application inside the Agentic Engineering toolbelt repository.

## 2. Run the deterministic bootstrap

Run one of:

```text
agentic init-app --create <target-directory>   # new directory: create it and initialize Git
agentic init-app <target-directory>            # existing Git repository root: add missing files only
```

Pass `--create` when the target directory does not exist yet — without it the command stops rather than creating anything. An existing target must already be a Git repository root.

If the `agentic` launcher is unavailable, stop and tell the user to run the toolbelt installer from its source repository. Do not recreate the scaffold ad hoc.

The command creates only missing workflow files and directories. A conflict is a stop, not permission to replace local policy.

## 3. Make the repository instructions real

Fill the generated `AGENTS.md` with facts discovered from the target repository:

- project purpose and architecture boundaries;
- exact setup, build, test, lint, and type-check commands;
- deployment and rollback ownership;
- definition of done and review expectations;
- any directory-specific rules that every agent must follow.

Keep `CLAUDE.md` as a thin adapter that points to `AGENTS.md`. Do not copy shared skills or agent prompts into the application repository.

## 4. Route into the lifecycle

End by choosing exactly one next gate:

- If the product boundary is still foggy, recommend `wayfinder`.
- Otherwise, start `spec` for the first product behavior contract.

The required order after bootstrap is:

```text
map when needed -> spec -> plan -> execute/tdd -> review-plan -> audits by risk -> commit/ship -> operate
```

Never skip the spec or begin product implementation during bootstrap.

## Success criteria

- The target application repository—not the toolbelt—owns its product code and local policy.
- Existing files were preserved or merged only with explicit approval.
- `AGENTS.md` contains real project commands rather than generic placeholders.
- The next action is `wayfinder` or `spec`, never implementation.
