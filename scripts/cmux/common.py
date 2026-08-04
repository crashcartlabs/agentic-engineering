"""Shared safety-critical primitives for cmux orchestration."""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path


AGENTS = ("claude", "codex", "pi")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def agent_launch_line(
    agent: str,
    model: str,
    task: str,
    *,
    cwd: Path | None = None,
    unsafe_yolo: bool = False,
) -> str:
    """Build one shell-safe launch line; bypass flags require explicit opt-in."""
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}; must be one of {list(AGENTS)}")
    model_arg = shlex.quote(model)
    task_arg = shlex.quote(task)
    if agent == "claude":
        bypass = " --dangerously-skip-permissions" if unsafe_yolo else ""
        line = f"claude{bypass} --model {model_arg} {task_arg}"
    elif agent == "codex":
        bypass = " --dangerously-bypass-approvals-and-sandbox" if unsafe_yolo else ""
        line = f"codex{bypass} -m {model_arg} {task_arg}"
    else:
        line = f"pi --model {model_arg} {task_arg}"
    if cwd is not None:
        line = f"cd {shlex.quote(str(cwd))} && {line}"
    return line


def write_text_exclusive(path: Path, text: str) -> None:
    """Create a UTF-8 file without following symlinks or crossing a TOCTOU gap."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ELOOP}:
            raise FileExistsError(path) from exc
        raise
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def fleet_manifest_path(repo: Path, run_slug: str) -> Path:
    """Return the owner-local manifest path under Git common state, never the checkout."""
    root_proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    common_proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if root_proc.returncode or common_proc.returncode:
        raise ValueError(f"cannot resolve Git state for {repo}")
    root = Path(root_proc.stdout.strip()).resolve()
    common = Path(common_proc.stdout.strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    return common / "agentic-engineering" / "cmux-fleets" / f"{run_slug}.json"


def write_private_json(path: Path, payload: dict) -> None:
    """Atomically write owner-only JSON without following a final-path symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temp_name, 0o600)
        if path.is_symlink():
            raise FileExistsError(path)
        os.replace(temp_name, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def load_fleet_manifest(repo: Path, run_slug: str) -> tuple[Path, dict]:
    path = fleet_manifest_path(repo, run_slug)
    if path.is_symlink():
        raise ValueError(f"refusing symlinked fleet manifest: {path}")
    if os.name != "nt" and path.exists() and (path.stat().st_mode & 0o077):
        raise ValueError(f"fleet manifest is not owner-only: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read fleet manifest {path}: {exc}") from exc
    root = Path(
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    ).resolve()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("run_slug") != run_slug
        or payload.get("repo") != str(root)
        or not isinstance(payload.get("entries"), list)
    ):
        raise ValueError(f"fleet manifest failed identity/schema validation: {path}")
    for entry in payload["entries"]:
        if not isinstance(entry, dict):
            raise ValueError(f"fleet manifest contains a non-object entry: {path}")
        for key in ("workspace_ref", "surface_ref"):
            value = entry.get(key)
            if value is not None and (not isinstance(value, str) or not UUID_RE.fullmatch(value)):
                raise ValueError(f"fleet manifest contains an unsafe {key}: {path}")
    return path, payload
