---
name: cmux
description: "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language — open, inspect, prompt, read, and tear down cmux workspaces and panes, and fan out fleets of Claude Code / Codex / pi agents across isolated git worktrees. Use whenever asked to deploy, spawn, check on, or tear down cmux workspaces or agent fleets. Prefix requests with the `cmux` skill."
disable-model-invocation: true
argument-hint: "[what to do in cmux]"
---


# cmux

## Purpose

You are driving **cmux**, a CLI + Unix socket for controlling terminal
surfaces (and the agents running inside them). Everything nests in one
hierarchy: **Window** → **Workspace** (tab) → **Pane** (split region) →
**Surface** (a terminal or browser tab within a pane). Every object is
addressable and scriptable from the command line.

Two things this skill does:

**A. General driving** — ad-hoc requests: open a workspace, run something in
it, read back the result, close it.

**B. Fleet workflows** — `cmux deploy N workspaces of <agent> to build
features ...` (fan-out: different features, one agent each) and bake-offs
(`agentic cmux-fleet --arrange grid` — same feature, several agent/model
combos). Both call the installed toolbelt entry point, so they work from any
target repository.

## Preflight (every invocation)

1. `cmux --help` if anything below seems stale — cmux evolves; trust
   `--help` over memory, never guess a flag. **`cmux` may not be on `$PATH`**
   even when the app is installed and running (confirmed live) — if `cmux
   --help`/`cmux ping` returns "command not found", fall back to
   `/Applications/cmux.app/Contents/Resources/bin/cmux` directly (same
   candidate list `spawn_fleet.py` already checks).
2. Confirm the socket is reachable: `cmux ping`. If it fails, **don't assume
   cmux is down** — `cmux ping` is itself refused from outside a cmux pane
   under `automation.socketControlMode: cmuxOnly`, *even when cmux is fully
   running* (confirmed live: `ps`/`pgrep` showed the process up while `ping`
   returned "Broken pipe"). Check `cmux capabilities` next (step 3) before
   concluding cmux needs launching — if `capabilities` also fails, *then*
   `open -a cmux` and poll (~20s).
3. Confirm `cmux capabilities` reports an access mode usable from the current
   process. Prefer running the orchestrator inside cmux so the default
   `cmuxOnly` policy remains intact. Do not change the global policy silently;
   `--allow-all-socket` is the explicit, backed-up escape hatch described in
   `references/socket-policy.md`.
4. `cmux hooks setup --yes` so notification-based waiting works (see
   `references/events-and-waiting.md`) — idempotent, so it's fine to run on
   every invocation (`spawn_fleet.py` does); for ad-hoc driving, once per
   session is enough.

## A. General driving

- **Discover before acting**: `cmux tree --all`, `cmux list-workspaces`,
  `cmux list-pane-surfaces --workspace <ref>`.
- **Capture refs at creation, never guess them.** `cmux workspace create
  --json` returns `workspace_ref` + `surface_ref`; `cmux new-split <dir>
  --json` returns a new `surface_ref`. Refs like `surface:3` are positional
  and renumber as things open/close — **for anything you'll refer back to
  later** (a manifest, a variable held across multiple commands), add
  `--id-format both` to the same call: it adds `workspace_id`/`surface_id`
  (UUIDs) alongside the positional refs in the same JSON response, and those
  UUIDs work as direct drop-in values for any later `--workspace`/`--surface`
  flag (confirmed live). `agentic cmux-fleet` always does this for
  exactly this reason — its manifests store UUIDs, not positional refs.
- **The four-verb control loop:**
  - `cmux send --workspace <ws> --surface <ref> "<text>"` — types text (does
    **not** submit). **Only for a short, single-line text.** For anything
    with real content (a task, an instruction, more than one sentence), use
    `agentic cmux-send` instead — see below and
    `references/agent-launch-flags.md`. Typing multi-line text through raw
    `cmux send` corrupts the pane (confirmed live).
  - `cmux send-key --workspace <ws> --surface <ref> enter` — submits.
  - `cmux read-screen --workspace <ws> --surface <ref> [--scrollback --lines N]`
    — your eyes.
  - `cmux close-surface --surface <ref>` — end a surface. Close only surfaces
    you created or explicitly identified — never loop a close over the whole
    tree.
- **Credentials:** `cmux workspace create --env-file <path>` loads
  `KEY=VALUE` lines into every surface in that workspace. Use it only when the
  user explicitly names a readable file; never auto-discover the target
  repo's `.env`. Never `cat`/echo the file's contents;
  if an agent fails to authenticate, `cmux workspace env --workspace <ref>
  --mask` shows presence without revealing values.
