#!/usr/bin/env python3
"""Bootstrap a cmux fleet: worktrees + cmux workspaces/panes, one per entry.

Usage: spawn_fleet.py --repo <path> --entry "label:agent:model:description"
       [--entry ...] --arrange {tabs,grid} [--run-slug <slug>]
       [--orchestrator claude|none] [--env-file <path>]
       spawn_fleet.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from common import (
    AGENTS,
    fleet_manifest_path,
    load_fleet_manifest,
    agent_launch_line as shared_agent_launch_line,
    write_private_json,
    write_text_exclusive,
)

CMUX_BIN_CANDIDATES = ["cmux", "/Applications/cmux.app/Contents/Resources/bin/cmux"]
CMUX_CONFIG_PATH = Path.home() / ".config" / "cmux" / "cmux.json"
UUID_RE = re.compile(r"[0-9a-fA-F-]{36}")


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


@dataclass
class Entry:
    label: str
    agent: str
    model: str
    description: str


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_entry(raw: str) -> Entry:
    # split(":", 3) takes the first 3 colons only, so `model` can never itself
    # contain a colon here -- a model needing one (e.g. pi's "sonnet:high"
    # thinking-level shorthand) silently gets truncated into `description`
    # instead. This format doesn't support colon-containing model IDs; if
    # that's ever needed, the delimiter itself has to change.
    parts = raw.split(":", 3)
    if len(parts) != 4:
        raise ValueError(f"--entry must be 'label:agent:model:description', got: {raw!r}")
    label, agent, model, description = parts
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}; must be one of {sorted(AGENTS)}")
    label, model, description = label.strip(), model.strip(), description.strip()
    if not label or not description:
        raise ValueError(f"--entry label and description must be non-empty, got: {raw!r}")
    if not model:
        raise ValueError(f"--entry model must be non-empty, got: {raw!r}")
    normalized_label = slugify(label)
    if not normalized_label:
        raise ValueError(f"--entry label becomes empty after slugification: {label!r}")
    return Entry(label=normalized_label, agent=agent, model=model, description=description)


def derive_run_slug(entries: list[Entry], explicit: str | None, now: float) -> str:
    if explicit:
        normalized = slugify(explicit)
        if not normalized:
            raise ValueError(f"--run-slug becomes empty after slugification: {explicit!r}")
        return normalized
    if not entries:
        raise ValueError("derive_run_slug requires at least one entry when no explicit run-slug is given")
    base = slugify(entries[0].description)[:40].strip("-") or "fleet"
    suffix = format(int(now), "x")
    return f"{base}-{suffix}"


TASK_FILE_NAME = "TASK.md"
TASK_POINTER_PROMPT = "Read TASK.md in the current directory and do exactly what it says."


def exclude_from_worktree_git(dir_path: Path, entry: str) -> None:
    """Add `entry` to dir_path's git info/exclude, so an untracked file (e.g.
    TASK.md) written into it doesn't show up in `git status`/`git add .` --
    without this, a launched agent using a broad staging command can
    accidentally commit the orchestration prompt into its own result
    (confirmed live). A worktree's `.git` is a file pointing at the real
    git-dir, not a directory, so `git rev-parse --git-path` is used to find
    the real info/exclude location instead of assuming `<dir>/.git/info/exclude`.
    Skips gracefully if dir_path isn't inside a git repo at all.
    The written pattern is anchored with a leading '/' -- gitignore/exclude
    semantics treat a slash-free pattern as matching that basename in every
    directory of the tree, not just the root where TASK.md is always
    written, so a bare pattern would also hide an unrelated same-named file
    nested elsewhere in the repo (confirmed live).
    Kept in sync with scripts/cmux/send_task.py's copy of this helper."""
    proc = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "--git-path", "info/exclude"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return
    exclude_path = Path(proc.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = dir_path / exclude_path
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    anchored_entry = entry if entry.startswith("/") else f"/{entry}"
    existing = exclude_path.read_text() if exclude_path.exists() else ""
    if anchored_entry not in existing.splitlines():
        with exclude_path.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(anchored_entry + "\n")
    warn_if_exclude_ineffective(dir_path, entry)


def entry_visible_in_git_status(dir_path: Path, entry: str) -> bool:
    """True if `entry` still shows up in `git status --porcelain` for
    dir_path -- meaning some higher-priority ignore source (a repo's own
    tracked .gitignore takes precedence over info/exclude) is overriding the
    info/exclude entry we just added."""
    proc = subprocess.run(
        ["git", "-C", str(dir_path), "status", "--porcelain", "--", entry],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def warn_if_exclude_ineffective(dir_path: Path, entry: str) -> None:
    """info/exclude is git's lowest-priority ignore source: a repo's own
    tracked .gitignore (e.g. a `!entry` negation, or a broad `!*` after a
    `*`) can still override it, leaving `entry` trackable/untracked despite
    the exclude entry just added -- silently defeating the whole point of
    excluding it. This is a soft convenience layer, not a correctness-critical
    guard (unlike the overwrite-refusal in resolve_task_text), so warn rather
    than die() -- aborting an otherwise-successful worktree/pane bootstrap
    over it would be the wrong tradeoff.
    Kept in sync with scripts/cmux/send_task.py's copy of this helper."""
    if entry_visible_in_git_status(dir_path, entry):
        print(
            f"warning: {entry} in {dir_path} is still visible to `git status` despite the "
            f"info/exclude entry just added -- a tracked .gitignore pattern in that repo may "
            f"be overriding it; {entry} could end up committed by an agent running a broad "
            "`git add`",
            file=sys.stderr,
        )


def resolve_task_text(description: str, worktree_dir: Path) -> str:
    """cmux delivers a pane's initial --command by typing it into the pane's
    shell as keystrokes, not by exec'ing it as a process argument -- so a
    multi-line description has each '\\n' land as a real Enter press,
    submitting a partial command before shlex.quote()'s closing quote is
    typed. Confirmed live: this hung one agent's shell in an open quote
    (claude never launched) and garbled the prompt text in two others.
    Route around it entirely for anything multi-line: write the real spec to
    a file in the worktree and launch with a short single-line pointer
    instead."""
    if "\n" not in description:
        return description
    task_path = worktree_dir / TASK_FILE_NAME
    try:
        write_text_exclusive(task_path, description)
    except FileExistsError:
        die(f"{task_path} already exists in this worktree (including a symlink) -- refusing to overwrite it with the fleet task text")
    exclude_from_worktree_git(worktree_dir, TASK_FILE_NAME)
    return TASK_POINTER_PROMPT


def agent_launch_line(
    agent: str,
    model: str,
    description: str,
    cwd: Path | None = None,
    *,
    unsafe_yolo: bool = False,
) -> str:
    return shared_agent_launch_line(
        agent, model, description, cwd=cwd, unsafe_yolo=unsafe_yolo
    )


def build_grid_layout(pairs: list[tuple[Entry, Path]], *, unsafe_yolo: bool = False) -> dict:
    """Balanced binary-split tree, one pane per (entry, worktree) pair.

    Alternates split direction per level so 4 entries render as a 2x2 grid
    and 8 as a balanced 8-way split, matching cmux's own split-pane model
    (there is no literal rows x cols grid primitive).
    """

    if not pairs:
        raise ValueError("build_grid_layout requires at least one entry")

    def leaf(entry: Entry, worktree: Path) -> dict:
        task_text = resolve_task_text(entry.description, worktree)
        line = agent_launch_line(
            entry.agent, entry.model, task_text, cwd=worktree, unsafe_yolo=unsafe_yolo
        )
        return {"pane": {"surfaces": [{"type": "terminal", "name": entry.label, "command": line}]}}

    def build(items: list[tuple[Entry, Path]], direction: str) -> dict:
        if len(items) == 1:
            entry, worktree = items[0]
            return leaf(entry, worktree)
        mid = len(items) // 2
        next_direction = "vertical" if direction == "horizontal" else "horizontal"
        return {
            "direction": direction,
            "split": 0.5,
            "children": [build(items[:mid], next_direction), build(items[mid:], next_direction)],
        }

    return build(pairs, "horizontal")


def build_manifest(run_slug: str, repo: Path, arrange: str, entries: list[Entry], placements: list[dict]) -> dict:
    if len(entries) != len(placements):
        raise ValueError(
            f"build_manifest: entries ({len(entries)}) and placements ({len(placements)}) must be the same length"
        )
    return {
        "schema_version": 1,
        "run_slug": run_slug,
        "repo": str(repo),
        "arrange": arrange,
        "entries": [
            {
                "label": e.label, "agent": e.agent, "model": e.model, "description": e.description,
                **p,
            }
            for e, p in zip(entries, placements)
        ],
    }


def _write_partial_manifest(
    manifest_path: Path, run_slug: str, repo: Path, arrange: str, entries: list[Entry], placements: list[dict]
) -> None:
    """On a mid-loop failure, record whatever entries succeeded before it --
    otherwise a worktree (and, in spawn_tabs, an already-live cmux pane)
    created earlier in the loop has no manifest entry at all, leaving
    `/cmux check|collect|teardown` nothing to find or clean it up with."""
    if not placements:
        return
    partial = build_manifest(run_slug, repo, arrange, entries[: len(placements)], placements)
    partial["partial"] = True
    write_private_json(manifest_path, partial)


def find_cmux_bin() -> str:
    for candidate in CMUX_BIN_CANDIDATES:
        if "/" in candidate:
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    die("cmux CLI not found on PATH or at /Applications/cmux.app/Contents/Resources/bin/cmux")
    raise AssertionError("unreachable")  # die() exits; this satisfies type checkers


def cmux(bin_path: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CMUX_QUIET": "1"}
    return subprocess.run([bin_path, *args], capture_output=True, text=True, env=env)


def cmux_json(bin_path: str, *args: str) -> dict | None:
    proc = cmux(bin_path, *args)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _cmux_uuid(payload: dict | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F-]{36}", value) is None:
        return None
    return value


def _close_incomplete_workspace(bin_path: str, payload: dict | None) -> None:
    """Best-effort rollback when cmux created something but omitted durable UUIDs."""
    if not isinstance(payload, dict):
        return
    reference = _cmux_uuid(payload, "workspace_id") or payload.get("workspace_ref")
    if isinstance(reference, str) and reference:
        cmux(bin_path, "workspace", "close", "--workspace", reference)


def _cmux_process_alive() -> bool:
    return subprocess.run(["pgrep", "-f", "Contents/MacOS/cmux"], capture_output=True).returncode == 0


def ensure_cmux_running(bin_path: str) -> None:
    if cmux(bin_path, "ping").returncode == 0:
        return
    if _cmux_process_alive():
        # The app is running but refused our ping -- under socketControlMode
        # cmuxOnly, `ping` itself is refused from outside a cmux pane even
        # though the app is fully up (confirmed live), so process liveness
        # is the only reliable "is it running" signal here. Don't relaunch
        # or spin on ping (which can never succeed while that policy holds);
        # ensure_socket_allowall(), called next, is what actually fixes this.
        return
    subprocess.run(["open", "-a", "cmux"])
    for _ in range(40):
        time.sleep(0.5)
        if cmux(bin_path, "ping").returncode == 0 or _cmux_process_alive():
            return
    die("cmux failed to start within 20s; check for an onboarding/permission dialog")


def _capabilities_allowall(bin_path: str, tries: int = 6) -> bool:
    # A single un-polled check can be a false negative right after
    # ensure_cmux_running returns: process-liveness is confirmed before the
    # socket server has necessarily finished initializing, so a socket that
    # is merely still starting up would otherwise look identical to one
    # genuinely refusing us under cmuxOnly.
    for i in range(tries):
        caps = cmux_json(bin_path, "capabilities")
        if caps and caps.get("access_mode") == "allowAll":
            return True
        if i < tries - 1:
            time.sleep(0.5)
    return False


def _capabilities_accessible(bin_path: str, tries: int = 6) -> bool:
    """True when the current caller can use cmux under either supported policy."""
    for i in range(tries):
        caps = cmux_json(bin_path, "capabilities")
        if caps and caps.get("access_mode") in {"cmuxOnly", "allowAll"}:
            return True
        if i < tries - 1:
            time.sleep(0.5)
    return False


def ensure_socket_allowall(bin_path: str) -> None:
    if _capabilities_allowall(bin_path):
        return
    print("cmux socketControlMode is not allowAll; raising it (backing up cmux.json first)...")
    config: dict = {}
    if CMUX_CONFIG_PATH.exists():
        config = json.loads(CMUX_CONFIG_PATH.read_text())
        backup = CMUX_CONFIG_PATH.with_name(CMUX_CONFIG_PATH.name + f".bak.{int(time.time())}")
        shutil.copy2(CMUX_CONFIG_PATH, backup)
    config.setdefault("automation", {})["socketControlMode"] = "allowAll"
    CMUX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CMUX_CONFIG_PATH.write_text(json.dumps(config, indent=2))
    # reload-config is itself refused under cmuxOnly, so a full restart is
    # required to pick up the new policy from disk (confirmed live).
    subprocess.run(["osascript", "-e", 'tell application "cmux" to quit'])
    time.sleep(2)
    ensure_cmux_running(bin_path)
    if not _capabilities_allowall(bin_path, tries=40):
        die("failed to raise cmux's socketControlMode to allowAll after restart")


def find_or_create_window(bin_path: str) -> str:
    proc = cmux(bin_path, "list-windows")
    match = UUID_RE.search(proc.stdout or "")
    if match:
        return match.group(0)
    proc = cmux(bin_path, "new-window")
    match = UUID_RE.search(proc.stdout or "")
    if not match:
        die(f"failed to create a cmux window: {proc.stdout}{proc.stderr}")
    return match.group(0)


def resolve_repo_root(path: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"{path} is not inside a git repository: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def worktree_path_for(repo: Path, run_slug: str, label: str) -> Path:
    return repo.parent / f"{repo.name}-worktrees" / f"{run_slug}-{label}"


def branch_name_for(run_slug: str, label: str) -> str:
    return f"cmux/{run_slug}-{label}"


def branch_exists(repo: Path, branch: str) -> bool:
    # Git's ref namespace is hierarchical (refs/heads/ is a tree, not a flat
    # list), so an exact-match probe alone misses two real collision shapes
    # that still make `git worktree add -b <branch>` fail with "cannot lock
    # ref": (a) a ref already exists *nested under* the target (e.g.
    # refs/heads/cmux/run-x-api/sub blocks creating refs/heads/cmux/run-x-api),
    # and (b) an ancestor path component of the target is itself already a
    # ref (e.g. a branch literally named "cmux" blocks any cmux/* branch).
    # Confirmed live: `show-ref --verify` returns false in both cases even
    # though branch creation genuinely fails.
    if subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo).returncode == 0:
        return True
    child_probe = subprocess.run(
        ["git", "for-each-ref", f"refs/heads/{branch}/"], cwd=repo, capture_output=True, text=True,
    )
    if child_probe.stdout.strip():
        return True
    parts = branch.split("/")
    for i in range(1, len(parts)):
        ancestor = "/".join(parts[:i])
        if subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{ancestor}"], cwd=repo).returncode == 0:
            return True
    return False


def preflight_worktree_paths(repo: Path, run_slug: str, entries: list[Entry]) -> None:
    """Check every entry's worktree path, branch name, and label uniqueness
    before creating anything -- any collision on a later entry must not
    leave earlier entries' cmux workspaces running with nothing recorded to
    track or tear them down."""
    seen_labels: dict[str, str] = {}
    duplicate_labels = []
    for e in entries:
        if e.label in seen_labels:
            duplicate_labels.append(e.label)
        seen_labels[e.label] = e.description
    if duplicate_labels:
        die(f"duplicate entry label(s) after slugifying: {sorted(set(duplicate_labels))}")

    collisions = [str(p) for e in entries if (p := worktree_path_for(repo, run_slug, e.label)).exists()]
    if collisions:
        die("worktree(s) already exist: " + ", ".join(collisions))

    existing_branches = [b for e in entries if branch_exists(repo, (b := branch_name_for(run_slug, e.label)))]
    if existing_branches:
        die("branch(es) already exist: " + ", ".join(existing_branches))


def create_worktree(repo: Path, run_slug: str, label: str) -> tuple[Path, str]:
    branch = branch_name_for(run_slug, label)
    worktree_dir = worktree_path_for(repo, run_slug, label)
    if worktree_dir.exists():
        die(f"worktree already exists: {worktree_dir}")
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), "-b", branch],
        cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        die(f"git worktree add failed for {label}: {proc.stderr.strip()}")
    return worktree_dir, branch


def spawn_tabs(
    bin_path: str, repo: Path, run_slug: str, entries: list[Entry], window: str, env_file: Path | None,
    manifest_path: Path, *, unsafe_yolo: bool = False,
) -> list[dict]:
    placements: list[dict] = []
    try:
        for entry in entries:
            worktree_dir, branch = create_worktree(repo, run_slug, entry.label)
            # Record this entry's worktree/branch right away, with placeholder
            # refs, so a failure in resolve_task_text() (or anything below)
            # still leaves this entry in `placements` -- its worktree already
            # exists on disk by this point and needs a manifest entry for
            # /cmux collect/teardown to find it by, even if the pane was never
            # created (Finding 3).
            placement = {
                "worktree_path": str(worktree_dir), "branch": branch, "window_ref": window,
                "workspace_ref": None, "surface_ref": None,
            }
            placements.append(placement)
            _write_partial_manifest(manifest_path, run_slug, repo, "tabs", entries, placements)
            task_text = resolve_task_text(entry.description, worktree_dir)
            line = agent_launch_line(
                entry.agent, entry.model, task_text, unsafe_yolo=unsafe_yolo
            )
            args = [
                "workspace", "create", "--name", entry.label, "--window", window,
                "--cwd", str(worktree_dir), "--command", line, "--id-format", "both", "--json",
            ]
            if env_file:
                args += ["--env-file", str(env_file)]
            created = cmux_json(bin_path, *args)
            if not created:
                die(f"failed to create workspace for entry {entry.label}")
            workspace_id = _cmux_uuid(created, "workspace_id")
            surface_id = _cmux_uuid(created, "surface_id")
            if workspace_id is not None:
                placement["workspace_ref"] = workspace_id
            if surface_id is not None:
                placement["surface_ref"] = surface_id
            _write_partial_manifest(manifest_path, run_slug, repo, "tabs", entries, placements)
            if workspace_id is None or surface_id is None:
                _close_incomplete_workspace(bin_path, created)
                die(f"cmux returned incomplete workspace identifiers for entry {entry.label}")
            # Store UUIDs, not positional refs (workspace:N/surface:N) -- those
            # renumber as things open/close, so a manifest driven minutes/hours
            # later (check/collect/teardown) needs the stable UUID form, which
            # --id-format both provides alongside the positional one.
            cmux(bin_path, "workspace-action", "--action", "set-color", "--workspace", workspace_id, "--color", "Teal")
    except BaseException:
        _write_partial_manifest(manifest_path, run_slug, repo, "tabs", entries, placements)
        raise
    return placements


def spawn_grid(
    bin_path: str, repo: Path, run_slug: str, entries: list[Entry], window: str, env_file: Path | None,
    manifest_path: Path, *, unsafe_yolo: bool = False,
) -> list[dict]:
    worktrees: list[tuple[Path, str]] = []
    workspace_id: str | None = None
    surface_id: str | None = None
    try:
        for e in entries:
            worktrees.append(create_worktree(repo, run_slug, e.label))
            partial_placements = [
                {
                    "worktree_path": str(wt), "branch": branch, "window_ref": window,
                    "workspace_ref": None, "surface_ref": None,
                }
                for wt, branch in worktrees
            ]
            _write_partial_manifest(
                manifest_path, run_slug, repo, "grid", entries, partial_placements
            )

        args = ["workspace", "create", "--name", run_slug, "--window", window, "--cwd", str(repo), "--id-format", "both", "--json"]
        if env_file:
            args += ["--env-file", str(env_file)]

        if len(entries) == 1:
            worktree_dir, _branch = worktrees[0]
            task_text = resolve_task_text(entries[0].description, worktree_dir)
            line = agent_launch_line(
                entries[0].agent,
                entries[0].model,
                task_text,
                cwd=worktree_dir,
                unsafe_yolo=unsafe_yolo,
            )
            args += ["--command", line]
        else:
            # build_grid_layout()'s leaf() closure calls resolve_task_text()
            # per entry -- a failure there (e.g. a worktree's repo already
            # tracks TASK.md) must hit the same salvage handler below as the
            # single-entry call above and the worktree-creation loop, so it's
            # kept inside this same try instead of a second try/except.
            pairs = [(e, wt[0]) for e, wt in zip(entries, worktrees)]
            args += ["--layout", json.dumps(build_grid_layout(pairs, unsafe_yolo=unsafe_yolo))]

        # The actual workspace-creation call must stay inside this same try:
        # by this point every entry in `worktrees` already has a real
        # worktree on disk, so a failure here (bad --env-file, a dropped
        # cmux socket, cmux itself rejecting the workspace/layout) still
        # needs the same salvage handling below -- otherwise die() below
        # fires with no manifest ever written, even though nothing on disk
        # needs cleaning up.
        created = cmux_json(bin_path, *args)
        if not created:
            die(f"failed to create grid workspace for run {run_slug}")
        workspace_id = _cmux_uuid(created, "workspace_id")
        surface_id = _cmux_uuid(created, "surface_id")
        if workspace_id is None or (len(entries) == 1 and surface_id is None):
            _close_incomplete_workspace(bin_path, created)
            die(f"cmux returned incomplete workspace identifiers for grid {run_slug}")
    except BaseException:
        # By the time worktree creation succeeds, every entry in `worktrees`
        # has a real worktree on disk -- true whether the failure below
        # happened during that loop (partial `worktrees`), in the
        # resolve_task_text() calls just above, or in the workspace-creation
        # call itself (complete `worktrees`, but no pane exists yet for any
        # of them).
        partial_placements = [
            {
                "worktree_path": str(wt), "branch": branch, "window_ref": window,
                "workspace_ref": workspace_id,
                "surface_ref": surface_id if len(entries) == 1 else None,
            }
            for wt, branch in worktrees
        ]
        _write_partial_manifest(manifest_path, run_slug, repo, "grid", entries, partial_placements)
        raise

    provisional_placements = [
        {
            "worktree_path": str(worktree_dir),
            "branch": branch,
            "window_ref": window,
            "workspace_ref": workspace_id,
            "surface_ref": surface_id if len(entries) == 1 else None,
        }
        for worktree_dir, branch in worktrees
    ]
    _write_partial_manifest(
        manifest_path, run_slug, repo, "grid", entries, provisional_placements
    )
    cmux(bin_path, "workspace-action", "--action", "set-color", "--workspace", workspace_id, "--color", "Purple")

    if len(entries) == 1:
        # A single surface has no per-pane name to match against (unlike a
        # multi-pane --layout, whose leaves are named entry.label) -- the
        # --json response already names this surface directly, so use it.
        worktree_dir, branch = worktrees[0]
        return [{
            "worktree_path": str(worktree_dir), "branch": branch, "window_ref": window,
            "workspace_ref": workspace_id, "surface_ref": surface_id,
        }]

    # list-pane-surfaces defaults to the *focused* pane only; a multi-pane
    # grid needs every pane's surface, so enumerate panes first (confirmed
    # live: list-pane-surfaces --workspace <ws> alone silently returns just
    # one pane's surface even when the workspace has several). Positional
    # pane refs are fine here -- they're only used to enumerate within this
    # one bootstrap call, never persisted.
    panes_out = ""
    pane_refs: list[str] = []
    for _ in range(20):
        panes_out = cmux(bin_path, "list-panes", "--workspace", workspace_id).stdout
        pane_refs = re.findall(r"pane:\d+", panes_out)
        if len(pane_refs) >= len(entries):
            break
        time.sleep(0.25)
    if len(pane_refs) < len(entries):
        die(
            f"expected {len(entries)} panes in grid workspace {workspace_id}, "
            f"found {len(pane_refs)}: {panes_out.strip()!r}"
        )
    # Match surfaces to entries by the name each was created with (each
    # layout leaf's surface is named entry.label), not by pane-enumeration
    # order -- cmux's pane order isn't a documented contract, and a name
    # match is immune to it. --id-format both makes list-pane-surfaces print
    # "surface:N  <uuid>  <name>"; capture the uuid, not the positional ref,
    # for the same persisted-manifest reason as above.
    surface_by_label: dict[str, str] = {}
    for pane_ref in pane_refs:
        pane_surfaces_out = cmux(
            bin_path, "list-pane-surfaces", "--workspace", workspace_id, "--pane", pane_ref, "--id-format", "both",
        ).stdout
        match = re.search(r"surface:\d+\s+([0-9a-fA-F-]{36})\s+(\S+)", pane_surfaces_out)
        if not match:
            die(f"pane {pane_ref} in grid workspace {workspace_id} has no surfaces: {pane_surfaces_out.strip()!r}")
        surface_by_label[match.group(2)] = match.group(1)

    placements = []
    for entry, (worktree_dir, branch) in zip(entries, worktrees):
        surface_id = surface_by_label.get(entry.label)
        if surface_id is None:
            die(
                f"no pane named {entry.label!r} found in grid workspace {workspace_id}; "
                f"found names: {sorted(surface_by_label)}"
            )
        placements.append({
            "worktree_path": str(worktree_dir), "branch": branch, "window_ref": window,
            "workspace_ref": workspace_id, "surface_ref": surface_id,
        })
    return placements


def exec_orchestrator(
    manifest_path: Path, run_slug: str, repo: Path, *, unsafe_yolo: bool = False
) -> None:
    os.chdir(repo)
    prompt = (
        f"You are the orchestrator for cmux fleet '{run_slug}'. It is already "
        f"running — manifest at {manifest_path}. Use the /cmux skill's "
        "check/collect/teardown workflows against this manifest to monitor "
        "the agents, compare their results once they finish, and report "
        "which solution is best."
    )
    sys.stdout.flush()
    argv = ["claude"]
    if unsafe_yolo:
        argv.append("--dangerously-skip-permissions")
    argv.append(prompt)
    os.execvp("claude", argv)


def selftest() -> int:
    ok = True

    original_cmux_json = globals()["cmux_json"]
    try:
        globals()["cmux_json"] = lambda _bin, *_args: {"access_mode": "cmuxOnly"}
        if not _capabilities_accessible("cmux", tries=1):
            print("selftest: cmuxOnly caller should be accepted FAIL")
            ok = False
    finally:
        globals()["cmux_json"] = original_cmux_json
    if _cmux_uuid({"workspace_id": "missing"}, "workspace_id") is not None:
        print("selftest: malformed cmux UUID should be rejected FAIL")
        ok = False

    state_repo = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-manifest-state-"))
    try:
        subprocess.run(["git", "init", "--quiet"], cwd=state_repo, check=True)
        state_path = fleet_manifest_path(state_repo, "secure-run")
        state_manifest = build_manifest(
            "secure-run",
            state_repo.resolve(),
            "tabs",
            [Entry("one", "pi", "m", "task")],
            [{
                "worktree_path": str(state_repo / "wt"),
                "branch": "cmux/secure-run-one",
                "window_ref": "window",
                "workspace_ref": "11111111-1111-1111-1111-111111111111",
                "surface_ref": "22222222-2222-2222-2222-222222222222",
            }],
        )
        write_private_json(state_path, state_manifest)
        loaded_path, loaded = load_fleet_manifest(state_repo, "secure-run")
        if loaded_path != state_path or loaded.get("run_slug") != "secure-run":
            print("selftest: owner-local manifest validation FAIL")
            ok = False
        if ".git" not in state_path.parts or (os.name != "nt" and stat.S_IMODE(state_path.stat().st_mode) != 0o600):
            print("selftest: owner-local manifest location/mode FAIL", state_path)
            ok = False
        lock_path = state_path.with_suffix(".lock")
        identity = acquire_run_lock(lock_path)
        try:
            try:
                acquire_run_lock(lock_path)
                print("selftest: concurrent run lock should fail FAIL")
                ok = False
            except SystemExit:
                pass
        finally:
            release_run_lock(lock_path, identity)
    finally:
        shutil.rmtree(state_repo, ignore_errors=True)

    if slugify("Add Dark Mode!") != "add-dark-mode":
        print("selftest: slugify FAIL")
        ok = False

    e = parse_entry("plan-a:codex:gpt-5.5:Add a health endpoint: returns 200 OK")
    if not (
        e.label == "plan-a"
        and e.agent == "codex"
        and e.model == "gpt-5.5"
        and e.description == "Add a health endpoint: returns 200 OK"
    ):
        print("selftest: parse_entry FAIL", e)
        ok = False

    try:
        parse_entry("bad-entry-no-colons")
        print("selftest: parse_entry should have raised FAIL")
        ok = False
    except ValueError:
        pass

    try:
        parse_entry("label:pi::reply ready")
        print("selftest: parse_entry empty model should have raised FAIL")
        ok = False
    except ValueError:
        pass

    try:
        parse_entry("!!!:pi:model:reply ready")
        print("selftest: parse_entry empty slug should have raised FAIL")
        ok = False
    except ValueError:
        pass

    slug = derive_run_slug([e], None, 1735689600.0)
    if not slug.startswith("add-a-health-endpoint"):
        print("selftest: derive_run_slug FAIL", slug)
        ok = False
    if derive_run_slug([e], "My Run", 0.0) != "my-run":
        print("selftest: derive_run_slug explicit FAIL")
        ok = False
    try:
        derive_run_slug([e], "!!!", 0.0)
        print("selftest: derive_run_slug empty explicit slug should have raised FAIL")
        ok = False
    except ValueError:
        pass

    line = agent_launch_line("codex", "gpt-5.5", "do the thing")
    if "codex -m gpt-5.5" not in line or "dangerously" in line:
        print("selftest: agent_launch_line safe codex FAIL", line)
        ok = False
    unsafe_line = agent_launch_line(
        "codex", "gpt-5.5", "do the thing", unsafe_yolo=True
    )
    if "codex --dangerously-bypass-approvals-and-sandbox -m gpt-5.5" not in unsafe_line:
        print("selftest: agent_launch_line unsafe codex FAIL", unsafe_line)
        ok = False

    line_cwd = agent_launch_line("pi", "m", "do the thing", cwd=Path("/tmp/wt0"))
    if not line_cwd.startswith("cd /tmp/wt0 && pi --model m"):
        print("selftest: agent_launch_line cwd FAIL", line_cwd)
        ok = False

    unsafe_model_line = agent_launch_line("pi", "m; touch /tmp/pwned", "do the thing")
    # shlex.split simulates real shell tokenizing: the unsafe model must
    # survive as ONE argument to --model, not split into a second command.
    tokens = shlex.split(unsafe_model_line)
    if tokens[tokens.index("--model") + 1] != "m; touch /tmp/pwned":
        print("selftest: agent_launch_line unsafe model FAIL", unsafe_model_line, tokens)
        ok = False

    pairs4 = [(Entry(label=f"e{i}", agent="pi", model="m", description="d"), Path(f"/tmp/wt{i}")) for i in range(4)]
    layout = build_grid_layout(pairs4)
    if layout.get("direction") != "horizontal" or len(layout.get("children", [])) != 2:
        print("selftest: build_grid_layout top FAIL", layout)
        ok = False
    else:
        child = layout["children"][0]
        if "children" not in child or len(child["children"]) != 2:
            print("selftest: build_grid_layout depth FAIL", child)
            ok = False
        else:
            leaf = child["children"][0]
            cmd = leaf["pane"]["surfaces"][0]["command"]
            if not cmd.startswith("cd /tmp/wt0 && pi --model m"):
                print("selftest: build_grid_layout leaf command FAIL", cmd)
                ok = False

    manifest = build_manifest(
        "run-1", Path("/tmp/repo"), "tabs", [e],
        [{"worktree_path": "/tmp/repo-worktrees/run-1-plan-a", "branch": "cmux/run-1-plan-a",
          "window_ref": "window:1", "workspace_ref": "workspace:2", "surface_ref": "surface:3"}],
    )
    if manifest.get("run_slug") != "run-1" or len(manifest.get("entries", [])) != 1:
        print("selftest: build_manifest FAIL", manifest)
        ok = False

    try:
        build_grid_layout([])
        print("selftest: build_grid_layout empty should have raised FAIL")
        ok = False
    except ValueError:
        pass

    try:
        derive_run_slug([], None, 0.0)
        print("selftest: derive_run_slug empty should have raised FAIL")
        ok = False
    except ValueError:
        pass
    if derive_run_slug([], explicit="My Run", now=0.0) != "my-run":
        print("selftest: derive_run_slug empty with explicit FAIL")
        ok = False

    try:
        build_manifest("run-1", Path("/tmp/repo"), "tabs", [e, e], [{"worktree_path": "/tmp/wt0"}])
        print("selftest: build_manifest mismatched lengths should have raised FAIL")
        ok = False
    except ValueError:
        pass

    try:
        agent_launch_line("nonexistent-agent", "m", "task")
        print("selftest: agent_launch_line unknown agent should have raised FAIL")
        ok = False
    except ValueError:
        pass

    preflight_repo = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-preflight-"))
    existing_wt = worktree_path_for(preflight_repo, "run-x", "taken")
    existing_wt.mkdir(parents=True, exist_ok=True)
    try:
        preflight_worktree_paths(preflight_repo, "run-x", [Entry(label="taken", agent="pi", model="m", description="d")])
        print("selftest: preflight_worktree_paths should have raised FAIL")
        ok = False
    except SystemExit:
        pass
    finally:
        existing_wt.rmdir()
        existing_wt.parent.rmdir()
        shutil.rmtree(preflight_repo, ignore_errors=True)

    # Duplicate-label detection fires before any filesystem/git check, so it
    # doesn't need a real repo directory.
    try:
        preflight_worktree_paths(
            preflight_repo, "run-x",
            [Entry(label="dup", agent="pi", model="m", description="d1"), Entry(label="dup", agent="pi", model="m", description="d2")],
        )
        print("selftest: preflight_worktree_paths duplicate label should have raised FAIL")
        ok = False
    except SystemExit:
        pass

    if branch_name_for("run-x", "solo") != "cmux/run-x-solo":
        print("selftest: branch_name_for FAIL")
        ok = False

    task_wt = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-task-"))
    try:
        single_line = "do the thing"
        if resolve_task_text(single_line, task_wt) != single_line:
            print("selftest: resolve_task_text single-line FAIL")
            ok = False
        if (task_wt / TASK_FILE_NAME).exists():
            print("selftest: resolve_task_text single-line wrote a TASK.md FAIL")
            ok = False

        multi_line = "line one\nline two"
        resolved = resolve_task_text(multi_line, task_wt)
        if resolved != TASK_POINTER_PROMPT:
            print("selftest: resolve_task_text multi-line pointer FAIL", resolved)
            ok = False
        written = task_wt / TASK_FILE_NAME
        if not written.exists() or written.read_text() != multi_line:
            print("selftest: resolve_task_text multi-line TASK.md contents FAIL")
            ok = False
    finally:
        for f in task_wt.iterdir():
            f.unlink()
        task_wt.rmdir()

    # A worktree that already has its own tracked TASK.md (this repo's own
    # convention) must never be silently clobbered by the fleet task text.
    conflict_wt = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-task-conflict-"))
    try:
        (conflict_wt / TASK_FILE_NAME).write_text("original tracked content\n")
        try:
            resolve_task_text("line one\nline two", conflict_wt)
            print("selftest: resolve_task_text should refuse existing TASK.md FAIL")
            ok = False
        except SystemExit:
            pass
        if (conflict_wt / TASK_FILE_NAME).read_text() != "original tracked content\n":
            print("selftest: resolve_task_text overwrote existing TASK.md FAIL")
            ok = False
    finally:
        for f in conflict_wt.iterdir():
            f.unlink()
        conflict_wt.rmdir()

    # A dangling symlink is not reported by Path.exists(), but an exclusive,
    # no-follow create must still refuse it without writing through the link.
    symlink_wt = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-task-symlink-"))
    outside_task = symlink_wt.parent / "spawn-fleet-selftest-outside-task"
    outside_task.unlink(missing_ok=True)
    try:
        (symlink_wt / TASK_FILE_NAME).symlink_to(outside_task)
        try:
            resolve_task_text("line one\nline two", symlink_wt)
            print("selftest: resolve_task_text should refuse dangling TASK.md symlink FAIL")
            ok = False
        except SystemExit:
            pass
        if outside_task.exists():
            print("selftest: dangling TASK.md symlink target was written FAIL")
            ok = False
    finally:
        (symlink_wt / TASK_FILE_NAME).unlink(missing_ok=True)
        outside_task.unlink(missing_ok=True)
        symlink_wt.rmdir()

    # Finding 2: writing TASK.md into a real worktree must exclude it via that
    # worktree's git info/exclude, so it doesn't show up in `git status`/`git
    # add .` and can't get accidentally committed by an agent working there.
    exclude_repo = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-exclude-repo-"))
    exclude_wt = exclude_repo.parent / f"{exclude_repo.name}-wt"
    try:
        subprocess.run(["git", "init", "-q"], cwd=exclude_repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=exclude_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=exclude_repo, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=exclude_repo, check=True)
        subprocess.run(
            ["git", "worktree", "add", "-q", str(exclude_wt), "-b", "exclude-test"], cwd=exclude_repo, check=True,
        )
        resolve_task_text("line one\nline two", exclude_wt)
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=exclude_wt, capture_output=True, text=True, check=True,
        ).stdout
        if "TASK.md" in status:
            print("selftest: resolve_task_text did not exclude TASK.md from git status FAIL", repr(status))
            ok = False
        exclude_file = Path(
            subprocess.run(
                ["git", "-C", str(exclude_wt), "rev-parse", "--git-path", "info/exclude"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        )
        if not exclude_file.is_absolute():
            exclude_file = exclude_wt / exclude_file
        if f"/{TASK_FILE_NAME}" not in exclude_file.read_text().splitlines():
            print("selftest: TASK.md not added to worktree git info/exclude as an anchored '/TASK.md' pattern FAIL (Finding 3)")
            ok = False

        # Finding 3: the exclude pattern must be anchored to the worktree
        # root -- a bare `TASK.md` pattern would also hide an unrelated
        # nested `sub/TASK.md`, which is a real correctness gap for anyone
        # relying on `git status` to see all their real changes.
        (exclude_wt / "sub").mkdir(parents=True, exist_ok=True)
        (exclude_wt / "sub" / TASK_FILE_NAME).write_text("unrelated nested file\n")
        status_all = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=exclude_wt, capture_output=True, text=True, check=True,
        ).stdout
        if "sub/TASK.md" not in status_all:
            print("selftest: anchored exclude pattern incorrectly hid sub/TASK.md FAIL (Finding 3)", repr(status_all))
            ok = False
        if "TASK.md" in status_all.replace("sub/TASK.md", ""):
            print("selftest: root TASK.md unexpectedly visible in git status FAIL (Finding 3)", repr(status_all))
            ok = False
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(exclude_wt)], cwd=exclude_repo, capture_output=True)
        shutil.rmtree(exclude_repo, ignore_errors=True)
        shutil.rmtree(exclude_wt, ignore_errors=True)

    # Finding 2, negation-override case: a repo whose tracked .gitignore has
    # a `!TASK.md`-style negation takes precedence over info/exclude
    # (info/exclude is git's lowest-priority ignore source), so TASK.md
    # stays visible to `git status` despite the exclude entry -- the
    # verification step must detect this, not silently proceed.
    negated_repo = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-negated-gitignore-repo-"))
    try:
        subprocess.run(["git", "init", "-q"], cwd=negated_repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=negated_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=negated_repo, check=True)
        (negated_repo / ".gitignore").write_text("*\n!TASK.md\n")
        subprocess.run(["git", "add", "-f", ".gitignore"], cwd=negated_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=negated_repo, check=True)
        resolve_task_text("line one\nline two", negated_repo)
        if not entry_visible_in_git_status(negated_repo, TASK_FILE_NAME):
            print("selftest: entry_visible_in_git_status did not detect .gitignore negation overriding info/exclude FAIL (Finding 2)")
            ok = False
    finally:
        shutil.rmtree(negated_repo, ignore_errors=True)

    # Finding 2, graceful-skip case: a target dir with no enclosing git repo
    # at all must not raise -- exclude_from_worktree_git is a best-effort
    # convenience, not a hard requirement.
    non_repo_dir = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-not-a-repo-"))
    try:
        resolved = resolve_task_text("line one\nline two", non_repo_dir)
        if resolved != TASK_POINTER_PROMPT:
            print("selftest: resolve_task_text outside a git repo FAIL", resolved)
            ok = False
    finally:
        shutil.rmtree(non_repo_dir, ignore_errors=True)

    # A multi-line description in a grid leaf must resolve the same way --
    # the pane launch line should carry the pointer prompt, and TASK.md
    # should land in that leaf's own worktree, not a shared/wrong one.
    grid_wt = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-grid-task-"))
    try:
        multi_line_entry = Entry(label="e0", agent="pi", model="m", description="line one\nline two")
        leaf_layout = build_grid_layout([(multi_line_entry, grid_wt)])
        leaf_cmd = leaf_layout["pane"]["surfaces"][0]["command"]
        if TASK_POINTER_PROMPT not in leaf_cmd:
            print("selftest: build_grid_layout multi-line leaf command FAIL", leaf_cmd)
            ok = False
        if not (grid_wt / TASK_FILE_NAME).exists():
            print("selftest: build_grid_layout multi-line leaf TASK.md FAIL")
            ok = False
    finally:
        for f in grid_wt.iterdir():
            f.unlink()
        grid_wt.rmdir()

    # A mid-loop failure in spawn_tabs must leave a partial manifest behind
    # instead of an untracked worktree/pane. Reproduce with a real git repo
    # (so create_worktree does a genuine `git worktree add`) and a stub
    # `cmux` binary on PATH (no real cmux app needed): entry 1 fully
    # succeeds, entry 2's worktree also gets created but its worktree
    # inherits a tracked TASK.md from the repo, so resolve_task_text's
    # Finding-A guard raises before entry 2's pane is ever requested (Finding
    # 3: entry 2 must still land in the partial manifest, with null
    # workspace/surface refs, since its worktree genuinely exists on disk).
    # Entry 3 is never reached at all and must be absent from the manifest.
    fleet_repo = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-fleetrepo-"))
    worktrees_root = fleet_repo.parent / f"{fleet_repo.name}-worktrees"
    stub_dir = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-stubbin-"))
    old_path = os.environ.get("PATH", "")
    try:
        subprocess.run(["git", "init", "-q"], cwd=fleet_repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=fleet_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=fleet_repo, check=True)
        (fleet_repo / TASK_FILE_NAME).write_text("pre-existing tracked task file\n")
        subprocess.run(["git", "add", TASK_FILE_NAME], cwd=fleet_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=fleet_repo, check=True)

        stub_cmux = stub_dir / "cmux"
        stub_cmux.write_text(
            "#!/usr/bin/env bash\n"
            'case "$1" in\n'
            "  list-windows|new-window) echo 'window:1 11111111-1111-1111-1111-111111111111' ;;\n"
            '  workspace) if [ "$2" = "create" ]; then '
            "echo '{\"workspace_id\":\"22222222-2222-2222-2222-222222222222\",\"surface_id\":\"33333333-3333-3333-3333-333333333333\"}'; "
            "fi ;;\n"
            "esac\n"
            "exit 0\n"
        )
        stub_cmux.chmod(0o755)
        os.environ["PATH"] = f"{stub_dir}{os.pathsep}{old_path}"

        run_slug = "selftest-partial"
        manifest_path = fleet_repo / ".cmux" / "fleet" / f"{run_slug}.json"
        fleet_entries = [
            Entry(label="e1", agent="pi", model="m", description="single line ok"),
            Entry(label="e2", agent="pi", model="m", description="line one\nline two"),
            Entry(label="e3", agent="pi", model="m", description="never reached"),
        ]
        bin_path = find_cmux_bin()
        window = find_or_create_window(bin_path)
        try:
            spawn_tabs(bin_path, fleet_repo, run_slug, fleet_entries, window, None, manifest_path)
            print("selftest: spawn_tabs should have raised on entry 2 FAIL")
            ok = False
        except SystemExit:
            pass

        if not manifest_path.exists():
            print("selftest: spawn_tabs partial manifest not written FAIL")
            ok = False
        else:
            partial = json.loads(manifest_path.read_text())
            partial_entries = partial.get("entries", [])
            by_label = {pe["label"]: pe for pe in partial_entries}
            if not partial.get("partial") or sorted(by_label) != ["e1", "e2"]:
                print("selftest: spawn_tabs partial manifest contents FAIL", partial)
                ok = False
            elif by_label["e1"]["workspace_ref"] != "22222222-2222-2222-2222-222222222222":
                print("selftest: spawn_tabs partial manifest entry 1 (fully succeeded) FAIL", partial)
                ok = False
            elif by_label["e2"]["workspace_ref"] is not None or by_label["e2"]["surface_ref"] is not None:
                print(
                    "selftest: spawn_tabs partial manifest entry 2 (worktree exists, pane never created) "
                    "should have null refs FAIL (Finding 3)",
                    partial,
                )
                ok = False
            elif not by_label["e2"]["worktree_path"] or not by_label["e2"]["branch"]:
                print("selftest: spawn_tabs partial manifest entry 2 missing worktree/branch FAIL (Finding 3)", partial)
                ok = False

        e2_task = worktree_path_for(fleet_repo, run_slug, "e2") / TASK_FILE_NAME
        if not e2_task.exists() or e2_task.read_text() != "pre-existing tracked task file\n":
            print("selftest: spawn_tabs clobbered entry 2's tracked TASK.md FAIL")
            ok = False

        if worktree_path_for(fleet_repo, run_slug, "e3").exists():
            print("selftest: spawn_tabs should never have created entry 3's worktree FAIL (Finding 3)")
            ok = False

        # Finding 4: spawn_grid's post-worktree-creation resolve_task_text()
        # calls aren't covered by the worktree-creation try/except -- a
        # failure there must still salvage a partial manifest for every
        # worktree that was actually created, in both the single-entry direct
        # call and the multi-entry build_grid_layout() path. Reuse fleet_repo
        # (already has a tracked TASK.md at its root) so any grid worktree
        # here inherits the same conflict.
        grid_single_slug = "selftest-partial-grid-single"
        grid_single_manifest = fleet_repo / ".cmux" / "fleet" / f"{grid_single_slug}.json"
        grid_single_entries = [Entry(label="g1", agent="pi", model="m", description="line one\nline two")]
        try:
            spawn_grid(bin_path, fleet_repo, grid_single_slug, grid_single_entries, window, None, grid_single_manifest)
            print("selftest: spawn_grid single-entry should have raised on resolve_task_text FAIL (Finding 4)")
            ok = False
        except SystemExit:
            pass
        if not grid_single_manifest.exists():
            print("selftest: spawn_grid single-entry partial manifest not written FAIL (Finding 4)")
            ok = False
        else:
            partial = json.loads(grid_single_manifest.read_text())
            partial_entries = partial.get("entries", [])
            if not partial.get("partial") or len(partial_entries) != 1 or partial_entries[0]["label"] != "g1":
                print("selftest: spawn_grid single-entry partial manifest contents FAIL (Finding 4)", partial)
                ok = False
            elif "workspace_ref" not in partial_entries[0] or "surface_ref" not in partial_entries[0]:
                print(
                    "selftest: spawn_grid single-entry partial manifest missing workspace_ref/surface_ref "
                    "keys FAIL (round-2 Finding 3)", partial,
                )
                ok = False
            elif partial_entries[0]["workspace_ref"] is not None or partial_entries[0]["surface_ref"] is not None:
                print(
                    "selftest: spawn_grid single-entry partial manifest workspace_ref/surface_ref should be "
                    "null FAIL (round-2 Finding 3)", partial,
                )
                ok = False

        grid_multi_slug = "selftest-partial-grid-multi"
        grid_multi_manifest = fleet_repo / ".cmux" / "fleet" / f"{grid_multi_slug}.json"
        grid_multi_entries = [
            Entry(label="g1", agent="pi", model="m", description="single line ok"),
            Entry(label="g2", agent="pi", model="m", description="line one\nline two"),
        ]
        try:
            spawn_grid(bin_path, fleet_repo, grid_multi_slug, grid_multi_entries, window, None, grid_multi_manifest)
            print("selftest: spawn_grid multi-entry should have raised on resolve_task_text FAIL (Finding 4)")
            ok = False
        except SystemExit:
            pass
        if not grid_multi_manifest.exists():
            print("selftest: spawn_grid multi-entry partial manifest not written FAIL (Finding 4)")
            ok = False
        else:
            partial = json.loads(grid_multi_manifest.read_text())
            partial_entries = partial.get("entries", [])
            partial_labels = sorted(pe["label"] for pe in partial_entries)
            if not partial.get("partial") or partial_labels != ["g1", "g2"]:
                print("selftest: spawn_grid multi-entry partial manifest contents FAIL (Finding 4)", partial)
                ok = False
            elif any("workspace_ref" not in pe or "surface_ref" not in pe for pe in partial_entries):
                print(
                    "selftest: spawn_grid multi-entry partial manifest missing workspace_ref/surface_ref "
                    "keys FAIL (round-2 Finding 3)", partial,
                )
                ok = False
            elif any(pe["workspace_ref"] is not None or pe["surface_ref"] is not None for pe in partial_entries):
                print(
                    "selftest: spawn_grid multi-entry partial manifest workspace_ref/surface_ref should be "
                    "null FAIL (round-2 Finding 3)", partial,
                )
                ok = False

        # Finding 2 (round 3): spawn_grid's own `cmux_json(bin_path, *args)`
        # call -- the one that creates the real grid workspace, made AFTER
        # worktree creation and resolve_task_text() succeed -- must also be
        # covered by the salvage handler. Use entries with single-line
        # descriptions (so resolve_task_text never fails) and a stub `cmux`
        # whose `workspace create` itself fails, so the only failure point is
        # the workspace-creation call.
        ws_fail_stub_dir = Path(tempfile.mkdtemp(prefix="spawn-fleet-selftest-ws-fail-stubbin-"))
        ws_fail_stub_cmux = ws_fail_stub_dir / "cmux"
        ws_fail_stub_cmux.write_text(
            "#!/usr/bin/env bash\n"
            'case "$1" in\n'
            "  list-windows|new-window) echo 'window:1 11111111-1111-1111-1111-111111111111' ;;\n"
            '  workspace) if [ "$2" = "create" ]; then exit 1; fi ;;\n'
            "esac\n"
            "exit 0\n"
        )
        ws_fail_stub_cmux.chmod(0o755)
        try:
            grid_ws_fail_slug = "selftest-partial-grid-ws-fail"
            grid_ws_fail_manifest = fleet_repo / ".cmux" / "fleet" / f"{grid_ws_fail_slug}.json"
            grid_ws_fail_entries = [Entry(label="h1", agent="pi", model="m", description="single line ok")]
            try:
                spawn_grid(str(ws_fail_stub_cmux), fleet_repo, grid_ws_fail_slug, grid_ws_fail_entries, window, None, grid_ws_fail_manifest)
                print("selftest: spawn_grid should have raised on workspace-create failure FAIL (Finding 2, round 3)")
                ok = False
            except SystemExit:
                pass
            if not grid_ws_fail_manifest.exists():
                print("selftest: spawn_grid workspace-create-failure partial manifest not written FAIL (Finding 2, round 3)")
                ok = False
            else:
                partial = json.loads(grid_ws_fail_manifest.read_text())
                partial_entries = partial.get("entries", [])
                if not partial.get("partial") or len(partial_entries) != 1 or partial_entries[0]["label"] != "h1":
                    print("selftest: spawn_grid workspace-create-failure partial manifest contents FAIL (Finding 2, round 3)", partial)
                    ok = False
                elif partial_entries[0]["workspace_ref"] is not None or partial_entries[0]["surface_ref"] is not None:
                    print(
                        "selftest: spawn_grid workspace-create-failure partial manifest workspace_ref/surface_ref "
                        "should be null FAIL (Finding 2, round 3)", partial,
                    )
                    ok = False
            h1_wt = worktree_path_for(fleet_repo, grid_ws_fail_slug, "h1")
            if not h1_wt.exists():
                print("selftest: spawn_grid workspace-create-failure should have left the already-created worktree on disk FAIL (Finding 2, round 3)")
                ok = False
        finally:
            shutil.rmtree(ws_fail_stub_dir, ignore_errors=True)
    finally:
        os.environ["PATH"] = old_path
        shutil.rmtree(fleet_repo, ignore_errors=True)
        shutil.rmtree(worktrees_root, ignore_errors=True)
        shutil.rmtree(stub_dir, ignore_errors=True)

    print("spawn_fleet selftest: OK" if ok else "spawn_fleet selftest: FAIL")
    return 0 if ok else 1


