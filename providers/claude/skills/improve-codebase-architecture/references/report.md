# HTML Report Format

The architectural review is rendered as a single **fully self-contained** HTML file in the OS temp directory. No CDN scripts, no external stylesheets, no fonts, no remote images — every byte the page needs is in the file (inline `<style>`, inline SVG). This keeps the report portable and compatible with strict CSP rendering. All diagrams are hand-built from styled `<div>`s and inline SVG; there is no Mermaid and no Tailwind.

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Architecture review — {{repo name}}</title>
    <style>
      :root {
        --ink: #0f172a;      /* slate-900 */
        --paper: #fafaf9;    /* stone-50 */
        --line: #e2e8f0;     /* slate-200 */
        --muted: #64748b;    /* slate-500 */
        --accent: #059669;   /* emerald-600 */
        --leak: #dc2626;     /* red-600 */
        --warn-bg: #fef3c7;  /* amber-100 */
        --warn-ink: #92400e; /* amber-800 */
      }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--paper); color: var(--ink);
             font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
      main { max-width: 64rem; margin: 0 auto; padding: 3rem 1.5rem; }
      h1, h2, h3 { font-family: Georgia, "Times New Roman", serif; line-height: 1.2; }
      article { border: 1px solid var(--line); border-radius: 0.5rem;
                background: #fff; padding: 1.5rem; margin: 2.5rem 0; }
      .files { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
               font-size: 0.85rem; color: var(--muted); }
      .badge { display: inline-block; padding: 0.1rem 0.6rem; border-radius: 999px;
               font-size: 0.75rem; font-weight: 600; }
      .badge-strong      { background: #d1fae5; color: #065f46; } /* emerald */
      .badge-explore     { background: var(--warn-bg); color: var(--warn-ink); }
      .badge-speculative { background: #e2e8f0; color: #334155; } /* slate */
      .badge-dep { background: #eef2ff; color: #3730a3; }         /* indigo */
      .adr { background: var(--warn-bg); color: var(--warn-ink);
             border-radius: 0.375rem; padding: 0.5rem 0.75rem; font-size: 0.9rem; }
      .beforeafter { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
      @media (max-width: 40rem) { .beforeafter { grid-template-columns: 1fr; } }
      .diagram { border: 1px solid var(--line); border-radius: 0.5rem;
                 background: #fff; padding: 1rem; min-height: 18rem;
                 position: relative; overflow-x: auto; }
      .module { border: 2px solid var(--ink); border-radius: 0.25rem;
                padding: 0.5rem 0.75rem; text-align: center; }
      .module-label { font-size: 0.7rem; text-transform: uppercase;
                      letter-spacing: 0.08em; }
      .module-deep { background: linear-gradient(135deg, #0f172a, #1e293b);
                     color: #f8fafc; border-width: 4px; }
      .module-shallow { border-width: 1px; color: var(--muted); }
      .seam { stroke: var(--ink); stroke-dasharray: 4 4; }
      .leak { stroke: var(--leak); stroke-width: 2; }
      .faded { opacity: 0.35; }
    </style>
  </head>
  <body>
    <main>
      <header>...</header>
      <section id="candidates">...</section>
      <section id="top-recommendation">...</section>
    </main>
  </body>
</html>
```

## Header

Repo name, date, and a compact legend: solid box = module, dashed line = seam, red arrow = leakage, thick dark box = deep module. No introduction paragraph — straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse, plain, and uses the glossary terms (from the `codebase-design` skill) without ceremony.

Each candidate is one `<article>`:

- **Title** — short, names the deepening (e.g. "Collapse the Order intake pipeline").
- **Badge row** — recommendation strength (`Strong` = emerald, `Worth exploring` = amber, `Speculative` = slate), plus a tag for the dependency category (`in-process`, `local-substitutable`, `ports & adapters`, `mock`).
- **Files** — monospaced list (`class="files"`).
- **Before / After diagram** — the centrepiece. Two columns, side by side (`class="beforeafter"`). See patterns below.
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each. e.g. "Tests hit one interface", "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (if applicable) — one line in an amber-tinted box (`class="adr"`).

No paragraphs of explanation. If the diagram needs a paragraph to be understood, redraw the diagram.

## Diagram patterns

Everything is hand-built: modules as bordered `<div>`s, arrows and seams as inline SVG `<line>` / `<path>` elements (positioned absolutely over a relative container, or as a standalone `<svg>` with `<text>` labels). Pick the pattern that fits the candidate. Mix them. Don't make every diagram look the same — variety is part of the point.

### Boxes-and-arrows (the workhorse for dependencies / call flow)

Use when the point is "X calls Y calls Z, and look at the mess." Modules as `<div class="module">`s laid out with flex/grid; arrows as inline SVG overlaid on the container. Colour leakage edges red (`class="leak"`), render the deepened module as one thick-bordered dark box (`class="module-deep"`) with greyed-out internals (`class="faded"`). For "before: 6 round-trips; after: 1", draw a simple hand-built sequence: vertical lifelines as SVG lines, calls as horizontal arrows with small text labels.

### Cross-section (good for layered shallowness)

Stack horizontal bands (fixed-height `<div>`s with a left border accent) to show layers a call passes through. Before: 6 thin layers each doing nothing. After: 1 thick band labelled with the consolidated responsibility.

### Mass diagram (good for "interface as wide as implementation")

Two rectangles per module — one for interface surface area, one for implementation. Before: interface rectangle is nearly as tall as the implementation rectangle (shallow). After: interface rectangle is short, implementation rectangle is tall (deep).

### Call-graph collapse

Before: a tree of function calls rendered as nested boxes. After: the same tree collapsed into one box, with the now-internal calls shown faded inside it.

## Style guidance

- Lean editorial, not corporate-dashboard. Generous whitespace. Serif optional for headings (the scaffold's Georgia stack works well against stone/slate).
- Colour sparingly: one accent (emerald or indigo) plus red for leakage and amber for warnings.
- Keep diagrams ~320px tall so before/after sits comfortably side by side without scrolling.
- Use small uppercase letter-spaced labels (`class="module-label"`) for module names inside diagrams — they should read as schematic, not as UI.
- **No scripts at all.** The report is completely static — no CDN imports, no fetches, no interactivity. Wide diagrams scroll inside their own `overflow-x: auto` container; the page body never scrolls horizontally.
- **HTML-escape every repo-derived string.** Filenames, module names, `CONTEXT.md` excerpts, and ADR text are attacker-controllable repo content, not your own prose — escape `&`, `<`, `>`, `"`, and `'` in each one before it lands in a tag body or attribute (e.g. inside `.files`, a diagram label, or an `.adr` callout). The "no scripts" rule above only covers `<script>` tags you'd add on purpose; it does not cover repo content becoming executable markup on its own (e.g. a filename or doc excerpt containing an `onerror=` payload), so escaping is a separate, mandatory step for every such string.

## Top recommendation section

One larger card. Candidate name, one sentence on why, anchor link to its card. That's it.

## Tone

Plain English, concise — but the architectural nouns and verbs come straight from the `codebase-design` skill. Concision is not an excuse to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API, signature (for interface) · boundary (for seam) · layer, wrapper (for module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: *"locality: bugs concentrate in one module"*, *"leverage: one interface, N call sites"*, *"interface shrinks; implementation absorbs the wrappers"*. Don't write *"easier to maintain"* or *"cleaner code"* — those terms aren't in the glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. If a term isn't in the `codebase-design` glossary, reach for one that is before inventing a new one.
