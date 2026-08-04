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

# Files reset to an empty starting state in the public snapshot. They stay
# present (so AGENTS.md's references to them still resolve) but carry none of
# the private development narrative.
ISSUES_URL = "https://github.com/mike-jenkins-org/agentic-engineering/issues"


def reset_files(today: str) -> dict[str, str]:
    return {
        "DEVLOG.md": (
            "# Development Log\n\n"
            "Chronological record for the Agentic Engineering toolbelt. New entries go "
            "first and\nrecord the goal, material decisions, verification, and exact "
            "continuation point.\n\n"
            f"## {today} — Initial public release\n\n"
            "**Focus:** Establish the public snapshot of the Agentic Engineering toolbelt.\n\n"
            "**Done:**\n"
            "- Published the provider-neutral skills, agents, adapters, and toolbelt scripts.\n\n"
            "**Left off:** Public baseline established; ongoing development happens in the "
            "private repository.\n"
        ),
        "LESSONS.md": (
            "# LESSONS\n\n"
            "One-line lessons from mistakes and corrections, so the same error isn't "
            "repeated. See AGENTS.md §X.\n"
        ),
        "TODO.md": (
            "# TODO\n\n"
            "Work identified but deliberately deferred — see AGENTS.md §XIV.\n\n"
            "Deferred work is tracked as **GitHub issues** on this repo\n"
            f"(<{ISSUES_URL}>), one issue per work\n"
            "item. Add new deferred work as an issue; use this file only as offline scratch "
            "until the\nitem can be filed.\n"
        ),
    }


def run(cmd: list[str], cwd: pathlib.Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


GIT_ROUTING_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def ambient_git_env() -> dict[str, str]:
    """Ambient env minus Git routing variables — for every git call in this script.

    Routing variables (GIT_DIR & co.) override cwd entirely, so inheriting one
    would point the private-repo queries, the snapshot build, and the force-push
    itself at whatever repository the invoking tool had routed — pushing that
    repo's `main` to the public remote. Global/system config stays: the push
    needs its credential helpers, and the read-only queries are shaped by cwd,
    not config.
    """
    return {key: value for key, value in os.environ.items() if key not in GIT_ROUTING_VARS}


def _is_command_scope_config(key: str) -> bool:
    """Command-scope Git config exported via env (GIT_CONFIG_COUNT/KEY_n/VALUE_n,
    GIT_CONFIG_PARAMETERS from `git -c`): it overrides even a silenced
    global/system config, so the snapshot build must strip it too."""
    return key in ("GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS") or key.startswith(
        ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
    )


def snapshot_git_env() -> dict[str, str]:
    """Isolated env for building the snapshot repo (init/add/commit).

    On top of the routing-free ambient env, global/system config is silenced
    and command-scope env config is stripped: an inherited `commit.gpgSign`
    from either source would try to sign (and fail headless), and a
    `core.hooksPath` would run personal hooks against the export. The push
    deliberately keeps ambient config instead — credential helpers live in
    exactly the config silenced here.

    The snapshot identity is pinned in the environment as well: GIT_AUTHOR_* /
    GIT_COMMITTER_* variables outrank any `-c user.*` flags, so an inherited
    personal identity would otherwise sign the public commit — the exact leak
    this script exists to prevent. Inherited date overrides go too; the
    snapshot commit's timestamp must be the publish time, not tooling residue.
    """
    env = {key: value for key, value in ambient_git_env().items() if not _is_command_scope_config(key)}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    name, email = snapshot_identity()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = name
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = email
    for key in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        env.pop(key, None)
    return env


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
        env=ambient_git_env(),
    )
    if result.returncode != 0:
        raise SystemExit(f"error: cannot resolve ref {ref!r}: {result.stderr.strip()}")
    return result.stdout.strip()


def build_snapshot(ref: str, workdir: pathlib.Path, today: str) -> pathlib.Path:
    """Export the tracked tree at `ref` and apply the public transforms."""
    archive = workdir / "snapshot.tar"
    with archive.open("wb") as handle:
        subprocess.run(["git", "archive", ref], cwd=REPO, stdout=handle, check=True, env=ambient_git_env())
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

