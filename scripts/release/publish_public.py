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
import json
import os
import pathlib
import re
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


def snapshot_identity() -> tuple[str, str]:
    """Explicit, non-personal author identity for the generated snapshot commit.

    Inheriting ambient Git config would either publish the maintainer's real
    email — the exact leak this script exists to avoid — or fail outright on a
    machine with no global identity. Override via env when a different public
    attribution is wanted.
    """
    return (
        os.environ.get("AGENTIC_PUBLISH_AUTHOR_NAME", "Agentic Engineering"),
        os.environ.get("AGENTIC_PUBLISH_AUTHOR_EMAIL", "agentic-engineering@noreply.invalid"),
    )


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
        target = tree / name
        # Replace, never write-through: if the archived path is a symlink,
        # write_text would follow it (pre-3.12 extraction admits escaping
        # links) and the snapshot would keep the link instead of a reset file.
        if target.is_symlink() or target.exists():
            target.unlink()
        target.write_text(content, encoding="utf-8")
    return tree


MANIFESTS = ("toolbelt.json", "package.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


def verify_release_consistency(tree: pathlib.Path) -> str:
    """Check the exported tree's release contract; return its version.

    The tag preflight alone cannot catch a tagged ref whose manifests disagree
    or whose changelog lacks the release entry — the snapshot must satisfy the
    synchronized-release contract (docs/publishing.md) before any force-push.
    """
    versions: dict[str, str] = {}
    for rel in MANIFESTS:
        path = tree / rel
        if not path.is_file():
            raise SystemExit(f"error: {rel} is missing from the exported tree")
        version = json.loads(path.read_text(encoding="utf-8")).get("version")
        if not isinstance(version, str) or not version.strip():
            raise SystemExit(f"error: {rel} in the exported tree has no version")
        versions[rel] = version
    if len(set(versions.values())) > 1:
        raise SystemExit(f"error: manifest version mismatch in the exported tree: {versions}")
    release = next(iter(versions.values()))
    changelog = tree / "CHANGELOG.md"
    if not changelog.is_file() or not re.search(
        rf"^## \[{re.escape(release)}\]", changelog.read_text(encoding="utf-8"), re.MULTILINE
    ):
        raise SystemExit(f"error: exported CHANGELOG.md has no heading for version {release}")
    return release


def verify_release_tag(repo: pathlib.Path, ref: str, version: str) -> None:
    """Require v<version> to exist and point at the exported ref before pushing.

    The snapshot commit message embeds the private short SHA; the tag is what
    keeps that SHA resolvable later, so an untagged publish defeats the release
    identity (docs/publishing.md).
    """
    tag = f"v{version}"

    def commit_of(name: str) -> str | None:
        proc = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"{name}^{{commit}}"],
            cwd=repo, capture_output=True, text=True,
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    tag_commit = commit_of(f"refs/tags/{tag}")
    if tag_commit is None:
        raise SystemExit(
            f"error: release tag {tag} does not exist; tag the ref before publishing "
            "(see docs/publishing.md)"
        )
    if tag_commit != commit_of(ref):
        raise SystemExit(
            f"error: release tag {tag} does not point at {ref}; retag or pick the tagged ref"
        )


def publish(remote: str, ref: str, dry_run: bool, today: str) -> int:
    # Pin one immutable commit up front: a symbolic ref could advance between
    # archiving and tag verification, letting the preflight pass on a commit the
    # archive does not contain. Everything below uses this OID, never the ref.
    resolved = subprocess.run(
        ["git", "rev-parse", f"{ref}^{{commit}}"], cwd=REPO, capture_output=True, text=True
    )
    if resolved.returncode:
        raise SystemExit(f"error: cannot resolve ref {ref!r}: {resolved.stderr.strip()}")
    oid = resolved.stdout.strip()
    short_sha = resolve_ref(oid)
    with tempfile.TemporaryDirectory(prefix="agentic-publish-") as raw:
        workdir = pathlib.Path(raw)
        tree = build_snapshot(oid, workdir, today)
        if not dry_run:
            # Validate the exported tree itself — the working tree may sit on a
            # different version than the ref being published.
            version = verify_release_consistency(tree)
            verify_release_tag(REPO, oid, version)
        name, email = snapshot_identity()
        identity = ["-c", f"user.name={name}", "-c", f"user.email={email}"]
        run(["git", "init", "-q", "-b", "main"], cwd=tree)
        run(["git", "add", "-A"], cwd=tree)
        run(
            ["git", *identity, "commit", "-q", "-m", f"Agentic Engineering — public snapshot ({short_sha})"],
            cwd=tree,
        )
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

    # Clear the supported overrides while testing defaults: a maintainer's
    # legitimate AGENTIC_PUBLISH_* configuration must not fail the gate.
    saved_overrides = {
        key: os.environ.pop(key, None)
        for key in ("AGENTIC_PUBLISH_AUTHOR_NAME", "AGENTIC_PUBLISH_AUTHOR_EMAIL")
    }
    try:
        default_name, default_email = snapshot_identity()
        if "@" not in default_email or "noreply" not in default_email:
            failures.append("default snapshot identity is not a non-personal noreply address")
        os.environ["AGENTIC_PUBLISH_AUTHOR_NAME"] = "Custom Publisher"
        if snapshot_identity()[0] != "Custom Publisher":
            failures.append("snapshot identity env override was ignored")
    finally:
        os.environ.pop("AGENTIC_PUBLISH_AUTHOR_NAME", None)
        for key, value in saved_overrides.items():
            if value is not None:
                os.environ[key] = value

    with tempfile.TemporaryDirectory(prefix="publish-consistency-selftest-") as raw:
        tree = pathlib.Path(raw)
        for rel in MANIFESTS:
            target = tree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
        (tree / "CHANGELOG.md").write_text("# Changelog\n\n## [9.9.9] - 2026-01-01\n", encoding="utf-8")
        try:
            if verify_release_consistency(tree) != "9.9.9":
                failures.append("consistent exported tree did not report its version")
        except SystemExit:
            failures.append("a consistent exported tree was refused")
        (tree / "package.json").write_text(json.dumps({"version": "9.9.8"}), encoding="utf-8")
        try:
            verify_release_consistency(tree)
        except SystemExit:
            pass
        else:
            failures.append("a manifest version mismatch in the exported tree was not refused")
        (tree / "package.json").write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
        (tree / "CHANGELOG.md").write_text("# Changelog\n\nprose mentioning ## [9.9.9] only\n", encoding="utf-8")
        try:
            verify_release_consistency(tree)
        except SystemExit:
            pass
        else:
            failures.append("a missing changelog heading in the exported tree was not refused")

    with tempfile.TemporaryDirectory(prefix="publish-selftest-") as raw:
        repo = pathlib.Path(raw)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid.example"]
        subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*git, "commit", "-q", "-m", "one"], cwd=repo, check=True)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            pass
        else:
            failures.append("publishing without the release tag was not refused")
        subprocess.run([*git, "tag", "v9.9.9"], cwd=repo, check=True)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            failures.append("a correctly tagged ref was refused")
        (repo / "f.txt").write_text("y\n", encoding="utf-8")
        subprocess.run([*git, "commit", "-q", "-am", "two"], cwd=repo, check=True)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            pass
        else:
            failures.append("a tag pointing at an older commit was not refused")
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
