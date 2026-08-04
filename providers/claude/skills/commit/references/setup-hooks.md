# Setting up a pre-commit gate

Reached from Step 3 of the commit skill when a repo has no hook manager and the
user wants one. The husky flow is adapted from Matt Pocock's `setup-pre-commit` skill; the
pitfalls are from live runs.

## JS/TS repos — husky + lint-staged + prettier

1. **Detect the package manager** by lockfile: `package-lock.json` → npm,
   `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lock` **or `bun.lockb`** →
   bun (the binary `bun.lockb` was bun's only lockfile before 1.2 and persists
   after upgrades). Multiple lockfiles → package.json's `packageManager` field is
   the tie-breaker. No lockfile → npm.
2. **Install dev deps:** `husky`, `lint-staged`, `prettier` (and `typescript` +
   `@types/node` if the repo is TS without them).
3. **Init** via the detected manager — `npx husky init` / `pnpm exec husky init` /
   `yarn exec husky init` / `bunx husky init` — creates `.husky/pre-commit`
   (default `npm test`) and adds the `prepare: husky` script to package.json.
   **Check `prepare` first:** `husky init` *replaces* an existing prepare script
   (`"prepare": "npm run build"` becomes `"prepare": "husky"`) without warning —
   after init, merge the old script back (`"prepare": "husky && npm run build"`)
   so build-on-install keeps working.
   **Yarn Berry (2+) does not run `prepare` on install** — the default wiring
   leaves every fresh Berry clone silently gateless. For Berry repos follow
   husky's yarn guide instead: wire `"postinstall": "husky"` (plus `pinst` to
   disable it for published packages). The same merge rule applies here: an
   existing `postinstall` (codegen, native builds) is merged
   (`"postinstall": "husky && <existing>"`), never replaced.
4. **Write `.husky/pre-commit`:**

   ```
   npx lint-staged
   npm run typecheck
   npm test
   ```

   Omit the `typecheck`/`test` lines if the repo has no such script; for a TS repo
   without one, add `"typecheck": "tsc --noEmit"`. Use the detected manager's
   runners throughout — pnpm: `pnpm exec` / `pnpm run` / `pnpm test`; yarn:
   `yarn exec` / `yarn run` / `yarn test`; bun: `bunx` / `bun run` / `bun test` —
   so the hook resolves local binaries inside the repo's own toolchain (a Yarn PnP
   repo has no `node_modules/.bin` for `npx` to find).
5. **`.lintstagedrc`:** `{ "*": "prettier --write --ignore-unknown" }` — only if
   no lint-staged config exists already; check config files **and** package.json's
   `lint-staged` key. A new `.lintstagedrc` beside an existing config silently
   replaces the repo's own tasks with prettier-only, and nothing catches it
   because the hook still visibly fires.
6. **`.prettierrc`:** only if no prettier config exists already.

## Python repos — the pre-commit framework

1. **Install `pre-commit`** in the project venv or via pipx — system pip is blocked
   on externally-managed Pythons (PEP 668).
2. **Write `.pre-commit-config.yaml` from checks the repo already runs** (pyproject
   tool config, CI) as `repo: local` hooks, so the gate is the repo's own commands
   rather than imported defaults:

   ```yaml
   repos:
     - repo: local
       hooks:
         - id: lint
           name: ruff
           entry: ruff check
           language: system
           types: [python]
         - id: tests
           name: pytest
           entry: python -m pytest -q
           language: system
           pass_filenames: false
   ```

   Include only hooks whose tools the repo actually uses; a config with no hooks
   is not a gate.
3. **Wire and prove it:** `pre-commit install`, then `pre-commit run --all-files` —
   green on existing code before trusting it. Note `pre-commit install` refuses
   when `core.hooksPath` is set ("Cowardly refusing…") — Step 3 of the skill
   already stops on a foreign hooksPath before reaching here.

This path has not had a live run yet — verify it end-to-end the first time it fires
on a real repo.

## Pitfalls (all hit in live runs)

- **A new check fails on pre-existing code, not your work.** Wiring `tsc --noEmit`
  into a repo that never typechecked surfaced missing `@types/node` *and* a missing
  `"types": ["node"]` in tsconfig (TypeScript 6). Those gaps are part of the setup
  job: make the gate pass on the existing code before trusting it.
- **Verify the hook actually fires** on the setup commit (its output shows
  lint-staged/typecheck/test running); in a fresh clone the hooks are wired at
  install time by the `prepare` script (npm / pnpm / bun / Yarn 1 — Yarn Berry
  needs the `postinstall` wiring above), so an uninstalled clone silently has no
  gate.
