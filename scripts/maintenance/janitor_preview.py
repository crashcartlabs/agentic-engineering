#!/usr/bin/env python3
"""Preview the narrow Janitor-Agent cleanup slice.

This is intentionally a dry-run prototype. It discovers cleanup candidates and prints
the proposed actions, but it never deletes a branch, edits LESSONS.md, opens a branch,
or creates a pull request.

Usage:

    python3 scripts/maintenance/janitor_preview.py
    python3 scripts/maintenance/janitor_preview.py --json
    python3 scripts/maintenance/janitor_preview.py --selftest

The two candidate classes mirror issue #78:

- remote branches under origin/* whose tips are already reachable from the default
  branch, confirmed both by for-each-ref --merged and merge-base --is-ancestor;
- LESSONS.md entries explicitly flagged by a human with an adjacent marker:

      <!-- janitor:clear absorbed into path/to/file.md -->
      - 2026-07-04 - lesson text...

Ambiguous cases are reported, not acted on.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable


REMOTE = "origin"
LESSON_ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2}) ")
JANITOR_CLEAR = re.compile(r"^<!--\s*janitor:clear\s+(.+?)\s*-->$")


@dataclasses.dataclass(frozen=True)
class BranchInfo:
    remote_branch: str
    short_sha: str
    subject: str


@dataclasses.dataclass(frozen=True)
class BranchCandidate:
    remote_branch: str
    branch_name: str
    short_sha: str
    subject: str
    delete_command: str


@dataclasses.dataclass(frozen=True)
class LessonCandidate:
    marker_line: int
    lesson_line: int
    reason: str
    entry: str


@dataclasses.dataclass(frozen=True)
class Finding:
    scope: str
    message: str


@dataclasses.dataclass(frozen=True)
class Preview:
    repo: pathlib.Path
    generated_at: str
    base_ref: str | None
    fetched: bool
    branch_candidates: list[BranchCandidate]
    lesson_candidates: list[LessonCandidate]
    findings: list[Finding]


class GitError(RuntimeError):
    pass


def run(
    argv: list[str],
    *,
    cwd: pathlib.Path,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if check:
            raise GitError(f"{' '.join(argv)} failed: {exc}") from exc
        return subprocess.CompletedProcess(argv, 124, "", str(exc))
    if check and proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        detail = stderr or stdout or f"exit {proc.returncode}"
        raise GitError(f"{' '.join(argv)} failed: {detail}")
    return proc


def git_root(start: pathlib.Path) -> pathlib.Path:
    proc = run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    return pathlib.Path(proc.stdout.strip()).resolve()


def ref_exists(repo: pathlib.Path, ref: str) -> bool:
    return run(["git", "show-ref", "--verify", "--quiet", f"refs/{ref}"], cwd=repo, check=False).returncode == 0


_LS_REMOTE_SYMREF_RE = re.compile(r"^ref:\s+refs/heads/(\S+)\s+HEAD", re.MULTILINE)


def live_remote_default_branch(repo: pathlib.Path) -> tuple[str | None, Finding | None]:
    """The remote's *current* default branch name via a live, read-only
    `ls-remote` query against the remote itself, not the local cached
    refs/remotes/origin/HEAD symref. That local symref is written once (on
    clone, or by an explicit `git remote set-head`) and nothing about a plain
    fetch -- prune or no-prune -- ever refreshes it, so it can silently point
    at the wrong branch after a remote-side default rename (e.g. master ->
    main) while the old branch ref still exists locally and passes
    ref_exists(). Best-effort: any failure just means the caller can't verify
    and should say so, not raise."""
    proc = run(["git", "ls-remote", "--symref", REMOTE, "HEAD"], cwd=repo, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        return None, Finding("branches", f"Could not verify {REMOTE}'s live default branch via ls-remote: {detail}")
    match = _LS_REMOTE_SYMREF_RE.search(proc.stdout)
    if not match:
        return None, Finding(
            "branches", f"`git ls-remote --symref {REMOTE} HEAD` returned no symref; cannot verify the live default."
        )
    return match.group(1), None


def resolve_base_ref(repo: pathlib.Path, *, verify_live: bool) -> tuple[str | None, list[Finding]]:
    findings: list[Finding] = []

    if verify_live:
        live_branch, live_finding = live_remote_default_branch(repo)
        if live_finding is not None:
            # Couldn't verify (network/ls-remote failure) -- fall through to
            # the best-effort cached-ref logic below, same as verify_live=False.
            findings.append(live_finding)
        elif ref_exists(repo, f"remotes/{REMOTE}/{live_branch}"):
            return f"{REMOTE}/{live_branch}", findings
        else:
            # The live check succeeded and named the real default, but its
            # ref hasn't been fetched locally yet -- we now KNOW any cached
            # origin/HEAD is either this same unfetched branch or stale, so
            # falling through to trust the cache here (e.g. an old `master`
            # that still exists locally post-rename) would silently run
            # candidate generation against a base we've just confirmed is
            # wrong. Refuse instead of falling back.
            findings.append(
                Finding(
                    "branches",
                    f"{REMOTE}'s live default branch is {live_branch!r} but refs/remotes/{REMOTE}/{live_branch} "
                    "doesn't exist locally yet (not fetched); branch cleanup is report-only until it is.",
                )
            )
            return None, findings

    # No --short: like %(refname:short) in for-each-ref, `symbolic-ref
    # --short` disambiguates against a same-named colliding ref (e.g. a tag
    # literally called 'origin/main') by returning a longer form like
    # 'remotes/origin/main' -- which then made the ref_exists() check below
    # look up the wrong, doubled path and treat a perfectly valid origin/HEAD
    # as stale. The unabbreviated form is always the real target ref; strip
    # the known-fixed prefix ourselves instead.
    proc = run(
        ["git", "symbolic-ref", "--quiet", f"refs/remotes/{REMOTE}/HEAD"],
        cwd=repo,
        check=False,
    )
    head_prefix = "refs/remotes/"
    if proc.returncode == 0 and proc.stdout.strip():
        full_target = proc.stdout.strip()
        target = full_target[len(head_prefix):] if full_target.startswith(head_prefix) else full_target
        if ref_exists(repo, f"remotes/{target}"):
            # The cached symref's target still existing is not enough on its
            # own: after a remote-side rename (e.g. master -> main) that
            # happened between fetches, the cache can still say the OLD
            # branch while the new one also exists locally (a fetch updates
            # content but never refreshes this symref -- only `git remote
            # set-head` does). If the other main/master name also exists,
            # we cannot tell offline which one is actually current; refuse
            # rather than trust a cache that might be exactly this stale.
            other = f"remotes/{REMOTE}/{'master' if target.removeprefix(f'{REMOTE}/') == 'main' else 'main'}"
            if other != f"remotes/{target}" and ref_exists(repo, other):
                findings.append(
                    Finding(
                        "branches",
                        f"Cached {REMOTE}/HEAD says {target}, but {other.removeprefix('remotes/')} also "
                        f"exists locally and this wasn't live-verified (no --fetch); refusing to guess "
                        "which is authoritative. Branch cleanup is report-only until this is resolved.",
                    )
                )
                return None, findings
            if not verify_live:
                findings.append(
                    Finding(
                        "branches",
                        f"Using cached {REMOTE}/HEAD ({target}) without live verification (no --fetch); "
                        "it can go stale after a remote-side default-branch rename.",
                    )
                )
            return target, findings
        findings.append(
            Finding(
                "branches",
                f"{REMOTE}/HEAD points at stale ref {target}, which no longer exists; "
                "branch cleanup is report-only until this is resolved.",
            )
        )
        return None, findings

    # No main/master name-guessing fallback: without a resolvable origin/HEAD
    # (cached or live-verified), there is no authoritative signal for which
    # branch is actually the remote's default. A repo whose real default is
    # something else entirely (e.g. `develop`) that also happens to have an
    # `origin/main` branch for unrelated reasons would otherwise get main
    # silently guessed as the base, comparing merge-base checks against the
    # wrong branch and potentially proposing deletion of the real default.
    # Report-only is the only safe answer without --fetch's live check.
    findings.append(Finding("branches", "Could not resolve a default branch ref; branch cleanup is report-only."))
    return None, findings


def fetch_origin(repo: pathlib.Path) -> tuple[bool, Finding | None]:
    # --no-prune (not just omitting --prune): pruning deletes local
    # refs/remotes/origin/* refs, a repo-state mutation this dry-run tool must
    # never make. Without an explicit --no-prune, a repo/global git config
    # with fetch.prune or remote.origin.prune set would still prune here.
    # stale_remote_refs() below detects the same already-deleted-upstream
    # branches without touching anything.
    # --no-tags: a plain fetch auto-follows and creates new local tags for
    # any newly-reachable remote tag -- a real local-state write (a brand
    # new refs/tags/* entry) this dry-run tool must not make either.
    # --no-write-fetch-head: skips writing .git/FETCH_HEAD, the last
    # remaining local file this fetch would otherwise touch.
    # Explicit refspec, not "no refspec + rely on config": with no refspec on
    # the command line, git falls back to remote.origin.fetch, and a repo
    # with that customized (e.g. '+refs/heads/*:refs/heads/*') would have
    # this fetch write straight into local branches instead of remote-
    # tracking refs -- a far more severe mutation than anything else this
    # tool guards against.
    # --refmap= (empty) is required alongside the explicit refspec: a
    # command-line refspec does NOT replace remote.origin.fetch on its own --
    # both get applied together (confirmed live: with a malicious
    # '+refs/heads/*:refs/heads/*' config, supplying our own safe refspec on
    # the command line still let the configured one silently overwrite a
    # local branch). --refmap= is what actually suppresses the configured
    # refspec, confining every write to refs/remotes/origin/* regardless of
    # repo config.
    # --atomic: without it, a fetch that fails partway (e.g. a ref-namespace
    # conflict between a stale local ref and a newly-restructured remote
    # branch) can still have committed some ref updates before erroring,
    # leaving a genuinely mixed old/new state -- while this function reports
    # the failure as "using existing refs", implying nothing changed.
    # --atomic makes the whole set of ref updates one transaction: either
    # all of it applies or none of it does, so a failure here truly means
    # the pre-fetch refs are untouched.
    proc = run(
        [
            "git", "fetch", REMOTE, "+refs/heads/*:refs/remotes/origin/*", "--refmap=", "--atomic",
            "--quiet", "--no-prune", "--no-tags", "--no-write-fetch-head",
        ],
        cwd=repo,
        check=False,
    )
    if proc.returncode == 0:
        return True, None
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
    return False, Finding("branches", f"`git fetch {REMOTE}` failed; existing refs are unchanged (--atomic): {detail}")


_WOULD_PRUNE_RE = re.compile(r"\[deleted\]\s+\(none\)\s+->\s+(\S+)")


def stale_remote_refs(repo: pathlib.Path) -> set[str]:
    """Remote-tracking refs a real `git fetch --prune` would delete, i.e.
    branches already removed on the remote -- computed via `--dry-run` so
    nothing local is actually touched (true regardless of refspec; the
    explicit one here just keeps this in sync with fetch_origin's namespace).
    Best-effort: an empty set on failure just means no branch gets excluded
    as stale, not a hard error."""
    proc = run(
        ["git", "fetch", REMOTE, "+refs/heads/*:refs/remotes/origin/*", "--refmap=", "--dry-run", "--prune"],
        cwd=repo,
        check=False,
    )
    if proc.returncode != 0:
        return set()
    output = proc.stdout + proc.stderr
    return {match.group(1) for match in _WOULD_PRUNE_RE.finditer(output)}


def qualify_remote_ref(short: str) -> str:
    """Fully qualify a short 'origin/<branch>' name to 'refs/remotes/origin/<branch>'.

    Short names are ambiguous for git plumbing: if a tag or local branch happens
    to share the exact name (e.g. a tag literally called 'origin/main'), git's
    ref-resolution precedence can resolve the short form to the wrong object,
    silently comparing --merged/merge-base against the wrong commit. Every
    plumbing call (--merged=, merge-base --is-ancestor) must use this; short
    names are fine for display and for-each-ref's own path-prefix argument."""
    return f"refs/remotes/{short}"


def list_remote_branches(repo: pathlib.Path) -> list[BranchInfo]:
    # %(refname), not %(refname:short): when a tag or other ref happens to be
    # named exactly like a remote branch (e.g. a tag literally called
    # 'origin/main'), git's refname:short disambiguates the remote-tracking
    # ref to a longer form like 'remotes/origin/main' instead of 'origin/main'
    # to avoid ambiguity -- which then makes this a legitimately merged
    # branch silently look like an "unexpected remote branch name" downstream
    # and get dropped from the report. Strip the known-fixed prefix ourselves
    # instead, which is unambiguous regardless of any colliding ref elsewhere.
    proc = run(
        [
            "git",
            "for-each-ref",
            f"refs/remotes/{REMOTE}",
            "--format=%(refname)%09%(objectname:short)%09%(subject)",
        ],
        cwd=repo,
    )
    prefix = f"refs/remotes/{REMOTE}/"
    branches: list[BranchInfo] = []
    for line in proc.stdout.splitlines():
        full_refname, short_sha, subject = (line.split("\t", 2) + ["", ""])[:3]
        remote_branch = f"{REMOTE}/{full_refname[len(prefix):]}" if full_refname.startswith(prefix) else full_refname
        branches.append(BranchInfo(remote_branch=remote_branch, short_sha=short_sha, subject=subject))
    return branches


def merged_remote_branches(repo: pathlib.Path, base_ref: str) -> set[str]:
    # %(refname), not %(refname:short) -- same reason as list_remote_branches:
    # a same-named tag elsewhere in the repo makes refname:short produce a
    # disambiguated long form (e.g. 'remotes/origin/main') instead of
    # 'origin/main', which would silently desync this set's spelling from
    # list_remote_branches's (normalized) output and make classify_branch_
    # candidates() miss an already-merged branch as "not in merged".
    proc = run(
        [
            "git",
            "for-each-ref",
            f"--merged={qualify_remote_ref(base_ref)}",
            f"refs/remotes/{REMOTE}",
            "--format=%(refname)",
        ],
        cwd=repo,
    )
    prefix = f"refs/remotes/{REMOTE}/"
    merged: set[str] = set()
    for line in proc.stdout.splitlines():
        full_refname = line.strip()
        if not full_refname:
            continue
        merged.add(f"{REMOTE}/{full_refname[len(prefix):]}" if full_refname.startswith(prefix) else full_refname)
    return merged


def branch_tip_is_ancestor(repo: pathlib.Path, remote_branch: str, base_ref: str) -> bool:
    proc = run(
        ["git", "merge-base", "--is-ancestor", qualify_remote_ref(remote_branch), qualify_remote_ref(base_ref)],
        cwd=repo,
        check=False,
    )
    return proc.returncode == 0


def classify_branch_candidates(
    branches: Iterable[BranchInfo],
    *,
    base_ref: str | None,
    merged: set[str],
    is_ancestor: Callable[[str, str], bool],
) -> tuple[list[BranchCandidate], list[Finding]]:
    findings: list[Finding] = []
    candidates: list[BranchCandidate] = []
    if base_ref is None:
        return candidates, findings

    prefix = f"{REMOTE}/"
    for branch in branches:
        remote_branch = branch.remote_branch
        # Depending on git version/formatting, the symbolic origin/HEAD ref can render
        # as either `origin/HEAD` or just `origin`.
        if remote_branch in {REMOTE, f"{REMOTE}/HEAD"} or remote_branch == base_ref:
            continue
        if not remote_branch.startswith(prefix):
            findings.append(Finding("branches", f"Skipping unexpected remote branch name: {remote_branch}"))
            continue
        branch_name = remote_branch[len(prefix) :]
        if remote_branch not in merged:
            continue
        if not is_ancestor(remote_branch, base_ref):
            findings.append(
                Finding(
                    "branches",
                    f"{remote_branch} appeared in --merged output but failed merge-base confirmation.",
                )
            )
            continue
        candidates.append(
            BranchCandidate(
                remote_branch=remote_branch,
                branch_name=branch_name,
                short_sha=branch.short_sha,
                subject=branch.subject,
                # Use the fully-qualified ref, not the short name -- a branch
                # name that starts with `-` (e.g. `-old`) would otherwise be
                # parsed as an option instead of the ref to delete.
                delete_command=f"git push {REMOTE} --delete {shlex.quote('refs/heads/' + branch_name)}",
            )
        )
    return candidates, findings


def parse_lessons(text: str) -> tuple[list[LessonCandidate], list[Finding]]:
    candidates: list[LessonCandidate] = []
    findings: list[Finding] = []
    pending: tuple[int, str] | None = None

    for idx, line in enumerate(text.splitlines(), start=1):
        marker = JANITOR_CLEAR.match(line.strip())
        if marker:
            if pending is not None:
                findings.append(
                    Finding(
                        "lessons",
                        f"janitor:clear marker at line {pending[0]} was not followed by a lesson entry.",
                    )
                )
            pending = (idx, marker.group(1).strip())
            continue

        if pending is None:
            continue

        marker_line, reason = pending
        if LESSON_ENTRY.match(line):
            candidates.append(
                LessonCandidate(
                    marker_line=marker_line,
                    lesson_line=idx,
                    reason=reason,
                    entry=line,
                )
            )
        else:
            findings.append(
                Finding(
                    "lessons",
                    f"janitor:clear marker at line {marker_line} must be immediately followed by a dated lesson entry.",
                )
            )
        pending = None

    if pending is not None:
        findings.append(
            Finding("lessons", f"janitor:clear marker at line {pending[0]} was not followed by a lesson entry.")
        )
    return candidates, findings


def build_preview(repo: pathlib.Path, *, fetch: bool) -> Preview:
    findings: list[Finding] = []
    fetched = False
    if fetch:
        fetched, fetch_finding = fetch_origin(repo)
        if fetch_finding is not None:
            findings.append(fetch_finding)

    base_ref, base_findings = resolve_base_ref(repo, verify_live=fetch)
    findings.extend(base_findings)

    branch_candidates: list[BranchCandidate] = []
    if base_ref is not None:
        branches = list_remote_branches(repo)
        if fetch:
            stale = stale_remote_refs(repo)
            if stale:
                branches = [b for b in branches if b.remote_branch not in stale]
                for ref in sorted(stale):
                    findings.append(
                        Finding(
                            "branches",
                            f"{ref} is already deleted on {REMOTE}; excluded from candidates "
                            "(local tracking ref left as-is -- dry run never prunes).",
                        )
                    )
        merged = merged_remote_branches(repo, base_ref)
        branch_candidates, branch_findings = classify_branch_candidates(
            branches,
            base_ref=base_ref,
            merged=merged,
            is_ancestor=lambda branch, base: branch_tip_is_ancestor(repo, branch, base),
        )
        findings.extend(branch_findings)

    lessons_path = repo / "LESSONS.md"
    if lessons_path.exists():
        lesson_candidates, lesson_findings = parse_lessons(lessons_path.read_text(encoding="utf-8"))
        findings.extend(lesson_findings)
    else:
        lesson_candidates = []
        findings.append(Finding("lessons", "LESSONS.md is missing; no lesson cleanup candidates scanned."))

    return Preview(
        repo=repo,
        generated_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        base_ref=base_ref,
        fetched=fetched,
        branch_candidates=branch_candidates,
        lesson_candidates=lesson_candidates,
        findings=findings,
    )


def to_json(preview: Preview) -> str:
    payload = {
        "repo": str(preview.repo),
        "generated_at": preview.generated_at,
        "dry_run": True,
        "base_ref": preview.base_ref,
        "fetched": preview.fetched,
        "branch_candidates": [dataclasses.asdict(candidate) for candidate in preview.branch_candidates],
        "lesson_candidates": [dataclasses.asdict(candidate) for candidate in preview.lesson_candidates],
        "findings": [dataclasses.asdict(finding) for finding in preview.findings],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def md_code_span(text: str) -> str:
    """Wrap text in a Markdown inline code span that a backtick inside the
    text (a valid, if unusual, git ref-name character) cannot break out of.
    A CommonMark code span is delimited by a run of N backticks and closed
    by the same length run; using a run one longer than the longest
    backtick run already in the text guarantees it can't close early. Per
    spec, pad with a space when the text itself starts/ends with a
    backtick so the delimiter doesn't visually merge with the content."""
    runs = re.findall(r"`+", text)
    fence = "`" * (max((len(r) for r in runs), default=0) + 1)
    if text.startswith("`") or text.endswith("`"):
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def render_markdown(preview: Preview) -> str:
    lines = [
        "# Janitor Preview",
        "",
        f"- Repo: `{preview.repo}`",
        f"- Generated: `{preview.generated_at}`",
        f"- Base ref: {md_code_span(preview.base_ref or 'unresolved')}",
        f"- Fetch succeeded: `{'yes' if preview.fetched else 'no'}`",
        (
            "- Mode: dry run only; no branches, files, PRs, or issues were deleted, "
            "created, or edited. (With --fetch, refs/remotes/origin/* are refreshed "
            "to match the remote, same as any normal fetch -- no tags or FETCH_HEAD "
            "are written, and nothing is pruned.)"
            if preview.fetched
            else "- Mode: dry run only; no branches, files, PRs, or issues were deleted, created, or edited."
        ),
        "",
        "## Branch Deletion Candidates",
        "",
    ]

    if preview.branch_candidates:
        for candidate in preview.branch_candidates:
            subject = f" - {candidate.subject}" if candidate.subject else ""
            lines.append(
                f"- {md_code_span(candidate.remote_branch)} at `{candidate.short_sha}`{subject}\n"
                f"  Proposed command: {md_code_span(candidate.delete_command)}"
            )
    else:
        lines.append("None.")

    lines.extend(["", "## LESSONS Removal Candidates", ""])
    if preview.lesson_candidates:
        for candidate in preview.lesson_candidates:
            lines.append(
                f"- Lines {candidate.marker_line}-{candidate.lesson_line}: {candidate.entry}\n"
                f"  Human flag reason: {candidate.reason}"
            )
    else:
        lines.append("None.")

    lines.extend(["", "## Report-Only Findings", ""])
    if preview.findings:
        for finding in preview.findings:
            lines.append(f"- `{finding.scope}`: {finding.message}")
    else:
        lines.append("None.")

    return "\n".join(lines) + "\n"


def selftest() -> int:
    failures: list[str] = []

    prune_dry_run_output = (
        "From github.com:example/repo\n"
        " - [deleted]         (none)     -> origin/already-gone\n"
        "   1111111..2222222  main       -> origin/main\n"
        " - [deleted]         (none)     -> origin/-dash-gone\n"
    )
    parsed_stale = {m.group(1) for m in _WOULD_PRUNE_RE.finditer(prune_dry_run_output)}
    if parsed_stale != {"origin/already-gone", "origin/-dash-gone"}:
        failures.append(f"stale-ref regex parsed wrong refs from --dry-run --prune output: {parsed_stale!r}")

    # git allows a backtick in a ref name (confirmed: `git check-ref-format
    # --branch 'feature/`evil`'` exits 0), so a naive single-backtick
    # Markdown code span can be broken out of by branch text.
    if md_code_span("plain") != "`plain`":
        failures.append(f"md_code_span changed plain text unnecessarily: {md_code_span('plain')!r}")
    one_tick = md_code_span("a`b")
    if not (one_tick.startswith("``") and one_tick.endswith("``") and "a`b" in one_tick):
        failures.append(f"md_code_span did not escape a single backtick correctly: {one_tick!r}")
    leading_tick = md_code_span("`x`")
    if leading_tick != "`` `x` ``":
        failures.append(f"md_code_span did not pad a backtick-bounded string correctly: {leading_tick!r}")
    evil_branch = "feature/`; rm -rf /`"
    evil_base_ref = "origin/feature/`x"
    rendered_evil = render_markdown(
        Preview(
            repo=pathlib.Path("/repo"),
            generated_at="2026-07-07T00:00:00+00:00",
            base_ref=evil_base_ref,
            fetched=False,
            branch_candidates=[
                BranchCandidate(
                    remote_branch=evil_branch,
                    branch_name=evil_branch.removeprefix("origin/"),
                    short_sha="1234567",
                    subject="evil subject",
                    delete_command=f"git push origin --delete refs/heads/{evil_branch}",
                )
            ],
            lesson_candidates=[],
            findings=[],
        )
    )
    if md_code_span(evil_branch) not in rendered_evil:
        failures.append("render_markdown did not safely escape a branch name containing a backtick")
    if md_code_span(evil_base_ref) not in rendered_evil:
        failures.append("render_markdown did not safely escape the base ref containing a backtick")

    branches = [
        BranchInfo("origin", "0000000", "default pointer rendered short"),
        BranchInfo("origin/HEAD", "1111111", "default pointer"),
        BranchInfo("origin/main", "2222222", "default"),
        BranchInfo("origin/merged", "3333333", "merged work"),
        BranchInfo("origin/unmerged", "4444444", "active work"),
        BranchInfo("origin/false-positive", "5555555", "in merged list only"),
        BranchInfo("origin/-dash-prefixed", "6666666", "branch name starting with a dash"),
    ]
    branch_candidates, branch_findings = classify_branch_candidates(
        branches,
        base_ref="origin/main",
        merged={
            "origin/HEAD", "origin/main", "origin/merged", "origin/false-positive",
            "origin/-dash-prefixed",
        },
        is_ancestor=lambda branch, _base: branch in {"origin/merged", "origin/-dash-prefixed"},
    )
    if [candidate.remote_branch for candidate in branch_candidates] != ["origin/merged", "origin/-dash-prefixed"]:
        failures.append(f"branch classifier produced wrong candidates: {branch_candidates!r}")
    if not any("failed merge-base confirmation" in finding.message for finding in branch_findings):
        failures.append("branch classifier did not report the --merged/merge-base disagreement")
    dash_candidate = next((c for c in branch_candidates if c.branch_name == "-dash-prefixed"), None)
    if dash_candidate is None or dash_candidate.delete_command != "git push origin --delete refs/heads/-dash-prefixed":
        failures.append(
            f"dash-prefixed branch name did not produce an option-safe delete command: {dash_candidate!r}"
        )

    lesson_text = """\
# LESSONS

<!-- janitor:clear absorbed into commit/SKILL.md -->
- 2026-07-04 - Branch before commit.

- 2026-07-03 - Keep this one.
<!-- janitor:clear absorbed elsewhere -->
not a lesson
<!-- janitor:clear absorbed nowhere -->
"""
    lesson_candidates, lesson_findings = parse_lessons(lesson_text)
    if len(lesson_candidates) != 1:
        failures.append(f"lesson parser produced wrong candidate count: {lesson_candidates!r}")
    elif lesson_candidates[0].reason != "absorbed into commit/SKILL.md":
        failures.append(f"lesson parser kept wrong marker reason: {lesson_candidates[0]!r}")
    if len(lesson_findings) != 2:
        failures.append(f"lesson parser should report two malformed markers: {lesson_findings!r}")

    preview = Preview(
        repo=pathlib.Path("/repo"),
        generated_at="2026-07-07T00:00:00+00:00",
        base_ref="origin/main",
        fetched=False,
        branch_candidates=branch_candidates,
        lesson_candidates=lesson_candidates,
        findings=branch_findings + lesson_findings,
    )
    rendered = render_markdown(preview)
    if "Mode: dry run only" not in rendered or "git push origin --delete refs/heads/merged" not in rendered:
        failures.append("markdown renderer omitted dry-run mode or proposed branch command")

    parsed = json.loads(to_json(preview))
    if parsed["dry_run"] is not True or parsed["branch_candidates"][0]["remote_branch"] != "origin/merged":
        failures.append("json renderer omitted dry_run flag or branch candidate")

    # resolve_base_ref needs real git plumbing (symbolic-ref/show-ref), so
    # exercise it against a throwaway repo rather than mocking. No real
    # remote is needed: refs/remotes/origin/* refs can be created directly.
    tmp_root = pathlib.Path(tempfile.mkdtemp(prefix="janitor-preview-selftest-"))
    try:
        # No origin/HEAD at all, only one plausibly-named remote candidate
        # (origin/main): still refused. There is no main/master name-
        # guessing fallback -- without a resolvable origin/HEAD (cached or
        # live-verified), a single conventionally-named branch is not proof
        # it's the actual default (the real default could be something else
        # entirely, e.g. `develop`, that just doesn't happen to exist in
        # this fixture).
        single_repo = tmp_root / "single"
        single_repo.mkdir()
        run(["git", "init", "-q"], cwd=single_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=single_repo)
        run(["git", "config", "user.name", "Test"], cwd=single_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=single_repo)
        sha = run(["git", "rev-parse", "HEAD"], cwd=single_repo).stdout.strip()
        run(["git", "update-ref", "refs/remotes/origin/main", sha], cwd=single_repo)
        base, base_findings = resolve_base_ref(single_repo, verify_live=False)
        if base is not None:
            failures.append(
                f"resolve_base_ref guessed {base!r} from a single origin/main candidate with no "
                "origin/HEAD instead of refusing (report-only)"
            )
        if not any("report-only" in f.message for f in base_findings):
            failures.append("resolve_base_ref did not report the unresolvable-default-branch state")

        ambiguous_repo = tmp_root / "ambiguous"
        ambiguous_repo.mkdir()
        run(["git", "init", "-q"], cwd=ambiguous_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=ambiguous_repo)
        run(["git", "config", "user.name", "Test"], cwd=ambiguous_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=ambiguous_repo)
        sha = run(["git", "rev-parse", "HEAD"], cwd=ambiguous_repo).stdout.strip()
        run(["git", "update-ref", "refs/remotes/origin/main", sha], cwd=ambiguous_repo)
        run(["git", "update-ref", "refs/remotes/origin/master", sha], cwd=ambiguous_repo)
        base, ambiguous_findings = resolve_base_ref(ambiguous_repo, verify_live=False)
        if base is not None:
            failures.append(
                f"resolve_base_ref guessed {base!r} with two candidates and no origin/HEAD instead of "
                "refusing (report-only)"
            )
        if not any("report-only" in f.message for f in ambiguous_findings):
            failures.append("resolve_base_ref did not report the ambiguous-default-branch state")

        # A cached origin/HEAD symref whose target still exists locally is
        # not proof it's current: after a remote-side rename (master ->
        # main) between fetches, the symref can still say the OLD branch
        # while the new one also exists. Without live verification, seeing
        # BOTH main and master locally must refuse rather than trust
        # whichever the (possibly stale) cache happens to name.
        stale_head_repo = tmp_root / "stale-head"
        stale_head_repo.mkdir()
        run(["git", "init", "-q"], cwd=stale_head_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=stale_head_repo)
        run(["git", "config", "user.name", "Test"], cwd=stale_head_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=stale_head_repo)
        sha = run(["git", "rev-parse", "HEAD"], cwd=stale_head_repo).stdout.strip()
        run(["git", "update-ref", "refs/remotes/origin/master", sha], cwd=stale_head_repo)
        run(["git", "update-ref", "refs/remotes/origin/main", sha], cwd=stale_head_repo)
        run(["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master"], cwd=stale_head_repo)
        base, stale_head_findings = resolve_base_ref(stale_head_repo, verify_live=False)
        if base is not None:
            failures.append(
                f"resolve_base_ref trusted a cached origin/HEAD ({base!r}) even though the other "
                "main/master candidate also exists locally, instead of refusing (report-only)"
            )
        if not any("also exists locally" in f.message for f in stale_head_findings):
            failures.append("resolve_base_ref did not report the stale-cached-HEAD-with-coexisting-candidate state")

        # A remote with an unresolvable default (no origin/HEAD, no
        # origin/main, no origin/master -- e.g. the real default is named
        # `trunk`) must never fall back to a same-named local branch as the
        # comparison base, even when one happens to exist locally.
        unresolvable_repo = tmp_root / "unresolvable"
        unresolvable_repo.mkdir()
        run(["git", "init", "-q"], cwd=unresolvable_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=unresolvable_repo)
        run(["git", "config", "user.name", "Test"], cwd=unresolvable_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=unresolvable_repo)
        sha = run(["git", "rev-parse", "HEAD"], cwd=unresolvable_repo).stdout.strip()
        run(["git", "branch", "-M", "main"], cwd=unresolvable_repo)
        run(["git", "update-ref", "refs/remotes/origin/trunk", sha], cwd=unresolvable_repo)
        base, unresolvable_findings = resolve_base_ref(unresolvable_repo, verify_live=False)
        if base is not None:
            failures.append(
                f"resolve_base_ref fell back to a local branch ({base!r}) as the remote comparison "
                "base instead of refusing (report-only)"
            )
        if not any("report-only" in f.message for f in unresolvable_findings):
            failures.append("resolve_base_ref did not report the unresolvable-remote-default state")

        # Live rename detection: a remote's default branch renamed
        # master -> main after the local clone was made. The clone's cached
        # refs/remotes/origin/HEAD symref (written once at clone time) never
        # gets refreshed by a plain fetch, and refs/remotes/origin/master
        # still exists locally, so offline resolution keeps trusting it.
        # verify_live=True must detect the live rename via ls-remote and
        # either use the new branch (once fetched) or refuse rather than
        # silently trusting the now-known-stale cached master.
        upstream_repo = tmp_root / "upstream"
        upstream_repo.mkdir()
        run(["git", "init", "-q", "-b", "master"], cwd=upstream_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=upstream_repo)
        run(["git", "config", "user.name", "Test"], cwd=upstream_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=upstream_repo)

        rename_clone = tmp_root / "rename-clone"
        clone_proc = run(["git", "clone", "-q", str(upstream_repo), str(rename_clone)], cwd=tmp_root, check=False)
        if clone_proc.returncode != 0:
            failures.append(f"live-rename fixture: git clone failed: {clone_proc.stderr.strip()}")
        else:
            run(["git", "config", "user.email", "t@example.com"], cwd=rename_clone)
            run(["git", "config", "user.name", "Test"], cwd=rename_clone)
            # Simulate the remote-side rename without touching the clone.
            run(["git", "branch", "-m", "master", "main"], cwd=upstream_repo)

            offline_base, _ = resolve_base_ref(rename_clone, verify_live=False)
            if offline_base != "origin/master":
                failures.append(
                    f"live-rename fixture: offline resolution should still trust the stale cached "
                    f"origin/HEAD ('origin/master'), got {offline_base!r}"
                )

            unfetched_base, unfetched_findings = resolve_base_ref(rename_clone, verify_live=True)
            if unfetched_base is not None:
                failures.append(
                    f"live-rename fixture: verify_live=True used {unfetched_base!r} (likely the stale "
                    "cached origin/master) instead of refusing when the renamed branch isn't fetched yet"
                )
            if not any("not fetched" in f.message for f in unfetched_findings):
                failures.append("live-rename fixture: resolve_base_ref did not report the detected-but-unfetched rename")

            run(["git", "fetch", "-q", REMOTE], cwd=rename_clone, check=False)
            fetched_base, _ = resolve_base_ref(rename_clone, verify_live=True)
            if fetched_base != "origin/main":
                failures.append(
                    f"live-rename fixture: after fetching, verify_live=True should resolve to the "
                    f"renamed 'origin/main', got {fetched_base!r}"
                )

        # Adversarial: a tag literally named 'origin/main' shadows
        # refs/remotes/origin/main for git's short-name resolution (tags/ is
        # checked before remotes/ in git's disambiguation order). If the
        # --merged/merge-base plumbing used the short name, the tag -- pointed
        # at the SAME commit as an unmerged branch -- would make that branch
        # look trivially merged into itself. Fully-qualified refs must not be
        # fooled by this.
        shadow_repo = tmp_root / "shadow"
        shadow_repo.mkdir()
        run(["git", "init", "-q"], cwd=shadow_repo)
        run(["git", "config", "user.email", "t@example.com"], cwd=shadow_repo)
        run(["git", "config", "user.name", "Test"], cwd=shadow_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=shadow_repo)
        base_sha = run(["git", "rev-parse", "HEAD"], cwd=shadow_repo).stdout.strip()
        run(["git", "commit", "-q", "--allow-empty", "-m", "real main tip"], cwd=shadow_repo)
        real_main_sha = run(["git", "rev-parse", "HEAD"], cwd=shadow_repo).stdout.strip()
        run(["git", "checkout", "-q", "--detach", base_sha], cwd=shadow_repo)
        run(["git", "commit", "-q", "--allow-empty", "-m", "unmerged feature work"], cwd=shadow_repo)
        feature_sha = run(["git", "rev-parse", "HEAD"], cwd=shadow_repo).stdout.strip()
        run(["git", "update-ref", "refs/remotes/origin/main", real_main_sha], cwd=shadow_repo)
        run(["git", "update-ref", "refs/remotes/origin/feature", feature_sha], cwd=shadow_repo)
        # The adversarial tag: named exactly like the short base ref, pointed
        # at the unmerged branch's own tip so a shadowed lookup would make it
        # trivially "merged into itself".
        run(["git", "tag", "origin/main", feature_sha], cwd=shadow_repo)

        merged = merged_remote_branches(shadow_repo, "origin/main")
        if "origin/feature" in merged:
            failures.append(
                "merged_remote_branches was fooled by a shadowing tag named 'origin/main' into "
                "treating an unmerged branch as merged"
            )
        # Both list_remote_branches and merged_remote_branches now normalize
        # via %(refname) + manual prefix-stripping, so the shadowing tag no
        # longer desyncs their spelling -- exact match, not a suffix check.
        if "origin/main" not in merged:
            failures.append("merged_remote_branches did not report the real origin/main as merged into itself")
        listed_names = {b.remote_branch for b in list_remote_branches(shadow_repo)}
        if listed_names != {"origin/main", "origin/feature"}:
            failures.append(f"list_remote_branches produced unexpected names under a shadowing tag: {listed_names!r}")
        if branch_tip_is_ancestor(shadow_repo, "origin/feature", "origin/main"):
            failures.append(
                "branch_tip_is_ancestor was fooled by a shadowing tag named 'origin/main' into "
                "treating an unmerged branch as an ancestor"
            )
        # `symbolic-ref --short` has the same shadowing quirk as
        # %(refname:short): with the 'origin/main' tag present, it would
        # return 'remotes/origin/main' instead of 'origin/main', doubling the
        # 'remotes/' prefix in the later ref_exists() check and making a
        # perfectly valid, correctly-pointing origin/HEAD look stale.
        run(["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], cwd=shadow_repo)
        shadowed_base, shadowed_findings = resolve_base_ref(shadow_repo, verify_live=False)
        if shadowed_base != "origin/main":
            failures.append(
                f"resolve_base_ref treated a valid origin/HEAD as stale under a shadowing tag named "
                f"'origin/main' (returned {shadowed_base!r}, expected 'origin/main')"
            )
        if any("stale ref" in f.message for f in shadowed_findings):
            failures.append("resolve_base_ref reported a valid origin/HEAD as stale under a shadowing tag")

        # A repo with a customized remote.origin.fetch (e.g.
        # '+refs/heads/*:refs/heads/*') would have a plain, refspec-less
        # `git fetch origin` write straight into local branches instead of
        # remote-tracking refs. fetch_origin must supply its own explicit
        # refspec so this can never happen regardless of repo config.
        refspec_upstream = tmp_root / "refspec-upstream"
        refspec_upstream.mkdir()
        run(["git", "init", "-q", "-b", "main"], cwd=refspec_upstream)
        run(["git", "config", "user.email", "t@example.com"], cwd=refspec_upstream)
        run(["git", "config", "user.name", "Test"], cwd=refspec_upstream)
        run(["git", "commit", "-q", "--allow-empty", "-m", "c1"], cwd=refspec_upstream)

        refspec_victim = tmp_root / "refspec-victim"
        clone_proc = run(
            ["git", "clone", "-q", str(refspec_upstream), str(refspec_victim)], cwd=tmp_root, check=False
        )
        if clone_proc.returncode != 0:
            failures.append(f"refspec-override fixture: git clone failed: {clone_proc.stderr.strip()}")
        else:
            run(["git", "config", "user.email", "t@example.com"], cwd=refspec_victim)
            run(["git", "config", "user.name", "Test"], cwd=refspec_victim)
            # Check out a different branch first: git's own "refusing to
            # fetch into branch checked out" guard would otherwise mask the
            # real vulnerability by rejecting the whole fetch outright
            # (confirmed live) -- the actual risk is a NON-checked-out local
            # branch (main here) silently getting overwritten, which that
            # guard does not protect against.
            run(["git", "checkout", "-q", "--orphan", "other"], cwd=refspec_victim)
            run(["git", "commit", "-q", "--allow-empty", "-m", "unrelated"], cwd=refspec_victim)
            # The malicious/customized config from the reported finding.
            run(["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"], cwd=refspec_victim)
            local_main_before = run(["git", "rev-parse", "refs/heads/main"], cwd=refspec_victim).stdout.strip()

            run(["git", "commit", "-q", "--allow-empty", "-m", "c2"], cwd=refspec_upstream)
            c2_sha = run(["git", "rev-parse", "HEAD"], cwd=refspec_upstream).stdout.strip()

            fetched, fetch_finding = fetch_origin(refspec_victim)
            if not fetched:
                failures.append(f"refspec-override fixture: fetch_origin failed: {fetch_finding}")
            local_main_after = run(["git", "rev-parse", "refs/heads/main"], cwd=refspec_victim).stdout.strip()
            remote_main_after = run(
                ["git", "rev-parse", "refs/remotes/origin/main"], cwd=refspec_victim
            ).stdout.strip()

            if local_main_after != local_main_before:
                failures.append(
                    "fetch_origin let a customized remote.origin.fetch overwrite the local main branch "
                    f"(was {local_main_before!r}, now {local_main_after!r}) -- explicit refspec override failed"
                )
            if remote_main_after != c2_sha:
                failures.append(
                    "fetch_origin did not update refs/remotes/origin/main to the new upstream commit "
                    f"(expected {c2_sha!r}, got {remote_main_after!r})"
                )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if failures:
        print("janitor preview selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("janitor preview selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Path inside the repo to scan (default: current directory).")
    parser.add_argument("--fetch", action="store_true", help="Refresh origin refs before scanning.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Markdown.")
    parser.add_argument("--selftest", action="store_true", help="Run embedded parser/classifier tests.")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    try:
        repo = git_root(pathlib.Path(args.repo).resolve())
        preview = build_preview(repo, fetch=args.fetch)
    except GitError as exc:
        print(f"janitor preview: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(to_json(preview))
    else:
        print(render_markdown(preview), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
