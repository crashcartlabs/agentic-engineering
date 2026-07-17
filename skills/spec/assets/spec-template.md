# <Spec title>

<!--
Fill every section. If a section does not apply, write "N/A - <one-line reason>".
Delete instructional comments before approval.
-->

| Field | Value |
| --- | --- |
| Status | draft |
| Source | <rough idea / conversation / wayfinder issue / GitHub issue> |
| Owner | <human owner or "TBD"> |
| Created | <YYYY-MM-DD> |
| Related map / issue | <link or N/A> |
| Plan | not started |

## Summary

<One paragraph describing the product behavior this spec defines.>

## Problem

<The problem from the user's perspective.>

## Users / Personas

- <User/persona> - <goal or pain>

## Goals

- <Product outcome or capability>

## Non-goals

- <Explicitly out of scope behavior>

## User Stories

1. As a <user>, I want <capability>, so that <outcome>.

## Acceptance Behavior

Write checkable behavior in plain language or Gherkin. Prefer concrete examples over
abstract labels.

```gherkin
Scenario: <happy path>
  Given <initial context>
  When <user action>
  Then <observable result>
```

## Edge Cases and Failure States

- <Condition> - <expected behavior>

## Business / Domain Rules

- <Rule the implementation must preserve>

## UX / API Expectations

- <Visible behavior, copy, interaction, response shape, or compatibility expectation>

## Data, Privacy, Security

- <Product-level expectation, constraint, or N/A with reason>

## Success Metrics

- <How the product outcome will be judged after release>

## Research / Provenance

Use `[VERIFIED: source]`, `[CITED: url]`, or `[ASSUMED]` for claims that shape the
product behavior.

- <Claim> - <tag>

## Open Questions

- <Question> - <why it matters / whether it blocks planning>

## Plan Handoff Notes

<Facts `/plan` should know, without prescribing implementation details.>

## Approval

- [ ] Product behavior is clear
- [ ] Acceptance behavior is checkable
- [ ] Non-goals are explicit
- [ ] Product-changing assumptions are accepted or resolved
- [ ] Ready for `/plan`
