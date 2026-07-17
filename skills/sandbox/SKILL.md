---
name: sandbox
description: "Run risky or destructive dev work inside a disposable Docker container instead of the live machine. Use when a task involves destructive git operations (rebase/reset/filter experiments), installing hooks or packages into a repo to see what breaks, running an unfamiliar installer or untrusted code, or dogfooding a skill that mutates a repo — anything where failure on the real tree would have consequences. Requires Docker on the host. Not for ordinary edits, running the repo's own gate, or work that must touch the real working tree."
---

# Sandbox

Bounded disposable space: the host checkout is never mounted. A sanitized
`git archive HEAD` file seeds a fresh local repo, and the container is deleted on exit.
Full mechanics, remaining trust, and confidentiality limits are in the toolbelt source's
`sandbox/README.md` (the source path is reported by `agentic doctor`).

## Decide sandbox vs live

Run it in the sandbox when the honest answer to "what if this goes wrong?" involves
the working tree, the hooks, installed packages, or the machine. Run it live when
the repo's own gate already covers it — tests, linters, and ordinary edits don't
need isolation. If Docker isn't available (`docker info` fails), say so and either
ask to proceed live or stop — never silently downgrade a "sandbox this" request to
the real tree.

## Use

```sh
agentic sandbox --repo <target-repo>          # offline shell, the default
agentic sandbox --repo <target-repo> --online # explicit network access
```

- The seed is committed `HEAD` only — commit (locally) or export a patch first if the experiment
  needs uncommitted work.
- Untrusted code gets the offline service. Do not run a network installer offline and
  pretend it was tested; use `sandbox-online` only when downloads are necessary and
  acknowledge that it can transmit every tracked file in the seed.
- For hook-setup and destructive-git experiments, build a scratch repo under
  `/work` instead of using the clone — smaller blast surface, cleaner readout.

## Getting results out

Everything inside vanishes on exit — that is the point, not a bug. Before exiting,
export what matters: print a patch (`git add -A && git diff --cached`) or the
relevant logs to stdout and capture them on the host side. Landing exported
changes on the real tree is a deliberate second step through the normal gate
(`/commit`), never an automatic sync.

## Hard rules

- Never weaken the isolation to make an experiment easier: no checkout bind
  mounts of the real repo, no `docker run -v $(pwd):/work`, no `--privileged`, no
  mounting the Docker socket.
- Report sandbox results as sandbox results — "worked in the sandbox" is evidence,
  not proof it works on the host; say what was and wasn't covered.
- A failed experiment needs no cleanup — exit and let `--rm` do it. Never try to
  "fix" a wrecked sandbox clone; recreate it.
