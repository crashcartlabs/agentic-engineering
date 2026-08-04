#!/usr/bin/env python3
"""Worktree pipeline dashboard — one self-contained HTML snapshot of every stream.

    python3 scripts/dashboard/dashboard.py --selftest   # run embedded fixture checks

(One-shot and `--watch` rendering modes land in later phases of the same script.)

A "stream" is one entry from `git worktree list` against a configured target repo. For
each stream this reads its local `plans/*.md` (including whatever is currently
uncommitted) and the most recent matching report under `reviews/`, `code-reviews/`,
`security-reviews/`, `skill-scans/`, and PR/CI state via `gh`.

Every filesystem/subprocess read is wrapped defensively: a stream with no plan, no PR, a
malformed report, or a file mid-write by an active executor must degrade to "unknown",
never crash the whole run (see the plan's Risks & rollback section).

Pure stdlib only — no new dependency. `gh` is required for PR/CI state, matching this
repo's other skills.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field

DASHBOARD_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(DASHBOARD_DIR.parent / "ci"))
# Shared with scripts/ci/lint_plans.py so dashboard parsing cannot drift from plan lint.
from lint_common import META_ROW as _META_ROW  # noqa: E402

CONFIG_PATH = DASHBOARD_DIR / "config.json"
CONFIG_EXAMPLE_PATH = DASHBOARD_DIR / "config.example.json"
DEFAULT_HTML_PATH = DASHBOARD_DIR / "dashboard.html"
DEFAULT_PID_PATH = DASHBOARD_DIR / "dashboard.pid"
DEFAULT_LOG_PATH = DASHBOARD_DIR / "dashboard.log"
DEFAULT_REFRESH_SECONDS = 15
DEFAULT_LOG_MAX_BYTES = 256 * 1024
POSIX_ONLY_MESSAGE = "POSIX-only (macOS/Linux); not supported on Windows"

BABYSITTING_LABEL = "babysitting-active"


class DashboardError(Exception):
    """A recoverable, user-facing error — bad config, a tool that can't run at all."""


class SymlinkWriteRefused(DashboardError):
    """A fixed-path write target is a symlink; the write was refused (O_NOFOLLOW)."""


def platform_support_error(
    os_name: str,
    sys_platform: str,
    has_o_nofollow: bool,
    ps_available: bool,
) -> str | None:
    supported_os = os_name == "posix" and (sys_platform == "darwin" or sys_platform.startswith("linux"))
    if not supported_os or not has_o_nofollow or not ps_available:
        return POSIX_ONLY_MESSAGE
    return None


def current_platform_support_error() -> str | None:
    return platform_support_error(
        os.name,
        sys.platform,
        hasattr(os, "O_NOFOLLOW"),
        shutil.which("ps") is not None,
    )


def require_supported_platform() -> None:
    error = current_platform_support_error()
    if error:
        raise DashboardError(error)


def write_text_no_follow(path: pathlib.Path, text: str) -> None:
    """Atomically (over)write `path`, refusing to follow a pre-existing symlink.

    Opens with `O_NOFOLLOW` so a symlink planted at a fixed output path (`dashboard.html`,
    `dashboard.pid`) is never written through — no check-then-write race either, since
    the open itself is the check.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SymlinkWriteRefused(f"{path} is a symlink — refusing to write through it") from exc
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


class CappedLog:
    """Line-compatible stderr sink that truncates on open and keeps only the newest bytes."""

    encoding = "utf-8"
    errors = "backslashreplace"

    def __init__(
        self,
        path: pathlib.Path,
        max_bytes: int = DEFAULT_LOG_MAX_BYTES,
        truncate: bool = True,
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
        if truncate:
            flags |= os.O_TRUNC
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(path, flags, 0o644)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise SymlinkWriteRefused(f"{path} is a symlink — refusing to write through it") from exc
            raise DashboardError(f"could not open log {path}: {exc}") from exc
        self._closed = False

    def write(self, text: str) -> int:
        if self._closed:
            return 0
        rendered = str(text)
        data = rendered.encode(self.encoding, self.errors)
        os.write(self._fd, data)
        self._cap()
        return len(rendered)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        if self._closed:
            return
        os.close(self._fd)
        self._closed = True

    def isatty(self) -> bool:
        return False

    def _cap(self) -> None:
        size = os.fstat(self._fd).st_size
        if size <= self.max_bytes:
            return
        os.lseek(self._fd, size - self.max_bytes, os.SEEK_SET)
        tail = b""
        while len(tail) < self.max_bytes:
            chunk = os.read(self._fd, self.max_bytes - len(tail))
            if not chunk:
                break
            tail += chunk
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, tail)
        os.lseek(self._fd, 0, os.SEEK_END)


# --- data model --------------------------------------------------------------------


@dataclass
class Worktree:
    path: pathlib.Path
    branch: str | None  # None when the worktree is detached


@dataclass
class Task:
    marker: str  # ' ', '~', 'x', or '!'
    text: str


@dataclass
class Phase:
    number: int
    name: str
    tasks: list[Task] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return bool(self.tasks) and all(t.marker == "x" for t in self.tasks)


@dataclass
class PlanInfo:
    path: pathlib.Path
    status: str | None
    phases: list[Phase]

    @property
    def total_phases(self) -> int:
        return len(self.phases)

    def current_phase_number(self) -> int | None:
        """First phase with an incomplete or `[~]`/`[!]` task; None if all done (or no phases)."""
        for p in self.phases:
            if not p.done:
                return p.number
        return None

    def has_blocked_task(self) -> bool:
        return bool(self.blocked_tasks())

    def blocked_tasks(self) -> list[Task]:
        return [t for p in self.phases for t in p.tasks if t.marker == "!"]


@dataclass
class ReviewBadge:
    kind: str  # "review-plan" | "code-review" | "security-audit" | "skill-safety-scan"
    label: str  # display text: "APPROVE", "2 findings", "CLEAR", "see report"
    severity: str  # "good" | "warn" | "bad" | "unknown"
    count: int | None = None  # confirmed-finding count, where the report gives one
    path: pathlib.Path | None = None


@dataclass
class PrState:
    number: int
    state: str  # OPEN | MERGED | CLOSED
    url: str
    mergeable: str  # MERGEABLE | CONFLICTING | UNKNOWN
    ci_status: str  # passing | failing | pending | none
    babysitting: bool
    comment_count: int  # issue comments
    review_count: int  # submitted reviews
    is_draft: bool
    merge_state_status: str  # CLEAN | BEHIND | BLOCKED | DIRTY | DRAFT | HAS_HOOKS | UNKNOWN | UNSTABLE
    review_decision: str  # APPROVED | REVIEW_REQUIRED | CHANGES_REQUESTED | "" (no review requirement)


# --- 1.1 config ----------------------------------------------------------------------


def load_config(path: pathlib.Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise DashboardError(
            f"No config at {path}. Copy {CONFIG_EXAMPLE_PATH.name} to {path.name} "
            f"(next to it) and set repo_path to your target repo."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DashboardError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DashboardError(f"{path} must contain a JSON object at the top level.")
    if not data.get("repo_path"):
        raise DashboardError(f"{path} is missing the required field 'repo_path'.")
    data.setdefault("refresh_interval_seconds", DEFAULT_REFRESH_SECONDS)
    try:
        interval_ok = int(data["refresh_interval_seconds"]) > 0
    except (TypeError, ValueError):
        interval_ok = False
    if not interval_ok:
        raise DashboardError(
            f"{path}'s refresh_interval_seconds must be a positive integer, "
            f"got {data['refresh_interval_seconds']!r}."
        )
    return data


# --- 1.2 worktree discovery -----------------------------------------------------------


def parse_worktree_list_porcelain(text: str) -> list[Worktree]:
    """Parse `git worktree list --porcelain` output into (path, branch) pairs.

    Records are separated by a blank line; each starts with a `worktree <path>` line,
    optionally followed by `branch refs/heads/<name>` or a bare `detached` line.

    A `prunable <reason>` line means the worktree's directory no longer exists (deleted
    but not yet pruned from git's own metadata) — that record is skipped entirely,
    since every downstream `git`/`gh` call against it would run with a nonexistent
    `cwd` and produce a stream that looks like a genuinely broken/unreachable one
    (e.g. a misleading "PR status unknown" attention item) rather than the deleted,
    inactive worktree it actually is.
    """
    worktrees: list[Worktree] = []
    path: pathlib.Path | None = None
    branch: str | None = None
    started = False
    prunable = False

    def flush() -> None:
        nonlocal path, branch, started, prunable
        if started and path is not None and not prunable:
            worktrees.append(Worktree(path=path, branch=branch))
        path, branch, started, prunable = None, None, False, False

    for line in text.splitlines():
        if line == "":
            flush()
        elif line.startswith("worktree "):
            flush()
            path = pathlib.Path(line[len("worktree "):])
            started = True
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif line == "detached":
            branch = None
        elif line.startswith("prunable"):
            prunable = True
        # "HEAD ...", "locked" carry nothing this dashboard needs.
    flush()
    return worktrees


def run_worktree_list(repo_path: pathlib.Path) -> list[Worktree]:
    try:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DashboardError(f"git worktree list failed for {repo_path}: {exc}") from exc
    if proc.returncode != 0:
        raise DashboardError(
            f"git worktree list failed for {repo_path}: {proc.stderr.strip()}"
        )
    return parse_worktree_list_porcelain(proc.stdout)


# --- 1.3 plan-file parsing -------------------------------------------------------------

_H2 = re.compile(r"^##\s+(?!#)")
_PHASE_HEADING = re.compile(r"^###\s+Phase\s+(\d+)\s*[—–-]\s*(.+?)\s*$")
_TASK_LINE = re.compile(r"^-\s*\[( |~|x|X|!)\]\s*(?:\d+(?:\.\d+)*\s+)?(.+)$")


def parse_plan_text(text: str) -> tuple[str | None, list[Phase]]:
    """Pure parse of a plan file's body: metadata Status + per-phase task checkboxes.

    Tasks are only attributed to a phase between its `### Phase N — ...` heading and the
    next level-2 (`## `) heading — so trailing sections like "Definition of Done" (which
    also use `- [ ]` checkboxes) never get folded into the last phase.
    """
    status: str | None = None
    phases: list[Phase] = []
    current: Phase | None = None
    for line in text.splitlines():
        m = _META_ROW.match(line)
        if m and m.group(1) == "Status":
            status = m.group(2).strip()
            continue
        if _H2.match(line):
            current = None
            continue
        m = _PHASE_HEADING.match(line)
        if m:
            current = Phase(number=int(m.group(1)), name=m.group(2))
            phases.append(current)
            continue
        m = _TASK_LINE.match(line)
        if m and current is not None:
            current.tasks.append(Task(marker=m.group(1).lower(), text=m.group(2).strip()))
    return status, phases


READ_TEXT_MAX_BYTES = 256 * 1024


def read_text_safely(path: pathlib.Path) -> str | None:
    """Read a file, treating any failure (mid-write, permissions, encoding) as unknown.

    Caps the read at `READ_TEXT_MAX_BYTES` and parses the truncated text rather than
    rejecting an oversized file outright — the plan/report structure this dashboard
    cares about (metadata table, phase headings, verdict line) always lives near the
    top of a legitimate file.
    """
    try:
        with path.open("rb") as f:
            data = f.read(READ_TEXT_MAX_BYTES)
    except OSError:
        return None
    if len(data) < READ_TEXT_MAX_BYTES:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    # Only reached when the read hit the cap: a truncated read can cut a multi-byte
    # UTF-8 character in half at the very tail. Drop just that dangling fragment
    # rather than treating the whole (legitimately oversized) file as unreadable.
    for cut in range(4):
        try:
            return data[: len(data) - cut].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def plan_slug(path: pathlib.Path) -> str:
    """`plans/2026-07-06-topic-slug.md` -> `topic-slug`; falls back to the stem."""
    m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)\.md$", path.name)
    return m.group(1) if m else path.stem


def branch_to_plan_slug(branch: str) -> str | None:
    return branch[len("plan/"):] if branch.startswith("plan/") else None


def branch_to_kebab(branch: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")


def extract_plan_branch(text: str) -> str | None:
    """Pull just a plan file's `**Branch**` metadata row — a light, standalone parse
    (not the full `parse_plan_text`) so every candidate can be checked during matching
    without pulling in phase/task parsing for files that won't even be selected."""
    for line in text.splitlines():
        m = _META_ROW.match(line)
        if m and m.group(1) == "Branch":
            return m.group(2).strip()
    return None


def newest_statable_path(paths: list[pathlib.Path]) -> pathlib.Path | None:
    newest: pathlib.Path | None = None
    newest_mtime: float | None = None
    for p in paths:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if newest is None or newest_mtime is None or mtime > newest_mtime:
            newest = p
            newest_mtime = mtime
    return newest


def find_plan_for_worktree(worktree: Worktree) -> pathlib.Path | None:
    """Locate the plan file relevant to a worktree: the one matching its branch's
    topic slug, or (no match / no branch) the most recently modified `plans/*.md`.

    Tries three signals in order: a candidate's own recorded `**Branch**` metadata
    (authoritative — covers branches whose name can't be recovered from any filename
    slug at all, e.g. `claude/issue-triage-if9y4i`), then the `plan/<slug>`
    branch-prefix form, then the branch's own kebab-cased slug — before finally
    falling back to whichever plan file was modified most recently.
    """
    plans_dir = worktree.path / "plans"
    if not plans_dir.is_dir():
        return None
    candidates = [p for p in plans_dir.glob("*.md") if p.name != "README.md"]
    if not candidates:
        return None
    if worktree.branch:
        branch_matches = []
        for p in candidates:
            text = read_text_safely(p)
            if text is not None and extract_plan_branch(text) == worktree.branch:
                branch_matches.append(p)
        if branch_matches:
            # Branch metadata is authoritative: if every candidate becomes
            # unstatable mid-read, degrade to no plan rather than falling through to
            # a slug/newest fallback that could attach another stream's plan.
            return newest_statable_path(branch_matches)

        slug_candidates = [s for s in (branch_to_plan_slug(worktree.branch), branch_to_kebab(worktree.branch)) if s]
        for slug in slug_candidates:
            matches = [p for p in candidates if plan_slug(p) == slug]
            if matches:
                newest = newest_statable_path(matches)
                if newest is not None:
                    return newest
    return newest_statable_path(candidates)


