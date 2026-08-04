# tests — improve-codebase-architecture

Scenarios for `/improve-codebase-architecture`. These are **design-verified** against
the current `SKILL.md` and `references/report.md`; no full scan was driven in this
session. The first real run with the maintainer should replace or extend these with live evidence.

Last verified: 2026-07-08

## Scenario 1 — Golden: full scan produces a report, then a grilled candidate

**Input:** `/improve-codebase-architecture` in a repo with a `CONTEXT.md` glossary,
a few ADRs under `docs/adr/`, and a cluster of shallow pass-through modules.

**Expected process:** The skill loads the `/codebase-design` vocabulary first, reads
`CONTEXT.md` and the ADRs, then explores via a read-only Explore subagent rather than
reading the whole codebase into the main thread. It writes a self-contained HTML report
to `<tmpdir>/architecture-review-<timestamp>.html` (never into the repo), opens it with
the platform opener, and reports the absolute path. Each candidate card has files,
problem, solution, wins, a before/after diagram, and a strength badge; the report ends
with a Top recommendation. It proposes no interfaces yet — it stops and asks "Which of
these would you like to explore?" When the user picks one, it runs `/grilling`, and
uses `/domain-modeling` to update `CONTEXT.md` as decisions crystallize.

**Verify:** `SKILL.md` orders the process explore → report → ask → grill, forbids
proposing interfaces before the user picks, and routes the vocabulary through
`/codebase-design`; `references/report.md` defines the card fields and badges.

## Scenario 2 — Edge: report must be CSP-safe and self-contained

**Input:** Step 2 renders the report on a machine where external network requests
from rendered HTML are blocked (strict CSP, or offline).

**Expected process:** The report still renders fully: it is a single HTML file with
inline CSS only, hand-built div/SVG diagrams, and **no** CDN scripts (no Tailwind, no
Mermaid), external stylesheets, fonts, or remote images. Wide diagrams scroll inside
their own `overflow-x: auto` container.

**Verify:** `references/report.md` scaffold contains no external URLs and no `<script>`
tags, and its style guidance says "No scripts at all"; `SKILL.md` step 2 requires
"inline CSS only, no CDN scripts, no external requests of any kind."

## Scenario 3 — Weird: candidate contradicts an ADR / user rejects with a reason

**Input:** The strongest deepening candidate contradicts `docs/adr/0007-*.md`; later,
the user rejects another candidate because a regulatory constraint forbids merging the
two modules.

**Expected process:** The ADR-contradicting candidate is surfaced only because the
friction is real enough to warrant revisiting the ADR, and its card carries a clear
warning callout naming the ADR; theoretical refactors an ADR forbids are not listed.
For the rejection, the skill offers to record an ADR — framed as preventing future
reviews from re-suggesting it — because the reason is load-bearing; it would not offer
one for an ephemeral "not worth it right now."

**Verify:** `SKILL.md` step 2 defines the ADR-conflict rule and step 3 defines the
load-bearing-reason test for offering an ADR.

## Scenario 4 — Trigger discipline: explicit invocation only

**Input:** Mid-task, the model notices general architectural mess while fixing a bug.

**Expected process:** The skill does not auto-start — it is a heavyweight periodic scan
gated behind explicit invocation. At most, the model may suggest running it.

**Verify:** `toolbelt.json` and provider metadata make the skill explicit-only and the description says
explicit-trigger only, and distinguishes it from `/code-audit` and `/simplify`.
