# tests — codebase-design

Verification scenarios for the `codebase-design` skill. Each names the input, the
expected behavior traced against SKILL.md, and how to verify it. This is a vocabulary
and design-reasoning skill, so scenarios verify that the terms are used exactly and
the principles are applied, not that code is produced.

**Status: design-verified (traced, not live-verified).** Scenarios traced against SKILL.md
at port time (2026-07-08); no live dogfood run yet.

Last traced: 2026-07-08

## Scenario 1 — Golden: design a module's interface with the vocabulary

**Input:** "Design an interface for a rate limiter that several services will call.
Right now each service has its own copy-pasted token-bucket logic."

**Expected:** The response uses the glossary exactly — **module**, **interface**,
**seam**, **depth**, **leverage**, **locality** — and never substitutes "component,"
"service," "API," or "boundary." It proposes a small interface (few methods, simple
params), names what the implementation hides, applies the deletion test (deleting the
module would scatter token-bucket logic back across N callers, so it earns its keep),
and states that the interface is the test surface.

**Verify:** No forbidden substitute terms appear where glossary terms apply; the
proposed interface is smaller than the sum of the call sites it replaces; the deletion
test is invoked with the correct verdict.

## Scenario 2 — Edge: refuse a hypothetical seam

**Input:** "Should I put an interface in front of this logger so we can swap it later?"
Only one concrete logger exists and no test needs a stand-in.

**Expected:** The skill applies "one adapter means a hypothetical seam, two adapters
means a real one" and recommends *against* introducing the seam — a single-adapter
seam is just indirection — while naming what would change the answer (a second adapter
with a real justification, typically production + test).

**Verify:** The recommendation is "no seam," cites the one-adapter/two-adapter rule,
and names the condition under which the seam becomes real.

## Scenario 3 — Reference routing: deepening a cluster

**Input:** "These five small modules all touch the orders flow and every change hits
three of them. Two call our internal inventory service over HTTP and one calls Stripe."

**Expected:** The skill recognizes a deepening candidate and consults
[references/DEEPENING.md](references/DEEPENING.md): dependencies are classified
(remote-but-owned → port with HTTP adapter for production and in-memory adapter for
tests; true external → injected port with a mock adapter), and the testing strategy is
replace-don't-layer — old shallow-module unit tests are deleted once interface-level
tests exist, not kept alongside them.

**Verify:** Each dependency lands in the correct category; the recommendation shape
matches DEEPENING.md's port-and-adapters phrasing; the plan deletes superseded shallow
tests rather than layering new ones on top.

## Scenario 4 — Reference routing: design it twice

**Input:** "I'm not sure this is the right interface — explore some alternatives."

**Expected:** The skill follows
[references/DESIGN-IT-TWICE.md](references/DESIGN-IT-TWICE.md): frames the problem
space for the user first (constraints, dependency categories, an illustrative sketch),
spawns 3+ parallel sub-agents each with a radically different design constraint, then
presents the designs sequentially, compares them by depth, locality, and seam
placement, and ends with an opinionated recommendation (or hybrid) rather than a menu.

**Verify:** The problem-space framing precedes the spawn; the sub-agent briefs carry
distinct constraints; the comparison uses the three named axes; a single recommendation
is given.