def load_plan_info(path: pathlib.Path) -> PlanInfo | None:
    text = read_text_safely(path)
    if text is None:
        return None
    status, phases = parse_plan_text(text)
    return PlanInfo(path=path, status=status, phases=phases)


# --- 1.4 review-report parsing ---------------------------------------------------------


def classify_review_plan(text: str) -> ReviewBadge:
    m = re.search(r"Verdict:\s*(APPROVE|REVISE|BLOCKED)\b", text)
    if not m:
        return ReviewBadge("review-plan", "see report", "unknown")
    verdict = m.group(1)
    severity = {"APPROVE": "good", "REVISE": "bad", "BLOCKED": "bad"}[verdict]
    return ReviewBadge("review-plan", verdict, severity)


def classify_code_review(text: str) -> ReviewBadge:
    if re.search(r"Verdict:\s*No correctness issues found\.", text):
        return ReviewBadge("code-review", "no issues", "good", count=0)
    m = re.search(r"Verdict:\s*(\d+)\s*confirmed findings?\s*\(([^)]*)\)", text)
    if not m:
        return ReviewBadge("code-review", "see report", "unknown")
    total = int(m.group(1))
    bug_match = re.search(r"(\d+)\s*bugs?", m.group(2))
    bugs = int(bug_match.group(1)) if bug_match else 0
    severity = "bad" if bugs else ("warn" if total else "good")
    return ReviewBadge("code-review", f"{total} finding{'s' if total != 1 else ''}", severity, count=total)


def classify_security_audit(text: str) -> ReviewBadge:
    if re.search(r"Verdict:\s*No exploitable vulnerabilities found", text):
        return ReviewBadge("security-audit", "no findings", "good", count=0)
    m = re.search(r"Verdict:\s*(\d+)\s*confirmed findings?\s*\(([^)]*)\)", text)
    if not m:
        return ReviewBadge("security-audit", "see report", "unknown")
    total = int(m.group(1))
    counts = {level: 0 for level in ("critical", "high", "medium", "low")}
    for count_str, level in re.findall(r"(\d+)\s*(critical|high|medium|low)", m.group(2)):
        counts[level] = int(count_str)
    severity = "bad" if (counts["critical"] or counts["high"]) else ("warn" if total else "good")
    return ReviewBadge("security-audit", f"{total} finding{'s' if total != 1 else ''}", severity, count=total)


def classify_skill_safety_scan(text: str) -> ReviewBadge:
    # Confirmed live against a real generated report (skill-scans/2026-07-04-ship.md):
    # the verdict is a `## Verdict: <...>` heading, unlike the other three skills' plain
    # `Verdict: <...>` line — resolving the plan's Phase-1 open assumption.
    m = re.search(r"^##\s*Verdict:\s*(CLEAR|BLOCKED|NEEDS REVIEW)\s*$", text, re.MULTILINE)
    if not m:
        return ReviewBadge("skill-safety-scan", "see report", "unknown")
    verdict = m.group(1)
    severity = {"CLEAR": "good", "NEEDS REVIEW": "warn", "BLOCKED": "bad"}[verdict]
    return ReviewBadge("skill-safety-scan", verdict, severity)


_REVIEW_CLASSIFIERS = {
    "reviews": ("review-plan", classify_review_plan),
    "code-reviews": ("code-review", classify_code_review),
    "security-reviews": ("security-audit", classify_security_audit),
    "skill-scans": ("skill-safety-scan", classify_skill_safety_scan),
}


def _report_declares_identity(text: str, branch: str | None, plan_path: pathlib.Path | None) -> bool | None:
    """Best-effort cross-check: does this report's own embedded identity (a `Plan:`
    line for review-plan reports, or the `# Code Review`/`# Security Audit` H1's
    branch) agree with the stream's actual plan/branch? Returns True/False when the
    report's format makes this checkable, or None when it can't be determined
    (`skill-safety-scan` reports don't embed this, and a `--full` security audit
    isn't branch-scoped) — callers should treat None as "can't rule it out."""
    m = re.search(r"^Plan:\s+(\S+)", text, re.MULTILINE)
    if m:
        return plan_path is not None and m.group(1).strip() == f"plans/{plan_path.name}"
    m = re.search(r"^# (?:Code Review|Security Audit) — (\S+) vs ", text, re.MULTILINE)
    if m:
        return branch is not None and m.group(1).strip() == branch
    return None


def find_latest_review(
    worktree_path: pathlib.Path,
    review_dir: str,
    slug_candidates: list[str],
    branch: str | None = None,
    plan_path: pathlib.Path | None = None,
) -> pathlib.Path | None:
    """Report filenames follow the same `YYYY-MM-DD-<slug>.md` convention as plan files,
    so match on the **exact** extracted slug (plus an optional same-day `-N` disambiguation
    suffix) rather than a substring — a substring match would let e.g. a `dashboard` stream
    slug wrongly pick up an unrelated `worktree-pipeline-dashboard` report.

    The `-N` suffix itself is ambiguous — a legitimate stream slug that ends in digits
    (e.g. `api-2`) is indistinguishable, by filename alone, from `api`'s own second
    same-day re-review. A `-N`-suffix match is therefore cross-checked against the
    report's own embedded identity (`_report_declares_identity`) before being
    accepted; an exact match never needs this, since there's no ambiguity to resolve.
    """
    d = worktree_path / review_dir
    if not d.is_dir():
        return None
    slugs = [s.lower() for s in slug_candidates if s]

    def match_kind(report_slug: str) -> str:
        """'exact' | 'suffix' | 'none' — 'suffix' matches need the identity check."""
        for candidate in slugs:
            if report_slug == candidate:
                return "exact"
        for candidate in slugs:
            if re.match(rf"^{re.escape(candidate)}-\d+$", report_slug):
                return "suffix"
        return "none"

    matches: list[pathlib.Path] = []
    for p in d.glob("*.md"):
        kind = match_kind(plan_slug(p).lower())
        if kind == "none":
            continue
        if kind == "exact":
            matches.append(p)
            continue
        text = read_text_safely(p)
        identity_ok = _report_declares_identity(text, branch, plan_path) if text is not None else None
        if identity_ok is not False:  # accept when confirmed OR when unverifiable
            matches.append(p)

    if not matches:
        return None
    try:
        return max(matches, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


def gather_review_badges(
    worktree_path: pathlib.Path,
    slug_candidates: list[str],
    branch: str | None = None,
    plan_path: pathlib.Path | None = None,
) -> list[ReviewBadge]:
    """Only ever returns a badge for a review type that actually has a matching report —
    a review type that doesn't apply to this stream stays silent, never "not run" clutter."""
    badges: list[ReviewBadge] = []
    for dirname, (_kind, classify) in _REVIEW_CLASSIFIERS.items():
        path = find_latest_review(worktree_path, dirname, slug_candidates, branch, plan_path)
        if path is None:
            continue
        text = read_text_safely(path)
        if text is None:
            continue
        badge = classify(text)
        badge.path = path
        badges.append(badge)
    return badges


# --- 1.5 gh PR/CI state -----------------------------------------------------------------


def parse_gh_pr_json(text: str) -> PrState | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "number" not in data:
        return None
    checks = data.get("statusCheckRollup") or []
    conclusions = []
    for c in checks:
        if not isinstance(c, dict):
            continue
        conclusion = c.get("conclusion")
        if not conclusion:
            # Legacy commit-status API (older repos) reports via `.state` instead of
            # `.conclusion`, using GitHub's uppercase `StatusState` enum (ERROR,
            # FAILURE, PENDING, SUCCESS) — normalize case before comparing, since a
            # raw case-sensitive match would silently miss every real value. `state ==
            # "PENDING"` (or anything else unrecognized) falls through as the existing
            # falsy conclusion, which the pending branch below already handles.
            state = (c.get("state") or "").upper()
            if state in ("FAILURE", "ERROR"):
                conclusion = "FAILURE"
            elif state == "SUCCESS":
                conclusion = "SUCCESS"
        conclusions.append(conclusion)
    if any(c in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE") for c in conclusions):
        ci_status = "failing"
    elif checks and any(not c for c in conclusions):
        ci_status = "pending"
    elif checks:
        ci_status = "passing"
    else:
        ci_status = "none"
    labels = {l.get("name") for l in (data.get("labels") or []) if isinstance(l, dict)}
    return PrState(
        number=data.get("number"),
        state=data.get("state", "UNKNOWN"),
        url=data.get("url", ""),
        mergeable=data.get("mergeable", "UNKNOWN"),
        ci_status=ci_status,
        babysitting=BABYSITTING_LABEL in labels,
        comment_count=len(data.get("comments") or []),
        review_count=len(data.get("reviews") or []),
        is_draft=data.get("isDraft", False),
        merge_state_status=data.get("mergeStateStatus", "UNKNOWN"),
        review_decision=data.get("reviewDecision") or "",
    )


def run_gh_pr_view(worktree_path: pathlib.Path, branch: str) -> tuple[PrState | None, str | None]:
    """Returns `(PrState, None)` on success, `(None, None)` for the expected "no PR
    exists for this branch" case, or `(None, <message>)` for a genuine `gh` failure
    (missing binary, timeout, not authenticated, rate-limited) — distinguished so a
    systemic `gh` outage doesn't silently look identical to "this stream has no PR"
    (which would otherwise report 0 open PRs / nothing needing attention even while
    PR/CI state for every stream is actually unavailable)."""
    try:
        fields = (
            "number,state,url,mergeable,statusCheckRollup,labels,comments,reviews,isDraft,"
            "mergeStateStatus,reviewDecision,headRefName,isCrossRepository"
        )
        proc = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all", "--limit", "20", "--json", fields],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"gh pr view failed: {exc}"
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return None, f"gh pr view failed: {stderr or 'unknown error'}"
    by_branch, error = parse_gh_pr_list_json(proc.stdout)
    return by_branch.get(branch), error


def run_gh_pr_list(repo_path: pathlib.Path) -> tuple[dict[str, PrState], str | None]:
    """Fetch PR/CI state once per render and index the newest PR by head branch."""
    fields = (
        "number,state,url,mergeable,statusCheckRollup,labels,comments,reviews,isDraft,"
        "mergeStateStatus,reviewDecision,headRefName,isCrossRepository"
    )
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", "1000", "--json", fields],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"gh pr list failed: {exc}"
    if proc.returncode != 0:
        return {}, f"gh pr list failed: {(proc.stderr or '').strip() or 'unknown error'}"
    return parse_gh_pr_list_json(proc.stdout)


def parse_gh_pr_list_json(text: str) -> tuple[dict[str, PrState], str | None]:
    """Parse one batched `gh pr list` response, newest row winning per branch."""
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"gh pr list returned invalid JSON: {exc}"
    if not isinstance(rows, list):
        return {}, "gh pr list returned an unexpected payload"
    by_branch: dict[str, PrState] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("headRefName"), str)
            or row.get("isCrossRepository") is True
        ):
            continue
        state = parse_gh_pr_json(json.dumps(row))
        if state is not None and row["headRefName"] not in by_branch:
            by_branch[row["headRefName"]] = state
    return by_branch, None


def resolve_default_branch(repo_path: pathlib.Path) -> str | None:
    """Never hardcode `main` — a repo's default branch name varies."""
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            ref = proc.stdout.strip()
            return ref[len("origin/"):] if ref.startswith("origin/") else ref
    except (OSError, subprocess.TimeoutExpired):
        pass
    for candidate in ("main", "master"):
        for ref in (f"refs/heads/{candidate}", f"refs/remotes/origin/{candidate}"):
            try:
                proc = subprocess.run(
                    ["git", "show-ref", "--verify", "--quiet", ref],
                    cwd=repo_path,
                    timeout=10,
                )
                if proc.returncode == 0:
                    return candidate
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


_LOCAL_EXCLUDE_LINES = (
    "scripts/dashboard/config.json",
    "scripts/dashboard/dashboard.html",
    "scripts/dashboard/dashboard.pid",
    "scripts/dashboard/dashboard.log",
    "scripts/dashboard/.dashboard.html.tmp*",
)


