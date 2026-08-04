---
name: grilling
description: "Stress-test a plan, design, or decision by interviewing the user one question at a time until shared understanding is reached. Use when the user says 'grill me on this', 'stress-test this plan/design', 'interview me about this', 'poke holes in this', or asks to be challenged on an approach before building. Not for writing the plan itself (the `plan` skill), mapping a foggy idea (the `wayfinder` skill), or reviewing finished code (the `code-audit` skill)."
---


# grilling — Interview the user until the design holds

Adapted from Matt Pocock's MIT-licensed skills collection (github.com/mattpocock/skills); full attribution lives in the toolbelt repository's `ATTRIBUTION.md`.

You are the interviewer. The user has a plan, design, or decision they want
stress-tested *before* anything is built. Your job is to find the unexamined
assumptions, unresolved dependencies, and vague terms by asking about them — not to
rewrite the artifact, and not to implement anything.

## How to run the interview

1. **Read first.** Read the plan/design under discussion and the code it touches
   before the first question. If a *fact* can be found by exploring the environment,
   look it up instead of asking — the user's attention is for judgment calls, not
   lookups. The *decisions*, though, are the user's: put each one to them and wait
   for their answer; never decide on their behalf.
2. **One question at a time.** Ask a single question, then wait. Batching questions
   is bewildering and lets weak answers hide behind strong ones.
3. **Recommendation-first.** Every question carries your recommended answer and the
   reason for it, so the user can confirm or redirect rather than start from a blank.
4. **Walk the dependency tree.** Take the design branch by branch, resolving the
   decisions in dependency order — settle what a later choice depends on before
   asking about the later choice.
5. **Challenge vagueness.** When an answer uses an overloaded or undefined term, or
   two answers quietly conflict, stop and resolve it before moving on. For a
   docs-backed run, use the `domain-modeling` skill during the interview to capture ADRs and
   glossary entries as decisions settle.
6. **Keep a visible ledger.** Maintain a short running list of settled decisions and
   still-open questions, and show it as it grows so the user always sees the state
   of the interview.

## Completion

The grilling is done when the user confirms shared understanding — every branch of
the design tree visited, no open question left that would change the build — or the
user ends it. Close by replaying the settled decisions and any accepted risks in
your own words for a final confirmation, then offer the next step **chosen from the
artifact's state** — the `spec` skill for a still-foggy idea, the `plan` skill to write or revise the
plan, or the `execute` skill with `<plan-file>` when the grilled artifact is an already-approved
plan that survived intact — always an offer, never an auto-run.

## Hard rules

- Interview only: no code, no plan-writing, no fixes. Route plan writing or revision to the `plan` skill, and execution of an already-approved plan to the `execute` skill.
- One question per turn, each with a recommended answer.
- Explore the codebase for answerable questions instead of asking them.
