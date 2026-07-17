#!/usr/bin/env python3
"""Generate the weekly report-only janitor routine.

The routine reports maintenance candidates; it does not delete files, prune
branches, edit record files, or mutate GitHub issues.

Usage:

    python3 scripts/maintenance/weekly_janitor_report.py
    python3 scripts/maintenance/weekly_janitor_report.py --fetch --output report.md
    python3 scripts/maintenance/weekly_janitor_report.py --json
    python3 scripts/maintenance/weekly_janitor_report.py --selftest
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

import janitor_preview


LESSON_AGE_DAYS = 14
ISSUE_STALE_DAYS = 14
DEVLOG_ENTRY_LIMIT = 8
MERGE_LIMIT = 10
TARGET_ISSUE = 65
DASHBOARD_PRS = (81, 83, 84)

DEVLOG_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}\b", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class LessonAgeCandidate:
    line: int
    date: str
    age_days: int
    entry: str


@dataclasses.dataclass(frozen=True)
class LocalBranchCandidate:
    branch_name: str
    short_sha: str
    subject: str
    worktree_path: str | None
    scope: str = "local"


@dataclasses.dataclass(frozen=True)
class MergeCoverage:
    short_sha: str
    subject: str
    matched: bool
    evidence: str | None


@dataclasses.dataclass(frozen=True)
class DevlogCoverage:
    path: str
    entries_scanned: int
    merge_commits_scanned: int
    matched_count: int
    merges: list[MergeCoverage]


@dataclasses.dataclass(frozen=True)
class IssueActionItem:
    number: int
    title: str
    state: str
    state_reason: str | None
    updated_at: str
    closed_at: str | None
    url: str
    note: str


@dataclasses.dataclass(frozen=True)
class PullRequestItem:
    number: int
    title: str
    state: str
    merged_at: str | None
    url: str


@dataclasses.dataclass(frozen=True)
class StaleIssueCandidate:
    number: int
    title: str
    updated_at: str
    age_days: int
    labels: list[str]
    url: str


@dataclasses.dataclass(frozen=True)
class ClutterCandidate:
    path: str
    kind: str
    detail: str


@dataclasses.dataclass(frozen=True)
class IssueReport:
    repo_slug: str | None
    stale_days: int
    target_issue: int | None
    open_issues_scanned: int
    action_items: list[IssueActionItem]
    dashboard_prs: list[PullRequestItem]
    stale_open_issues: list[StaleIssueCandidate]


@dataclasses.dataclass(frozen=True)
class WeeklyReport:
    repo: pathlib.Path
    generated_at: str
    report_date: str
    base_ref: str | None
    fetched: bool
    lesson_age_days: int
    lesson_age_candidates: list[LessonAgeCandidate]
    absorbed_lesson_candidates: list[janitor_preview.LessonCandidate]
    devlog_coverage: DevlogCoverage
    branch_scope: str
    local_branch_candidates: list[LocalBranchCandidate]
    issue_report: IssueReport
    clutter_candidates: list[ClutterCandidate]
    findings: list[janitor_preview.Finding]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_iso_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def scan_old_lessons(text: str, *, today: dt.date, age_days: int) -> list[LessonAgeCandidate]:
    candidates: list[LessonAgeCandidate] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        match = janitor_preview.LESSON_ENTRY.match(line)
        if not match:
            continue
        lesson_date = dt.date.fromisoformat(match.group(1))
        age = (today - lesson_date).days
        if age > age_days:
            candidates.append(
                LessonAgeCandidate(
                    line=idx,
                    date=lesson_date.isoformat(),
                    age_days=age,
                    entry=line,
                )
            )
    return candidates


def parse_worktree_branches(repo: pathlib.Path) -> dict[str, str]:
    proc = janitor_preview.run(["git", "worktree", "list", "--porcelain"], cwd=repo, check=False)
    if proc.returncode != 0:
        return {}

    branches: dict[str, str] = {}
    current_worktree: str | None = None
    prefix = "refs/heads/"
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            current_worktree = line[len("worktree ") :]
        elif line.startswith("branch ") and current_worktree is not None:
            ref = line[len("branch ") :]
            if ref.startswith(prefix):
                branches[ref[len(prefix) :]] = current_worktree
    return branches


def local_branch_ref(branch_name: str) -> str:
    return f"refs/heads/{branch_name}"


def local_branch_tip_is_ancestor(repo: pathlib.Path, branch_name: str, base_ref: str) -> bool:
    proc = janitor_preview.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            local_branch_ref(branch_name),
            janitor_preview.qualify_remote_ref(base_ref),
        ],
        cwd=repo,
        check=False,
    )
    return proc.returncode == 0


def ref_tip_is_ancestor(repo: pathlib.Path, ref_name: str, base_ref: str) -> bool:
    proc = janitor_preview.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            ref_name,
            janitor_preview.qualify_remote_ref(base_ref),
        ],
        cwd=repo,
        check=False,
    )
    return proc.returncode == 0


def list_merged_local_branches(
    repo: pathlib.Path,
    *,
    base_ref: str | None,
) -> tuple[list[LocalBranchCandidate], list[janitor_preview.Finding]]:
    findings: list[janitor_preview.Finding] = []
    if base_ref is None:
        return [], [janitor_preview.Finding("local-branches", "Skipped local branch scan because base ref is unresolved.")]

    current = janitor_preview.run(["git", "branch", "--show-current"], cwd=repo, check=False).stdout.strip()
    base_branch = base_ref.removeprefix(f"{janitor_preview.REMOTE}/")
    worktree_paths = parse_worktree_branches(repo)

    proc = janitor_preview.run(
        [
            "git",
            "for-each-ref",
            f"--merged={janitor_preview.qualify_remote_ref(base_ref)}",
            "refs/heads",
            "--format=%(refname)%09%(objectname:short)%09%(subject)",
        ],
        cwd=repo,
    )
    prefix = "refs/heads/"
    candidates: list[LocalBranchCandidate] = []
    for line in proc.stdout.splitlines():
        full_refname, short_sha, subject = (line.split("\t", 2) + ["", ""])[:3]
        if not full_refname.startswith(prefix):
            findings.append(janitor_preview.Finding("local-branches", f"Skipping unexpected local ref: {full_refname}"))
            continue
        branch_name = full_refname[len(prefix) :]
        if branch_name in {current, base_branch}:
            continue
        if not local_branch_tip_is_ancestor(repo, branch_name, base_ref):
            findings.append(
                janitor_preview.Finding(
                    "local-branches",
                    f"{branch_name} appeared in --merged output but failed merge-base confirmation.",
                )
            )
            continue
        candidates.append(
            LocalBranchCandidate(
                branch_name=branch_name,
                short_sha=short_sha,
                subject=subject,
                worktree_path=worktree_paths.get(branch_name),
            )
        )
    return candidates, findings


def list_merged_remote_branches(
    repo: pathlib.Path,
    *,
    base_ref: str | None,
) -> tuple[list[LocalBranchCandidate], list[janitor_preview.Finding]]:
    findings: list[janitor_preview.Finding] = []
    if base_ref is None:
        return [], [janitor_preview.Finding("remote-branches", "Skipped remote branch scan because base ref is unresolved.")]

    base_branch = base_ref.removeprefix(f"{janitor_preview.REMOTE}/")
    proc = janitor_preview.run(
        [
            "git",
            "for-each-ref",
            f"--merged={janitor_preview.qualify_remote_ref(base_ref)}",
            f"refs/remotes/{janitor_preview.REMOTE}",
            "--format=%(refname)%09%(objectname:short)%09%(subject)",
        ],
        cwd=repo,
    )
    prefix = f"refs/remotes/{janitor_preview.REMOTE}/"
    candidates: list[LocalBranchCandidate] = []
    for line in proc.stdout.splitlines():
        full_refname, short_sha, subject = (line.split("\t", 2) + ["", ""])[:3]
        if not full_refname.startswith(prefix):
            findings.append(janitor_preview.Finding("remote-branches", f"Skipping unexpected remote ref: {full_refname}"))
            continue
        branch_name = full_refname[len(prefix) :]
        if branch_name in {"HEAD", base_branch}:
            continue
        if not ref_tip_is_ancestor(repo, full_refname, base_ref):
            findings.append(
                janitor_preview.Finding(
                    "remote-branches",
                    f"{janitor_preview.REMOTE}/{branch_name} appeared in --merged output but failed merge-base confirmation.",
                )
            )
            continue
        candidates.append(
            LocalBranchCandidate(
                branch_name=f"{janitor_preview.REMOTE}/{branch_name}",
                short_sha=short_sha,
                subject=subject,
                worktree_path=None,
                scope="remote",
            )
        )
    return candidates, findings


def devlog_tail(text: str, *, entry_limit: int) -> tuple[str, int]:
    matches = list(DEVLOG_HEADING.finditer(text))
    if not matches:
        return text, 0
    end = matches[entry_limit].start() if len(matches) > entry_limit else len(text)
    return text[matches[0].start() : end], min(len(matches), entry_limit)


def recent_merge_commits(repo: pathlib.Path, *, limit: int) -> list[tuple[str, str]]:
    proc = janitor_preview.run(
        ["git", "log", "--first-parent", "--merges", f"-n{limit}", "--format=%h%x09%s"],
        cwd=repo,
        check=False,
    )
    if proc.returncode != 0:
        return []
    commits: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        short_sha, subject = (line.split("\t", 1) + [""])[:2]
        commits.append((short_sha, subject))
    return commits


def merge_needles(subject: str) -> list[str]:
    needles = [subject]
    for number in re.findall(r"#(\d+)", subject):
        needles.extend([f"#{number}", f"PR #{number}", f"pull request #{number}"])
    from_match = re.search(r"\bfrom\s+[^/\s]+/(\S+)", subject)
    if from_match:
        needles.append(from_match.group(1))
    issue_match = re.search(r"\bissue[- #](\d+)", subject, flags=re.IGNORECASE)
    if issue_match:
        number = issue_match.group(1)
        needles.extend([f"issue-{number}", f"issue #{number}", f"#{number}"])
    # Preserve order while removing duplicates and empty strings.
    seen: set[str] = set()
    out: list[str] = []
    for needle in needles:
        needle = needle.strip()
        lowered = needle.lower()
        if needle and lowered not in seen:
            seen.add(lowered)
            out.append(needle)
    return out


def devlog_evidence_matches(haystack: str, needle: str) -> bool:
    lowered = needle.lower()
    escaped = re.escape(lowered)
    if re.fullmatch(r"#\d+", lowered):
        pattern = rf"(?<![#\w]){escaped}(?!\d)"
    elif re.fullmatch(r"(?:pr|pull request|issue)[ #\-]\d+", lowered):
        pattern = rf"(?<![\w-]){escaped}(?!\d)"
    else:
        pattern = rf"(?<![A-Za-z0-9_.-]){escaped}(?![A-Za-z0-9_./-])"
    return re.search(pattern, haystack) is not None


def scan_devlog_coverage(
    repo: pathlib.Path,
    *,
    entry_limit: int,
    merge_limit: int,
) -> tuple[DevlogCoverage, list[janitor_preview.Finding]]:
    path = repo / "DEVLOG.md"
    if not path.exists():
        return (
            DevlogCoverage("DEVLOG.md", 0, 0, 0, []),
            [janitor_preview.Finding("devlog", "DEVLOG.md is missing; recent merge coverage was not scanned.")],
        )
    tail, entries_scanned = devlog_tail(path.read_text(encoding="utf-8"), entry_limit=entry_limit)
    haystack = tail.lower()
    merges: list[MergeCoverage] = []
    for short_sha, subject in recent_merge_commits(repo, limit=merge_limit):
        evidence = next((needle for needle in merge_needles(subject) if devlog_evidence_matches(haystack, needle)), None)
        merges.append(MergeCoverage(short_sha=short_sha, subject=subject, matched=evidence is not None, evidence=evidence))
    matched_count = sum(1 for merge in merges if merge.matched)
    return DevlogCoverage("DEVLOG.md", entries_scanned, len(merges), matched_count, merges), []


def repo_slug(repo: pathlib.Path) -> str | None:
    proc = janitor_preview.run(["git", "remote", "get-url", janitor_preview.REMOTE], cwd=repo, check=False)
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    if url.startswith("https://github.com/"):
        slug = url.removeprefix("https://github.com/").removesuffix(".git")
        return slug or None
    ssh_match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1)
    return None


def gh_json(args: list[str]) -> tuple[object | None, str | None]:
    if shutil.which("gh") is None:
        return None, "`gh` is not installed; GitHub issue scan was skipped."
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"`gh {' '.join(args)}` failed: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        return None, detail
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"`gh {' '.join(args)}` returned invalid JSON: {exc}"


def parse_json_lines(output: str) -> tuple[list[dict[str, object]] | None, str | None]:
    records: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            return None, f"`gh api --jq` returned invalid JSON line: {exc}"
        if not isinstance(item, dict):
            return None, "`gh api --jq` returned a non-object JSON line."
        records.append(item)
    return records, None


def gh_json_lines(args: list[str]) -> tuple[list[dict[str, object]] | None, str | None]:
    if shutil.which("gh") is None:
        return None, "`gh` is not installed; GitHub issue scan was skipped."
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"`gh {' '.join(args)}` failed: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        return None, detail
    return parse_json_lines(proc.stdout)


def paginated_issue_records(payload: object) -> list[dict[str, object]] | None:
    """Flatten `gh api --paginate --slurp repos/:owner/:repo/issues` output."""
    if not isinstance(payload, list):
        return None
    pages: list[object]
    if all(isinstance(page, list) for page in payload):
        pages = payload
    else:
        pages = [payload]

    records: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, list):
            return None
        for item in page:
            if not isinstance(item, dict):
                return None
            # The REST issues endpoint includes pull requests; stale issue scans do not.
            if not item.get("pull_request"):
                records.append(item)
    return records


def label_names(labels: object) -> list[str]:
    if not isinstance(labels, list):
        return []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
            if name:
                names.append(str(name))
        elif isinstance(label, str):
            names.append(label)
    return names


def stale_issue_candidates_from_records(
    records: list[dict[str, object]],
    *,
    today: dt.date,
    stale_days: int,
) -> tuple[list[StaleIssueCandidate], list[janitor_preview.Finding]]:
    stale: list[StaleIssueCandidate] = []
    findings: list[janitor_preview.Finding] = []
    for issue in records:
        updated_at = str(issue.get("updated_at") or issue.get("updatedAt") or "")
        try:
            age = (today - parse_iso_datetime(updated_at).date()).days
        except ValueError:
            findings.append(
                janitor_preview.Finding("issues", f"Could not parse updated_at for issue #{issue.get('number')}: {updated_at}")
            )
            continue
        if age >= stale_days:
            stale.append(
                StaleIssueCandidate(
                    number=int(issue["number"]),
                    title=str(issue.get("title", "")),
                    updated_at=updated_at,
                    age_days=age,
                    labels=label_names(issue.get("labels")),
                    url=str(issue.get("html_url") or issue.get("url") or ""),
                )
            )
    return stale, findings


def scan_issues(
    repo: pathlib.Path,
    *,
    today: dt.date,
    stale_days: int,
    target_issue: int | None = TARGET_ISSUE,
    dashboard_prs: tuple[int, ...] = DASHBOARD_PRS,
) -> tuple[IssueReport, list[janitor_preview.Finding]]:
    findings: list[janitor_preview.Finding] = []
    slug = repo_slug(repo)
    if slug is None:
        findings.append(janitor_preview.Finding("issues", f"Could not parse GitHub repo slug from {janitor_preview.REMOTE}."))
        return IssueReport(None, stale_days, target_issue, 0, [], [], []), findings

    action_items: list[IssueActionItem] = []
    issue_payload: object | None = None
    issue_error: str | None = None
    if target_issue is not None:
        issue_payload, issue_error = gh_json(
            [
                "issue", "view", str(target_issue), "--repo", slug, "--json",
                "number,title,state,stateReason,updatedAt,closedAt,url",
            ]
        )
    if issue_error is not None and target_issue is not None:
        findings.append(janitor_preview.Finding("issues", f"Could not inspect issue #{target_issue}: {issue_error}"))
    elif isinstance(issue_payload, dict):
        state = str(issue_payload.get("state", "UNKNOWN"))
        state_reason = issue_payload.get("stateReason")
        closed_at = issue_payload.get("closedAt")
        if state == "CLOSED":
            note = (
                f"First actioned item is closed as {state_reason or 'closed'}"
                f"{f' at {closed_at}' if closed_at else ''}."
            )
        else:
            note = (
                "First actioned item remains open; close it if the dashboard work is complete "
                "or slim it to the remaining instrumentation ideas."
            )
        action_items.append(
            IssueActionItem(
                number=int(issue_payload["number"]),
                title=str(issue_payload.get("title", "")),
                state=state,
                state_reason=str(state_reason) if state_reason is not None else None,
                updated_at=str(issue_payload.get("updatedAt", "")),
                closed_at=str(closed_at) if closed_at else None,
                url=str(issue_payload.get("url", "")),
                note=note,
            )
        )

    dashboard_pr_items: list[PullRequestItem] = []
    for number in dashboard_prs:
        pr_payload, pr_error = gh_json(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                slug,
                "--json",
                "number,title,state,mergedAt,url",
            ]
        )
        if pr_error is not None:
            findings.append(janitor_preview.Finding("issues", f"Could not inspect PR #{number}: {pr_error}"))
        elif isinstance(pr_payload, dict):
            dashboard_pr_items.append(
                PullRequestItem(
                    number=int(pr_payload["number"]),
                    title=str(pr_payload.get("title", "")),
                    state=str(pr_payload.get("state", "UNKNOWN")),
                    merged_at=str(pr_payload["mergedAt"]) if pr_payload.get("mergedAt") else None,
                    url=str(pr_payload.get("url", "")),
                )
            )

    open_records, open_error = gh_json_lines(
        [
            "api",
            "--method",
            "GET",
            "--paginate",
            f"repos/{slug}/issues",
            "-f",
            "state=open",
            "-f",
            "per_page=100",
            "--jq",
            ".[] | {number,title,updated_at,labels,html_url,pull_request}",
        ]
    )
    stale: list[StaleIssueCandidate] = []
    open_count = 0
    if open_error is not None:
        findings.append(janitor_preview.Finding("issues", f"Could not list open issues: {open_error}"))
    elif open_records is not None:
        open_records = [record for record in open_records if not record.get("pull_request")]
        open_count = len(open_records)
        stale, stale_findings = stale_issue_candidates_from_records(
            open_records,
            today=today,
            stale_days=stale_days,
        )
        findings.extend(stale_findings)
    return IssueReport(slug, stale_days, target_issue, open_count, action_items, dashboard_pr_items, stale), findings


def scan_clutter(repo: pathlib.Path) -> list[ClutterCandidate]:
    candidates: list[ClutterCandidate] = []
    for root, dirs, files in os.walk(repo):
        root_path = pathlib.Path(root)
        if ".git" in dirs:
            dirs.remove(".git")
        if "__pycache__" in dirs:
            pycache = root_path / "__pycache__"
            pycache_files = sum(1 for child in pycache.rglob("*") if child.is_file())
            candidates.append(
                ClutterCandidate(
                    path=pycache.relative_to(repo).as_posix(),
                    kind="pycache_dir",
                    detail=f"{pycache_files} cached files",
                )
            )
            dirs.remove("__pycache__")
        for filename in files:
            path = root_path / filename
            if filename == ".DS_Store":
                candidates.append(
                    ClutterCandidate(path=path.relative_to(repo).as_posix(), kind="ds_store", detail="macOS metadata file")
                )
            elif filename.endswith(".pyc"):
                candidates.append(
                    ClutterCandidate(path=path.relative_to(repo).as_posix(), kind="pyc_file", detail="Python bytecode file")
                )
    return sorted(candidates, key=lambda candidate: (candidate.kind, candidate.path))


def build_report(
    repo: pathlib.Path,
    *,
    fetch: bool,
    branch_scope: str,
    lesson_age_days: int,
    issue_stale_days: int,
    devlog_entry_limit: int,
    merge_limit: int,
    target_issue: int | None = TARGET_ISSUE,
    dashboard_prs: tuple[int, ...] = DASHBOARD_PRS,
    now: dt.datetime | None = None,
) -> WeeklyReport:
    now = now or utc_now()
    today = now.date()
    preview = janitor_preview.build_preview(repo, fetch=fetch)
    findings = list(preview.findings)

    lessons_path = repo / "LESSONS.md"
    if lessons_path.exists():
        lesson_age_candidates = scan_old_lessons(
            lessons_path.read_text(encoding="utf-8"),
            today=today,
            age_days=lesson_age_days,
        )
    else:
        lesson_age_candidates = []
        findings.append(janitor_preview.Finding("lessons", "LESSONS.md is missing; lesson age scan was skipped."))

    devlog_coverage, devlog_findings = scan_devlog_coverage(repo, entry_limit=devlog_entry_limit, merge_limit=merge_limit)
    findings.extend(devlog_findings)

    if branch_scope == "remote":
        local_branch_candidates = [
            LocalBranchCandidate(
                branch_name=candidate.branch_name,
                short_sha=candidate.short_sha,
                subject=candidate.subject,
                worktree_path=None,
                scope="remote",
            )
            for candidate in preview.branch_candidates
        ]
        local_branch_findings = []
    else:
        local_branch_candidates, local_branch_findings = list_merged_local_branches(repo, base_ref=preview.base_ref)
    findings.extend(local_branch_findings)

    issue_report, issue_findings = scan_issues(
        repo,
        today=today,
        stale_days=issue_stale_days,
        target_issue=target_issue,
        dashboard_prs=dashboard_prs,
    )
    findings.extend(issue_findings)

    return WeeklyReport(
        repo=repo,
        generated_at=now.isoformat(),
        report_date=today.isoformat(),
        base_ref=preview.base_ref,
        fetched=preview.fetched,
        lesson_age_days=lesson_age_days,
        lesson_age_candidates=lesson_age_candidates,
        absorbed_lesson_candidates=preview.lesson_candidates,
        devlog_coverage=devlog_coverage,
        branch_scope=branch_scope,
        local_branch_candidates=local_branch_candidates,
        issue_report=issue_report,
        clutter_candidates=scan_clutter(repo),
        findings=findings,
    )


def report_to_json(report: WeeklyReport) -> str:
    payload = dataclasses.asdict(report)
    payload["repo"] = str(report.repo)
    payload["dry_run"] = True
    payload["report_only"] = True
    return json.dumps(payload, indent=2, sort_keys=True)


def render_markdown(report: WeeklyReport) -> str:
    md_code_span = janitor_preview.md_code_span
    devlog = report.devlog_coverage
    missing_merges = [merge for merge in devlog.merges if not merge.matched]
    lines = [
        "# Weekly Janitor Report",
        "",
        f"- Repo: `{report.repo}`",
        f"- Generated: `{report.generated_at}`",
        f"- Report date: `{report.report_date}`",
        f"- Base ref: {md_code_span(report.base_ref or 'unresolved')}",
        f"- Fetch succeeded: `{'yes' if report.fetched else 'no'}`",
        "- Mode: report-only; no branches, files, pull requests, or issues were deleted, created, edited, closed, or reopened.",
        "",
        f"## LESSONS Entries Older Than {report.lesson_age_days} Days Or Absorbed",
        "",
        (
            f"- Path: `LESSONS.md`; older-than candidates: `{len(report.lesson_age_candidates)}`; "
            f"absorbed-marker candidates: `{len(report.absorbed_lesson_candidates)}`."
        ),
    ]

    if report.lesson_age_candidates:
        for candidate in report.lesson_age_candidates:
            lines.append(
                f"- `LESSONS.md:{candidate.line}` age `{candidate.age_days}` days: {candidate.entry}"
            )
    if report.absorbed_lesson_candidates:
        for candidate in report.absorbed_lesson_candidates:
            lines.append(
                f"- `LESSONS.md:{candidate.marker_line}-{candidate.lesson_line}` absorbed: {candidate.entry}\n"
                f"  Human flag reason: {candidate.reason}"
            )
    if not report.lesson_age_candidates and not report.absorbed_lesson_candidates:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## DEVLOG Tail Vs Recent Merges",
            "",
            (
                f"- Path: `{devlog.path}`; entries scanned: `{devlog.entries_scanned}`; "
                f"merge commits scanned: `{devlog.merge_commits_scanned}`; "
                f"matched: `{devlog.matched_count}`; missing: `{len(missing_merges)}`."
            ),
        ]
    )
    if devlog.merges:
        for merge in missing_merges:
            lines.append(f"- Missing DEVLOG-tail evidence: `{merge.short_sha}` {merge.subject}")
        if not missing_merges:
            lines.append("- All scanned merge commits had evidence in the DEVLOG tail.")
    else:
        lines.append("- No recent merge commits found.")

    lines.extend(
        [
            "",
            "## Fully Merged Branches",
            "",
            (
                f"- Scope: `{report.branch_scope}`; "
                f"base ref: {md_code_span(report.base_ref or 'unresolved')}; "
                f"candidates: `{len(report.local_branch_candidates)}`."
            ),
        ]
    )
    if report.local_branch_candidates:
        for candidate in report.local_branch_candidates:
            subject = f" - {candidate.subject}" if candidate.subject else ""
            worktree = f"; worktree: `{candidate.worktree_path}`" if candidate.worktree_path else ""
            lines.append(f"- {md_code_span(candidate.branch_name)} at `{candidate.short_sha}`{subject}; scope: `{candidate.scope}`{worktree}")
    else:
        lines.append("- None.")

    issue = report.issue_report
    lines.extend(
        [
            "",
            "## Stale Open Issues",
            "",
            (
                f"- Repo: `{issue.repo_slug or 'unresolved'}`; stale threshold: `{issue.stale_days}` days; "
                f"open issues scanned: `{issue.open_issues_scanned}`; "
                f"stale open issues: `{len(issue.stale_open_issues)}`."
            ),
        ]
    )
    if issue.action_items:
        for action in issue.action_items:
            reason = f"/{action.state_reason}" if action.state_reason else ""
            lines.append(
                f"- First actioned item: #{action.number} `{action.state}{reason}` updated `{action.updated_at}`: "
                f"{action.title} ({action.url})\n"
                f"  {action.note}"
            )
    elif issue.target_issue is None:
        lines.append("- First actioned item inspection is disabled.")
    else:
        lines.append(f"- First actioned item: issue #{issue.target_issue} could not be inspected.")
    if issue.dashboard_prs:
        for pr in issue.dashboard_prs:
            merged = f", merged `{pr.merged_at}`" if pr.merged_at else ""
            lines.append(
                f"- Dashboard PR #{pr.number}: `{pr.state}`{merged}: {pr.title} ({pr.url})"
            )
    if issue.stale_open_issues:
        for stale in issue.stale_open_issues:
            labels = f"; labels: {', '.join(stale.labels)}" if stale.labels else ""
            lines.append(
                f"- Stale open issue: #{stale.number} age `{stale.age_days}` days, updated `{stale.updated_at}`"
                f"{labels}: {stale.title} ({stale.url})"
            )
    else:
        lines.append("- No stale open issues at the configured threshold.")

    lines.extend(
        [
            "",
            "## .DS_Store / pycache Clutter",
            "",
            f"- Scope: repo tree excluding `.git`; candidates: `{len(report.clutter_candidates)}`.",
        ]
    )
    if report.clutter_candidates:
        for candidate in report.clutter_candidates:
            lines.append(f"- `{candidate.path}` ({candidate.kind}): {candidate.detail}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Report-Only Findings", ""])
    if report.findings:
        for finding in report.findings:
            lines.append(f"- `{finding.scope}`: {finding.message}")
    else:
        lines.append("- None.")

    return "\n".join(lines) + "\n"


def selftest() -> int:
    failures: list[str] = []
    today = dt.date(2026, 7, 8)
    old_lessons = scan_old_lessons(
        "# LESSONS\n\n- 2026-06-20 - Old enough.\n- 2026-06-25 - Also old.\n- 2026-07-01 - Fresh.\n",
        today=today,
        age_days=14,
    )
    if [candidate.line for candidate in old_lessons] != [3]:
        failures.append(f"lesson age scan reported wrong lines: {old_lessons!r}")

    tail, entries = devlog_tail(
        "# DEVLOG\n\n## 2026-07-08 - A\nbody issue #92\n\n## 2026-07-07 - B\nbody\n\n## 2026-07-06 - C\nbody\n",
        entry_limit=2,
    )
    if entries != 2 or "2026-07-06" in tail:
        failures.append("DEVLOG tail scanner did not stop at the configured entry limit")
    needles = merge_needles("Merge pull request #92 from example-org/m0-safety-net-selftests-dashboard")
    if "#92" not in needles or "m0-safety-net-selftests-dashboard" not in needles:
        failures.append(f"merge needles missed PR number or branch: {needles!r}")
    if not devlog_evidence_matches("body issue #92", "#92"):
        failures.append("DEVLOG evidence matcher missed an exact PR token")
    if devlog_evidence_matches("body issue #920", "#92"):
        failures.append("DEVLOG evidence matcher accepted a partial PR token")
    if not devlog_evidence_matches("from example-org/m0-safety-net-selftests-dashboard", "m0-safety-net-selftests-dashboard"):
        failures.append("DEVLOG evidence matcher missed an owner/branch mention")
    if devlog_evidence_matches("body old-m0-safety-net-selftests-dashboard-extra", "m0-safety-net-selftests-dashboard"):
        failures.append("DEVLOG evidence matcher accepted a partial branch token")
    parsed_lines, parse_error = parse_json_lines('{"number": 1}\n{"number": 2}\n')
    if parse_error is not None or [record["number"] for record in parsed_lines or []] != [1, 2]:
        failures.append(f"JSON-lines parser did not parse gh --jq output: records={parsed_lines!r} error={parse_error!r}")

    issue_pages = [
        [
            {
                "number": 1,
                "title": "Old issue",
                "updated_at": "2026-06-20T00:00:00Z",
                "labels": [{"name": "maintenance"}],
                "html_url": "https://github.com/example-org/repo/issues/1",
                "pull_request": None,
            }
        ],
        [
            {
                "number": 2,
                "title": "Open PR from issues endpoint",
                "updated_at": "2026-06-19T00:00:00Z",
                "pull_request": {"url": "https://api.github.com/repos/example-org/repo/pulls/2"},
                "html_url": "https://github.com/example-org/repo/pull/2",
            },
            {
                "number": 3,
                "title": "Fresh issue",
                "updated_at": "2026-07-07T00:00:00Z",
                "labels": [],
                "html_url": "https://github.com/example-org/repo/issues/3",
                "pull_request": None,
            },
        ],
    ]
    issue_records = paginated_issue_records(issue_pages)
    if [record["number"] for record in issue_records or []] != [1, 3]:
        failures.append(f"paginated issue records did not flatten pages or filter PRs: {issue_records!r}")
    elif issue_records is not None:
        stale_issues, issue_findings = stale_issue_candidates_from_records(
            issue_records,
            today=today,
            stale_days=14,
        )
        if issue_findings:
            failures.append(f"stale issue conversion unexpectedly reported findings: {issue_findings!r}")
        if [candidate.number for candidate in stale_issues] != [1] or stale_issues[0].labels != ["maintenance"]:
            failures.append(f"stale issue conversion reported wrong candidates: {stale_issues!r}")

    original_repo_slug = globals()["repo_slug"]
    original_gh_json = globals()["gh_json"]
    original_gh_json_lines = globals()["gh_json_lines"]
    pr_calls: list[int] = []
    try:
        globals()["repo_slug"] = lambda _repo: "owner/repo"

        def fake_gh_json(args):
            if args[:2] == ["issue", "view"]:
                return None, "unavailable"
            if args[:2] == ["pr", "view"]:
                number = int(args[2])
                pr_calls.append(number)
                return {
                    "number": number,
                    "title": f"PR {number}",
                    "state": "MERGED",
                    "mergedAt": "2026-07-01T00:00:00Z",
                    "url": f"https://example/{number}",
                }, None
            return None, "unexpected"

        globals()["gh_json"] = fake_gh_json
        globals()["gh_json_lines"] = lambda _args: ([], None)
        configured_report, _configured_findings = scan_issues(
            pathlib.Path("/repo"),
            today=today,
            stale_days=14,
            target_issue=7,
            dashboard_prs=(81, 83),
        )
        if pr_calls != [81, 83] or [item.number for item in configured_report.dashboard_prs] != [81, 83]:
            failures.append("configured dashboard PRs were not inspected and returned")
        if configured_report.target_issue != 7:
            failures.append("configured target issue was not retained in the report model")
    finally:
        globals()["repo_slug"] = original_repo_slug
        globals()["gh_json"] = original_gh_json
        globals()["gh_json_lines"] = original_gh_json_lines

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="weekly-janitor-selftest-"))
    try:
        (tmp / ".DS_Store").write_text("", encoding="utf-8")
        pycache = tmp / "pkg" / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "mod.cpython-311.pyc").write_bytes(b"")
        clutter = scan_clutter(tmp)
        kinds = {candidate.kind for candidate in clutter}
        if kinds != {"ds_store", "pycache_dir"}:
            failures.append(f"clutter scanner reported wrong kinds: {clutter!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    sample_report = WeeklyReport(
        repo=pathlib.Path("/repo"),
        generated_at="2026-07-08T00:00:00+00:00",
        report_date="2026-07-08",
        base_ref="origin/main",
        fetched=False,
        lesson_age_days=14,
        lesson_age_candidates=old_lessons,
        absorbed_lesson_candidates=[],
        devlog_coverage=DevlogCoverage(
            path="DEVLOG.md",
            entries_scanned=2,
            merge_commits_scanned=1,
            matched_count=0,
            merges=[MergeCoverage("abc1234", "Merge pull request #92 from example-org/example", False, None)],
        ),
        branch_scope="local",
        local_branch_candidates=[LocalBranchCandidate("old-branch", "abc1234", "done", None)],
        issue_report=IssueReport(
            repo_slug="example-org/repo",
            stale_days=14,
            target_issue=65,
            open_issues_scanned=0,
            action_items=[
                IssueActionItem(
                    number=65,
                    title="Pipeline dashboard",
                    state="CLOSED",
                    state_reason="COMPLETED",
                    updated_at="2026-07-08T01:43:23Z",
                    closed_at="2026-07-08T01:43:23Z",
                    url="https://github.com/example-org/repo/issues/65",
                    note="First actioned item is closed as COMPLETED at 2026-07-08T01:43:23Z.",
                )
            ],
            dashboard_prs=[
                PullRequestItem(
                    number=83,
                    title="Worktree pipeline dashboard",
                    state="MERGED",
                    merged_at="2026-07-06T22:34:16Z",
                    url="https://github.com/example-org/repo/pull/83",
                )
            ],
            stale_open_issues=[],
        ),
        clutter_candidates=[],
        findings=[],
    )
    rendered = render_markdown(sample_report)
    expected_headings = (
        "## LESSONS Entries Older Than 14 Days Or Absorbed",
        "## DEVLOG Tail Vs Recent Merges",
        "## Fully Merged Branches",
        "## Stale Open Issues",
        "## .DS_Store / pycache Clutter",
    )
    for heading in expected_headings:
        if heading not in rendered:
            failures.append(f"markdown report omitted heading: {heading}")
    if "report-only" not in rendered or "First actioned item: #65" not in rendered:
        failures.append("markdown report omitted report-only mode or issue #65 action item")
    if "Dashboard PR #83" not in rendered:
        failures.append("markdown report omitted dashboard PR context")
    custom_issue_report = dataclasses.replace(
        sample_report.issue_report,
        target_issue=7,
        action_items=[],
    )
    custom_rendered = render_markdown(dataclasses.replace(sample_report, issue_report=custom_issue_report))
    if "issue #7 could not be inspected" not in custom_rendered or "issue #65 could not be inspected" in custom_rendered:
        failures.append("markdown report did not render the configured target issue")

    parsed = json.loads(report_to_json(sample_report))
    if parsed["report_only"] is not True or parsed["issue_report"]["action_items"][0]["number"] != 65:
        failures.append("json report omitted report_only flag or issue #65 action item")

    if failures:
        print("weekly janitor report selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("weekly janitor report selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Path inside the repo to scan (default: current directory).")
    parser.add_argument("--fetch", action="store_true", help="Refresh origin refs before scanning.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Markdown.")
    parser.add_argument("--output", help="Write the report to this path instead of stdout.")
    parser.add_argument(
        "--branch-scope",
        choices=("local", "remote"),
        default="local",
        help="Scan developer-local branches or remote-tracking branches for merged cleanup candidates.",
    )
    parser.add_argument("--lesson-age-days", type=int, default=LESSON_AGE_DAYS)
    parser.add_argument("--issue-stale-days", type=int, default=ISSUE_STALE_DAYS)
    parser.add_argument("--devlog-entries", type=int, default=DEVLOG_ENTRY_LIMIT)
    parser.add_argument("--merge-limit", type=int, default=MERGE_LIMIT)
    parser.add_argument(
        "--target-issue",
        type=int,
        default=TARGET_ISSUE,
        help="Optional issue to call out first; use 0 to disable (default: %(default)s).",
    )
    parser.add_argument(
        "--dashboard-prs",
        default=",".join(str(number) for number in DASHBOARD_PRS),
        help="Comma-separated PR numbers to summarize; empty disables the list.",
    )
    parser.add_argument("--selftest", action="store_true", help="Run embedded parser/report tests.")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    try:
        repo = janitor_preview.git_root(pathlib.Path(args.repo).resolve())
        try:
            dashboard_prs = tuple(
                int(value.strip()) for value in args.dashboard_prs.split(",") if value.strip()
            )
        except ValueError as exc:
            raise janitor_preview.GitError(f"--dashboard-prs must contain integers: {exc}") from exc
        report = build_report(
            repo,
            fetch=args.fetch,
            branch_scope=args.branch_scope,
            lesson_age_days=args.lesson_age_days,
            issue_stale_days=args.issue_stale_days,
            devlog_entry_limit=args.devlog_entries,
            merge_limit=args.merge_limit,
            target_issue=args.target_issue or None,
            dashboard_prs=dashboard_prs,
        )
    except janitor_preview.GitError as exc:
        print(f"weekly janitor report: {exc}", file=sys.stderr)
        return 2

    rendered = report_to_json(report) + "\n" if args.json else render_markdown(report)
    if args.output:
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
