---
name: updating-npm-package
description: "Safely move an existing npm dependency to a newer version — check the registry for the latest, read the changelog across the span, auto-apply semver-safe minor/patch bumps and prove them against the repo's gate, and for majors produce a migration validation report for a human instead of applying. Use when asked to update or upgrade a package, bump a dependency, check whether a dep is outdated, or clear an outdated-dependency warning. Not a blind `npm update` or `npm audit fix --force` (majors are reported, never auto-applied), and not for adding a brand-new dependency."
---

# Updating an npm package

Move a dependency forward without moving the blast radius onto the user. The
invariant: a bump lands in the tree only when it is **semver-safe** *and* the
repo's **gate** is green afterward; anything that could break — every **major**,
and any minor/patch whose changelog admits a breaking change — is **reported for a
human decision, never silently applied**. Every dependency is permanent code you
don't control, so the first question is not "which version" but "should
this dep exist at all."

Be explicit at **every** step about whether an update is being **applied** or
**reported for a human** — the user must never have to guess whether the tree
changed.

## Step 1 — Read first: is this update even wanted?

Read `package.json`, the lockfile, and AGENTS.md's dependency rules before touching anything.
Get the **installed** version from the lockfile or `npm ls <pkg>` — not from the
`package.json` range, which is `^1.2.0` while the installed build may be `1.4.1`.

Then ask the dependency question out loud: does the project still need this dep, and
could the standard library or a dep already present cover it (`crypto.randomUUID()`
over the `uuid` package)? **Prefer removing or avoiding a dependency over updating
it.** If the dep is unused or trivially replaceable, say so and stop — a recommended
removal is a better outcome than a clean upgrade of dead weight.

**Completion criterion:** the exact installed version, the `package.json` range, and
a stated reason the dep still earns its place.

## Step 2 — Check the registry and classify the jump

These npm invocations are identical on PowerShell and POSIX. Run them **one per
line** — don't chain with `&&`, which Windows PowerShell 5.1 rejects — and **quote
every `pkg@version` specifier** so neither shell mis-parses it:

- `npm view <pkg> version` — the latest published version.
- `npm view <pkg> versions --json` — every published version, so you can see what
  sits between installed and latest.