def ensure_local_excludes(config: dict | None = None, log_path: pathlib.Path | None = None) -> None:
    """Keep this dashboard's local-only files (config, rendered HTML, pidfile, log) out of
    `git status` without touching the tracked `.gitignore` — same "ignore it locally"
    convention documented in `skills/security-audit/SKILL.md` and
    `skills/code-audit/SKILL.md`: append to `<git-common-dir>/info/exclude`
    instead. Best-effort only — any failure here is cosmetic (untracked files showing up
    in `git status`), never fatal to the dashboard itself.

    Also covers a *configured* `output_path` and CLI `--log` path when they resolve to
    somewhere inside this same repo — the fixed default lines alone don't help if either
    was pointed elsewhere (e.g. into one of the watched worktrees), which would
    otherwise make the dashboard mark that stream dirty with output the dashboard itself
    just wrote.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=DASHBOARD_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if proc.returncode != 0 or not proc.stdout.strip():
        return
    exclude_path = (DASHBOARD_DIR / proc.stdout.strip()).resolve() / "info" / "exclude"

    lines = list(_LOCAL_EXCLUDE_LINES)
    configured_paths: list[tuple[pathlib.Path, bool]] = []
    configured_output = config.get("output_path") if config else None
    if configured_output:
        configured_paths.append((pathlib.Path(configured_output), True))
    if log_path:
        configured_paths.append((log_path, False))
    if configured_paths:
        try:
            toplevel = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=DASHBOARD_DIR,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if toplevel.returncode == 0 and toplevel.stdout.strip():
                repo_root = pathlib.Path(toplevel.stdout.strip()).resolve()
                for configured_path, include_temp in configured_paths:
                    rel = configured_path.expanduser().resolve().relative_to(repo_root)
                    lines.append(rel.as_posix())
                    if include_temp:
                        lines.append((rel.parent / f".{rel.name}.tmp*").as_posix())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass  # outside this repo, or git/path resolution failed -- best-effort only

    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        existing_lines = set(existing.splitlines())
        missing = [line for line in lines if line not in existing_lines]
        if not missing:
            return
        with exclude_path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            for line in missing:
                f.write(line + "\n")
    except OSError:
        return


# --- 2.3 dirty-tree + staleness ----------------------------------------------------------


def _unquote_git_path(path: str) -> str:
    """Undo git's C-style path quoting (`core.quotePath`, on by default): a path
    containing a space, a quote/backslash, or a non-ASCII byte is wrapped in double
    quotes with backslash escapes (`\\"`, `\\\\`, `\\t`, `\\n`, `\\NNN` octal bytes) —
    left as-is, a later `(worktree_path / path).stat()` looks for a file that
    literally includes the quote characters and never finds the real one."""
    if not (path.startswith('"') and path.endswith('"') and len(path) >= 2):
        return path
    inner = path[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt in ('"', "\\"):
                out.append(nxt)
                i += 2
            elif nxt == "t":
                out.append("\t")
                i += 2
            elif nxt == "n":
                out.append("\n")
                i += 2
            elif nxt.isdigit() and inner[i + 1 : i + 4].isdigit():
                out.append(chr(int(inner[i + 1 : i + 4], 8)))
                i += 4
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_git_status_porcelain(text: str | bytes) -> list[str]:
    if isinstance(text, bytes):
        records = text.split(b"\0")
        paths: list[str] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            status = record[:2]
            path = record[3:] if len(record) > 3 else b""
            paths.append(os.fsdecode(path))
            if b"R" in status or b"C" in status:
                index += 1  # -z emits the rename/copy source as the next NUL record.
        return paths
    paths: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        rest = line[3:] if len(line) > 3 else ""
        if " -> " in rest:  # renames: "old -> new"
            rest = rest.split(" -> ", 1)[1]
        paths.append(_unquote_git_path(rest))
    return paths


def is_dirty_beyond_plan(paths: list[str] | None) -> bool | None:
    """Dirty means uncommitted changes *beyond* the expected `[~]` marks in a plan file —
    an executor mid-`/execute` is expected to have its current plan file modified."""
    if paths is None:
        return None
    return any(not re.match(r"^plans/[^/]+\.md$", p) for p in paths)


def run_git_status(worktree_path: pathlib.Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            # `-uall`: repos with `status.showUntrackedFiles=no` otherwise hide new
            # untracked files, which would make a genuinely dirty stream look clean.
            ["git", "status", "--porcelain=v1", "-z", "-uall"],
            cwd=worktree_path,
            capture_output=True,
            text=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_git_status_porcelain(proc.stdout)


def run_last_commit_epoch(worktree_path: pathlib.Path) -> int | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def compute_last_change_epoch(
    worktree_path: pathlib.Path, commit_epoch: int | None, dirty_paths: list[str] | None
) -> int | None:
    """Last commit time, or later if a dirty file's mtime is more recent — an actively
    edited stream (mid-`/execute`) should not read as stale just because its last commit
    is old."""
    if dirty_paths is None:
        return None
    candidates = [commit_epoch] if commit_epoch is not None else []
    for rel in dirty_paths:
        try:
            candidates.append(int((worktree_path / rel).stat().st_mtime))
        except OSError:
            continue
    return max(candidates) if candidates else None


def format_staleness(last_change_epoch: int | None, now: float) -> str:
    if last_change_epoch is None:
        return "unknown"
    delta = max(0.0, now - last_change_epoch)
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


# --- 2.1 / 2.2 / 2.4 stage, needs-attention, aggregation ----------------------------------


@dataclass
class StreamState:
    worktree: Worktree
    plan: PlanInfo | None
    badges: list[ReviewBadge]
    pr: PrState | None
    default_branch: str | None
    dirty: bool | None
    last_change_epoch: int | None
    pr_fetch_error: str | None = None  # set only for a genuine `gh` failure, never for "no PR"


def compute_stage(s: StreamState) -> str:
    """The single canonical pipeline stage for a stream, per the plan's ladder:

        No plan -> Plan draft/approved -> Executing (Phase N of Total)
                 -> Review badges | Committed, unshipped -> PR open/babysitting -> Merged

    A `done` plan splits into "Review badges" (a review report already exists) or
    "Committed, unshipped" (none yet) — both are superseded by a PR's state once one
    exists, which is the actual rightmost end of the ladder.
    """
    if s.pr is not None and s.pr.state == "MERGED":
        return "Merged"
    if s.pr is not None and s.pr.state == "OPEN":
        return "PR open (babysitting)" if s.pr.babysitting else "PR open"
    if s.plan is None:
        return "No plan"
    if s.plan.status in ("draft", "approved"):
        return "Plan draft/approved"
    if s.plan.status == "in-progress":
        n = s.plan.current_phase_number()
        total = s.plan.total_phases
        if n is None or total == 0:
            return "Executing"
        return f"Executing (Phase {n} of {total})"
    if s.plan.status == "done":
        return "Review badges" if s.badges else "Committed, unshipped"
    return "Unknown"


def compute_needs_attention(s: StreamState) -> list[str]:
    """The dashboard attention triggers, each independent of the others."""
    reasons: list[str] = []
    if s.pr is not None and s.pr.state == "OPEN":
        blocked_by_merge_state = s.pr.merge_state_status in ("BLOCKED", "BEHIND")
        blocked_by_review = s.pr.review_decision in ("REVIEW_REQUIRED", "CHANGES_REQUESTED")
        if (
            s.pr.mergeable == "MERGEABLE"
            and s.pr.ci_status == "passing"
            and not s.pr.is_draft
            and not blocked_by_merge_state
            and not blocked_by_review
        ):
            reasons.append(f"PR #{s.pr.number} is merge-ready")
        if s.pr.mergeable == "CONFLICTING":
            reasons.append(f"PR #{s.pr.number} has a merge conflict")
    for badge in s.badges:
        if badge.kind == "review-plan" and badge.label in ("REVISE", "BLOCKED"):
            reasons.append(f"review-plan verdict is {badge.label}")
        if badge.kind == "security-audit" and (badge.count or 0) > 0:
            reasons.append(f"security-audit found {badge.count} confirmed finding(s)")
    if s.plan is not None:
        blocked_tasks = s.plan.blocked_tasks()
        if blocked_tasks:
            more = f" (+{len(blocked_tasks) - 1} more)" if len(blocked_tasks) > 1 else ""
            reasons.append(f"plan has blocked task: {blocked_tasks[0].text}{more}")
    if s.default_branch and s.worktree.branch == s.default_branch:
        reasons.append(f"checked out on {s.default_branch} — the repo's own default branch")
    if s.pr_fetch_error:
        reasons.append(f"PR status unknown for this stream — {s.pr_fetch_error}")
    return reasons


def compute_summary(streams: list[StreamState]) -> str:
    n = len(streams)
    open_prs = sum(1 for s in streams if s.pr and s.pr.state == "OPEN")
    attention = sum(1 for s in streams if compute_needs_attention(s))
    return (
        f"{n} stream{'s' if n != 1 else ''}, "
        f"{open_prs} open PR{'s' if open_prs != 1 else ''}, "
        f"{attention} needing attention"
    )


# --- build ---------------------------------------------------------------------------------


def build_streams(config: dict) -> list[StreamState]:
    repo_path = pathlib.Path(config["repo_path"]).expanduser().resolve()
    default_branch = resolve_default_branch(repo_path)
    worktrees = run_worktree_list(repo_path)
    pr_by_branch, pr_batch_error = run_gh_pr_list(repo_path)
    streams: list[StreamState] = []
    for wt in worktrees:
        plan_path = find_plan_for_worktree(wt)
        plan = load_plan_info(plan_path) if plan_path else None
        slug_candidates: list[str] = []
        if plan_path:
            slug_candidates.append(plan_slug(plan_path))
        if wt.branch:
            slug_candidates.append(branch_to_kebab(wt.branch))
        badges = gather_review_badges(wt.path, slug_candidates, wt.branch, plan_path)
        pr = pr_by_branch.get(wt.branch) if wt.branch else None
        pr_fetch_error = pr_batch_error if wt.branch else None
        if wt.branch and pr is None:
            targeted_pr, targeted_error = run_gh_pr_view(wt.path, wt.branch)
            if targeted_pr is not None or targeted_error is None:
                pr = targeted_pr
                pr_fetch_error = targeted_error
            elif pr_fetch_error:
                pr_fetch_error = f"{pr_fetch_error}; {targeted_error}"
            else:
                pr_fetch_error = targeted_error
        dirty_paths = run_git_status(wt.path)
        commit_epoch = run_last_commit_epoch(wt.path)
        streams.append(
            StreamState(
                worktree=wt,
                plan=plan,
                badges=badges,
                pr=pr,
                default_branch=default_branch,
                dirty=is_dirty_beyond_plan(dirty_paths),
                last_change_epoch=compute_last_change_epoch(wt.path, commit_epoch, dirty_paths),
                pr_fetch_error=pr_fetch_error,
            )
        )
    return streams


# --- 3.1 / 3.3 HTML rendering ----------------------------------------------------------------


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, sans-serif; margin: 2rem; background: #fff; color: #111; }
a { color: #0450a3; }
header { margin-bottom: 1rem; }
.summary { font-size: 1.1rem; font-weight: 600; }
.generated { color: #666; font-size: 0.85rem; }
.banner { padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1rem; }
.banner.attention { background: #ffe8e8; border: 1px solid #e88; }
.banner.ok { background: #e8ffe8; border: 1px solid #8e8; }
main { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
.card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; }
.card h2 { margin-top: 0; font-size: 1.05rem; }
.path { font-size: 0.8rem; color: #555; word-break: break-all; }
.phases { list-style: none; padding-left: 0; margin: 0.5rem 0; }
.phases li { padding: 0.1rem 0; }
.phases li.current { font-weight: 700; }
.phases li.done { color: #2a7a2a; }
.badges { margin: 0.4rem 0; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 10px; margin: 0.1rem 0.2rem 0.1rem 0; font-size: 0.78rem; }
.badge.good { background: #d6f5d6; }
.badge.warn { background: #fff3cd; }
.badge.bad { background: #f8d7da; }
.badge.unknown { background: #eee; }
.flag.dirty { color: #b5651d; font-size: 0.8rem; font-weight: 600; }
.flag.unknown { color: #777; font-size: 0.8rem; font-weight: 600; }
.blocked-task { margin: 0.5rem 0; padding: 0.45rem 0.6rem; border-left: 3px solid #b00020; background: #fff4f4; font-size: 0.9rem; }
.blocked-task ul { margin: 0.25rem 0 0; padding-left: 1.2rem; }
.stale { color: #888; font-size: 0.85rem; }
.muted { color: #888; }
.pr-error { color: #b5651d; font-weight: 600; }
@media (prefers-color-scheme: dark) {
  body { background: #111; color: #eee; }
  a { color: #8ab4ff; }
  .card { background: #1c1c1c; border-color: #333; }
  .path, .generated, .stale, .muted { color: #999; }
  .pr-error { color: #e0a458; }
  .flag.unknown { color: #aaa; }
  .banner.attention { background: #3a1414; border-color: #833; }
  .banner.ok { background: #143a14; border-color: #383; }
  .phases li.done { color: #7fd07f; }
  .blocked-task { background: #3a1414; border-left-color: #ff8a8a; }
  .badge.good { background: #234a23; }
  .badge.warn { background: #4a3f13; }
  .badge.bad { background: #4a1f24; }
  .badge.unknown { background: #333; }
}
"""


def stream_label(s: StreamState) -> str:
    return s.worktree.branch or s.worktree.path.name


def render_card(s: StreamState) -> str:
    branch = escape(s.worktree.branch or "(detached)")
    path = str(s.worktree.path)
    stage = escape(compute_stage(s))
    if s.dirty is True:
        dirty_flag = ' <span class="flag dirty">dirty</span>'
    elif s.dirty is None:
        dirty_flag = ' <span class="flag unknown">dirty: unknown</span>'
    else:
        dirty_flag = ""
    staleness = escape(format_staleness(s.last_change_epoch, time.time()))

    if s.plan and s.plan.phases:
        current = s.plan.current_phase_number()
        items = []
        for p in s.plan.phases:
            cls = "current" if p.number == current else ("done" if p.done else "")
            marker = "✓" if p.done else ("→" if p.number == current else "•")
            items.append(f'<li class="{cls}">{marker} Phase {p.number} — {escape(p.name)}</li>')
        phase_html = f'<ul class="phases">{"".join(items)}</ul>'
    elif s.plan is None:
        phase_html = '<p class="muted">No plan file.</p>'
    else:
        phase_html = '<p class="muted">Plan has no phases yet.</p>'

    badges_html = ""
    if s.badges:
        chips = "".join(
            f'<span class="badge {b.severity}">{escape(b.kind)}: {escape(b.label)}</span>' for b in s.badges
        )
        badges_html = f'<div class="badges">{chips}</div>'

    blocked_html = ""
    if s.plan:
        blocked_tasks = s.plan.blocked_tasks()
        if blocked_tasks:
            label = "Blocked task" if len(blocked_tasks) == 1 else "Blocked tasks"
            task_items = "".join(f"<li>{escape(t.text)}</li>" for t in blocked_tasks)
            blocked_html = f'<div class="blocked-task"><strong>{label}</strong><ul>{task_items}</ul></div>'

    pr_html = ""
    if s.pr:
        babysit = " (babysitting)" if s.pr.babysitting else ""
        pr_html = (
            f'<p class="pr">PR <a href="{escape(s.pr.url)}">#{s.pr.number}</a> '
            f"{escape(s.pr.state)} — mergeable: {escape(s.pr.mergeable)}, "
            f"CI: {escape(s.pr.ci_status)}{babysit}, "
            f"{s.pr.comment_count} comment(s), {s.pr.review_count} review(s)</p>"
        )
    elif s.pr_fetch_error:
        pr_html = f'<p class="pr-error">⚠ PR status unknown — {escape(s.pr_fetch_error)}</p>'

    return (
        f'<section class="card">\n'
        f"  <h2>{branch}{dirty_flag}</h2>\n"
        f'  <p class="path"><a href="file://{escape(path)}">{escape(path)}</a></p>\n'
        f'  <p class="stage">{stage} &middot; <span class="stale">{staleness}</span></p>\n'
        f"  {phase_html}\n"
        f"  {blocked_html}\n"
        f"  {badges_html}\n"
        f"  {pr_html}\n"
        f"</section>\n"
    )


