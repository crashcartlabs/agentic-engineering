#!/usr/bin/env python3
"""Publish a clean, single-commit snapshot of this toolbelt to a public repo.

The private repo is the source of truth: it keeps the full history and the
working record files (DEVLOG, LESSONS, TODO). The public repo is a curated
snapshot with none of that development history. This script:

  1. exports the tracked tree at a chosen ref (default: main),
  2. resets the working record files to an empty starting state, and
  3. force-pushes it as a single commit to the public repo's main branch,

so the public repo's history is always exactly one "public snapshot" commit —
no personal emails, no session ids, no branch/PR churn.

Usage:
    python3 scripts/release/publish_public.py --remote <git-url> [--ref main]
    python3 scripts/release/publish_public.py --remote <git-url> --dry-run
    just publish <git-url>

`--dry-run` builds the snapshot and prints its path without pushing.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]

# Files reset to a bare starting state in the public snapshot. They stay present
# (so AGENTS.md's references to them still resolve) but carry none of the private
# development narrative. DEVLOG keeps a single dated entry because the record lint
# requires at least one; LESSONS and TODO are bare headers.
def reset_files(today: str) -> dict[str, str]:
    return {
        "DEVLOG.md": (
            "# Development Log\n\n"
            f"## {today} — Initial public release\n\n"
            "**Focus:** Public snapshot of the Agentic Engineering toolbelt.\n"
        ),
        "LESSONS.md": "# LESSONS\n",
        "TODO.md": (
            "# TODO\n\n"
            "The backlog lives in GitHub issues (AGENTS.md §XIV); this file holds only unfiled\n"
            "temporary scratch, and is empty when nothing is pending filing.\n"
        ),
    }


def run(cmd: list[str], cwd: pathlib.Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def resolve_ref(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", ref],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"error: cannot resolve ref {ref!r}: {result.stderr.strip()}")
    return result.stdout.strip()


def build_snapshot(ref: str, workdir: pathlib.Path, today: str) -> pathlib.Path:
    """Export the tracked tree at `ref` and apply the public transforms."""
    archive = workdir / "snapshot.tar"
    with archive.open("wb") as handle:
        subprocess.run(["git", "archive", ref], cwd=REPO, stdout=handle, check=True)
    tree = workdir / "tree"
    tree.mkdir()
    with tarfile.open(archive) as handle:
        if sys.version_info >= (3, 12):
            handle.extractall(tree, filter="data")
        else:
            handle.extractall(tree)
    for name, content in reset_files(today).items():
        (tree / name).write_text(content, encoding="utf-8")
    return tree


def publish(remote: str, ref: str, dry_run: bool, today: str) -> int:
    short_sha = resolve_ref(ref)
    with tempfile.TemporaryDirectory(prefix="agentic-publish-") as raw:
        workdir = pathlib.Path(raw)
        tree = build_snapshot(ref, workdir, today)
        run(["git", "init", "-q", "-b", "main"], cwd=tree)
        run(["git", "add", "-A"], cwd=tree)
        run(["git", "commit", "-q", "-m", f"Agentic Engineering — public snapshot ({short_sha})"], cwd=tree)
        if dry_run:
            # Keep the built tree around for inspection by copying it out of the
            # soon-to-be-deleted temp dir.
            out = REPO / ".public-snapshot-dryrun"
            # rm -rf equivalence: the leftover may be a file or symlink, which
            # rmtree refuses; only a real directory takes the tree removal.
            if out.is_symlink() or out.is_file():
                out.unlink()
            elif out.exists():
                shutil.rmtree(out)
            # symlinks=True preserves tracked symlinks as links (the prior `cp -r`
            # behavior); the default would dereference them, making the inspection
            # copy differ from the tree actually committed and pushed.
            shutil.copytree(tree, out, symlinks=True)
            print(f"dry run: built public snapshot of {ref} ({short_sha}) at {out}")
            print("        (no push performed; remove the directory when done)")
            return 0
        print(f"publishing snapshot of {ref} ({short_sha}) to {remote} (force-push to main)")
        run(["git", "push", "--force", remote, "main:main"], cwd=tree)
        print("published.")
    return 0


def selftest() -> int:
    today = "2026-01-01"
    files = reset_files(today)
    failures: list[str] = []
    # Exact expected contents, not substring probes: any drift in a reset file —
    # including a bare private handle that no URL/handle regex would catch — fails
    # here without this check ever having to name a private sentinel.
    expected = {
        "DEVLOG.md": (
            "# Development Log\n\n"
            f"## {today} — Initial public release\n\n"
            "**Focus:** Public snapshot of the Agentic Engineering toolbelt.\n"
        ),
        "LESSONS.md": "# LESSONS\n",
        "TODO.md": (
            "# TODO\n\n"
            "The backlog lives in GitHub issues (AGENTS.md §XIV); this file holds only unfiled\n"
            "temporary scratch, and is empty when nothing is pending filing.\n"
        ),
    }
    for name, content in expected.items():
        if files.get(name) != content:
            failures.append(f"{name} reset deviates from its expected exact content")
    if set(files) != set(expected):
        failures.append(f"reset file set changed: {sorted(files)} != {sorted(expected)}")
    print("publish_public selftest:", "OK" if not failures else "FAIL")
    for failure in failures:
        print(f"  - {failure}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish a clean public snapshot of this toolbelt.")
    parser.add_argument("--remote", help="git URL of the public repository")
    parser.add_argument("--ref", default="main", help="source ref to snapshot (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="build the snapshot without pushing")
    parser.add_argument("--selftest", action="store_true", help="run embedded checks and exit")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.remote and not args.dry_run:
        parser.error("--remote is required unless --dry-run is given")
    today = datetime.date.today().isoformat()
    return publish(args.remote or "", args.ref, args.dry_run, today)


if __name__ == "__main__":
    raise SystemExit(main())