# Official SemVer 2.0.0 shape (semver.org): synchronized manifests are not
# enough — `release-2` in all four would still violate the versioning contract
# and break every consumer that orders releases. ASCII + fullmatch, because
# `$` accepts a trailing newline and a bare `\d` accepts non-ASCII digits.
SEMVER_RE = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?",
    re.ASCII,
)


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
    if not SEMVER_RE.fullmatch(release):
        raise SystemExit(f"error: synchronized version {release!r} is not valid SemVer")
    changelog = tree / "CHANGELOG.md"
    if not changelog.is_file() or not changelog_has_release_heading(
        changelog.read_text(encoding="utf-8"), release
    ):
        raise SystemExit(f"error: exported CHANGELOG.md has no heading for version {release}")
    return release


def changelog_has_release_heading(text: str, release: str) -> bool:
    """A line-anchored `## [<release>]` heading in the *rendered* changelog.

    A matching line inside a fenced code block is a documented example, not the
    release entry, so fenced content is excluded before matching. Mirrors the
    toolbelt source gate's check.
    """
    heading = re.compile(rf"^## \[{re.escape(release)}\]")
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and line.strip() == marker:
                fence = None
            continue
        if fence is None and heading.match(line):
            return True
    return False


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
            cwd=repo, capture_output=True, text=True, env=ambient_git_env(),
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
        ["git", "rev-parse", f"{ref}^{{commit}}"],
        cwd=REPO, capture_output=True, text=True, env=ambient_git_env(),
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
        build_env = snapshot_git_env()
        run(["git", "init", "-q", "-b", "main"], cwd=tree, env=build_env)
        run(["git", "add", "-A"], cwd=tree, env=build_env)
        run(
            ["git", *identity, "commit", "-q", "-m", f"Agentic Engineering — public snapshot ({short_sha})"],
            cwd=tree,
            env=build_env,
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
        # Routing-free, config-kept: the push must target the snapshot repo under
        # cwd while still finding the maintainer's credential helpers.
        run(["git", "push", "--force", remote, "main:main"], cwd=tree, env=ambient_git_env())
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
            "Chronological record for the Agentic Engineering toolbelt. New entries go "
            "first and\nrecord the goal, material decisions, verification, and exact "
            "continuation point.\n\n"
            f"## {today} — Initial public release\n\n"
            "**Focus:** Establish the public snapshot of the Agentic Engineering toolbelt.\n\n"
            "**Done:**\n"
            "- Published the provider-neutral skills, agents, adapters, and toolbelt scripts.\n\n"
            "**Left off:** Public baseline established; ongoing development happens in the "
            "private repository.\n"
        ),
        "LESSONS.md": (
            "# LESSONS\n\n"
            "One-line lessons from mistakes and corrections, so the same error isn't "
            "repeated. See AGENTS.md §X.\n"
        ),
        "TODO.md": (
            "# TODO\n\n"
            "Work identified but deliberately deferred — see AGENTS.md §XIV.\n\n"
            "Deferred work is tracked as **GitHub issues** on this repo\n"
            "(<https://github.com/mike-jenkins-org/agentic-engineering/issues>), one issue per work\n"
            "item. Add new deferred work as an issue; use this file only as offline scratch "
            "until the\nitem can be filed.\n"
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

    poison = {
        "GIT_INDEX_FILE": "/nonexistent/index",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "commit.gpgSign",
        "GIT_CONFIG_VALUE_0": "true",
        "GIT_AUTHOR_NAME": "Private Person",
        "GIT_AUTHOR_EMAIL": "private@personal.example",
        "GIT_COMMITTER_NAME": "Private Person",
        "GIT_COMMITTER_EMAIL": "private@personal.example",
        "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z",
    }
    saved_poison = {key: os.environ.pop(key, None) for key in poison}
    try:
        os.environ.update(poison)
        build_env = snapshot_git_env()
        if any(key in build_env for key in GIT_ROUTING_VARS):
            failures.append("snapshot git env kept an inherited routing variable")
        if any(key in build_env for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")):
            failures.append("snapshot git env kept command-scope config that overrides silenced files")
        if build_env.get("GIT_CONFIG_GLOBAL") != os.devnull or build_env.get("GIT_CONFIG_SYSTEM") != os.devnull:
            failures.append("snapshot git env does not silence global/system config")
        # Identity env vars outrank -c user.* flags, so the env itself must
        # carry the non-personal snapshot identity, never the inherited one.
        expected_name, expected_email = snapshot_identity()
        if (
            build_env.get("GIT_AUTHOR_NAME") != expected_name
            or build_env.get("GIT_COMMITTER_NAME") != expected_name
            or build_env.get("GIT_AUTHOR_EMAIL") != expected_email
            or build_env.get("GIT_COMMITTER_EMAIL") != expected_email
        ):
            failures.append("snapshot git env does not pin the non-personal identity over inherited GIT_AUTHOR/COMMITTER vars")
        if "GIT_AUTHOR_DATE" in build_env or "GIT_COMMITTER_DATE" in build_env:
            failures.append("snapshot git env kept inherited commit-date overrides")
        push_env = ambient_git_env()
        if any(key in push_env for key in GIT_ROUTING_VARS):
            failures.append("ambient git env kept an inherited routing variable")
        for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            if push_env.get(key) != os.environ.get(key):
                failures.append("ambient git env altered config the push needs for credentials")
    finally:
        for key, value in saved_poison.items():
            if value is None:
                os.environ.pop(key, None)
            else:
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
        for rel in MANIFESTS:
            (tree / rel).write_text(json.dumps({"version": "release-2"}), encoding="utf-8")
        (tree / "CHANGELOG.md").write_text("# Changelog\n\n## [release-2] - 2026-01-01\n", encoding="utf-8")
        try:
            verify_release_consistency(tree)
        except SystemExit:
            pass
        else:
            failures.append("a synchronized but non-SemVer version was not refused")
        for rel in MANIFESTS:
            (tree / rel).write_text(json.dumps({"version": "1.2.3\n"}), encoding="utf-8")
        (tree / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.3\n] - 2026-01-01\n", encoding="utf-8")
        try:
            verify_release_consistency(tree)
        except SystemExit:
            pass
        else:
            failures.append("a version with a trailing newline was not refused")
        for rel in MANIFESTS:
            (tree / rel).write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
        (tree / "CHANGELOG.md").write_text(
            "# Changelog\n\n```markdown\n## [9.9.9] - 2026-01-01\n```\n", encoding="utf-8"
        )
        try:
            verify_release_consistency(tree)
        except SystemExit:
            pass
        else:
            failures.append("a changelog heading inside a fenced example was accepted as the entry")

    with tempfile.TemporaryDirectory(prefix="publish-selftest-") as raw:
        repo = pathlib.Path(raw)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid.example"]
        # The fixture commits run under the isolated snapshot env so a
        # developer's ambient gpgSign/hooks cannot redden the selftest.
        fixture_env = snapshot_git_env()
        subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True, env=fixture_env)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True, env=fixture_env)
        subprocess.run([*git, "commit", "-q", "-m", "one"], cwd=repo, check=True, env=fixture_env)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            pass
        else:
            failures.append("publishing without the release tag was not refused")
        subprocess.run([*git, "tag", "v9.9.9"], cwd=repo, check=True, env=fixture_env)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            failures.append("a correctly tagged ref was refused")
        (repo / "f.txt").write_text("y\n", encoding="utf-8")
        subprocess.run([*git, "commit", "-q", "-am", "two"], cwd=repo, check=True, env=fixture_env)
        try:
            verify_release_tag(repo, "main", "9.9.9")
        except SystemExit:
            pass
        else:
            failures.append("a tag pointing at an older commit was not refused")

    # Source-side release contract: the gate runs this selftest, so a version
    # bump that desynchronizes the real manifests, skips the changelog heading,
    # or writes a non-SemVer value fails here — before publish preflight ever runs.
    try:
        verify_release_consistency(REPO)
    except SystemExit as exc:
        failures.append(f"the repository's own release contract is broken: {exc}")
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
