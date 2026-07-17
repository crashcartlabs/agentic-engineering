# Socket policy

cmux's Unix socket (`~/.local/state/cmux/cmux.sock`) is gated by
`automation.socketControlMode` in `~/.config/cmux/cmux.json`:

- `cmuxOnly` (default) — only processes running inside a cmux-launched terminal may
  drive the socket.
- `allowAll` — any local process may drive it, without a password.
- `password` — requires a configured socket password.

Prefer `cmuxOnly`: start the orchestrator inside cmux and keep the socket unavailable to
unrelated local processes. A worktree does not reduce the risk created by `allowAll`.

Check the live value with `cmux capabilities`. Do not use `cmux ping` alone to decide
whether the app is running: from outside cmux, `ping` is refused under `cmuxOnly` even
when the process is healthy. Check process liveness before relaunching.

## Explicit allow-all escape hatch

Use `spawn_fleet.py --allow-all-socket` only when running inside cmux or password mode
is not practical and the user accepts that any local process may control cmux. The
script then:

1. backs up `~/.config/cmux/cmux.json` to a timestamped file;
2. preserves unrelated keys while setting `automation.socketControlMode` to `allowAll`;
3. fully restarts cmux because `reload-config` is unavailable through a refused socket;
4. verifies the effective mode before creating worktrees or workspaces.

Without that flag, the script refuses to change global socket policy and explains how
to continue safely. Restoration is deliberate: replace the config with the timestamped
backup and restart cmux after the external orchestration session ends.
