#!/usr/bin/env python3
"""Shared source-selection helpers for the lint scripts.

Every lint uses one explicit source for both enumeration and reads. Interactive checks
default to the working tree (including untracked, non-ignored files); pre-commit uses the
index. Mixing index enumeration with working-tree reads caused staged-invalid content to
pass when the unstaged file happened to be valid.
"""

from __future__ import annotations

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "worktree"


def configure(source: str) -> None:
    """Select `worktree` or `index` for subsequent helper calls."""
    if source not in {"worktree", "index"}:
        raise ValueError(f"unsupported lint source: {source}")
    global SOURCE
    SOURCE = source


def tracked_files(
    *pathspecs: str,
    repo: pathlib.Path | str = REPO,
    source: str | None = None,
    env: dict[str, str] | None = None,
) -> list[pathlib.Path]:
    """Files in the selected source matching pathspecs."""
    repo = pathlib.Path(repo).resolve()
    selected = source or SOURCE
    args = ["git", "ls-files", "-z"]
    if selected == "worktree":
        args.extend(["--cached", "--others", "--exclude-standard"])
    elif selected != "index":
        raise ValueError(f"unsupported lint source: {selected}")
    args.extend(["--", *pathspecs])
    out = subprocess.run(
        args,
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    ).stdout
    paths = [repo / rel.decode("utf-8") for rel in out.split(b"\0") if rel]
    if selected == "worktree":
        paths = [path for path in paths if path.is_file()]
    return sorted(set(paths))


def tracked_text(
    path: pathlib.Path | str,
    *,
    repo: pathlib.Path | str = REPO,
    encoding: str = "utf-8",
    env: dict[str, str] | None = None,
    source: str | None = None,
) -> str | None:
    """Return text from the selected source, or None when the file is absent there.

    During pre-commit, the index is the commit candidate. During interactive work, the
    working tree is what the user is about to run and should be checked as it exists.
    """
    repo = pathlib.Path(repo).resolve()
    path = pathlib.Path(path)
    abs_path = path if path.is_absolute() else repo / path
    try:
        rel = abs_path.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise ValueError(f"{path} is outside {repo}") from exc

    selected = source or SOURCE
    if selected == "worktree":
        try:
            return abs_path.read_text(encoding=encoding)
        except FileNotFoundError:
            return None
    if selected != "index":
        raise ValueError(f"unsupported lint source: {selected}")
    proc = subprocess.run(
        ["git", "show", f":{rel}"],
        cwd=repo,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode(encoding)


def is_tracked(path: pathlib.Path, tracked: list[pathlib.Path]) -> bool:
    """True if `path` is one of `tracked`, or a directory containing one of them.

    `path` must be inside REPO first — every tracked path starts with REPO's own
    prefix, so without this check a link escaping the repo (e.g. `..` from a
    root-level doc) would prefix-match REPO's *parent* and be wrongly reported as
    tracked, defeating the whole guarantee.
    """
    if path != REPO and REPO not in path.parents:
        return False
    if path in tracked:
        return True
    prefix = path.as_posix() + "/"
    return any(f.as_posix().startswith(prefix) for f in tracked)
