#!/usr/bin/env python3
"""Check that relative Markdown links resolve to real, tracked targets.

Scope is deliberately local and hermetic: inline `[text](target)` links whose target is
a repo-relative path must point at an existing, **tracked** file or directory. External
URLs (http/https/mailto) are out of scope — checking their liveness in CI is
network-flaky, so that is left to a scheduled check, not the gate. Fenced code blocks
are skipped so example link syntax in docs is not mistaken for a real link.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any broken local link.

Both scanned sources and targets come from the same source selected by the aggregate
gate: working tree for interactive checks and Git index for pre-commit.
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r"\b(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)
EXTERNAL = ("http://", "https://", "mailto:", "file://", "//")
# `code-reviews/` remains a local report directory. The plan/security/skill evidence
# directories are tracked ordinary Markdown and should be linted when committed.
SKIP_DIRS = {"code-reviews"}


def iter_md(tracked: list[pathlib.Path]) -> list[pathlib.Path]:
    out = []
    for p in tracked:
        if p.suffix != ".md":
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(REPO).parts):
            continue
        out.append(p)
    return sorted(out)


def strip_fences(text: str) -> str:
    """Blank out ``` fenced blocks so example link syntax inside them isn't scanned."""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def selftest() -> int:
    text = "[good](docs/file.md)\n```md\n[ignored](missing.md)\n```\n[web](https://example.test)\n"
    visible = LINK_RE.findall(strip_fences(text))
    failures: list[str] = []
    if visible != ["docs/file.md", "https://example.test"]:
        failures.append(f"link/fence extraction drifted: {visible!r}")
    local = [target for target in visible if target and not target.startswith(EXTERNAL)]
    if local != ["docs/file.md"]:
        failures.append(f"external-link exclusion drifted: {local!r}")
    if failures:
        print("markdown link selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("markdown link selftest: OK (local, external, and fenced negatives pinned)")
    return 0


def main() -> int:
    tracked = gittracked.tracked_files()
    errors: list[str] = []
    for md in iter_md(tracked):
        source_text = gittracked.tracked_text(md)
        if source_text is None:
            errors.append(f"{md.relative_to(REPO).as_posix()}: missing from selected source")
            continue
        text = strip_fences(source_text)
        for target in LINK_RE.findall(text):
            target = target.strip()
            # A title after the URL: [x](path "title") — keep just the path.
            target = target.split(" ", 1)[0].split("\t", 1)[0]
            if not target or target.startswith("#"):
                continue
            if target.startswith(EXTERNAL):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (md.parent / path_part).resolve()
            if not gittracked.is_tracked(resolved, tracked):
                rel = md.relative_to(REPO).as_posix()
                errors.append(f"{rel}: broken link -> {target}")

    for page in sorted(path for path in tracked if path.suffix.lower() in {".html", ".htm"}):
        source_text = gittracked.tracked_text(page)
        if source_text is None:
            errors.append(f"{page.relative_to(REPO).as_posix()}: missing from selected source")
            continue
        for target in HTML_LINK_RE.findall(source_text):
            target = target.strip()
            if not target or target.startswith("#") or target.startswith(EXTERNAL):
                continue
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            resolved = (page.parent / path_part).resolve()
            if not gittracked.is_tracked(resolved, tracked):
                rel = page.relative_to(REPO).as_posix()
                errors.append(f"{rel}: broken HTML link -> {target}")

    return print_lint_epilogue("local link check", errors, "Markdown and HTML relative links resolve")


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
