---
name: dashboard
description: "Start, inspect, or stop the worktree pipeline dashboard through the installed toolbelt entry point. Invoke as /dashboard start or /dashboard stop."
---

# /dashboard — worktree pipeline dashboard lifecycle

Use the installed `agentic dashboard` entry point. Never resolve
`scripts/dashboard/dashboard.py`, its config, pidfile, log, or HTML relative to the
target application: those assets belong to the installed toolbelt source.

Read `$ARGUMENTS`. If it is neither `start` nor `stop`, ask which action is meant.
Dashboard lifecycle is POSIX-only (macOS/Linux); relay the command's platform error on
Windows instead of substituting a forceful process command.

## Start

The target is the application repository the agent is currently working in, unless the
user explicitly names another repository.

Launch the installed watcher detached from the current session:

```sh
nohup agentic dashboard --watch --repo <target-repo> >/dev/null 2>&1 &
```

Poll briefly—at most about 30 seconds—with:

```sh
agentic dashboard --status --repo <target-repo>
```

The status command validates that the pidfile names the real watcher and that the HTML
output is a regular non-symlink file. Success prints the PID plus absolute output and log
paths; report those paths. If status remains nonzero, report startup failure and the
diagnostic it printed. Do not guess or manually signal a PID.

## Stop

Run:

```sh
agentic dashboard --stop
```

The command validates process identity, sends `SIGTERM`, waits briefly for clean pidfile
removal, and reports whether the watcher stopped. Relay the result. Never escalate to
`kill -9` without a separate user request.

## Hard rules

- Explicit-trigger only; invocation policy is generated from `toolbelt.json`.
- Use only the installed lifecycle commands, never target-repo-relative helper paths.
- Never signal an unvalidated PID or silently force-kill a stuck watcher.
- Treat `dashboard.html` as sensitive local output: it contains absolute filesystem paths
  and live PR URLs, so do not share it unredacted.
