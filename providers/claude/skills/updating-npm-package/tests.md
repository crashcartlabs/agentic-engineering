# tests — updating-npm-package

Status: partially-live (one S2 sub-clause design-level — see below)
Last traced: 2026-07-04 (live dogfood, scratch repo, real registry)

All four scenarios ran live on 2026-07-04 against the real npm registry in a scratch
repo (record at the bottom of this file). The versions in the scenario texts below
remain illustrative; the live run's actual versions are in the record.

## Scenario 1 — Golden: semver-safe minor applied and validated

**Input:** A repo whose lockfile pins `zod@3.22.4` under a `^3.22.0` range;
`npm view zod version` reports a newer `3.23.8` (a **minor** jump); the CHANGELOG for
the span lists only additive API. The gate is `npm run typecheck` then `npm test`.

**Expected output:** Classified minor → semver-safe path. `npm install "zod@3.23.8"`
scoped to the one package; `package-lock.json` updates alongside `package.json` and no
other dependency moves; the gate runs green; reported as **applied**, `3.22.4 →
3.23.8`, citing the changelog span read in Step 3.

**Verify:** `package.json` shows the new range, `git diff package-lock.json` touches
only zod's entries, both gate commands exit 0, and the report says "applied" in words.

## Scenario 2 — Edge: major reported, never applied

**Input:** The same repo, but `npm view` shows the target is a **major** jump
(`4.0.0` from `3.x`); the release ships a migration guide naming removed and renamed
APIs.

**Expected output:** **Nothing is installed.** A validation report is produced: the
jump and why it's gated (major), the breaking changes from the migration guide, the
in-repo call sites found by grepping the affected APIs, a risk/effort read, a link to
the migration guide, and an explicit *reported for human decision, not applied*
verdict.

**Verify:** `git status --porcelain` shows no change to `package.json` or the
lockfile; the report enumerates breaking changes and concrete call sites; the verdict
line marks it not applied.

**Status: split (per build-skill Step 6).** The major-detection → not-applied path and the
breaking-changes enumeration are **live-verified** (2026-07-04 run below). The *concrete
call sites* half of the Verify clause is **design-verified only** — the live run found zero
affected call sites (synthetic consumer), so the non-empty call-site enumeration was never
demonstrated. It becomes live only when a fixture is run where the major genuinely hits call
sites.

## Scenario 3 — Weird: an applied minor breaks the gate → revert + report

**Input:** A minor bump whose changelog read as additive, but installing it turns the
gate red — the publisher shipped a behavior change under a minor (semver violated).

**Expected output:** The failure is traced to the bump, not patched over. `git restore
package.json package-lock.json`, then `npm install` resyncs `node_modules`; the gate
re-runs and returns to green; the bump is reported as **reverted, not applied** and
reclassified as needing the Step 5 validation-report treatment. No test or source file
was edited to force the gate green.

**Verify:** `git status` is clean (tree back to pre-bump), the gate exits 0 on the
restored tree, and the report names the exact gate failure and marks the update
reverted.

## Scenario 4 — Boundary: the stdlib already covers the dep

**Input:** The "update" request targets `uuid`, but the project runs on a Node
version where `crypto.randomUUID()` covers its only call site.

**Expected output:** Per §VIII, Step 1 surfaces that the dep can be **removed** rather
than updated — naming the stdlib replacement and the single call site — and does not
proceed to bump it. Nothing is installed or updated; removal is framed as the
recommended action for a human decision.

**Verify:** no install ran; the report names the stdlib replacement and the call site,
and recommends removal over an update.

## Dogfood record (2026-07-04, live — scratch repo, macOS, real npm registry)

Run by the model driving the skill through the active harness (invocation-policy check:
model-invocable as intended). Scratch repo: `zod@3.22.4` (range `^3.22.0`), `ms@2.0.0`,
`uuid@9.0.1`; gate = `npm run typecheck` (`tsc --noEmit`) + `npm test`; baseline green.
Residual: the scratch consumer is synthetic — the packages, versions, registry lookups,
changelogs, lockfile mechanics, and gate were all real, but the call sites were
constructed; a rerun against a real consuming repo's organic dependency drift remains open.

- **Scenario 2 — PASS** (run first: "update zod"). Registry: latest `4.4.3` from installed
  `3.22.4` → **major** → Step 5. Validation report produced from the real migration guide
  (zod.dev/v4/changelog): error-customization unification, top-level string formats,
  `z.record` arity, `.default()` semantics, removed object/ZodError methods. Affected-API
  grep found **zero** in-repo call sites needing edits. `git status --porcelain` empty —
  nothing installed; verdict line stated. **Sub-path caveat:** the Verify clause's
  "enumerates concrete call sites" was *vacuously* satisfied — zero affected sites existed in
  the synthetic consumer, so the not-applied verdict and breaking-changes enumeration are live
  but the *non-empty* call-site enumeration is design-level (never demonstrated with a real
  site). Closing it needs a fixture where the major genuinely hits call sites.
- **Scenario 1 — PASS** ("bump zod within v3"). Target `3.25.76`, classified minor;
  changelog span read (3.23.0 additive with two non-applicable caveats, 3.24.0 additive,
  3.25.x adds `zod/v4` subpath leaving classic import untouched). Applied scoped
  (`npm install "zod@3.25.76"`); lockfile diff touched only zod entries; gate green;
  reported **applied, 3.22.4 → 3.25.76**.
- **Scenario 3 — PASS**, on a *real* semver-in-spirit violation, not a staged one:
  `ms 2.0.0 → 2.1.3`. The 2.1.x changelog reads purely additive ("add week support"), but
  that very addition flips `ms('1w')` from `undefined` to a number, breaking the repo's
  contract that unsupported delay units are rejected — the gate went red on exactly that
  assert. Step 6 ran faithfully: failure traced to the bump, `git restore package.json
  package-lock.json` + `npm install` resync, baseline confirmed (`ms@2.0.0`, `'1w'` →
  `undefined`), gate green, reported **reverted, not applied**, reclassified for Step 5
  treatment. The test was never edited.
- **Scenario 4 — PASS** ("update uuid"). Step 1's §VIII question stopped the bump: single
  call site (`src/id.js`, `uuidv4()`), runtime Node 26 where `crypto.randomUUID()` covers
  it. Recommended **removal over update**, framed for a human decision; nothing installed,
  tree clean.
