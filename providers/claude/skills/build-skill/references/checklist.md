# Pre-ship checklist

The mechanical gate a skill must clear before it ships — a self-contained stand-in
for `check-skill`. If you have skill-kit installed, run `check-skill <skill-dir>`
instead and treat this as the manual fallback. Walk every item; **hard gates block
shipping**, strong recommendations are prompts to look, not verdicts.

*Credit: distilled from skill-kit's 21-check harness (`check-skill`). Run the real
linter when it's available — it catches leaked secrets and portability bugs a manual
pass will miss.*

## Contents

- [Hard gates](#hard-gates-must-pass) — must pass, no exceptions
- [Strong recommendations](#strong-recommendations-look-before-shipping) — look before shipping

## Hard gates (must pass)

- **Frontmatter parses** — valid YAML between `---` markers.
- **`name`** present, ≤64 chars, matches `^[a-z0-9-]+$`, equals the folder name, and
  contains no "anthropic"/"claude"/XML.
- **`description`** present, ≤1024 chars, no angle brackets / XML.
- **`description` is third person** — no "I can…", "You can…". Canonical descriptions
  remain valid across providers even when an adapter makes the skill explicit-only.
- **No Windows backslash paths** in `SKILL.md` or reference `.md` files — e.g. `C:\…` or `\\host\share`. <!-- allowlist windows-path -->
  Scripts may carry them; a genuinely Windows-documenting line can be marked exempt.
- **No leaked secrets** anywhere in the skill tree (`sk-…`, `ghp_…`, `AKIA…`). A
  deliberate example key must be explicitly allowlisted.
- **`tests.md` present** with a `Last verified:` date and ≥3 real scenarios — for any
  skill outside a `staging/` area. (Structural headings like Contents/Notes don't
  count as scenarios.)

## Strong recommendations (look before shipping)

- **`name` uses gerund form** where natural (`processing-pdfs`, `improving-skills`).
- **`description` carries genuine trigger phrasing** — an explicit "Use when…" /
  "when the user…" clause, not a bare mid-sentence "when".
- **≥2 concrete trigger conditions** in that clause, generalized to intent categories
  (see `writing-descriptions.md`).
- **`description` ≥40 chars** of real substance.
- **`SKILL.md` body ≤500 lines** — split detail into supporting files past that.
- **Reference `.md` files ≤200 lines each**; any over 100 lines opens with a
  `## Contents` table of contents.
- **Reference docs live in `references/`**, scripts in `scripts/`, templates/assets in
  `assets/` — nothing loose beside `SKILL.md` except governance files (`SKILL.md`,
  `tests.md`, `test-prompts.md`, `goal.md`, `README.md`).
- **Every supporting file is linked from `SKILL.md`** (no orphans the agent never
  loads) and references stay one level deep (no `a → b → c` chains).
- **No security smells** left unexamined — piped shell installers, recursive
  force-deletes, base64-decoded payloads, unexpected outbound POSTs. Each is a human
  judgement call, not an automatic block.

## Beyond the static gate

Passing this checklist proves the skill is *well-formed* — never that it's worth
invoking. Two deeper questions the mechanical gate can't answer:

- **Does it trigger?** Run the real scenarios and near-misses; confirm it fires when
  it should and declines the near-misses (see `writing-descriptions.md`).
- **Does it beat just asking the model?** For a generative/judgment skill (idea
  generation, review, research, summarization), run a blind head-to-head against the
  cold model before promoting. A skill can be perfectly structured and still lose,
  its scaffolding burying its rigor. Record the verdict; don't skip it silently.