def render_html(
    streams: list[StreamState],
    refresh_seconds: int,
    generated_at: dt.datetime,
    render_seconds: float | None = None,
) -> str:
    summary = compute_summary(streams)
    attention_items = []
    for s in streams:
        for reason in compute_needs_attention(s):
            attention_items.append(f"<li><strong>{escape(stream_label(s))}</strong> — {escape(reason)}</li>")
    if attention_items:
        banner = f'<div class="banner attention"><h2>Needs attention</h2><ul>{"".join(attention_items)}</ul></div>'
    else:
        banner = '<div class="banner ok">Nothing needs attention right now.</div>'

    cards = "".join(render_card(s) for s in streams) or "<p>No worktrees found.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>Worktree Pipeline Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Worktree Pipeline Dashboard</h1>
  <p class="summary">{escape(summary)}</p>
  <p class="generated">Generated {escape(generated_at.strftime('%Y-%m-%d %H:%M:%S'))} — refreshes every {refresh_seconds}s{f' — rendered in {render_seconds:.2f}s' if render_seconds is not None else ''}</p>
</header>
{banner}
<main>
{cards}</main>
</body>
</html>
"""


def write_dashboard(config: dict) -> pathlib.Path:
    started = time.monotonic()
    streams = build_streams(config)
    output_path = pathlib.Path(config.get("output_path") or DEFAULT_HTML_PATH).expanduser()
    html = render_html(
        streams,
        int(config.get("refresh_interval_seconds", DEFAULT_REFRESH_SECONDS)),
        dt.datetime.now(),
        time.monotonic() - started,
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DashboardError(f"could not create dashboard output directory {output_path.parent}: {exc}") from exc
    if output_path.is_symlink():
        raise SymlinkWriteRefused(f"{output_path} is a symlink — refusing to write through it")
    # Write to a same-directory temp file and atomically replace, so a browser's
    # meta-refresh (or a kill mid-write) never observes a truncated/partial document —
    # `Path.write_text` in place truncates the file before the new content lands. The
    # temp path's name is predictable (`.{name}.tmp<pid>`), so it gets the same
    # O_NOFOLLOW protection as the final path — a plain `Path.write_text` there would
    # follow a symlink pre-planted at that exact name, writing the rendered dashboard
    # through it to an attacker-chosen file.
    tmp_path = output_path.with_name(f".{output_path.name}.tmp{os.getpid()}")
    try:
        write_text_no_follow(tmp_path, html)
    except SymlinkWriteRefused as exc:
        # Deliberately a plain DashboardError, not SymlinkWriteRefused: the temp
        # path's name is fixed for this process's whole lifetime (PID-based), so
        # unlike a symlinked *final* output path (recoverable — an operator can fix
        # it while the watcher keeps running), a symlinked temp path will fail
        # identically on every future tick too. run_watch's initial-render check
        # treats a bare SymlinkWriteRefused there as non-fatal; this must not be
        # mistaken for that recoverable case, or a watcher could start and hold a
        # valid pidfile while every render silently fails forever.
        raise DashboardError(
            f"temp file for {output_path} ({tmp_path}) is a symlink — refusing to write through it"
        ) from exc
    except OSError as exc:
        raise DashboardError(f"could not write dashboard temp file {tmp_path}: {exc}") from exc
    try:
        tmp_path.replace(output_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise DashboardError(f"could not replace dashboard output {output_path}: {exc}") from exc
    return output_path


# --- 4.2 watch mode --------------------------------------------------------------------------


def is_live_dashboard_watcher(command: str, returncode: int) -> bool:
    """Pure check: does a `ps -o command=` result describe a live `dashboard.py --watch`
    process? Mirrors the liveness check in `skills/dashboard/SKILL.md`'s `stop`
    step — a non-zero `ps` exit means the PID isn't running at all."""
    if returncode != 0:
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if "-c" in argv:
        return False
    return "--watch" in argv and any(arg.endswith("scripts/dashboard/dashboard.py") for arg in argv)


