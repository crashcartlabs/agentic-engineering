# Publishing (two-repo model)

This toolbelt is developed in a **private** repository and released as a curated
**public** snapshot. The two repos have the same file tree; only the history and a
few working files differ.

| Repo | Visibility | Holds |
|---|---|---|
| `agentic-engineering-private` | private | Full history, PRs, and the live `DEVLOG.md` / `LESSONS.md` / `TODO.md` working notes. Do development here. |
| `agentic-engineering` | public | A single-commit snapshot of the tree, with the working record files reset to an empty starting state. No development history. |

## Why a snapshot, not a mirror

Publishing the private history would expose commit metadata (author emails, session
ids, old branch/PR churn) that has nothing to do with the released code. Instead each
release replaces the public repo's `main` with **one** clean commit built from the
private tree, so the public history is always exactly one "public snapshot" commit.

## Releasing

From a clean checkout of the private repo, on the ref you want to publish (normally
`main`):

```sh
# inspect what would be published, without pushing
just publish-dry-run            # builds .public-snapshot-dryrun/ (gitignored)

# publish: force-push a clean single commit to the public repo's main
just publish git@github.com:mike-jenkins-org/agentic-engineering.git
```

`scripts/release/publish_public.py` exports the tracked tree at the chosen ref, resets
`DEVLOG.md` (to a single "Initial public release" entry), `LESSONS.md`, and `TODO.md`
to their empty starting state, and force-pushes the result. Everything else ships
verbatim, so the public repo stays gate-green and self-consistent.

The force-push is intentional: the public `main` is a disposable snapshot, never a
branch you develop on. All development, issues, and PRs live in the private repo.
