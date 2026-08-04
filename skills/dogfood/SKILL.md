---
name: dogfood
description: "Live-test a skill in this repo to confirm it works as intended — the Definition-of-Done check applied to a skill. Validates the SKILL.md statically, checks registration + invocation policy, dogfoods it on a real input across a happy and an edge path, verifies the skill's own contracts hold (read-only, hermetic, redaction, fan-out), then proposes the DEVLOG/backlog/LESSONS updates. Invoke the `dogfood` skill with `<skill-name> [what to focus the test on]`. Explicit-trigger only."
---

# dogfood — Live-test a skill in this repo

Confirm a skill actually works when run — not that its SKILL.md reads well. This is the Definition of Done applied to a skill: the stated behavior happens for real, the skill's own guarantees hold, and the result is recorded. "Self-reviewed" is not "dogfooded" — every skill in this repo's DEVLOG was built and read over, then sat untested until a fresh session ran it for real. This skill is that fresh-session run, made repeatable.

**Adaptive by design.** Automate everything automatable (static checks, invocation policy, contract scans). For the live run, drive the skill directly if it's model-invocable; otherwise prepare the exact command for the user to type and inspect what it produces. Never fake a pass — if a check can't run this session, say so.

## Two hard constraints — internalize these first

1. **A freshly-built skill only registers as a `command` in the *next* session** (LESSONS.md). If the target was created in *this* session, its command does not exist yet — you can do the static checks now, but the live dogfood must happen in a fresh session. Don't pretend otherwise.
2. **Invocation policy is adapter-specific.** Read the canonical intent from
   `toolbelt.json` and inspect the active provider's metadata. An explicit-only skill
   must be invoked by the user using that harness's syntax; prepare the exact invocation,
   then inspect the artifacts and behavior it produced.

## Inputs

Invoke the `dogfood` skill with `<skill-name> [focus]`.
- `<skill-name>` — the skill to test, resolved to `skills/<skill-name>/SKILL.md` (this also covers agent-launcher skills like `execute`; test the launcher, and note when a spawned agent is the real thing under test).
- `[focus]` — optional; narrows what the dogfood exercises (a specific path, edge case, or contract). If given, prioritize it.

If the file doesn't exist, stop and say so — don't guess at a different skill.

## Pipeline

### 1. Read the target skill — before testing anything
Read the whole `SKILL.md` (and any `assets/`/`references/` it points to). Do not skim. From it, extract two things:
- **The skill's type** — this decides what "working" means (see the type table below).
- **The skill's stated success criteria and contracts** — its own promises: what it produces, where, and what it guarantees (read-only, hermetic, redacts secrets, fans out subagents, stops on a blocker…). These are the bar the live run is measured against.

### 2. Static validation (automate now, any session)
- Frontmatter parses as YAML; its only keys are `name` and `description`; `name` matches
  the directory; `description` describes trigger and behavior.
- For a skill owned by this toolbelt, its invocation entry in `toolbelt.json` and its
  provider metadata agree. UI argument hints are provider conveniences, never a
  canonical skill requirement.
- Every asset/reference file the SKILL.md points to exists.
- Scan the body for a contract that contradicts itself — e.g. a "read-only" skill that instructs editing a tracked file (LESSONS.md: use `.git/info/exclude`, never mutate a tracked file for bookkeeping).

### 3. Registration + invocation-policy check
- **Invocation policy:** inspect the active adapter rather than probing one provider's
  tool semantics. For Codex, check `agents/openai.yaml`; for Claude, use the plugin's
  skill listing and description boundary; for Pi, use its discovered skill listing.
- **Registration:** use the active harness's own listing or explicit invocation and
  distinguish "not installed" from "installed but explicit-only." If the harness
  requires a reload or new session, complete static checks now and run the live path
  after that boundary.

### 4. Dogfood on a real input — happy path + one edge path
Pick a **real** input, never a toy (a real diff for a review skill, a real design/task for an interactive one, real conversation state for a write-only one). For anything that mutates a repo or runs a subagent destructively, use a throwaway repo/worktree, as the executor dogfood did.

- **Model-invocable skill:** drive it directly when the active harness exposes it.
- **Explicit-trigger skill:** output the exact provider-native invocation for the user,
  state what to watch for, let the user run it, then inspect the result.

Run at least two paths, mirroring how skills have been validated here: the **happy path** and one **edge/failure path** (executor: happy + blocker; security-audit: findings + clean-bill + scanner-absent). The edge path is where skills actually break.

### 5. Verify behavior against the skill's contracts
"Working as intended" = the promises from Step 1 held when run. Check the ones that apply:

| Skill type | What to actually verify |
|---|---|
| **prompt-only** (grilling, domain-modeling) | It followed its own instructions on the real input — cadence, one-question-at-a-time, explores code instead of asking, etc. |
| **interactive/foreground** (plan) | Gates fire, teach-back/alignment happens, it pushes back where told to. |
| **orchestrator / fan-out** (code-audit, security-audit) | Subagents actually spawned (not a solo read-through); the adversarial-verify stage ran; report landed in the git-excluded dir; **`git status` shows no tracked-file changes** from the run (read-only, LESSONS.md); graceful degradation where claimed (e.g. scanner absent). |
| **subagent-launcher** (execute) | Correct stop/surface on a blocker; per-phase commits; stayed in scope; didn't touch intent/tests. |
| **write-only artifact** (handoff) | Output is complete and correctly shaped; path printed prominently; cross-platform path correct; secrets redacted. |

Cross-cutting, always: any "hermetic / no network" claim didn't phone home and pinned safe flags (LESSONS.md); any secret was redacted, never persisted raw.

### 6. Report the verdict
State, per check: **PASS / FAIL / PARTIAL**, each with the concrete evidence (the command run, the output observed, the `git status`). List explicitly what could **not** be tested this session and why (e.g. "needs a fresh session for registration") — no silent gaps; an untested check is not a pass.

### 7. Propose the record-keeping — don't auto-write
Handoffs and records are **offers**, and the DEVLOG is boundary-written by the foreground session. So *propose*, for the user to approve:
- any GitHub issue or backlog item to update, if the run was tied to one,
- a DEVLOG.md entry (the repo-root chronological record of the work) for the session,
- a LESSONS.md line **iff** a mistake or correction surfaced — only then.

Do not write these until the user says go.
