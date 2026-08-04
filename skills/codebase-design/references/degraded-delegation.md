# Degraded delegation — when the harness cannot fan out

A skill that hard-requires delegation (fan-out **or** single-subagent) must still work
when the active harness cannot do it the way the skill describes. This file is the
fallback contract: it is intentionally byte-identical in every skill that carries it —
the repository gate enforces that, so edit every copy together or none.

## What "delegation" means per harness

The skills in this repo delegate through the active harness's own mechanism — never a
tool the harness does not have. What each provider offers today:

| Harness | Delegation mechanism | Concurrency |
|---|---|---|
| Claude Code | markdown agents (`.claude-plugin/` skills, `.md` files with frontmatter) | parallel spawn supported |
| Codex | generated agent TOML (`providers/codex/agents/*.toml`) | parallel spawn supported |
| Pi | the `subagent` extension (`providers/pi/extensions/subagent.ts`) — runs one provider-neutral agent in an isolated process | **one delegated task at a time** |
| Hermes | `delegate_task` | parallel spawn supported |

A skill that says "spawn N subagents concurrently" describes the **intent** — N
independent, fresh-context passes over the same pinned scope — not a specific API. If
the harness's mechanism differs from the literal instruction, degrade to the recipe
below, never to a solo read-through.

## Sequential fresh-context fallback

When the harness can run only one delegated task at a time (or parallel spawn is
unavailable), run the passes **one after another, each in a fresh context**:

1. **Same pinned scope, one pass at a time.** Each pass receives exactly the scope the
   skill pinned (diff, worktree paths, lens brief) and nothing carried over from the
   previous pass's context. Do not accumulate findings in a growing conversation — the
   point of the fan-out is independent lenses, and a shared context re-couples them.
2. **Same evidence contract per pass.** Each pass reports in the skill's contract
   shape; merge and dedupe the results exactly as you would after a parallel fan-out.
3. **Order does not change the outcome.** Passes are independent; run them in any
   order that fits the harness's queue. If the skill's sections have a defined order
   (e.g. recon before hunting), preserve it.
4. **Budget the same total effort.** Sequential passes cost the harness wall-clock
   time, not diligence. Do not skip lenses to "save time" — that is the solo
   read-through economy again.

## No delegation at all → stop

If the harness has **no** delegation mechanism (no subagent tool, no extension), the
skill **cannot run**: its findings are defined as the output of independent passes, so
a solo read-through is not a degraded mode but a different (and forbidden) behavior.
Stop, surface a clear one-line refusal, and run `agentic doctor` to diagnose the
installation — do not improvise a substitute.

## The hard rule

**Never substitute a solo read-through for delegated passes.** A single context
reading the whole scope misses what independent, fresh-context lenses catch — that is
the entire point of the fan-out. If you catch yourself about to "just read it
yourself," you are about to violate the skill's core contract. Degrade to sequential
fresh-context passes, or stop.
