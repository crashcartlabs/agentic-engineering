#!/usr/bin/env python3
"""Create the single-file, committed-state seed used by the Docker sandbox."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


class ArchiveError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise ArchiveError(f"git {' '.join(args)} failed: {detail.strip()}") from exc


def prepare(repo: Path, output: Path) -> str:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ArchiveError(f"repository directory does not exist: {repo}")
    top = Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    commit = git(top, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ArchiveError(f"refusing symlink output: {output}")

    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        result = subprocess.run(
            ["git", "-C", str(top), "archive", "--format=tar", "--output", str(temp), commit],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if result.returncode:
            raise ArchiveError(f"git archive failed: {result.stderr.strip()}")
        os.chmod(temp, 0o600)
        os.replace(temp, output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArchiveError(f"could not create archive: {exc}") from exc
    finally:
        temp.unlink(missing_ok=True)
    return commit


def main() -> int:
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        commit = prepare(args.repo, args.output)
    except ArchiveError as exc:
        print(f"sandbox archive: error: {exc}", file=sys.stderr)
        return 2
    print(f"sandbox archive: {args.output.expanduser().resolve()} ({commit[:12]})")
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="sandbox-archive-selftest-") as raw:
        root = Path(raw)
        repo = root / "repo"
        repo.mkdir()

        def run(*args: str) -> None:
            subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )

        run("init", "--quiet")
        run("config", "user.name", "Sandbox Selftest")
        run("config", "user.email", "sandbox@example.test")
        (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
        ignored = repo / "dist" / "schema.json"
        ignored.parent.mkdir()
        ignored.write_text("{}\n", encoding="utf-8")
        (repo / ".env").write_text("untracked-secret\n", encoding="utf-8")
        run("add", "tracked.txt", ".gitignore")
        run("add", "-f", "dist/schema.json")
        run("commit", "--quiet", "-m", "seed")
        archive = root / "nested" / "source.tar"
        prepare(repo, archive)
        with tarfile.open(archive) as handle:
            names = set(handle.getnames())
        failures: list[str] = []
        if "tracked.txt" not in names:
            failures.append("tracked file missing from archive")
        if "dist/schema.json" not in names:
            failures.append("force-tracked ignored file missing from archive")
        if ".env" in names or any(name == ".git" or name.startswith(".git/") for name in names):
            failures.append("untracked file or Git metadata leaked into archive")
        if failures:
            print("sandbox archive selftest: FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        seed = root / "seed"
        seed.mkdir()
        with tarfile.open(archive) as handle:
            if sys.version_info >= (3, 12):
                handle.extractall(seed, filter="data")
            else:
                handle.extractall(seed)
        subprocess.run(["git", "init", "--quiet"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.name", "Sandbox Selftest"], cwd=seed, check=True)
        subprocess.run(["git", "config", "user.email", "sandbox@example.test"], cwd=seed, check=True)
        subprocess.run(["git", "add", "-f", "-A"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "--quiet", "-m", "sandbox seed"], cwd=seed, check=True)
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=seed, check=True, capture_output=True, text=True
        ).stdout.splitlines()
        if "dist/schema.json" not in tracked:
            failures.append("sandbox seed lost a force-tracked ignored file")
        entrypoint = (Path(__file__).resolve().parents[2] / "sandbox" / "entrypoint.sh").read_text()
        if "git -C /work/repo add -f -A" not in entrypoint or "commit --allow-empty" not in entrypoint:
            failures.append("sandbox entrypoint is missing force-add or allow-empty reconstruction")
        if failures:
            print("sandbox archive selftest: FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1
    print("sandbox archive selftest: OK (tracked HEAD only; untracked and .git excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