def _read_live_watcher_pid(pid_path: pathlib.Path) -> int | None:
    """Return the PID in `pid_path` if it names a still-live `dashboard.py --watch`
    process, else None (missing file, unparseable PID, dead PID, or a PID reused by an
    unrelated process — all treated as "not a live watcher")."""
    try:
        pid = int(pid_path.read_text(encoding="utf-8").splitlines()[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if is_live_dashboard_watcher(proc.stdout, proc.returncode):
        return pid
    return None


def check_watch_start_preconditions(pid_path: pathlib.Path = DEFAULT_PID_PATH) -> None:
    """Refuse starts that cannot proceed before opening/truncating the watcher log."""
    if pid_path.is_symlink():
        raise SymlinkWriteRefused(f"{pid_path} is a symlink — refusing to write through it")
    live_pid = _read_live_watcher_pid(pid_path)
    if live_pid is not None:
        raise DashboardError(
            f"an existing dashboard watcher is already running as pid {live_pid}; "
            f"stop it first"
        )


def _read_lock_bytes(lock_path: pathlib.Path) -> bytes | None:
    """Read a lock file's bytes without following a symlink, or None if it is
    absent or is a symlink (a swapped-in symlink is treated as "not ours")."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags)
    except OSError:
        return None
    try:
        return os.read(fd, 4096)
    finally:
        os.close(fd)


def _publish_watch_lock(lock_path: pathlib.Path) -> str | None:
    """Publish a fully written lock atomically, or return None if one exists.
    Identity is a random token on the lock's second line (its first line is the
    owning pid, kept for liveness checks). Inode numbers are not stable across
    unlink+recreate on every filesystem — ext4 reuses them — so ownership must
    be established by content, not by (st_dev, st_ino)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    fd, temp_name = tempfile.mkstemp(prefix=f".{lock_path.name}.", dir=lock_path.parent)
    temp_path = pathlib.Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"{os.getpid()}\n{token}\n".encode("ascii"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(temp_path, lock_path, follow_symlinks=False)
        except FileExistsError:
            return None
        return token
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


def acquire_watch_lock(lock_path: pathlib.Path) -> str:
    """Atomically claim a complete watcher lock, reclaiming only a stable stale file."""
    for _ in range(3):
        try:
            identity = _publish_watch_lock(lock_path)
        except OSError as exc:
            raise DashboardError(f"could not acquire watcher lock {lock_path}: {exc}") from exc
        if identity is None:
            if lock_path.is_symlink():
                raise SymlinkWriteRefused(f"{lock_path} is a symlink — refusing it")
            before = _read_lock_bytes(lock_path)
            if before is None:
                continue
            live_pid = _read_live_watcher_pid(lock_path)
            if live_pid is not None:
                raise DashboardError(f"an existing dashboard watcher is already running as pid {live_pid}")
            after = _read_lock_bytes(lock_path)
            if after is None or after != before:
                continue
            lock_path.unlink(missing_ok=True)
            continue
        return identity
    raise DashboardError(f"watcher lock {lock_path} changed repeatedly; try again")


def release_watch_lock(lock_path: pathlib.Path, identity: str) -> None:
    """Remove the lock only if it still carries the token this process wrote.
    Ownership is by content, not inode: ext4 reuses inode numbers across
    unlink+recreate, so a stat-identity check could delete a lock a different
    process now holds."""
    raw = _read_lock_bytes(lock_path)
    if raw is None:
        return
    lines = raw.decode("ascii", "replace").splitlines()
    if len(lines) >= 2 and lines[1] == identity:
        lock_path.unlink(missing_ok=True)


def stop_watch(pid_path: pathlib.Path = DEFAULT_PID_PATH) -> int:
    if pid_path.is_symlink():
        raise SymlinkWriteRefused(f"{pid_path} is a symlink — refusing to signal from it")
    pid = _read_live_watcher_pid(pid_path)
    if pid is None:
        print("dashboard: no live watcher found")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise DashboardError(f"could not signal dashboard watcher {pid}: {exc}") from exc
    for _ in range(50):
        if not pid_path.exists() and _read_live_watcher_pid(pid_path) is None:
            print(f"dashboard: watcher {pid} stopped")
            return 0
        time.sleep(0.1)
    raise DashboardError(f"watcher {pid} did not exit cleanly; inspect {DEFAULT_LOG_PATH}")


def watch_status(config: dict, pid_path: pathlib.Path = DEFAULT_PID_PATH) -> int:
    if pid_path.is_symlink():
        raise SymlinkWriteRefused(f"{pid_path} is a symlink — refusing to trust it")
    pid = _read_live_watcher_pid(pid_path)
    output = pathlib.Path(config.get("output_path", DEFAULT_HTML_PATH)).expanduser()
    if pid is None:
        print("dashboard: stopped")
        return 1
    if output.is_symlink() or not output.is_file():
        print(f"dashboard: watcher {pid} is live but output is unavailable: {output}")
        return 1
    print(f"dashboard: running pid={pid} repo={config['repo_path']} output={output} log={DEFAULT_LOG_PATH}")
    return 0


def run_watch(config: dict, pid_path: pathlib.Path = DEFAULT_PID_PATH) -> None:
    """Loop rewriting the HTML every `refresh_interval_seconds`; write the pidfile on
    start and remove it on any clean exit (SIGTERM/SIGINT or falling out of the loop).

    Checks, in order: (1) the pidfile path itself is not a symlink — checked *before*
    any render, so a pre-planted pidfile symlink can never be masked by a freshly
    written `dashboard.html` that makes `/dashboard start` look like it succeeded;
    (2) no other live watcher already owns the pidfile (overwriting would orphan it);
    (3) the first render succeeds — a config whose `repo_path` is wrong (or isn't a
    git repo) refuses to start rather than leaving a live, pidfile-tracked process
    that can never write anything, with `/dashboard start` reporting success for a
    watcher that can never do its job. A symlinked *final output* path specifically
    is not treated as fatal here, even on this first render — matching every later
    tick, where it degrades to a logged, per-tick refusal rather than blocking
    startup, because an operator can fix it while the watcher keeps running (the
    pidfile, and therefore `/dashboard stop`, is unaffected by an html-only
    symlink). A symlinked *temp* path (the intermediate atomic-write target) is a
    different story and **is** fatal here even though it's also a `SymlinkWriteRefused`
    at the `write_dashboard` level — its name is fixed for this process's entire
    lifetime, so it would fail identically on every future tick, not just this one;
    `write_dashboard` re-raises that specific case as a plain `DashboardError` so it
    isn't mistaken for the recoverable final-output case here. Once past all three
    startup checks, later per-tick failures of any kind are logged-and-retried
    rather than fatal.
    """
    check_watch_start_preconditions(pid_path)
    lock_path = pid_path.with_suffix(pid_path.suffix + ".lock")
    lock_identity = acquire_watch_lock(lock_path)
    try:
        try:
            write_dashboard(config)
        except SymlinkWriteRefused as exc:
            print(f"dashboard: {exc}", file=sys.stderr)
    # Any other DashboardError (e.g. build_streams failing outright on a broken
    # repo_path) propagates uncaught here -- refuse to start rather than retry
    # forever on a config that can never produce any data at all.

        write_text_no_follow(pid_path, str(os.getpid()))

        stop = False

        def handle_signal(_signum: int, _frame: object) -> None:
            nonlocal stop
            stop = True

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        while not stop:
            try:
                write_dashboard(config)
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
            interval = int(config.get("refresh_interval_seconds", DEFAULT_REFRESH_SECONDS))
            for _ in range(interval):
                if stop:
                    break
                time.sleep(1)
    finally:
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        release_watch_lock(lock_path, lock_identity)


# --- CLI ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worktree pipeline dashboard")
    parser.add_argument("--selftest", action="store_true", help="run embedded fixture checks and exit")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="loop, rewriting the HTML on a timer")
    mode.add_argument("--stop", action="store_true", help="stop the validated background watcher")
    mode.add_argument("--status", action="store_true", help="report validated watcher/output state")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="path to config.json")
    parser.add_argument("--repo", default=None, help="override repo_path from the config")
    parser.add_argument(
        "--log",
        default=None,
        help=(
            "watch-mode stderr log path; defaults to scripts/dashboard/dashboard.log, "
            "truncated on start and capped at 256 KiB"
        ),
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    try:
        require_supported_platform()
    except DashboardError as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 1
    if args.stop:
        try:
            return stop_watch()
        except DashboardError as exc:
            print(f"dashboard: {exc}", file=sys.stderr)
            return 1

    original_stderr = sys.stderr
    log_file: CappedLog | None = None
    log_path = pathlib.Path(args.log).expanduser() if args.log else DEFAULT_LOG_PATH
    try:
        config_path = pathlib.Path(args.config)
        if args.repo and not config_path.exists():
            config = {
                "repo_path": str(pathlib.Path(args.repo).expanduser().resolve()),
                "refresh_interval_seconds": DEFAULT_REFRESH_SECONDS,
            }
        else:
            try:
                config = load_config(config_path)
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
                return 1
        if args.repo:
            config["repo_path"] = str(pathlib.Path(args.repo).expanduser().resolve())

        if args.status:
            try:
                return watch_status(config)
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
                return 1

        ensure_local_excludes(config, log_path if args.watch else None)

        if args.watch:
            try:
                check_watch_start_preconditions()
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
                return 1
            try:
                log_file = CappedLog(log_path)
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
                return 1
            sys.stderr = log_file
            print(
                f"dashboard: watcher log started at {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"(max {DEFAULT_LOG_MAX_BYTES} bytes)",
                file=sys.stderr,
            )
            try:
                run_watch(config)
            except DashboardError as exc:
                print(f"dashboard: {exc}", file=sys.stderr)
                return 1
            return 0

        try:
            output_path = write_dashboard(config)
        except DashboardError as exc:
            print(f"dashboard: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {output_path}")
        return 0
    finally:
        if log_file is not None:
            sys.stderr = original_stderr
            log_file.close()


# --- selftest ------------------------------------------------------------------------------


@dataclass
class SelftestFailure:
    desc: str
    expected: object
    actual: object


class SelftestHarness:
    def __init__(self) -> None:
        self.failures: list[SelftestFailure] = []
        self.check_count = 0

    def check(self, desc: str, actual: object, expected: object = True) -> None:
        self.check_count += 1
        if actual != expected:
            self.failures.append(SelftestFailure(desc, expected, actual))

    def check_in(self, desc: str, actual: object, expected_values: tuple[object, ...]) -> None:
        self.check_count += 1
        if actual not in expected_values:
            self.failures.append(SelftestFailure(desc, expected_values, actual))

    def check_contains(self, desc: str, actual: list[str], substring: str) -> None:
        self.check_count += 1
        if not any(substring in item for item in actual):
            self.failures.append(SelftestFailure(desc, f"contains {substring!r}", actual))

    def check_not_contains(self, desc: str, actual: list[str], substring: str) -> None:
        self.check_count += 1
        if any(substring in item for item in actual):
            self.failures.append(SelftestFailure(desc, f"does not contain {substring!r}", actual))

    def check_raises(self, desc: str, exc_type: type[BaseException], func) -> None:
        self.check_count += 1
        try:
            func()
        except exc_type:
            return
        except Exception as exc:  # noqa: BLE001 - selftest reports unexpected exception types
            actual = f"raised {type(exc).__name__}: {exc}"
        else:
            actual = "returned normally"
        self.failures.append(SelftestFailure(desc, f"raises {exc_type.__name__}", actual))


SELFTEST_PLAN_TEXT = """\
# Some plan

| | |
|---|---|
| **Status** | in-progress |
| **Created** | 2026-07-01 |
| **Modified** | 2026-07-01 |
| **Branch** | plan/some-feature |
| **Related plans** | none |

## Implementation phases

### Phase 1 — Setup

- [x] 1.1 done task

**Validation:** n/a

### Phase 2 — Build

- [~] 2.1 in-progress task
- [ ] 2.2 not-started task

**Validation:** n/a

### Phase 3 — Ship

- [ ] 3.1 later task

**Validation:** n/a

## Definition of Done

- [ ] All success criteria met
"""


def _selftest_config_parsing(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config_path = pathlib.Path(tmp) / "config.json"
        config_path.write_text("[]", encoding="utf-8")
        h.check_raises("load_config: rejects a non-object JSON root", DashboardError, lambda: load_config(config_path))

        config_path.write_text(json.dumps({"repo_path": "/x", "refresh_interval_seconds": 0}), encoding="utf-8")
        h.check_raises("load_config: rejects refresh_interval_seconds=0", DashboardError, lambda: load_config(config_path))

        config_path.write_text(json.dumps({"repo_path": "/x", "refresh_interval_seconds": -5}), encoding="utf-8")
        h.check_raises("load_config: rejects negative refresh_interval_seconds", DashboardError, lambda: load_config(config_path))

        config_path.write_text(json.dumps({"repo_path": "/x", "refresh_interval_seconds": 30}), encoding="utf-8")
        h.check("load_config: accepts a positive refresh_interval_seconds", load_config(config_path)["refresh_interval_seconds"], 30)


def _selftest_platform_guard(h: SelftestHarness) -> None:
    h.check(
        "platform guard: supported POSIX platform with O_NOFOLLOW and ps -> no error",
        platform_support_error("posix", "linux", True, True),
        None,
    )
    h.check(
        "platform guard: Windows rejected with clear POSIX-only message",
        platform_support_error("nt", "win32", False, False),
        POSIX_ONLY_MESSAGE,
    )
    h.check(
        "platform guard: missing O_NOFOLLOW rejected with clear POSIX-only message",
        platform_support_error("posix", "linux", False, True),
        POSIX_ONLY_MESSAGE,
    )
    h.check(
        "platform guard: missing ps rejected with clear POSIX-only message",
        platform_support_error("posix", "linux", True, False),
        POSIX_ONLY_MESSAGE,
    )

    class Capture:
        def __init__(self) -> None:
            self.text = ""

        def write(self, text: str) -> None:
            self.text += text

        def flush(self) -> None:
            pass

    original_platform_check = globals()["current_platform_support_error"]
    original_stderr = sys.stderr
    capture = Capture()
    try:
        globals()["current_platform_support_error"] = lambda: POSIX_ONLY_MESSAGE
        sys.stderr = capture
        unsupported_exit = main([])
    finally:
        globals()["current_platform_support_error"] = original_platform_check
        sys.stderr = original_stderr
    h.check(
        "platform guard: normal main exits nonzero before POSIX-only paths",
        (unsupported_exit, POSIX_ONLY_MESSAGE in capture.text, "Traceback" in capture.text),
        (1, True, False),
    )


def _selftest_worktree_parsing(h: SelftestHarness) -> None:
    porcelain = (
        "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n"
        "worktree /repo/.claude/worktrees/feature\nHEAD def456\nbranch refs/heads/plan/some-feature\n\n"
        "worktree /repo/.claude/worktrees/scratch\nHEAD 789abc\ndetached\n"
    )
    wts = parse_worktree_list_porcelain(porcelain)
    h.check("worktree porcelain: 3 worktrees parsed", len(wts), 3)
    h.check("worktree porcelain: main branch", wts[0].branch if len(wts) > 0 else None, "main")
    h.check("worktree porcelain: plan/ branch", wts[1].branch if len(wts) > 1 else None, "plan/some-feature")
    h.check("worktree porcelain: detached has no branch", wts[2].branch if len(wts) > 2 else "missing", None)

    porcelain_with_prunable = porcelain + (
        "\nworktree /repo/.claude/worktrees/deleted\nHEAD 111222\n"
        "branch refs/heads/plan/deleted-feature\nprunable gitdir file points to non-existent location\n"
    )
    wts_pruned = parse_worktree_list_porcelain(porcelain_with_prunable)
    h.check(
        "worktree porcelain: a prunable record is skipped entirely, not treated as a live stream",
        (len(wts_pruned), any(w.branch == "plan/deleted-feature" for w in wts_pruned)),
        (3, False),
    )


def _selftest_plan_parsing(h: SelftestHarness) -> tuple[list[Phase], list[Phase]]:
    status, phases = parse_plan_text(SELFTEST_PLAN_TEXT)
    h.check("plan parse: status", status, "in-progress")
    h.check("plan parse: 3 phases", len(phases), 3)
    h.check(
        "plan parse: phase 1 has 1 task and is done",
        (len(phases[0].tasks), phases[0].done) if len(phases) > 0 else None,
        (1, True),
    )
    h.check("plan parse: phase 2 not done (has [~])", phases[1].done if len(phases) > 1 else None, False)
    h.check(
        "plan parse: Definition of Done checkbox not folded into phase 3",
        len(phases[2].tasks) if len(phases) > 2 else None,
        1,
    )
    info = PlanInfo(path=pathlib.Path("x.md"), status=status, phases=phases)
    h.check("plan parse: current phase is 2", info.current_phase_number(), 2)

    all_done_text = SELFTEST_PLAN_TEXT.replace("[~] 2.1", "[x] 2.1").replace("[ ] 2.2", "[x] 2.2").replace("[ ] 3.1", "[x] 3.1")
    _, phases_done = parse_plan_text(all_done_text)
    info_done = PlanInfo(path=pathlib.Path("x.md"), status="done", phases=phases_done)
    h.check("plan parse: all-done plan has no current phase", info_done.current_phase_number(), None)

    blocked_text = SELFTEST_PLAN_TEXT.replace("[~] 2.1", "[!] 2.1")
    _, phases_blocked = parse_plan_text(blocked_text)
    info_blocked = PlanInfo(path=pathlib.Path("x.md"), status="in-progress", phases=phases_blocked)
    h.check("plan parse: [!] counts as incomplete", info_blocked.current_phase_number(), 2)
    h.check("plan parse: has_blocked_task true", info_blocked.has_blocked_task())
    return phases_blocked, phases_done


def _selftest_review_verdict_parsing(h: SelftestHarness) -> None:
    b = classify_review_plan("Verdict: APPROVE — all checks green.\n")
    h.check("review-plan APPROVE -> good", (b.label, b.severity), ("APPROVE", "good"))
    b = classify_review_plan("Verdict: REVISE — one criterion unproven.\n")
    h.check("review-plan REVISE -> bad", (b.label, b.severity), ("REVISE", "bad"))
    b = classify_review_plan("Verdict: BLOCKED — validation cannot run.\n")
    h.check("review-plan BLOCKED -> bad", (b.label, b.severity), ("BLOCKED", "bad"))
    b = classify_review_plan("not a real report at all\n")
    h.check("review-plan malformed -> fallback", (b.label, b.severity), ("see report", "unknown"))

    b = classify_code_review("Verdict: No correctness issues found.\n")
    h.check("code-review clean bill -> good", (b.severity, b.count), ("good", 0))
    b = classify_code_review("Verdict: 2 confirmed findings (1 bug, 1 risk)\n")
    h.check("code-review with a bug -> bad", (b.severity, b.count), ("bad", 2))
    b = classify_code_review("garbage\n")
    h.check("code-review malformed -> fallback", (b.label, b.severity), ("see report", "unknown"))

    b = classify_security_audit("Verdict: No exploitable vulnerabilities found in this change.\n")
    h.check("security-audit clean bill -> good", (b.severity, b.count), ("good", 0))
    b = classify_security_audit("Verdict: 2 confirmed findings (1 high, 1 medium)\n")
    h.check("security-audit high finding -> bad + count", (b.severity, b.count), ("bad", 2))
    b = classify_security_audit("Verdict: 1 confirmed findings (1 low)\n")
    h.check("security-audit low-only finding -> warn (not bad)", (b.severity, b.count), ("warn", 1))
    b = classify_security_audit("garbage\n")
    h.check("security-audit malformed -> fallback", (b.label, b.severity), ("see report", "unknown"))

    b = classify_skill_safety_scan("# Skill safety scan\n\n## Verdict: CLEAR\n\nNo findings.\n")
    h.check("skill-safety-scan CLEAR -> good", (b.label, b.severity), ("CLEAR", "good"))
    b = classify_skill_safety_scan("## Verdict: NEEDS REVIEW\n")
    h.check("skill-safety-scan NEEDS REVIEW -> warn", b.severity, "warn")
    b = classify_skill_safety_scan("## Verdict: BLOCKED\n")
    h.check("skill-safety-scan BLOCKED -> bad", b.severity, "bad")
    b = classify_skill_safety_scan("nonsense, no heading\n")
    h.check("skill-safety-scan malformed -> fallback", (b.label, b.severity), ("see report", "unknown"))


def _selftest_report_lookup_parsing(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        review_dir = wt_path / "code-reviews"
        review_dir.mkdir()
        (review_dir / "2026-07-06-dashboard.md").write_text("x", encoding="utf-8")
        found = find_latest_review(wt_path, "code-reviews", ["dashboard"])
        h.check("find_latest_review: exact slug match still works", found.name if found is not None else None, "2026-07-06-dashboard.md")

        (review_dir / "2026-07-06-dashboard-2.md").write_text("x", encoding="utf-8")
        found_suffix = find_latest_review(wt_path, "code-reviews", ["dashboard"])
        h.check_in(
            "find_latest_review: same-day -N suffix still matches",
            found_suffix.name if found_suffix is not None else None,
            ("2026-07-06-dashboard.md", "2026-07-06-dashboard-2.md"),
        )

        (review_dir / "2026-07-06-worktree-pipeline-dashboard.md").write_text("x", encoding="utf-8")
        found_no_substr = find_latest_review(wt_path, "code-reviews", ["dashboard"])
        h.check_in(
            "find_latest_review: unrelated substring slug is not matched",
            found_no_substr.name if found_no_substr is not None else None,
            ("2026-07-06-dashboard.md", "2026-07-06-dashboard-2.md"),
        )

    h.check(
        "_report_declares_identity: review-plan Plan: line, matching",
        _report_declares_identity("Plan:    plans/2026-07-06-foo.md  (status: done)\n", None, pathlib.Path("plans/2026-07-06-foo.md")),
        True,
    )
    h.check(
        "_report_declares_identity: review-plan Plan: line, mismatched",
        _report_declares_identity("Plan:    plans/2026-07-06-other.md\n", None, pathlib.Path("plans/2026-07-06-foo.md")),
        False,
    )
    h.check(
        "_report_declares_identity: code-review/security-audit H1 branch, matching",
        _report_declares_identity("# Code Review — plan/api vs main  (1 file, +1/-0 lines)\n", "plan/api", None),
        True,
    )
    h.check(
        "_report_declares_identity: code-review/security-audit H1 branch, mismatched",
        _report_declares_identity("# Code Review — plan/api-2 vs main  (1 file, +1/-0 lines)\n", "plan/api", None),
        False,
    )
    h.check(
        "_report_declares_identity: no identity line -> None (unverifiable)",
        _report_declares_identity("no identity info here\n", "plan/foo", None),
        None,
    )

    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        review_dir = wt_path / "code-reviews"
        review_dir.mkdir()
        (review_dir / "2026-07-06-api.md").write_text(
            "# Code Review — plan/api vs main  (1 file, +1/-0 lines)\n\nVerdict: No correctness issues found.\n",
            encoding="utf-8",
        )
        (review_dir / "2026-07-06-api-2.md").write_text(
            "# Code Review — plan/api-2 vs main  (1 file, +1/-0 lines)\n\nVerdict: 1 confirmed findings (1 bug)\n",
            encoding="utf-8",
        )
        found_disambiguated = find_latest_review(wt_path, "code-reviews", ["api"], branch="plan/api")
        h.check(
            "find_latest_review: a -N-suffix candidate whose embedded identity disagrees is rejected",
            found_disambiguated.name if found_disambiguated is not None else None,
            "2026-07-06-api.md",
        )


def _selftest_plan_lookup_parsing(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        plans_dir = wt_path / "plans"
        plans_dir.mkdir()
        target = plans_dir / "2026-07-01-feature-foo.md"
        target.write_text("x", encoding="utf-8")
        unrelated = plans_dir / "2026-07-06-unrelated.md"
        unrelated.write_text("x", encoding="utf-8")
        os.utime(unrelated, (time.time() + 10, time.time() + 10))
        found_kebab = find_plan_for_worktree(Worktree(path=wt_path, branch="feature/foo"))
        h.check(
            "find_plan_for_worktree: non-plan/-prefixed branch matches its own kebab slug over a newer unrelated plan",
            found_kebab.name if found_kebab is not None else None,
            "2026-07-01-feature-foo.md",
        )

    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        plans_dir = wt_path / "plans"
        plans_dir.mkdir()
        real_branch = "claude/issue-triage-if9y4i"
        target = plans_dir / "2026-07-03-reviewer-agent.md"
        target.write_text(f"# Reviewer Agent\n\n| **Status** | done |\n| **Branch** | {real_branch} |\n", encoding="utf-8")
        unrelated = plans_dir / "2026-07-06-unrelated.md"
        unrelated.write_text("# Unrelated\n\n| **Status** | done |\n| **Branch** | other |\n", encoding="utf-8")
        os.utime(unrelated, (time.time() + 10, time.time() + 10))
        found_branch_meta = find_plan_for_worktree(Worktree(path=wt_path, branch=real_branch))
        h.check(
            "find_plan_for_worktree: Branch metadata match wins even when no slug could recover it",
            found_branch_meta.name if found_branch_meta is not None else None,
            "2026-07-03-reviewer-agent.md",
        )

    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        plans_dir = wt_path / "plans"
        plans_dir.mkdir()
        branch = "plan/flaky-branch"
        target = plans_dir / "2026-07-01-flaky-branch.md"
        target.write_text(f"# Target\n\n| **Branch** | {branch} |\n", encoding="utf-8")
        failing = plans_dir / "2026-07-06-flaky-branch.md"
        failing.write_text(f"# Flaky\n\n| **Branch** | {branch} |\n", encoding="utf-8")
        path_type = type(target)
        original_stat = path_type.stat

        def fake_branch_match_stat(self, *args, **kwargs):
            if self == failing:
                raise OSError("selftest injected stat failure")
            return original_stat(self, *args, **kwargs)

        try:
            path_type.stat = fake_branch_match_stat
            found_after_branch_stat_failure = find_plan_for_worktree(Worktree(path=wt_path, branch=branch))
        finally:
            path_type.stat = original_stat
        h.check(
            "find_plan_for_worktree: Branch metadata stat-failing candidate is skipped",
            found_after_branch_stat_failure.name if found_after_branch_stat_failure is not None else None,
            "2026-07-01-flaky-branch.md",
        )

    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        plans_dir = wt_path / "plans"
        plans_dir.mkdir()
        branch = "plan/all-unstatable"
        branch_match = plans_dir / "2026-07-01-all-unstatable.md"
        branch_match.write_text(f"# Target\n\n| **Branch** | {branch} |\n", encoding="utf-8")
        unrelated = plans_dir / "2026-07-06-unrelated.md"
        unrelated.write_text("# Unrelated\n\n| **Branch** | other |\n", encoding="utf-8")
        path_type = type(branch_match)
        original_stat = path_type.stat

        def fail_branch_match_stat(self, *args, **kwargs):
            if self == branch_match:
                raise OSError("selftest injected stat failure")
            return original_stat(self, *args, **kwargs)

        try:
            path_type.stat = fail_branch_match_stat
            found_all_unstatable_branch = find_plan_for_worktree(Worktree(path=wt_path, branch=branch))
        finally:
            path_type.stat = original_stat
        h.check(
            "find_plan_for_worktree: all Branch metadata matches unstatable -> unknown",
            found_all_unstatable_branch,
            None,
        )

    with tempfile.TemporaryDirectory() as tmp:
        wt_path = pathlib.Path(tmp)
        plans_dir = wt_path / "plans"
        plans_dir.mkdir()
        failing = plans_dir / "2026-07-01-feature-foo.md"
        failing.write_text("# Feature Foo\n", encoding="utf-8")
        target = plans_dir / "2026-07-02-feature-foo.md"
        target.write_text("# Feature Foo\n", encoding="utf-8")
        path_type = type(target)
        original_stat = path_type.stat

        def fake_slug_stat(self, *args, **kwargs):
            if self == failing:
                raise OSError("selftest injected stat failure")
            return original_stat(self, *args, **kwargs)

        try:
            path_type.stat = fake_slug_stat
            found_after_slug_stat_failure = find_plan_for_worktree(Worktree(path=wt_path, branch="feature/foo"))
        finally:
            path_type.stat = original_stat
        h.check(
            "find_plan_for_worktree: slug stat-failing candidate is skipped",
            found_after_slug_stat_failure.name if found_after_slug_stat_failure is not None else None,
            "2026-07-02-feature-foo.md",
        )


def _selftest_pr_json_core_parsing(h: SelftestHarness) -> None:
    pr_json = json.dumps(
        {
            "number": 42,
            "state": "OPEN",
            "url": "https://example/42",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "SUCCESS"}],
            "labels": [{"name": BABYSITTING_LABEL}],
            "comments": [{}, {}, {}],
            "reviews": [{}],
        }
    )
    pr = parse_gh_pr_json(pr_json)
    h.check("gh pr parse: number", pr.number if pr is not None else None, 42)
    h.check("gh pr parse: ci passing", pr.ci_status if pr is not None else None, "passing")
    h.check("gh pr parse: babysitting label detected", pr.babysitting if pr is not None else None)
    h.check("gh pr parse: comment/review counts", (pr.comment_count, pr.review_count) if pr is not None else None, (3, 1))
    h.check("gh pr parse: isDraft absent -> is_draft False", pr.is_draft if pr is not None else None, False)
    h.check("gh pr parse: mergeStateStatus read", pr.merge_state_status if pr is not None else None, "CLEAN")
    h.check("gh pr parse: reviewDecision read", pr.review_decision if pr is not None else None, "APPROVED")
    h.check("gh pr parse: empty output -> no PR", parse_gh_pr_json(""), None)
    h.check("gh pr parse: malformed json -> no PR", parse_gh_pr_json("not json"), None)

    minimal_pr_json = json.dumps({"number": 48, "state": "OPEN"})
    minimal_pr = parse_gh_pr_json(minimal_pr_json)
    h.check(
        "gh pr parse: mergeStateStatus/reviewDecision default sanely when absent",
        (minimal_pr.merge_state_status, minimal_pr.review_decision) if minimal_pr is not None else None,
        ("UNKNOWN", ""),
    )


def _selftest_pr_json_status_parsing(h: SelftestHarness) -> None:
    legacy_status_pr_json = json.dumps(
        {
            "number": 44,
            "state": "OPEN",
            "url": "https://example/44",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"state": "failure"}],
            "labels": [],
            "comments": [],
            "reviews": [],
        }
    )
    legacy_pr = parse_gh_pr_json(legacy_status_pr_json)
    h.check("gh pr parse: legacy commit-status 'failure' state -> ci failing", legacy_pr.ci_status if legacy_pr is not None else None, "failing")

    legacy_status_uppercase_json = json.dumps(
        {
            "number": 45,
            "state": "OPEN",
            "url": "https://example/45",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"state": "FAILURE"}],
            "labels": [],
            "comments": [],
            "reviews": [],
        }
    )
    legacy_uppercase_pr = parse_gh_pr_json(legacy_status_uppercase_json)
    h.check(
        "gh pr parse: legacy commit-status uppercase 'FAILURE' state -> ci failing",
        legacy_uppercase_pr.ci_status if legacy_uppercase_pr is not None else None,
        "failing",
    )

    startup_failure_pr_json = json.dumps(
        {
            "number": 46,
            "state": "OPEN",
            "url": "https://example/46",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"conclusion": "STARTUP_FAILURE"}],
            "labels": [],
            "comments": [],
            "reviews": [],
        }
    )
    startup_failure_pr = parse_gh_pr_json(startup_failure_pr_json)
    h.check("gh pr parse: STARTUP_FAILURE conclusion -> ci failing", startup_failure_pr.ci_status if startup_failure_pr is not None else None, "failing")

    stale_pr_json = json.dumps(
        {
            "number": 47,
            "state": "OPEN",
            "url": "https://example/47",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"conclusion": "STALE"}],
            "labels": [],
            "comments": [],
            "reviews": [],
        }
    )
    stale_pr = parse_gh_pr_json(stale_pr_json)
    h.check("gh pr parse: STALE conclusion -> ci failing (not silently passing)", stale_pr.ci_status if stale_pr is not None else None, "failing")

    draft_pr_json = json.dumps(
        {
            "number": 43,
            "state": "OPEN",
            "url": "https://example/43",
            "mergeable": "MERGEABLE",
            "isDraft": True,
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            "labels": [],
            "comments": [],
            "reviews": [],
        }
    )
    draft_pr = parse_gh_pr_json(draft_pr_json)
    h.check("gh pr parse: isDraft true -> is_draft True", draft_pr.is_draft if draft_pr is not None else None)


