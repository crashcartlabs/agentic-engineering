# tests — authoring-skills

A router's job is trigger accuracy: fire on *authoring* a skill, decline everything
else. These three are design-verified against the current `description` and body; a
live trigger-accuracy pass should confirm them once the skill is in use.

## Scenario 1 — Positive: new skill from a repeated task

**Input:** "I keep writing the same prompt to summarize PRs — can we make that a skill?"

**Expected:** the router fires, names the do-the-work-first principle, and points the
user to `/build-skill` (it cannot fire it for them).

**Verify:** "Which workflow" → "New skill" branch names `/build-skill [name]`.

## Scenario 2 — Positive: sharpen an existing skill

**Input:** "My code-audit skill over-triggers — help me fix it."

**Expected:** the router fires and points the user to `/build-skill [name]`, which is
the only live destination for skill authoring and improvement.

**Verify:** the body routes every authoring or improvement request to `/build-skill [name]`.

## Scenario 3 — Negative near-miss: using, not authoring

**Input:** "Run the code-audit skill on my diff." / "What skills do I have?"

**Expected:** the router does **not** fire — this is using/listing an existing skill,
not authoring one.

**Verify:** the "Not this skill" clause and the description's closing sentence exclude
merely using, listing, or invoking a skill.