def acquire_run_lock(lock_path: Path) -> str:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        lock_path.parent.chmod(0o700)
    token = uuid.uuid4().hex
    try:
        write_text_exclusive(lock_path, f"{os.getpid()}\n{token}\n")
    except FileExistsError:
        die(
            f"fleet run lock already exists at {lock_path}; another launch may be active. "
            "Remove it only after confirming no launch is running."
        )
    return token


def release_run_lock(lock_path: Path, identity: str) -> None:
    # Ownership is by the token on the lock's second line, not by inode: ext4
    # reuses inode numbers across unlink+recreate, so a stat-identity check
    # could delete a lock a different launch now holds.
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags)
    except OSError:
        return
    try:
        raw = os.read(fd, 4096)
    finally:
        os.close(fd)
    lines = raw.decode("ascii", "replace").splitlines()
    if len(lines) >= 2 and lines[1] == identity:
        lock_path.unlink(missing_ok=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run embedded fixture checks and exit")
    parser.add_argument("--repo", type=Path, help="target repo (default: current directory)")
    parser.add_argument("--run-slug", help="short slug naming this run (default: derived)")
    parser.add_argument("--print-manifest", metavar="SLUG", help="validate and print an existing manifest path")
    parser.add_argument("--entry", action="append", default=[], help="label:agent:model:description, repeatable")
    parser.add_argument("--arrange", choices=["tabs", "grid"], default="tabs")
    parser.add_argument("--orchestrator", choices=["claude", "none"], default="none")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="explicit readable environment file to pass to cmux; never auto-discovered",
    )
    parser.add_argument(
        "--unsafe-yolo",
        action="store_true",
        help="explicitly disable Claude/Codex safeguards for every launched agent",
    )
    parser.add_argument(
        "--allow-all-socket",
        action="store_true",
        help="explicitly back up and change cmux socketControlMode to allowAll",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    repo = resolve_repo_root((args.repo or Path.cwd()).resolve())
    if args.print_manifest:
        try:
            path, _payload = load_fleet_manifest(repo, slugify(args.print_manifest))
        except ValueError as exc:
            die(str(exc))
        print(path)
        return 0
    if not args.entry:
        die("at least one --entry is required")
    entries = [parse_entry(e) for e in args.entry]
    run_slug = derive_run_slug(entries, args.run_slug, time.time())
    missing_agents = sorted({entry.agent for entry in entries if shutil.which(entry.agent) is None})
    if args.orchestrator == "claude" and shutil.which("claude") is None:
        missing_agents.append("claude (orchestrator)")
    if missing_agents:
        die("agent executable(s) not found before worktree creation: " + ", ".join(missing_agents))
    manifest_path = fleet_manifest_path(repo, run_slug)
    lock_path = manifest_path.with_suffix(".lock")
    lock_identity = acquire_run_lock(lock_path)
    try:
        if manifest_path.exists():
            die(
                f"a fleet manifest already exists at {manifest_path} -- refusing to overwrite it "
                "(the earlier fleet's refs would become untrackable); pass a different --run-slug"
            )
        preflight_worktree_paths(repo, run_slug, entries)
        env_file = args.env_file.resolve() if args.env_file else None
        if env_file is not None and (not env_file.is_file() or not os.access(env_file, os.R_OK)):
            die(f"--env-file is not a readable file: {env_file}")

        bin_path = find_cmux_bin()
        ensure_cmux_running(bin_path)
        if not _capabilities_accessible(bin_path):
            if not args.allow_all_socket:
                die(
                    "cmux socket access is unavailable under the current policy; run the "
                    "orchestrator inside cmux or pass --allow-all-socket to explicitly back "
                    "up and relax the global socket policy"
                )
            ensure_socket_allowall(bin_path)
        window = find_or_create_window(bin_path)
        hooks_result = cmux(bin_path, "hooks", "setup", "--yes")
        if hooks_result.returncode != 0:
            print(
                "warning: `cmux hooks setup --yes` failed -- notification-based waiting "
                "(references/events-and-waiting.md) will not work for this fleet; "
                f"read-screen-based checking still does. stderr: {hooks_result.stderr.strip()}",
                file=sys.stderr,
            )

        if args.arrange == "tabs":
            placements = spawn_tabs(
                bin_path, repo, run_slug, entries, window, env_file, manifest_path,
                unsafe_yolo=args.unsafe_yolo,
            )
        else:
            placements = spawn_grid(
                bin_path, repo, run_slug, entries, window, env_file, manifest_path,
                unsafe_yolo=args.unsafe_yolo,
            )

        manifest = build_manifest(run_slug, repo, args.arrange, entries, placements)
        write_private_json(manifest_path, manifest)
        print(f"fleet '{run_slug}' bootstrapped: {manifest_path}")
    finally:
        release_run_lock(lock_path, lock_identity)

    if args.orchestrator == "claude":
        exec_orchestrator(
            manifest_path, run_slug, repo, unsafe_yolo=args.unsafe_yolo
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