def _selftest_git_status_parsing(h: SelftestHarness) -> None:
    h.check("_unquote_git_path: plain path unchanged", _unquote_git_path("src/app.py"), "src/app.py")
    h.check("_unquote_git_path: quoted path with a space", _unquote_git_path('"file with space.txt"'), "file with space.txt")
    h.check("_unquote_git_path: escaped quote and backslash", _unquote_git_path('"a\\"b\\\\c"'), 'a"b\\c')
    h.check("_unquote_git_path: escaped tab/newline", _unquote_git_path('"a\\tb\\nc"'), "a\tb\nc")
    h.check("parse_git_status_porcelain: quoted path is unquoted", parse_git_status_porcelain('?? "file with space.txt"\n'), ["file with space.txt"])
    h.check(
        "parse_git_status_porcelain: NUL bytes preserve non-ASCII filenames",
        parse_git_status_porcelain("?? café.txt\0".encode()),
        ["café.txt"],
    )
    h.check(
        "parse_git_status_porcelain: NUL rename keeps destination and consumes source",
        parse_git_status_porcelain(b"R  new name.txt\0old name.txt\0"),
        ["new name.txt"],
    )


def _selftest_batched_pr_parsing(h: SelftestHarness) -> None:
    payload = json.dumps(
        [
            {
                "headRefName": "plan/one",
                "isCrossRepository": True,
                "number": 99,
                "state": "OPEN",
                "url": "https://example/fork",
                "labels": [],
                "comments": [],
                "reviews": [],
                "statusCheckRollup": [],
            },
            {
                "headRefName": "plan/one",
                "isCrossRepository": False,
                "number": 2,
                "state": "OPEN",
                "url": "https://example/2",
                "labels": [],
                "comments": [],
                "reviews": [],
                "statusCheckRollup": [],
            },
            {
                "headRefName": "plan/one",
                "number": 1,
                "state": "CLOSED",
                "url": "https://example/1",
                "labels": [],
                "comments": [],
                "reviews": [],
                "statusCheckRollup": [],
            },
        ]
    )
    by_branch, error = parse_gh_pr_list_json(payload)
    h.check("batched PR parse: valid payload has no error", error, None)
    h.check("batched PR parse: first/newest row wins for duplicate head", by_branch["plan/one"].number, 2)
    invalid, invalid_error = parse_gh_pr_list_json("not json")
    h.check("batched PR parse: invalid JSON yields empty index", invalid, {})
    h.check("batched PR parse: invalid JSON is visible", bool(invalid_error), True)


def _selftest_parsing(h: SelftestHarness) -> tuple[list[Phase], list[Phase]]:
    _selftest_config_parsing(h)
    _selftest_worktree_parsing(h)
    phases_blocked, phases_done = _selftest_plan_parsing(h)
    _selftest_review_verdict_parsing(h)
    _selftest_report_lookup_parsing(h)
    _selftest_plan_lookup_parsing(h)
    _selftest_pr_json_core_parsing(h)
    _selftest_pr_json_status_parsing(h)
    _selftest_git_status_parsing(h)
    _selftest_batched_pr_parsing(h)
    return phases_blocked, phases_done


def _selftest_make_stream(plan=None, badges=None, pr=None, default_branch=None, branch="plan/foo", pr_fetch_error=None, dirty=False):
    return StreamState(
        worktree=Worktree(path=pathlib.Path("/tmp/x"), branch=branch),
        plan=plan,
        badges=badges or [],
        pr=pr,
        default_branch=default_branch,
        dirty=dirty,
        last_change_epoch=None,
        pr_fetch_error=pr_fetch_error,
    )


def _selftest_make_pr(
    mergeable="MERGEABLE", ci_status="passing", babysitting=False, state="OPEN", is_draft=False,
    merge_state_status="CLEAN", review_decision="",
):
    return PrState(
        number=1, state=state, url="u", mergeable=mergeable, ci_status=ci_status,
        babysitting=babysitting, comment_count=0, review_count=0, is_draft=is_draft,
        merge_state_status=merge_state_status, review_decision=review_decision,
    )


