# tests - domain-modeling

Scenarios for `/domain-modeling`. These are **design-verified** against the current
`SKILL.md`, `references/CONTEXT-FORMAT.md`, and `references/ADR-FORMAT.md`; no live
slash-command run has been driven yet.

## Scenario 1 - Golden: resolve a first domain term

**Input:** In a repo with no `CONTEXT.md`, the user is designing an ordering flow and
settles that an "Order" is a customer's requested purchase before fulfillment begins.

**Expected process:** The skill creates a root `CONTEXT.md` lazily only after the term
is resolved, records the term using the context format, and keeps the definition to
domain language only. Implementation details such as table names, DTOs, or API routes
are left out.

**Verify:** `SKILL.md` says to create `CONTEXT.md` only when the first term is resolved,
to update it inline, and to use `references/CONTEXT-FORMAT.md`; that reference requires
tight term definitions and excludes general programming or implementation details.

## Scenario 2 - Edge: existing glossary conflicts with the conversation

**Input:** `CONTEXT.md` defines "Cancellation" as voiding an entire order, but the user
starts using "cancellation" for removing one line item from an order.

**Expected process:** The skill stops and challenges the conflict immediately, asking
which meaning is canonical instead of silently adding a second inconsistent term. Once
resolved, it updates the glossary inline with the chosen language and avoided synonyms.

**Verify:** `SKILL.md` requires challenging terms that conflict with `CONTEXT.md`,
sharpening overloaded language, and updating `CONTEXT.md` as terms crystallize.

## Scenario 3 - Weird: code contradicts the proposed model

**Input:** The user says partial cancellation is supported, but code inspection shows
the current implementation only cancels entire orders.

**Expected process:** The skill checks the claim against the code, surfaces the
contradiction, and asks whether the model or the code is authoritative before recording
anything.

**Verify:** `SKILL.md` includes a `Cross-reference with code` section that requires
checking stated behavior against the code and surfacing contradictions.

## Scenario 4 - Boundary: decision is not ADR-worthy

**Input:** During the discussion, the team chooses a reversible variable name or a
minor local helper shape.

**Expected process:** No ADR is created. The skill only offers an ADR when the decision
is hard to reverse, surprising without context, and the result of a real trade-off.

**Verify:** `SKILL.md` and `references/ADR-FORMAT.md` both require all three ADR
criteria and say to create `docs/adr/` lazily only when a real ADR is needed.
