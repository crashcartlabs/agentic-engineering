# Disposable agent sandbox

This container provides a bounded, disposable workspace for experiments. The host
checkout is never mounted. A host-side helper exports the selected repository's
committed `HEAD` as one tar archive; the container expands that archive into a fresh
local Git repository under `/work/repo`.

Docker (Desktop on macOS/Windows or Engine on Linux) is required.

## Start

From this toolbelt, the simplest path is:

```sh
# Offline by default: prepares the target repo's committed HEAD, then starts a shell.
just sandbox ~/projects/my-app

# Explicitly allow network access for dependency downloads.
just sandbox-online ~/projects/my-app
```

The equivalent direct flow is:

```sh
python3 scripts/sandbox/prepare_archive.py \
  --repo ~/projects/my-app --output .sandbox/source.tar
docker compose -f sandbox/compose.yaml run --rm sandbox

# Networked variant, only when required:
docker compose -f sandbox/compose.yaml run --rm sandbox-online
```

First use builds Debian, Git, Node 22, Python 3, and common build tools. Rebuild after
changing the image with `docker compose -f sandbox/compose.yaml build`.

## Threat model

The sandbox protects host integrity by exposing only a read-only archive file and by
running as a non-root user with all Linux capabilities dropped, `no-new-privileges`,
PID/CPU/memory limits, a read-only root filesystem, and bounded tmpfs storage. The
default service has no network.

Its confidentiality boundary is the archive, not the repository. The archive contains
every file tracked by the chosen `HEAD`, including any secret that was committed. It
does not contain the checkout's `.git` directory, uncommitted changes, ignored files,
stashes, hooks, sibling repositories, or host credentials. Submodule contents are not
included. Inspect the commit before treating unknown code as untrusted.

Docker itself, its daemon, the base image, and the host kernel remain trusted. The
networked variant can transmit archive contents and generated data. Resource limits
reduce accidents and denial-of-service impact; they do not make hostile native code
equivalent to a separate machine or VM.

The image intentionally follows the official floating Node 22 Bookworm slim tag and
Debian package security updates instead of freezing apt packages indefinitely. Rebuild
regularly, review base-image updates, and pin a digest in a higher-assurance deployment.

| Property | Behavior |
|---|---|
| Host input | one read-only `git archive HEAD` tar file |
| Working copy | fresh local Git repo at `/work/repo` |
| Uncommitted/ignored host files | not included |
| Lifetime | `--rm`; container and tmpfs changes vanish on exit |
| User | non-root `agent`, capabilities dropped |
| Limits | 4 GB RAM, 2 CPUs, 256 PIDs, 2 GB `/work`, 512 MB `/tmp` |
| Network | none for `sandbox`; bridge network for `sandbox-online` |

## Getting work out

Everything inside is disposable. Export a patch to stdout before the container exits:

```sh
docker compose -f sandbox/compose.yaml run --rm sandbox \
  bash -c 'your-experiment 1>&2 && git add -A && git --no-pager diff --cached HEAD' \
  > sandbox.patch
```

Review the patch on the host, then apply it deliberately with `git apply sandbox.patch`.

## Scratch repositories

To test destructive Git operations without the seeded source, create another repo under
the bounded `/work` tmpfs:

```sh
mkdir /work/scratch && cd /work/scratch && git init
```