def _selftest_aggregation(h: SelftestHarness, phases_blocked: list[Phase], phases_done: list[Phase]) -> None:
    h.check("stage: no plan", compute_stage(_selftest_make_stream(plan=None)), "No plan")
    h.check(
        "stage: draft/approved",
        compute_stage(_selftest_make_stream(plan=PlanInfo(pathlib.Path("x"), "approved", []))),
        "Plan draft/approved",
    )
    executing_plan = PlanInfo(pathlib.Path("x"), "in-progress", phases_blocked)
    h.check("stage: executing phase N of total", compute_stage(_selftest_make_stream(plan=executing_plan)), "Executing (Phase 2 of 3)")
    done_plan = PlanInfo(pathlib.Path("x"), "done", phases_done)
    h.check("stage: committed unshipped", compute_stage(_selftest_make_stream(plan=done_plan)), "Committed, unshipped")
    h.check(
        "stage: review badges",
        compute_stage(_selftest_make_stream(plan=done_plan, badges=[ReviewBadge("review-plan", "APPROVE", "good")])),
        "Review badges",
    )
    h.check("stage: PR open", compute_stage(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr())), "PR open")
    h.check(
        "stage: PR open babysitting",
        compute_stage(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(babysitting=True))),
        "PR open (babysitting)",
    )
    h.check("stage: merged", compute_stage(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(state="MERGED"))), "Merged")

    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr()))
    h.check_contains("attention: merge-ready PR", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(is_draft=True)))
    h.check_not_contains("attention: draft PR not flagged merge-ready", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(merge_state_status="BLOCKED")))
    h.check_not_contains("attention: mergeStateStatus BLOCKED not flagged merge-ready", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(merge_state_status="BEHIND")))
    h.check_not_contains("attention: mergeStateStatus BEHIND not flagged merge-ready", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(review_decision="REVIEW_REQUIRED")))
    h.check_not_contains("attention: reviewDecision REVIEW_REQUIRED not flagged merge-ready", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(review_decision="CHANGES_REQUESTED")))
    h.check_not_contains("attention: reviewDecision CHANGES_REQUESTED not flagged merge-ready", reasons, "merge-ready")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(review_decision="APPROVED")))
    h.check_contains("attention: reviewDecision APPROVED still flagged merge-ready", reasons, "merge-ready")

    revise_badge = ReviewBadge("review-plan", "REVISE", "bad")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, badges=[revise_badge]))
    h.check_contains("attention: REVISE verdict", reasons, "REVISE")
    sec_badge = ReviewBadge("security-audit", "1 finding", "bad", count=1)
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, badges=[sec_badge]))
    h.check_contains("attention: confirmed security-audit finding", reasons, "security-audit")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=_selftest_make_pr(mergeable="CONFLICTING")))
    h.check_contains("attention: merge conflict", reasons, "merge conflict")
    reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, branch="main", default_branch="main"))
    h.check_contains("attention: checked out on default branch", reasons, "default branch")
    blocked_reasons = compute_needs_attention(_selftest_make_stream(plan=executing_plan))
    h.check_contains("attention: blocked plan task", blocked_reasons, "blocked task")
    h.check_contains("attention: blocked plan task includes task text", blocked_reasons, "in-progress task")
    unblocked_reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan))
    h.check_not_contains("attention: plan without blocked task has no blocked-task reason", unblocked_reasons, "blocked task")
    clean_reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, default_branch="main", branch="plan/foo"))
    h.check("attention: clean stream has none", clean_reasons, [])
    fetch_error_reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr_fetch_error="gh pr view failed: not authenticated"))
    h.check_contains("attention: a genuine gh fetch error surfaces distinctly from 'no PR'", fetch_error_reasons, "PR status unknown")
    no_pr_reasons = compute_needs_attention(_selftest_make_stream(plan=done_plan, pr=None, pr_fetch_error=None))
    h.check_not_contains("attention: a stream with genuinely no PR (no fetch error) has no such reason", no_pr_reasons, "PR status unknown")

    h.check("dirty: only the plan file changed -> not dirty", is_dirty_beyond_plan(["plans/2026-07-01-foo.md"]), False)
    h.check("dirty: another file also changed -> dirty", is_dirty_beyond_plan(["plans/2026-07-01-foo.md", "src/app.py"]))
    h.check("dirty: no changes -> not dirty", is_dirty_beyond_plan([]), False)
    h.check("dirty: unknown git status -> unknown", is_dirty_beyond_plan(None), None)
    h.check("staleness: unknown git status -> unknown", compute_last_change_epoch(pathlib.Path("/tmp/x"), 123, None), None)

    original_subprocess_run = subprocess.run

    class FailedGitStatus:
        returncode = 128
        stdout = ""

    def fake_failed_git_status(*_args, **_kwargs):
        return FailedGitStatus()

    try:
        subprocess.run = fake_failed_git_status
        failed_dirty_paths = run_git_status(pathlib.Path("/tmp/dashboard-selftest"))
    finally:
        subprocess.run = original_subprocess_run
    failed_dirty_state = is_dirty_beyond_plan(failed_dirty_paths)
    failed_dirty_html = render_card(_selftest_make_stream(plan=done_plan, dirty=failed_dirty_state))
    h.check("run_git_status: git failure returns unknown sentinel", failed_dirty_paths, None)
    h.check("render_card: unknown dirty state renders unknown", "dirty: unknown" in failed_dirty_html)
    h.check("render_card: unknown dirty state has unknown staleness", "unknown</span>" in failed_dirty_html)
    summary = compute_summary([
        _selftest_make_stream(plan=done_plan, pr=_selftest_make_pr()),
        _selftest_make_stream(plan=None),
    ])
    h.check("summary: counts streams/PRs/attention", summary, "2 streams, 1 open PR, 1 needing attention")


def _selftest_rendering(h: SelftestHarness, phases_done: list[Phase]) -> None:
    h.check("escape: amp/lt/gt/double-quote", escape('<a href="x">&</a>'), "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;")
    h.check("escape: single quote -> &#x27;", escape("it's"), "it&#x27;s")

    done_plan = PlanInfo(pathlib.Path("x"), "done", phases_done)
    card_html = render_card(_selftest_make_stream(plan=done_plan, pr_fetch_error="gh pr view failed: rate limited"))
    h.check(
        "render_card: a gh fetch error renders a distinct warning, not silence",
        ("PR status unknown" in card_html, "rate limited" in card_html),
        (True, True),
    )
    blocked_plan = PlanInfo(pathlib.Path("x"), "in-progress", [Phase(1, "Escaping", [Task("!", "<unsafe & task>")])])
    blocked_card_html = render_card(_selftest_make_stream(plan=blocked_plan))
    h.check(
        "render_card: blocked task renders a visible indicator",
        ('class="blocked-task"' in blocked_card_html, "Blocked task" in blocked_card_html),
        (True, True),
    )
    h.check(
        "render_card: blocked task text is escaped",
        ("&lt;unsafe &amp; task&gt;" in blocked_card_html, "<unsafe & task>" in blocked_card_html),
        (True, False),
    )
    unblocked_card_html = render_card(_selftest_make_stream(plan=done_plan))
    h.check("render_card: card without blocked task has no blocked indicator", 'class="blocked-task"' in unblocked_card_html, False)
    blocked_dashboard_html = render_html([_selftest_make_stream(plan=blocked_plan)], 15, dt.datetime(2026, 7, 8, 12, 0, 0))
    h.check(
        "render_html: blocked task appears in the needs-attention banner",
        ("Needs attention" in blocked_dashboard_html, "plan has blocked task" in blocked_dashboard_html),
        (True, True),
    )