- `npm outdated <pkg>` — current / wanted / latest at a glance (it exits **non-zero**
  when something is outdated; that's informational, not a failure).

Compare installed → target and classify by semver: **patch** (`x.y.Z`), **minor**
(`x.Y.z`), **major** (`X.y.z`). A `0.y.z` package is special — under semver a `0.x`
minor bump is allowed to break, so treat `0.x → 0.(x+1)` as **major-risk**, not
minor.

**Completion criterion:** a target version chosen and classified patch / minor /
major, with the `0.x` caveat applied.

## Step 3 — Read the changelog across the span

Never trust the version number alone; publishers break semver. Read the release
notes / CHANGELOG for **every** version from installed+1 through target — the
package's own `CHANGELOG.md`, its GitHub releases, or `npm view <pkg>@<target>`. A
minor or patch whose notes admit a breaking change is **reclassified onto the major
path** (Step 5).

**Completion criterion:** the changelog span installed→target has been read, and the
jump is confirmed either semver-safe (→ Step 4) or breaking (→ Step 5).

## Step 4 — Minor & patch: apply, then prove it with the gate

Reached only for a **confirmed** semver-safe jump.

- **Snapshot for a one-command revert:** if `package.json` and the lockfile are clean,
  note that — Step 6 restores with a plain `git restore`. If they are **already dirty**,
  do not bump over unrelated edits blind: first capture them (`git stash push -- package.json
  package-lock.json`, or save `git diff -- package.json package-lock.json` to a patch) so
  Step 6 can restore the exact pre-bump baseline and reapply them — or, if you can't
  separate them cleanly, decline the bump and say so rather than risk the user's work.
- **Install the exact target, scoped to the one package** so nothing else moves:
  `npm install "<pkg>@<target>"`.
- **Watch the lockfile.** Expect the lockfile to change and travel *with*
  `package.json`. If instead the **whole** lockfile churns — npm reformatted it
  because your npm version differs from the one that wrote it — stop and surface
  that; it is a separate change, not this bump.
- **Run the repo's own gate.** Discover it the way `commit` does: hook manager,
  `package.json` scripts (`lint` / `typecheck` / `test`), CONTRIBUTING, CI. Run each,
  e.g. `npm run typecheck`, then `npm test`.
- **Green → the update is applied.** Say so explicitly and name `old → new`.
- **Red and the failure traces to the bump** → this "safe" bump wasn't; hand to
  Step 6.

**Completion criterion:** either the bump is applied with the gate green (and stated
as applied), or it failed the gate and control passed to Step 6.

## Step 5 — Major (or breaking minor): report, never apply

Do **not** install. Produce a **validation report** for a human containing:

- **The jump** (installed → target) and **why it's gated** — a major, or a breaking
  change shipped in a minor.
- **Breaking changes** — the actual removed / renamed / changed APIs, from the
  migration guide and changelog, not a vague "may break."
- **The migration guide** — find the project's UPGRADING / MIGRATION doc or the
  release's guide and link it.
- **Required code changes in this repo** — grep for the affected APIs and list the
  concrete call sites that would need editing.
- **Risk & effort** — how much of the codebase it touches and whether tests cover
  those paths.
- **Verdict line:** *reported for human decision, not applied.*

**Completion criterion:** a validation report exists covering breaking changes,
in-repo call sites, a migration-guide link, and risk — and nothing was installed.

## Step 6 — If an applied bump breaks the gate: revert, then report

A minor/patch that fails the gate is **reverted, not patched over** — don't
paper over a failure; find the cause, and when the cause is the dependency, back it
out):

- Restore to the **pre-bump baseline Step 4 recorded** — not a blanket wipe. If the
  manifest and lockfile were **clean** before the bump, `git restore package.json
  package-lock.json` is correct. If they were **already dirty**, a blanket `git restore`
  destroys the user's unrelated edits — instead restore the baseline and `git stash pop`
  the pre-existing edits you stashed in Step 4 (or reapply the patch you saved). If you
  couldn't cleanly separate your bump from pre-existing edits you declined back in Step 4;
  never discard uncommitted work to undo your own change.
- `npm install` — resync `node_modules` to the restored lockfile.
- Re-run the gate to confirm you are back to green.
- **Report:** the bump attempted, the exact gate failure, and that it was **reverted,
  not applied** — reclassified as needing the Step 5 treatment.

**Completion criterion:** the tree is back to its pre-bump state, the gate is green
again, and the failure is reported with the update marked reverted.

## Hard rules

- **Never a blind `npm update` or `npm audit fix --force`.** Both cross boundaries
  you haven't read — `--force` installs semver-**major** (breaking) versions, and a
  bare `npm update` bumps every in-range dep at once. Move one named package at a
  time.
- **Majors are never auto-applied.** A major — or any bump whose changelog admits a
  breaking change — is reported for a human. Full stop.
- **Semver-safe is a claim to verify, not to trust.** Read the changelog; publishers
  break semver, and `0.x` minors are breaking by spec.
- **The gate is the proof.** No minor/patch counts as applied until the repo's own
  gate ran green after it. No gate → the bump is reported, not applied.
- **State applied vs reported every time.** The user never guesses whether the tree
  changed.
- **Adding a new dependency is out of scope** — that's a separate dependency decision.
  This skill moves deps that already exist; it does not introduce them, and it
  prefers recommending removal of a dep the stdlib covers over updating it.
- **Scope every install to the named package; let the lockfile travel with the
  manifest.** Never hand-edit the lockfile, and surface a surprise full-lockfile
  reformat instead of committing it.
