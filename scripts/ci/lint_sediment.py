#!/usr/bin/env python3
"""Keep provider-neutral content free of personal and repo-specific sediment.

The shared skills (`skills/`) and canonical agent prompts (`agents/`) install into
other repositories and other machines, so they must not carry facts that are true
only here: private account handles, personal machine paths, this repo's own gate
command, or internal milestone names. This lint fails the build when such sediment
lands in shared content, so neutrality is enforced rather than re-argued in review.

Two checks:

1. Denylist scan over tracked `skills/` and `agents/` files — including each
   skill's `tests.md`, because generation and installation copy entire skill
   directories, so run evidence travels to other machines exactly like skill
   bodies do (only the explicitly machine-specific skills in EXEMPT_SKILLS are
   skipped). The tracked patterns are deliberately generic so no private token is
   itself republished by this file; exact private strings belong in the
   `AGENTIC_SEDIMENT_EXTRA` env var (comma-separated literals, set as a CI secret
   where needed) and are never echoed on a match.
2. Identity check: every `skills/*/references/shared-pipeline.md` copy must be
   byte-identical — that file is single-sourced by convention and duplicated only
   because installed skills must stay self-contained.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO

# Skills deliberately kept machine-specific (macOS cmux, POSIX dashboard). They
# are exempt from the PORTABILITY patterns only — leak patterns (private
# namespaces, internal milestones, this-repo commands) still apply, because
# installation copies their files to users like any other skill.
EXEMPT_SKILLS = {"cmux", "dashboard"}
PORTABILITY_LABELS = {
    "hardcoded macOS home path",
    "hardcoded Linux home path",
    "hardcoded root home path",
    "hardcoded Windows home path",
}

SHARED_BASENAME = "shared-pipeline.md"

DENYLIST: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private namespace reference", re.compile(r"mjenkins", re.IGNORECASE)),
    ("personal-machine claim", re.compile(r"installed globally on this machine", re.IGNORECASE)),
    # First character of a real username — [A-Za-z0-9_] — but not `<`, so doc
    # placeholders like /Users/<you> or C:\Users\<you> stay legal while concrete
    # usernames are caught, on every platform's home-path form.
    ("hardcoded macOS home path", re.compile(r"/Users/[A-Za-z0-9_]")),
    ("hardcoded Linux home path", re.compile(r"/home/[A-Za-z0-9_]")),
    ("hardcoded root home path", re.compile(r"/root/[A-Za-z0-9_.]")),
    ("hardcoded Windows home path", re.compile(r"[A-Za-z]:[/\\]Users[/\\][A-Za-z0-9_]")),
    ("this-repo gate command", re.compile(r"scripts/ci/check_all\.py")),
    ("internal milestone reference", re.compile(r"\bM2-\d\d\b")),
)


def extra_literals() -> tuple[str, ...]:
    raw = os.environ.get("AGENTIC_SEDIMENT_EXTRA", "")
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def scan_text(
    rel: str, text: str, extra: tuple[str, ...], skip_labels: frozenset[str] = frozenset()
) -> list[str]:
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in DENYLIST:
            if label in skip_labels:
                continue
            if pattern.search(line):
                errors.append(f"{rel}:{lineno}: {label} (pattern: {pattern.pattern})")
        for token in extra:
            if token in line:
                # Never echo the token: the env extension exists precisely so
                # private strings stay out of tracked text and CI logs.
                errors.append(f"{rel}:{lineno}: AGENTIC_SEDIMENT_EXTRA token matched")
    return errors


def scan_path(
    rel: str, extra: tuple[str, ...], skip_labels: frozenset[str] = frozenset()
) -> list[str]:
    """Apply the denylist to the repository-relative path itself.

    Generation and installation publish filenames just like contents, so a
    private token in a path is sediment even when the file body is clean.
    """
    errors: list[str] = []
    for label, pattern in DENYLIST:
        if label in skip_labels:
            continue
        if pattern.search(rel):
            errors.append(f"{rel}: path itself matches {label} (pattern: {pattern.pattern})")
    for token in extra:
        if token in rel:
            errors.append(f"{rel}: path itself matches an AGENTIC_SEDIMENT_EXTRA token")
    return errors


def shared_pipeline_errors(contents: dict[str, str]) -> list[str]:
    if len(set(contents.values())) > 1:
        names = ", ".join(sorted(contents))
        return [f"{SHARED_BASENAME} copies differ ({names}); they must be byte-identical"]
    return []


def scan_files() -> list[tuple[pathlib.Path, frozenset[str]]]:
    out: list[tuple[pathlib.Path, frozenset[str]]] = []
    for root in ("skills/", "agents/"):
        for path in gittracked.tracked_files(root):
            parts = path.relative_to(REPO).parts
            exempt = parts[0] == "skills" and len(parts) > 1 and parts[1] in EXEMPT_SKILLS
            out.append((path, frozenset(PORTABILITY_LABELS) if exempt else frozenset()))
    return out


def selftest() -> int:
    failures: list[str] = []
    dirty_lines = (
        "pushed to github.com/mjenkinsx0/private-repo",
        "opensrc is installed globally on this machine",
        "read /Users/someone/code/app",
        "read /Users/Alice/code/app",
        "read /home/alice/code/app",
        "read /root/private-app/config",
        "read C:\\Users\\someone\\code\\app",
        "read D:/Users/Alice/repo",
        "the gate is python3 scripts/ci/check_all.py",
        "revisit the M2-07 checklist",
    )
    for line in dirty_lines:
        if not scan_text("fixture.md", line, ()):
            failures.append(f"denylist missed: {line!r}")
    clean_lines = (
        "Discover the repo's gate from CI config; run it from the project root.",
        "an example path like /Users/<you>/code/app",
        "an example path like /home/<you>/code/app",
        "an example path like C:\\Users\\<you>\\repo or C:/Users/<you>/repo",
    )
    for line in clean_lines:
        if scan_text("fixture.md", line, ()):
            failures.append(f"clean fixture was flagged: {line!r}")
    hits = scan_text("fixture.md", "token hunter2 present", ("hunter2",))
    if not hits:
        failures.append("extra-literal token was not flagged")
    elif any("hunter2" in hit for hit in hits):
        failures.append("extra-literal match echoed the token")
    portability_skips = frozenset(PORTABILITY_LABELS)
    if scan_text("fixture.md", "read /Users/someone/code/app", (), portability_skips):
        failures.append("portability exemption did not suppress a home-path hit")
    if not scan_text("fixture.md", "pushed to github.com/mjenkinsx0/private", (), portability_skips):
        failures.append("portability exemption wrongly suppressed a leak pattern")
    if not scan_path("skills/demo/references/mjenkinsx0-private.md", ()):
        failures.append("a private token in a filename was not flagged")
    if scan_path("skills/demo/references/clean-reference.md", ()):
        failures.append("a clean path was wrongly flagged")
    hits = scan_path("skills/demo/hunter2-notes.md", ("hunter2",))
    if not hits:
        failures.append("an extra-literal token in a filename was not flagged")
    elif any("AGENTIC_SEDIMENT_EXTRA" not in hit for hit in hits):
        failures.append("path extra-token match did not use the non-echoing message")
    if shared_pipeline_errors({"a": "same", "b": "same"}):
        failures.append("identical shared-pipeline copies were flagged")
    if not shared_pipeline_errors({"a": "same", "b": "different"}):
        failures.append("diverged shared-pipeline copies were accepted")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sediment-selftest-") as raw:
        binary = pathlib.Path(raw) / "asset.bin"
        binary.write_bytes(b"\xff\xfepushed to github.com/mjenkinsx0/private\x00")
        fallback = read_text_or_none(binary, repo=pathlib.Path(raw))
        if fallback is None:
            failures.append("binary file was exempted instead of byte-scanned")
        elif not scan_text("asset.bin", fallback, ()):
            failures.append("sediment embedded in a binary asset was not flagged")
    if failures:
        print("sediment lint selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("sediment lint selftest: OK (denylist, env extension, and identity negatives pinned)")
    return 0


def read_text_or_none(path: pathlib.Path, repo: pathlib.Path = REPO) -> str | None:
    """Selected-source text, or a byte-preserving fallback for non-UTF-8 files.

    Skills may carry binary assets (provider generation copies them verbatim), and
    those assets are published like any other file — so instead of exempting their
    contents, undecodable files are re-read as latin-1, which maps every byte 1:1
    and lets the ASCII denylist patterns still match embedded sediment.
    """
    try:
        return gittracked.tracked_text(path, repo=repo)
    except UnicodeDecodeError:
        try:
            return gittracked.tracked_text(path, repo=repo, encoding="latin-1")
        except (UnicodeDecodeError, OSError):
            return None


def main() -> int:
    errors: list[str] = []
    extra = extra_literals()
    shared: dict[str, str] = {}
    for path, skip_labels in scan_files():
        rel = path.relative_to(REPO).as_posix()
        errors.extend(scan_path(rel, extra, skip_labels))
        text = read_text_or_none(path)
        if text is None:
            continue
        errors.extend(scan_text(rel, text, extra, skip_labels))
        if path.name == SHARED_BASENAME:
            shared[rel] = text
    errors.extend(shared_pipeline_errors(shared))
    return print_lint_epilogue(
        "sediment lint",
        errors,
        "shared skills/agents carry no personal or repo-specific sediment",
    )


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