def _selftest_safe_file_reads(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        big_path = pathlib.Path(tmpdir) / "big.md"
        header = (
            "# Big Plan\n\n"
            "| **Status** | in-progress |\n\n"
            "### Phase 1 — Setup\n\n"
            "- [x] 1.1 done task\n\n"
        )
        big_text = header + ("x" * (READ_TEXT_MAX_BYTES * 2))
        big_path.write_text(big_text, encoding="utf-8")
        read_back = read_text_safely(big_path)
        h.check(
            "read_text_safely: truncates oversized file to the cap",
            (read_back is not None, len(read_back.encode("utf-8")) <= READ_TEXT_MAX_BYTES if read_back is not None else None),
            (True, True),
        )
        h.check("read_text_safely: truncated read still starts with the real header", read_back.startswith(header) if read_back is not None else None)
        trunc_status, trunc_phases = parse_plan_text(read_back) if read_back is not None else (None, [])
        h.check("read_text_safely: truncated text still parses status", trunc_status, "in-progress")
        h.check("read_text_safely: truncated text still parses phase 1", len(trunc_phases), 1)

        small_path = pathlib.Path(tmpdir) / "small.md"
        small_path.write_text("small file, no truncation needed\n", encoding="utf-8")
        h.check("read_text_safely: small file returned whole", read_text_safely(small_path), "small file, no truncation needed\n")

        missing_path = pathlib.Path(tmpdir) / "missing.md"
        h.check("read_text_safely: missing file -> None", read_text_safely(missing_path), None)


def _selftest_fixed_path_writes(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        symlink_target = root / "target.txt"
        symlink_target.write_text("original\n", encoding="utf-8")
        symlink_path = root / "victim.txt"
        symlink_path.symlink_to(symlink_target)

        refused = False
        try:
            write_text_no_follow(symlink_path, "changed\n")
        except SymlinkWriteRefused:
            refused = True
        h.check("write_text_no_follow: refuses a planted symlink", refused)
        h.check("write_text_no_follow: symlink target is not modified", symlink_target.read_text(encoding="utf-8"), "original\n")

        regular_path = root / "regular.txt"
        write_text_no_follow(regular_path, "first\n")
        write_text_no_follow(regular_path, "second\n")
        h.check("write_text_no_follow: writes and overwrites a regular file", regular_path.read_text(encoding="utf-8"), "second\n")

    h.check("local excludes: default watcher log path is covered", "scripts/dashboard/dashboard.log" in _LOCAL_EXCLUDE_LINES)
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        log_target = root / "log-target.txt"
        log_target.write_text("keep log target\n", encoding="utf-8")
        log_link = root / "dashboard.log"
        log_link.symlink_to(log_target)
        h.check_raises("CappedLog: refuses a planted symlink", SymlinkWriteRefused, lambda: CappedLog(log_link, max_bytes=32))
        h.check("CappedLog: symlink target is not modified", log_target.read_text(encoding="utf-8"), "keep log target\n")

        log_path = root / "bounded.log"
        log_path.write_text("stale previous run\n", encoding="utf-8")
        log = CappedLog(log_path, max_bytes=12)
        try:
            log.write("abc")
            h.check("CappedLog: truncates old contents on start", log_path.read_text(encoding="utf-8"), "abc")
            log.write("defghijklmnop")
            capped = log_path.read_text(encoding="utf-8")
            h.check("CappedLog: caps log size", log_path.stat().st_size <= 12)
            h.check("CappedLog: keeps newest log bytes", capped, "efghijklmnop")
        finally:
            log.close()

    original_build_streams = globals()["build_streams"]
    try:
        globals()["build_streams"] = lambda _config: []
        _selftest_write_dashboard_paths(h)
    finally:
        globals()["build_streams"] = original_build_streams


def _selftest_write_dashboard_paths(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        output_target = root / "output-target.html"
        output_target.write_text("keep me\n", encoding="utf-8")
        output_path = root / "dashboard.html"
        output_path.symlink_to(output_target)

        refused = False
        try:
            write_dashboard({"repo_path": str(root / "repo"), "output_path": str(output_path), "refresh_interval_seconds": 1})
        except SymlinkWriteRefused:
            refused = True
        h.check("write_dashboard: refuses a symlinked final output path", refused)
        h.check("write_dashboard: refused output path remains a symlink", output_path.is_symlink())
        h.check("write_dashboard: symlinked output target is not modified", output_target.read_text(encoding="utf-8"), "keep me\n")

        normal_output = root / "normal.html"
        result = write_dashboard({"repo_path": str(root / "repo"), "output_path": str(normal_output), "refresh_interval_seconds": 1})
        normal_html = normal_output.read_text(encoding="utf-8")
        normal_tmp = normal_output.with_name(f".{normal_output.name}.tmp{os.getpid()}")
        h.check("write_dashboard: regular output path writes successfully", (result, normal_output.exists()), (normal_output, True))
        h.check("write_dashboard: regular output renders dashboard HTML", "No worktrees found." in normal_html)
        h.check("write_dashboard: regular output leaves no temp file behind", normal_tmp.exists(), False)

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        output_path = root / "temp-symlink.html"
        tmp_path = output_path.with_name(f".{output_path.name}.tmp{os.getpid()}")
        tmp_target = root / "tmp-target.html"
        tmp_target.write_text("keep temp target\n", encoding="utf-8")
        tmp_path.symlink_to(tmp_target)

        refused = False
        try:
            write_dashboard({"repo_path": str(root / "repo"), "output_path": str(output_path), "refresh_interval_seconds": 1})
        except DashboardError as exc:
            refused = type(exc) is DashboardError and "temp file" in str(exc)
        h.check("write_dashboard: refuses a symlinked temp output path as fatal", refused)
        h.check("write_dashboard: refused temp path remains a symlink", tmp_path.is_symlink())
        h.check("write_dashboard: temp symlink target is not modified", tmp_target.read_text(encoding="utf-8"), "keep temp target\n")
        h.check("write_dashboard: temp symlink refusal leaves no final output", output_path.exists(), False)


def _selftest_pidfile_liveness(h: SelftestHarness) -> None:
    h.check("is_live_dashboard_watcher: live matching command -> True", is_live_dashboard_watcher("/usr/bin/python3 scripts/dashboard/dashboard.py --watch", 0))
    h.check("is_live_dashboard_watcher: non-zero ps exit (pid not running) -> False", is_live_dashboard_watcher("/usr/bin/python3 scripts/dashboard/dashboard.py --watch", 1), False)
    h.check("is_live_dashboard_watcher: pid reused by unrelated process -> False", is_live_dashboard_watcher("/usr/sbin/some-other-daemon", 0), False)
    h.check("is_live_dashboard_watcher: dashboard.py without --watch -> False", is_live_dashboard_watcher("/usr/bin/python3 scripts/dashboard/dashboard.py --selftest", 0), False)
    h.check(
        "is_live_dashboard_watcher: inline -c command is not the dashboard watcher",
        is_live_dashboard_watcher("/usr/bin/python3 -c 'print(1)' scripts/dashboard/dashboard.py --watch", 0),
        False,
    )
    h.check(
        "is_live_dashboard_watcher: bare dashboard.py name is not enough",
        is_live_dashboard_watcher("/usr/bin/python3 dashboard.py --watch", 0),
        False,
    )
    h.check(
        "is_live_dashboard_watcher: --watch substring is not enough",
        is_live_dashboard_watcher("/usr/bin/python3 scripts/dashboard/dashboard.py --watching", 0),
        False,
    )


def _selftest_run_watch_fixture(
    config: dict,
    pid_path: pathlib.Path,
    fake_write_dashboard,
    fake_sleep=None,
    fake_live_pid_reader=None,
    suppress_stderr: bool = False,
) -> None:
    original_write_dashboard = globals()["write_dashboard"]
    original_read_live_watcher_pid = globals()["_read_live_watcher_pid"]
    original_sleep = time.sleep
    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sigint = signal.getsignal(signal.SIGINT)
    original_stderr = sys.stderr
    stderr_file = None
    try:
        globals()["write_dashboard"] = fake_write_dashboard
        if fake_live_pid_reader is not None:
            globals()["_read_live_watcher_pid"] = fake_live_pid_reader
        if fake_sleep is not None:
            time.sleep = fake_sleep
        if suppress_stderr:
            stderr_file = open(os.devnull, "w", encoding="utf-8")
            sys.stderr = stderr_file
        run_watch(config, pid_path)
    finally:
        sys.stderr = original_stderr
        if stderr_file is not None:
            stderr_file.close()
        globals()["write_dashboard"] = original_write_dashboard
        globals()["_read_live_watcher_pid"] = original_read_live_watcher_pid
        time.sleep = original_sleep
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGINT, original_sigint)


def _selftest_stop_watch_on_next_sleep(_seconds) -> None:
    signal.raise_signal(signal.SIGINT)


def _selftest_watch_refuses_symlinked_pidfile(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pid_target = root / "pid-target.txt"
        pid_target.write_text("keep pid target\n", encoding="utf-8")
        pid_path = root / "dashboard.pid"
        pid_path.symlink_to(pid_target)
        render_calls: list[str] = []

        def fake_write_dashboard(_config):
            render_calls.append("render")
            return root / "dashboard.html"

        refused = False
        try:
            _selftest_run_watch_fixture({"refresh_interval_seconds": 1}, pid_path, fake_write_dashboard, fake_sleep=_selftest_stop_watch_on_next_sleep)
        except SymlinkWriteRefused:
            refused = True
        except KeyboardInterrupt:
            refused = False
        h.check("run_watch: refuses a symlinked pidfile before rendering", (refused, render_calls), (True, []))
        h.check("run_watch: refused pidfile path remains a symlink", pid_path.is_symlink())
        h.check("run_watch: symlinked pidfile target is not modified", pid_target.read_text(encoding="utf-8"), "keep pid target\n")


def _selftest_output_parent_and_atomic_lock(h: SelftestHarness) -> None:
    original_build_streams = globals()["build_streams"]
    original_live_reader = globals()["_read_live_watcher_pid"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            output = root / "missing" / "nested" / "dashboard.html"
            globals()["build_streams"] = lambda _config: []
            written = write_dashboard({"repo_path": str(root), "output_path": str(output)})
            h.check("write_dashboard: creates an explicitly configured parent", written.is_file(), True)

            lock = root / "dashboard.pid.lock"
            identity = acquire_watch_lock(lock)
            globals()["_read_live_watcher_pid"] = lambda _path: 1234
            refused = False
            try:
                acquire_watch_lock(lock)
            except DashboardError:
                refused = True
            h.check("watch lock: a live owner cannot be overwritten", refused, True)
            globals()["_read_live_watcher_pid"] = original_live_reader

            lock.unlink()
            lock.write_text("replacement", encoding="utf-8")
            release_watch_lock(lock, identity)
            h.check("watch lock: release spares a file it does not own", lock.read_text(), "replacement")

            lock.unlink(missing_ok=True)
            own_identity = acquire_watch_lock(lock)
            release_watch_lock(lock, own_identity)
            h.check("watch lock: release removes the lock it owns", lock.exists(), False)
    finally:
        globals()["build_streams"] = original_build_streams
        globals()["_read_live_watcher_pid"] = original_live_reader


def _selftest_watch_refuses_live_pidfile(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pid_path = root / "dashboard.pid"
        pid_path.write_text("4321\n", encoding="utf-8")
        render_calls: list[str] = []

        def fake_write_dashboard(_config):
            render_calls.append("render")
            return root / "dashboard.html"

        refused_live_pid = False
        try:
            _selftest_run_watch_fixture(
                {"refresh_interval_seconds": 1},
                pid_path,
                fake_write_dashboard,
                fake_sleep=_selftest_stop_watch_on_next_sleep,
                fake_live_pid_reader=lambda _pid_path: 4321,
            )
        except DashboardError as exc:
            refused_live_pid = "already running" in str(exc)
        except KeyboardInterrupt:
            refused_live_pid = False
        h.check("run_watch: refuses a live existing pidfile before rendering", (refused_live_pid, render_calls), (True, []))
        h.check("run_watch: refused live pidfile is left intact", pid_path.read_text(encoding="utf-8"), "4321\n")


def _selftest_watch_initial_render_failure(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pid_path = root / "dashboard.pid"
        render_calls: list[bool] = []

        def fake_write_dashboard(_config):
            render_calls.append(pid_path.exists())
            raise DashboardError("initial render failed")

        refused_startup = False
        try:
            _selftest_run_watch_fixture({"refresh_interval_seconds": 1}, pid_path, fake_write_dashboard, fake_sleep=_selftest_stop_watch_on_next_sleep)
        except DashboardError as exc:
            refused_startup = "initial render failed" in str(exc)
        except KeyboardInterrupt:
            refused_startup = False
        h.check("run_watch: fatal initial render failure refuses startup before pidfile write", (refused_startup, render_calls), (True, [False]))
        h.check("run_watch: fatal initial render failure leaves no pidfile", pid_path.exists(), False)


def _selftest_watch_loop_lifecycle(h: SelftestHarness) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pid_path = root / "dashboard.pid"
        render_pid_snapshots: list[str | None] = []

        def fake_write_dashboard(_config):
            render_pid_snapshots.append(pid_path.read_text(encoding="utf-8") if pid_path.exists() else None)
            if len(render_pid_snapshots) == 1:
                raise SymlinkWriteRefused("dashboard.html is a symlink")
            return root / "dashboard.html"

        completed = False
        try:
            _selftest_run_watch_fixture(
                {"refresh_interval_seconds": 1},
                pid_path,
                fake_write_dashboard,
                fake_sleep=_selftest_stop_watch_on_next_sleep,
                suppress_stderr=True,
            )
            completed = True
        except (DashboardError, KeyboardInterrupt):
            completed = False
        h.check(
            "run_watch: recoverable initial output symlink refusal still writes pidfile and enters loop",
            (completed, render_pid_snapshots),
            (True, [None, f"{os.getpid()}"]),
        )
        h.check("run_watch: recoverable output symlink path removes pidfile on exit", pid_path.exists(), False)

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pid_path = root / "dashboard.pid"
        render_pid_snapshots: list[str | None] = []

        def fake_write_dashboard(_config):
            render_pid_snapshots.append(pid_path.read_text(encoding="utf-8") if pid_path.exists() else None)
            return root / "dashboard.html"

        completed = False
        try:
            _selftest_run_watch_fixture({"refresh_interval_seconds": 1}, pid_path, fake_write_dashboard, fake_sleep=_selftest_stop_watch_on_next_sleep)
            completed = True
        except (DashboardError, KeyboardInterrupt):
            completed = False
        h.check(
            "run_watch: normal startup render happens before pidfile and loop render sees pidfile",
            (completed, render_pid_snapshots),
            (True, [None, f"{os.getpid()}"]),
        )
        h.check("run_watch: normal exit removes pidfile", pid_path.exists(), False)


def _selftest_main_watch_log(h: SelftestHarness) -> None:
    original_load_config = globals()["load_config"]
    original_ensure_local_excludes = globals()["ensure_local_excludes"]
    original_run_watch = globals()["run_watch"]
    original_read_live_watcher_pid = globals()["_read_live_watcher_pid"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log_path = root / "watch.log"
            log_path.write_text("stale previous watcher run\n", encoding="utf-8")
            excluded_log_paths: list[pathlib.Path | None] = []

            def fake_load_config(_path):
                return {"repo_path": str(root), "refresh_interval_seconds": 1}

            def fake_ensure_local_excludes(_config, log_path=None):
                excluded_log_paths.append(log_path)

            def fake_run_watch(_config):
                print("dashboard: per-tick failure", file=sys.stderr)

            globals()["load_config"] = fake_load_config
            globals()["ensure_local_excludes"] = fake_ensure_local_excludes
            globals()["run_watch"] = fake_run_watch
            globals()["_read_live_watcher_pid"] = lambda _pid_path: None

            rc = main(["--watch", "--config", str(root / "config.json"), "--log", str(log_path)])
            log_text = log_path.read_text(encoding="utf-8")
            h.check("main --watch --log: returns success when watcher exits cleanly", rc, 0)
            h.check("main --watch --log: routes watcher stderr to the log", "per-tick failure" in log_text)
            h.check("main --watch --log: truncates previous log contents", "stale previous watcher run" in log_text, False)
            h.check("main --watch --log: passes log path to local-exclude bookkeeping", excluded_log_paths, [log_path])

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log_path = root / "watch.log"
            log_path.write_text("active watcher history\n", encoding="utf-8")
            globals()["load_config"] = lambda _path: {"repo_path": str(root), "refresh_interval_seconds": 1}
            globals()["ensure_local_excludes"] = lambda _config, log_path=None: None
            globals()["run_watch"] = lambda _config: None
            globals()["_read_live_watcher_pid"] = lambda _pid_path: 4321

            original_stderr = sys.stderr
            try:
                with open(os.devnull, "w", encoding="utf-8") as sink:
                    sys.stderr = sink
                    rc = main(["--watch", "--config", str(root / "config.json"), "--log", str(log_path)])
            finally:
                sys.stderr = original_stderr
            h.check("main --watch --log: duplicate watcher start refuses", rc, 1)
            h.check(
                "main --watch --log: duplicate watcher start preserves active log",
                log_path.read_text(encoding="utf-8"),
                "active watcher history\n",
            )
    finally:
        globals()["load_config"] = original_load_config
        globals()["ensure_local_excludes"] = original_ensure_local_excludes
        globals()["run_watch"] = original_run_watch
        globals()["_read_live_watcher_pid"] = original_read_live_watcher_pid


def _selftest_installed_entrypoint(h: SelftestHarness) -> None:
    original_write_dashboard = globals()["write_dashboard"]
    original_ensure_local_excludes = globals()["ensure_local_excludes"]
    original_live_reader = globals()["_read_live_watcher_pid"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            captured: list[dict] = []

            def fake_write(config):
                captured.append(dict(config))
                output = root / "dashboard.html"
                output.write_text("ok\n", encoding="utf-8")
                return output

            globals()["write_dashboard"] = fake_write
            globals()["ensure_local_excludes"] = lambda _config, _log=None: None
            rc = main(["--repo", str(root), "--config", str(root / "missing.json")])
            h.check("installed dashboard entrypoint: --repo works without toolbelt config", rc, 0)
            h.check(
                "installed dashboard entrypoint: repo override reaches renderer",
                captured[0]["repo_path"] if captured else None,
                str(root.resolve()),
            )

            output = root / "status.html"
            output.write_text("ok\n", encoding="utf-8")
            globals()["_read_live_watcher_pid"] = lambda _path: 4321
            h.check(
                "installed dashboard entrypoint: status validates live output",
                watch_status({"repo_path": str(root), "output_path": str(output)}),
                0,
            )
    finally:
        globals()["write_dashboard"] = original_write_dashboard
        globals()["ensure_local_excludes"] = original_ensure_local_excludes
        globals()["_read_live_watcher_pid"] = original_live_reader


def _selftest_hardening(h: SelftestHarness) -> None:
    _selftest_platform_guard(h)
    _selftest_safe_file_reads(h)
    _selftest_fixed_path_writes(h)
    _selftest_pidfile_liveness(h)
    _selftest_watch_refuses_symlinked_pidfile(h)
    _selftest_output_parent_and_atomic_lock(h)
    _selftest_watch_refuses_live_pidfile(h)
    _selftest_watch_initial_render_failure(h)
    _selftest_watch_loop_lifecycle(h)
    _selftest_main_watch_log(h)
    _selftest_installed_entrypoint(h)


def selftest() -> int:
    h = SelftestHarness()
    phases_blocked, phases_done = _selftest_parsing(h)
    _selftest_aggregation(h, phases_blocked, phases_done)
    _selftest_rendering(h, phases_done)
    platform_error = current_platform_support_error()
    if platform_error:
        _selftest_platform_guard(h)
    else:
        _selftest_hardening(h)

    if h.failures:
        print("dashboard selftest: FAIL")
        for failure in h.failures:
            print(f"  - {failure.desc}")
            print(f"    expected: {failure.expected!r}")
            print(f"    actual:   {failure.actual!r}")
        print(f"dashboard selftest: {h.check_count} checks run")
        return 1
    suffix = f"; POSIX hardening checks skipped: {platform_error}" if platform_error else ""
    print(f"dashboard selftest: OK ({h.check_count} checks{suffix})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
