# Writing the description

The `description:` is the **primary trigger mechanism** — the only thing (alongside
the name) the agent sees when deciding whether to consult a model-invoked skill. The
body loads *after* that decision, so a perfect body behind a weak description never
runs. Getting it right is its own craft.

Canonical descriptions must remain useful across harnesses. Even when one provider's
adapter marks a skill explicit-only, another provider may still display or reason over
the description. Apply the rules below to every skill and keep invocation policy out of
canonical frontmatter.

## What a description must carry

- **What it does AND when to use it**, in one place. All the "when to use" lives here,
  never only in the body.
- **Imperative, third person.** "Reviews a diff and… Use when the user asks to…" —
  not "I can review" or "You can use this to." First/second person fails the harness.
- **User intent, not implementation.** Describe what the user is trying to achieve,
  not the mechanics of how the skill works.

## Enumerate ≥2 concrete conditions — then generalize, don't list

Name at least two concrete trigger conditions: *"Use when the user asks to review a
PR, audit a diff, or check changes before merging"* beats *"Use when you have code to
look at."* But generalize to intent **categories** — do not enumerate an
ever-expanding list of exact queries. The description is injected into *every* prompt
and competes with every other skill; a query-by-query list bloats it and overfits.
When triggering misses, widen the *category* of intent, not the count of examples.

## Pushy ≠ broad (the one tension to get right)

Two pieces of guidance look like they conflict; they don't, because they act on
different axes:

- **Be a little pushy** (tone) to combat *under*-triggering. State plainly when the
  skill *should* fire — including phrasings where the user never names the skill or
  the file type.
- **Stay sharp** (boundary) to combat *over*-triggering. Keep the scope's edges
  concrete so the skill declines near-misses.

A description can and should be both. The failure modes are timid-and-narrow ("may be
useful if you happen to have a PDF") and pushy-but-vague ("use this whenever you have
anything to work with"). Aim for **pushy and sharp**.

| | Example |
|---|---|
| ✗ timid + narrow | `Builds a dashboard for internal data.` |
| ✗ pushy + vague | `Use this whenever the user has any data or numbers to deal with.` |
| ✓ pushy + sharp | `Builds a fast dashboard from internal metrics. Use when the user asks to visualize company data, build a metrics dashboard, or chart internal numbers — even if they don't say "dashboard".` |

## Leading words in the description

Word the description with the **leading words you actually use** when you want the
skill. When the same word lives in your prompts, your docs, and your codebase, the
agent links that shared language to the skill and fires it more reliably. This is the
invocation half of a leading word's job (see `great-skills.md`).

## Prove sharpness with near-misses

To confirm a description is sharp, find its **near-misses** — queries that share
keywords but need something else — and confirm the description declines them. For a
PDF skill, *"extract the fields from this API JSON response"* is a valuable negative
(shares "extract", not the PDF context); *"write a fibonacci function"* is a useless
negative because nothing about it tempts the skill. Capture the good near-misses in
`test-prompts.md` if you plan to autoresearch-improve the skill.

## Constraints

- ≤ 1024 chars (hard limit; over-limit is truncated). Aim for ~100–200 words.
- ≥ 40 chars of real substance — a one-liner is too vague to drive discovery.
- No angle brackets / XML in the description.
