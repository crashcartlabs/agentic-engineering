# cmux orchestrator — how-to guide

`just cmux-help` opens this file. It's the map for using a Claude Code / Codex /
`pi` session as an orchestrator that drives fleets of agents through cmux.

## The mental model

cmux nests everything in one hierarchy:

```
Window      a macOS window with its own sidebar
 └ Workspace  a sidebar entry (a "tab")
   └ Pane       a split region within a workspace
     └ Surface    a tab within a pane (terminal or browser)
```

Every object is addressable from the CLI. The whole system is four verbs:

```bash
cmux send        --surface <ref> "text"   # type into a terminal
cmux send-key    --surface <ref> enter    # press a key (send doesn't submit)
cmux read-screen --surface <ref>          # read what it printed
cmux close-surface --surface <ref>        # shut it down
```

## Two arrangements for a fleet

- **Fan-out (`tabs`)** — different features, one agent each. Each feature
  gets its own sibling workspace (tab) in a shared window.
- **Bake-off (`grid`)** — the same feature/bug, several agent/model combos,
  arranged as panes within one workspace so you can compare them side by
  side.

Both are driven by `scripts/cmux/spawn_fleet.py`, which also creates an
isolated `git worktree` per agent so concurrent runs never collide. Worktrees
separate files for concurrency; they are not a security boundary.

## The `just` recipes

- `just devcl` — start Claude Code in the current repo with its normal safety
  controls. Installed shared skills are available through the Claude adapter.
- `just devco` — start Codex in the current repo with its normal sandbox and
  approval controls. Installed shared skills are available as `$skill-name`.
- `just devpi` — start `pi` in the current repo with installed shared skills.
- `just build "<feature>"` — bake-off: 4 agent/model combos (Claude/opus,
  Codex/gpt-5.5, pi/glm-5.2, pi/minimax-m3) each build the same feature in
  their own worktree, arranged as 4 panes in one workspace. A Claude Code
  orchestrator is launched already primed with the manifest to supervise and
  report which solution is best. Agent safety controls remain enabled.
- `just debug "<bug>"` — same as `build`, but each combo doubled (8 total),
  for urgent parallel bug-fix attempts.
- `just build-unsafe "<feature>"` — the same bake-off with provider permission
  bypasses and outside-cmux socket control explicitly enabled. Use only in a
  disposable sandbox after reviewing the risk.
- `just cmux-help` — this file. `just help` opens the canonical app workflow.

By default these target wherever you ran `just` from, not this repo — pass
an explicit repo path as the second argument if you want to override that
(e.g. `just build "add dark mode" ~/projects/other-repo`).

## Socket and environment safety

The safe default keeps cmux's socket at `automation.socketControlMode:
cmuxOnly`; launch the orchestrator from a cmux pane. The tooling refuses to
weaken this policy silently. `--allow-all-socket` is an explicit escape hatch
that backs up the config before changing it; see
`skills/cmux/references/socket-policy.md` for the exact threat model and
restoration steps.

Environment files are never discovered or copied automatically. Pass a
specific readable file with `--env-file` only when the fleet actually needs
it, and treat every spawned agent as able to read that file.

## Follow-up

Once a fleet is deployed, ask the orchestrator things like:

- `/cmux check <fleet-slug>` — status of every agent in a fleet
- `/cmux collect <fleet-slug>` — git status/diff summary per agent
- `/cmux teardown <fleet-slug>` — close the fleet's surfaces (worktrees are
  never deleted automatically — they may hold work you want to keep)

Each fleet's manifest lands in the target repo at `.cmux/fleet/<slug>.json`,
untracked — add `.cmux/` to that repo's `.gitignore` if you don't want it
showing up in `git status`.
