# Agent launch flags and permission policy

Every subagent starts with its provider's normal permission and sandbox policy. A
worktree separates concurrent checkouts; it does not protect the host, credentials,
network, Docker daemon, home directory, or sibling repositories.

| Agent | Launch line | Model |
|---|---|---|
| Claude Code | `claude --model <model> "<task>"` | Prefer provider aliases when the user wants automatic family updates. |
| Codex | `codex -m <model> "<task>"` | Prefer the user's configured default when no comparison requires a pinned model. |
| `pi` | `pi --model <provider/id> "<task>"` | e.g. `openrouter/z-ai/glm-5.2`, `openrouter/minimax/minimax-m3`. |

For a plain orchestrator session (not a fleet member), omit `-m`/`--model`
entirely to use that CLI's own configured default rather than a value that
will go stale — this is what `just devco`/`just devpi` do.

`--unsafe-yolo` adds Claude's `--dangerously-skip-permissions` and Codex's
`--dangerously-bypass-approvals-and-sandbox` flags for that launch only. Use it only
after the user explicitly accepts the host-level risk. Never edit global provider
configuration to make bypass behavior the default.

## Long or multi-line task text corrupts the pane (confirmed live)

Whether you build a launch line yourself for `cmux send`, or `spawn_fleet.py`
builds one for a pane's `--command`/`--layout`, the text ultimately reaches
the pane by being **typed into its shell as keystrokes** — it is not exec'd
as a process argument. `shlex.quote()` (which `spawn_fleet.py` uses, and
which you should use too) safely escapes quotes and backticks for *shell
parsing*, but it does nothing about literal newlines: each `\n` in the task
text is sent as a real Enter keystroke, submitting whatever's been typed so
far *before* the quoted string closes.

**Observed live, across a real 4-agent fleet**, from a task description with
ordinary paragraph breaks: one pane's shell hung forever in an open `>`
quote-continuation prompt (`claude` never launched — bash was still waiting
for the closing quote); other panes launched `claude` but with duplicated,
interleaved, or truncated prompt text; `bash: syntax error near unexpected
token` and `command not found` lines appeared where stray fragments got
submitted as their own commands. One agent (running on the strongest model
in that fleet) noticed its own prompt looked corrupted and stopped to ask a
clarifying question rather than guess — a good sign the model is paying
attention, but you shouldn't rely on that catching it for you.

**The fix — never put a multi-line task in a launch line:**

1. Write the task to a file (e.g. `TASK.md`) inside the entry's worktree
   directory, using your own file-write tool directly — not through the
   terminal, so no keystroke-simulation is involved.
2. Build the launch line with a short, single-line pointer prompt instead:
   `claude --model <model> "Read TASK.md in
   the current directory and do exactly what it says."`

This applies to every agent row above (Claude Code, Codex, `pi`).

**`spawn_fleet.py` handles this automatically** via `resolve_task_text()`: an
`--entry` description containing `\n` gets written to `TASK.md` in that
entry's worktree, and the launch line uses the short pointer prompt instead
of the raw text. The manifest still records the entry's full original
`description` for `/cmux check`/`/cmux collect` to report — only the pane's
launch line is affected. Single-line descriptions pass through unchanged.
Covered by `spawn_fleet.py --selftest`.

**For manual driving, use `scripts/cmux/send_task.py` instead of raw `cmux
send`.** It applies the identical fix (`resolve_task_text`) outside the
fleet script, so ad-hoc driving doesn't rely on remembering to do this by
hand:

```bash
# Message an already-running pane (write your task to a scratch file first,
# via your own file-write tool -- never build the multi-line text as a shell
# string):
python3 scripts/cmux/send_task.py --workspace <ws> --surface <ref> \
  --dir <target-dir> --text-file <scratch-file>

# Launch a fresh agent instead of messaging one that's already running:
python3 scripts/cmux/send_task.py --workspace <ws> --surface <ref> \
  --dir <worktree-dir> --text-file <scratch-file> --launch claude --model opus
```

A single-line task passes through unchanged either way — this is safe to
use for every manual send, not just long ones. `--text` exists for short
one-liners; prefer `--text-file` for anything with real content, since it
sidesteps shell-quoting entirely. Covered by `send_task.py --selftest`.

**Recovering a pane that already got corrupted:** see "Recovering a stuck or
corrupted surface" in the main `SKILL.md`. After it's back to a clean
prompt, resend the short pointer-prompt version — don't just retype the
original multi-line text, or you'll reproduce the same corruption.
