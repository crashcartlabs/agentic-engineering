#!/bin/sh
# Expand the single committed-state archive into a disposable local git repo.
set -e

if [ ! -f /seed/source.tar ]; then
  echo "sandbox: missing /seed/source.tar; run scripts/sandbox/prepare_archive.py first" >&2
  exit 2
fi

if [ ! -d /work/repo ]; then
  mkdir -p /work/repo
  tar -xf /seed/source.tar -C /work/repo
  git -C /work/repo init --quiet
  git -C /work/repo add -f -A
  git -C /work/repo commit --allow-empty --quiet -m "sandbox seed"
fi

cd /work/repo

exec "$@"
