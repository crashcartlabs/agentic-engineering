# The great-skills lens

The vocabulary for reviewing a skill, distilled as a checklist. A skill exists to
wrangle **predictability** out of a stochastic model — the agent taking the same
*process* every run (not the same output; a brainstorming skill should predictably
diverge). Every term below is a lever on predictability. Read a skill against this
lens: for each line, name which lever it pulls, and cut the ones that pull nothing.

*Credit: this vocabulary is adapted from Matt Pocock's `writing-great-skills` skill
and its GLOSSARY (github.com/mattpocock/skills). The terms are his; the checklist
framing is ours.*

## Contents

- [Predictability](#predictability) — the root virtue
- [Invocation](#invocation) — how the skill is reached
- [Information hierarchy](#information-hierarchy) — how content is arranged
- [Steering](#steering) — how runtime behaviour is shaped
- [Pruning](#pruning) — how it is kept lean
- [The five failure modes](#the-five-failure-modes) — what to diagnose

## Predictability

The degree to which the skill makes the agent behave the same *way* every run — same
process, not same tokens. The root virtue; cost and maintainability are symptoms of
it, not rivals. When a lever below seems to conflict with another, the one that
serves predictability wins.

## Invocation

How the skill is reached, and the two costs you pay for the choice. You cannot escape
both — you choose which to spend.

- **Model-invoked** — the provider exposes the canonical `description`, so the agent
  can select the skill on its own. This pays **context load** because metadata remains
  available to the model. Pick this only when the agent must reach the skill
  autonomously, or another workflow must route to it.
- **Explicit-only** — a provider adapter keeps the skill out of implicit selection and
  requires the human to name it using that harness's invocation syntax. This spends
  **cognitive load** because the human becomes the index that must remember it exists.
  In this repository, `toolbelt.json` is the neutral policy source and
  `agents/openai.yaml` carries the Codex policy.
- **Router skill** — when user-invoked skills multiply past what the human can
  remember, one skill that names the others and when to reach for each cures that
  piled-up cognitive load.

Review check: is this skill model-invoked for a real reason, or is it paying context
load on every turn for a trigger nobody needs?

## Information hierarchy

A skill's content ranked by how immediately the agent needs it — a single ladder:

1. **In-skill step** — an ordered action in `SKILL.md`. The primary tier: what the
   agent does, in order. Each step ends on a **completion criterion** (see Steering).
2. **In-skill reference** — a definition, rule, or fact consulted on demand. Often a
   legitimately flat peer-set (every rule of a review on one rung) — fine, not a smell.
3. **External reference** — reference pushed into a separate file, reached by a
   **context pointer**, loaded only when the pointer fires.

**Progressive disclosure** is the move down the ladder — out of `SKILL.md` into a
linked file — so the top stays legible. The test is **branching**: inline what every
run needs; push behind a pointer what only some runs reach. A **context pointer**'s
*wording*, not its target, decides when and how reliably the agent reaches the
material — a must-have file behind a weak pointer is a variance bug; fix the wording
before you inline.

**Co-location** decides what sits *beside* a piece once the ladder has placed it:
keep a concept's definition, rules, and caveats under one heading, so reading one
part brings its neighbours. A skill should read like documentation written for the
agent.

Review check: could a reader act on the top of `SKILL.md` without scrolling? Is
anything inline that only one branch needs?

## Steering

The levers that shape runtime behaviour.

- **Leading word** — a compact concept already in the model's pretraining that the
  agent thinks *with* while running the skill (*lesson*, *fog of war*, *tracer
  bullets*, *tight loop*). Repeated as a token — never re-explained as a sentence —
  it accumulates a distributed definition and anchors a region of behaviour in the
  fewest tokens. It serves predictability twice: in the body it anchors *execution*;
  in the description it anchors *invocation* (word the description with the words you
  actually use when you want the skill). Reach for an existing word before coining
  one — a made-up word recruits no priors and you pay its definition in tokens.
- **Completion criterion** — the condition that tells the agent a unit of work is
  done. Two properties make it a lever: **clarity** (can the agent tell done from
  not-done?) resists premature completion; **demand** (how much it requires) sets how
  much **legwork** the agent does. "Every modified model accounted for" forces
  thorough work where "produce a change list" does not. The strongest criteria are
  both checkable *and* exhaustive.
- **Legwork** — the work an agent does behind the scenes within a step: reading
  files, exploring, digging up what it needs rather than offloading to the user.
  Raised by a demanding completion criterion or a leading word (*relentless*,
  *comprehensive*); goes thin when the demand is missing.

Review check: does every step end on a bar the agent can actually check? Is any bar
vague enough to let the agent declare done and move on?

## Pruning

Keeping the skill lean — each remedy paired with the failure it cures.

- **Single source of truth** — each meaning lives in exactly one authoritative place,
  so changing behaviour is a one-place edit. Its violation is *duplication*.
- **Relevance** — does the line still bear on what the skill does? A line loses it by
  never bearing on the task, or by going stale.
- **The no-op test** — run it on every *sentence* in isolation: does this change
  behaviour versus the model's default? If not, delete the whole sentence — don't
  trim words from it. Be aggressive; most prose that fails should go, not be
  rewritten. *Be thorough* is a no-op when the agent is already thorough-ish; the fix
  is a stronger leading word (*relentless*), not more words.

## The five failure modes

Use these to diagnose a skill that misbehaves:

- **Premature completion** — ending a step before it's genuinely done, attention
  slipping to *being done*. A between-steps failure. Defence in order: sharpen the
  completion criterion first (cheap, local); only if it is irreducibly fuzzy *and*
  you observe the rush, hide the later steps by splitting across a real context
  boundary (a user-invoked hand-off or a subagent — an inline call clears nothing).
- **Duplication** — the same meaning in more than one place. Costs maintenance and
  tokens, and inflates the meaning's rank on the ladder past its real one.
- **Sediment** — stale layers that settle because adding feels safe and removing
  feels risky. The default fate of any skill without a pruning discipline.
- **Sprawl** — simply too long, even when every line is live and unique. The cure is
  the ladder: disclose reference behind pointers, split by branch or sequence.
- **No-op** — a line the model already obeys by default, so you pay load to say
  nothing. Also the verdict on a leading word too weak to beat the default.
