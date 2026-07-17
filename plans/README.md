# plans/

Implementation plans produced by the `/plan` skill live here.

## Naming convention

```
<YYYY-MM-DD>-<kebab-topic>.md
```

Example: `2026-06-29-add-plan-skill.md`

- **Date first** — plans sort chronologically; recency is visible at a glance.
- **`<kebab-topic>`** — lowercase kebab-case, 3–6 words, naming the **outcome, not the activity** (`add-plan-skill`, not `working-on-planning`).

Status (`draft` → `approved` → `in-progress` → `done`) lives **inside** each plan's
metadata block, not in the filename — so the name never changes as the plan progresses.

Every new plan links its governing `specs/` artifact in the `Spec` metadata row. Drafts
may use `Branch: tbd`; approval writes the deterministic `plan/<topic-slug>` branch at
the same time as `Status: approved`. Older plans whose real execution branch predated
that contract use an explicit `legacy:` Branch value and retain their historical truth.