- **Targeting a directory:** `cmux workspace create --cwd <path>` (not
  `--repo` — that flag doesn't exist and errors; confirmed live). `--repo` is
  a `spawn_fleet.py` argument, not a `cmux` one — don't conflate the two.
- **Launching an agent directly** (outside the fleet scripts): use
  `agentic cmux-send --launch <agent> --model <model>` — see
  `references/agent-launch-flags.md` for safe defaults, the explicit
  `--unsafe-yolo` override, and why raw `cmux send` with a nontrivial task
  corrupts silently.
- **Waiting for a reply:** see `references/events-and-waiting.md` — prefer
  push (`cmux events`) over polling `read-screen` in a loop.
- **Recovering a stuck or corrupted surface:** `cmux send-key ... ctrl+c`
  (send it twice if a menu/dialog is on screen — the first press dismisses
  it, the second returns to a clean prompt; `escape` also dismisses a
  dialog). Always `read-screen` afterward to confirm you're back at a plain
  shell or an idle agent prompt before sending anything new — don't assume
  one interrupt was enough.
- **Canonical verb forms.** Use `cmux workspace create/list/close`, not the
  deprecated `new-workspace`/`list-workspaces`/`close-workspace` aliases
  (both work; the canonical form avoids a one-time deprecation notice).
  `--help` on this installed version doesn't list every real flag (e.g.
  `--json` isn't shown but works) — trust live testing over `--help` text
  when the two disagree, and re-test if something doesn't behave as written
  here.

## B. Fleet workflows

Both workflows call the same script with a list of general entries —
`label:agent:model:description` — differing only in `--arrange`:

- **`tabs` (fan-out)** — different features, one agent each. Each entry
  becomes its own sibling **workspace** (tab) in a shared window. Use for
  requests like *"deploy N workspaces of codex agents to build features a,
  b, c, d"*: one `--entry` per feature, same `agent`/`model`, different
  `description`.
- **`grid` (bake-off)** — the *same* feature/bug, several agent/model
  combos. All entries share **one workspace**, split into N **panes** (cmux's
  term — what a request might call "N windows in a grid" actually means N
  panes in one workspace). Use for requests like *"run a bake-off on
  <feature> with claude, codex, and pi"*: same `description` across entries,
  different `agent`/`model` each.

```bash
agentic cmux-fleet --repo <target-repo> --arrange {tabs|grid} \
  --entry "label1:agent:model:description1" \
  --entry "label2:agent:model:description2" ...
```

- Omit `--repo` to target the current directory.
- Omit `--run-slug` to let the script derive one; it prints the manifest path
  it wrote either way — always report that path back.
- The script handles preflight, worktree creation, workspace/pane creation,
  and writes an owner-only manifest under the repository's Git common state,
  outside contributor-controlled checkout content. Resolve and validate it
  with `agentic cmux-manifest <run-slug> --repo <target-repo>`.
- **Worktrees land as siblings, not nested.** Each entry's worktree is
  `<repo>-worktrees/<run-slug>-<label>/`, next to `<repo>` itself — not
  inside provider state. Fleet worktrees isolate concurrent checkouts for
  external agent processes, so they follow git's sibling-directory
  convention. They are **not a host security boundary**: an agent may still
  reach the user's home directory, credentials, Docker, sibling repositories,
  global Git configuration, and the network according to its provider
  permissions.
- **Multi-line `--entry` descriptions are handled automatically.** The
  script writes a description containing a newline to `TASK.md` in that
  entry's worktree and launches with a short pointer prompt instead of
  typing the raw text into the pane — see `references/agent-launch-flags.md`
  for why (a multi-line description used to reach the pane as literal
  keystrokes and break; confirmed live across a 4-agent run before this was
  fixed). This is script-only: manual `cmux send` driving still needs you to
  do this by hand.
- **Deploying returns immediately** — it does not wait for agents to finish.
  That's the point of a fleet: report the manifest and move on.

## Follow-up: check / collect / teardown

These are natural-language, driven directly via the `cmux` CLI against a
fleet's manifest — no script involved, since deciding what "done" or "best"
means belongs to you, not a mechanical bootstrap step.

- **`cmux check <fleet>`** — run `agentic cmux-manifest <fleet> --repo
  <target-repo>` and read only the validated path it returns (its
  `workspace_ref`/`surface_ref` fields are UUIDs, not positional refs —
  usable directly as `--workspace`/`--surface` values), `read-screen`
  each `surface_ref` (or wait on notification events per
  `references/events-and-waiting.md` if hooks are installed, matching on
  `workspace_id` against the manifest's `workspace_ref`), report per-entry
  status.
- **`cmux collect <fleet>`** — resolve the manifest with `agentic
  cmux-manifest` first; for each entry, `cd` into its `worktree_path`
  and report `git status`/`git diff --stat` — a summary, not a full diff dump
  unless asked.
- **`cmux teardown <fleet>`** — resolve the manifest with `agentic
  cmux-manifest` first, then close only the surfaces/workspaces recorded
  in that manifest (`cmux close-surface`/`cmux workspace close` per entry —
  never a broad close over the whole tree). **Never delete a worktree**
  unless explicitly asked — it may hold unmerged work; if asked, confirm
  `git status` is clean or the user has acknowledged discarding it first.
- **After a bake-off, naming a winner selects the result; it does not authorize
  destructive cleanup.** Present the exact winning and losing branches,
  worktrees, and cmux surfaces. Merge or otherwise preserve the winner as
  requested, then obtain separate approval before force-removing any losing
  branch or worktree. A reflog is recovery evidence, not permission to delete.

## Hard rules

- **Explicit-trigger only** (declared in `toolbelt.json` and provider metadata) — this never fires
  on its own.
- **Never guess a ref or a flag.** Re-read `tree`/`list-*` right before
  acting; trust `--help` and live testing over memory.
- **Never echo a secret** — env values loaded via `--env-file` are never
  printed back.
- **Close scoped, never broad.** Only close what you created or what an
  owner-local manifest validated by `agentic cmux-manifest` names. Never
  trust a fleet JSON file from the checkout.
- **Every spawned agent gets its own worktree.** Never point two fleet
  entries at the same working directory.
