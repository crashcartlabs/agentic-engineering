# tests - grilling

Scenarios for `/grilling`. These are **design-verified** against the current
`SKILL.md`; no live slash-command run has been driven yet.

## Scenario 1 - Golden: stress-test a plan one decision at a time

**Input:** The user asks "grill this plan" and provides a draft design with several
open choices.

**Expected process:** The skill interviews the user relentlessly about the plan, walking
the design tree decision by decision. It asks exactly one question, waits for feedback,
and includes the recommended answer with that question before moving on.

**Verify:** `SKILL.md` requires walking each branch of the design tree, resolving
dependencies one by one, providing a recommended answer for each question, and asking
one question at a time.

## Scenario 2 - Edge: answerable from the codebase

**Input:** The next design question is "does this service already have a retry helper?"
and the repository can answer it.

**Expected process:** The skill explores the codebase instead of asking the user to
answer a question the code can settle, then resumes the interview using that evidence.

**Verify:** `SKILL.md` says that if a question can be answered by exploring the
codebase, explore the codebase instead.

## Scenario 3 - Weird: tempting checklist dump

**Input:** The plan has many unclear areas, making it tempting to ask a batch of
questions about data model, rollout, validation, and failure modes all at once.

**Expected process:** The skill still asks only one question at a time. It may choose
the highest-dependency question first, but it does not dump a questionnaire because
multiple simultaneous questions are explicitly called bewildering.

**Verify:** `SKILL.md` says to ask questions one at a time, wait for feedback on each,
and not ask multiple questions at once.
