#!/usr/bin/env python3
"""Lint the repo's record files: DEVLOG.md and LESSONS.md.

Checks the mechanical invariants that reviews have caught by hand (see LESSONS):

- DEVLOG entries (`## YYYY-MM-DD ...`) are in newest-first order — dates never
  increase as you read down the file.
- No DEVLOG entry section is empty — a heading with no body is the signature of the
  orphaned-heading bug (LESSONS 2026-07-03), where a prepend ate the previous body.
- Every DEVLOG entry is structurally sound: it opens with a `**Focus:**` line and
  holds at most one each of `**Focus:**` / `**Done:**` / `**Left off:**`. A duplicate
  label is the signature of a *merged* entry — a prepend that replaced the previous
  heading and folded its body in (the PR #70 orphan, issue #71), which the empty-body
  check cannot see because both bodies survive.
- Every LESSONS entry (`- YYYY-MM-DD ...`) is newest-first, contiguous with the
  surrounding lesson entries, and carries a real date that is not in the future.

`--selftest` proves both directions on embedded fixtures (clean DEVLOG/LESSONS pass;
the merged-entry reproduction and each structural break are flagged) without touching
the real record files.

The real record files are read through gittracked.py from the source selected by the
aggregate gate: working tree for an interactive run, Git index for pre-commit.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import _parse_date, print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO

DEVLOG_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")
# The one-per-entry section labels. Deliberately only these three: other labels the
# corpus uses (**Decisions:**, **Verification:**, ...) are free-form.
SECTION_LABEL = re.compile(r"^\*\*(Focus|Done|Left off):\*\*")
LESSON_ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2}) ")
LESSON_BULLET = re.compile(r"^- +\S")  # any top-level bullet — must be a dated lesson


def check_devlog(name: str, text: str, errors: list[str]) -> None:
    lines = text.splitlines()

    # Collect entry headings with their line numbers.
    entries: list[tuple[int, dt.date, str]] = []
    for i, line in enumerate(lines):
        m = DEVLOG_HEADING.match(line)
        if m:
            d = _parse_date(m.group(1))
            if d is None:
                errors.append(f"{name}:{i + 1}: unparseable date in heading: {line!r}")
            else:
                entries.append((i, d, line))

    if not entries:
        errors.append(f"{name}: no `## YYYY-MM-DD` entries found")
        return

    # Newest-first: each date <= the one above it.
    for (i1, d1, l1), (i2, d2, _l2) in zip(entries, entries[1:]):
        if d2 > d1:
            errors.append(
                f"{name}:{i2 + 1}: entry {d2} is newer than the entry above it "
                f"({d1} at line {i1 + 1}) — DEVLOG must be newest-first"
            )

    bounds = [i for i, _d, _l in entries] + [len(lines)]
    for (start, _d, heading), end in zip(entries, bounds[1:]):
        body = [(j, lines[j]) for j in range(start + 1, end) if lines[j].strip()]

        # No empty entry sections (orphaned-heading signature).
        if not body:
            errors.append(
                f"{name}:{start + 1}: entry has no body — {heading.strip()!r} "
                f"(orphaned heading? see LESSONS 2026-07-03)"
            )
            continue

        # Entry structure (merged-entry signature, issue #71): at most one each of
        # Focus/Done/Left off, and the entry opens with its Focus.
        labels: dict[str, list[int]] = {}
        for j, line in body:
            m = SECTION_LABEL.match(line)
            if m:
                labels.setdefault(m.group(1), []).append(j)
        for label, locs in labels.items():
            if len(locs) > 1:
                errors.append(
                    f"{name}:{locs[1] + 1}: duplicate **{label}:** in the entry at "
                    f"line {start + 1} (first at line {locs[0] + 1}) — merged entry? "
                    f"a prepend may have replaced the previous heading "
                    f"(see LESSONS 2026-07-03, issue #71)"
                )
        if "Focus" not in labels:
            errors.append(
                f"{name}:{start + 1}: entry has no **Focus:** section — "
                f"{heading.strip()!r}"
            )
        elif not body[0][1].startswith("**Focus:**"):
            errors.append(
                f"{name}:{body[0][0] + 1}: entry at line {start + 1} must open with "
                f"**Focus:** — first body line is {body[0][1]!r}"
            )


def check_lessons(name: str, text: str, errors: list[str]) -> None:
    today = dt.date.today()
    lines = text.splitlines()
    entries: list[tuple[int, dt.date, str]] = []
    for i, line in enumerate(lines):
        m = LESSON_ENTRY.match(line)
        if not m:
            # A top-level bullet that is not a dated lesson breaks the invariant that every
            # lesson carries a real date (e.g. `- Remember to run the gate`) — flag it.
            if LESSON_BULLET.match(line):
                errors.append(f"{name}:{i + 1}: lesson bullet without a leading YYYY-MM-DD date: {line!r}")
            continue
        d = _parse_date(m.group(1))
        if d is None:
            errors.append(f"{name}:{i + 1}: unparseable date: {line!r}")
        elif d > today:
            errors.append(f"{name}:{i + 1}: date {d} is in the future")
        else:
            entries.append((i, d, line))

    # Newest-first: each date <= the one above it.
    for (i1, d1, _l1), (i2, d2, _l2) in zip(entries, entries[1:]):
        if d2 > d1:
            errors.append(
                f"{name}:{i2 + 1}: lesson date {d2} is newer than the entry above it "
                f"({d1} at line {i1 + 1}) — LESSONS must be newest-first"
            )
        for j in range(i1 + 1, i2):
            if not lines[j].strip():
                errors.append(
                    f"{name}:{j + 1}: blank line between lesson entries — "
                    f"LESSONS entries must be contiguous"
                )


def check_records(
    repo: pathlib.Path,
    errors: list[str],
    *,
    git_env: dict[str, str] | None = None,
) -> None:
    for fname, checker in (("DEVLOG.md", check_devlog), ("LESSONS.md", check_lessons)):
        path = repo / fname
        text = gittracked.tracked_text_or_none(path, repo=repo, env=git_env)
        if text is None:
            errors.append(f"{fname}: missing")
            continue
        checker(fname, text, errors)


def main() -> int:
    errors: list[str] = []
    check_records(REPO, errors)
    return print_lint_epilogue(
        "record-file lint",
        errors,
        "DEVLOG order + entry structure + non-empty sections, LESSONS dates",
    )


# --- selftest fixtures ------------------------------------------------------------

CLEAN_DEVLOG = """\
# DEVLOG

Intro prose above the first entry is not part of any entry.

## 2026-07-05 — newest entry

**Focus:** the newest session's goal.

**Done:**
- a thing that got done.

**Left off:** where the next session picks up.

## 2026-07-04 — older entry

**Focus:** the older session's goal.

**Done:**
- another thing. Prose may mention **Focus:** mid-line without tripping the lint.
"""

# Reproduces the PR #70 orphan: a prepend replaced the previous entry's heading and
# opening **Focus:** line, so the old body (dangling fragment + its **Done:** and
# **Left off:**) folded into the new entry. Both "sections" have bodies, so the
# empty-body check passes — only the duplicate-label rule catches it.
MERGED_DEVLOG = """\
# DEVLOG

## 2026-07-05 — prepend that replaced the previous heading

**Focus:** the new session's goal.

**Done:**
- the new session's work.

in one session) — the previous entry's body dangles here without its heading.

**Done:**
- the previous session's work, now misattributed to 2026-07-05.

**Left off:** the previous session's hand-off.

## 2026-07-03 — an intact older entry

**Focus:** fine.

**Done:**
- fine.
"""

FOCUS_NOT_FIRST_DEVLOG = """\
# DEVLOG

## 2026-07-05 — entry whose Focus is buried

**Done:**
- work listed before the focus.

**Focus:** stated too late.
"""

FOCUS_MISSING_DEVLOG = """\
# DEVLOG

## 2026-07-05 — entry with no Focus at all

**Done:**
- work with no stated focus.
"""

EMPTY_ENTRY_DEVLOG = """\
# DEVLOG

## 2026-07-05 — heading with no body

## 2026-07-04 — intact entry

**Focus:** fine.

**Done:**
- fine.
"""

OUT_OF_ORDER_DEVLOG = """\
# DEVLOG

## 2026-07-01 — older entry on top

**Focus:** fine.

**Done:**
- fine.

## 2026-07-02 — newer entry below

**Focus:** fine.

**Done:**
- fine.
"""

CLEAN_LESSONS = """\
# LESSONS

One-line lessons from mistakes and corrections, so the same error isn't repeated.

- 2000-01-02 — newest lesson.
- 2000-01-01 — older lesson.
"""

OUT_OF_ORDER_LESSONS = """\
# LESSONS

- 2000-01-01 — older lesson on top.
- 2000-01-02 — newer lesson below.
"""

BLANK_LINE_LESSONS = """\
# LESSONS

- 2000-01-02 — newest lesson.

- 2000-01-01 — older lesson.
"""

UNDATED_LESSONS = """\
# LESSONS

- Remember to run the gate.
"""

FUTURE_LESSONS = """\
# LESSONS

- 9999-12-31 — not yet.
"""

# (fixture name, expected substring in some finding, expected finding count)
BROKEN_FIXTURES = (
    ("merged.md", MERGED_DEVLOG, "duplicate **Done:**", 1),
    ("focus-not-first.md", FOCUS_NOT_FIRST_DEVLOG, "must open with **Focus:**", 1),
    ("focus-missing.md", FOCUS_MISSING_DEVLOG, "has no **Focus:** section", 1),
    ("empty-entry.md", EMPTY_ENTRY_DEVLOG, "entry has no body", 1),
    ("out-of-order.md", OUT_OF_ORDER_DEVLOG, "must be newest-first", 1),
)

BROKEN_LESSON_FIXTURES = (
    ("lessons-out-of-order.md", OUT_OF_ORDER_LESSONS, "LESSONS must be newest-first", 1),
    ("lessons-blank-line.md", BLANK_LINE_LESSONS, "blank line between lesson entries", 1),
    ("lessons-undated.md", UNDATED_LESSONS, "lesson bullet without a leading YYYY-MM-DD date", 1),
    ("lessons-future.md", FUTURE_LESSONS, "is in the future", 1),
)


def selftest() -> int:
    failures: list[str] = []

    clean_errors: list[str] = []
    check_devlog("clean.md", CLEAN_DEVLOG, clean_errors)
    check_lessons("clean-lessons.md", CLEAN_LESSONS, clean_errors)
    for e in clean_errors:
        failures.append(f"clean fixture wrongly flagged: {e}")

    for fname, fixture, expected, count in BROKEN_FIXTURES:
        found: list[str] = []
        check_devlog(fname, fixture, found)
        if not any(expected in e for e in found):
            failures.append(f"{fname}: no finding contains {expected!r} (got {found})")
        if len(found) != count:
            failures.append(f"{fname}: expected exactly {count} finding(s), got {len(found)}: {found}")
        if found and not any(re.search(rf"{re.escape(fname)}:\d+:", e) for e in found):
            failures.append(f"{fname}: findings carry no file:line")

    for fname, fixture, expected, count in BROKEN_LESSON_FIXTURES:
        found: list[str] = []
        check_lessons(fname, fixture, found)
        if not any(expected in e for e in found):
            failures.append(f"{fname}: no finding contains {expected!r} (got {found})")
        if len(found) != count:
            failures.append(f"{fname}: expected exactly {count} finding(s), got {len(found)}: {found}")
        if found and not any(re.search(rf"{re.escape(fname)}:\d+:", e) for e in found):
            failures.append(f"{fname}: findings carry no file:line")

    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)
        devlog = repo / "DEVLOG.md"
        lessons = repo / "LESSONS.md"
        git_env = os.environ.copy()
        for key in (
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_PREFIX",
            "GIT_WORK_TREE",
        ):
            git_env.pop(key, None)

        def run_git(*args: str) -> None:
            subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
                env=git_env,
            )

        run_git("init")
        devlog.write_text(CLEAN_DEVLOG, encoding="utf-8")
        lessons.write_text(CLEAN_LESSONS, encoding="utf-8")
        run_git("add", "DEVLOG.md", "LESSONS.md")

        devlog.write_text(EMPTY_ENTRY_DEVLOG, encoding="utf-8")
        indexed_errors: list[str] = []
        previous = gittracked.SOURCE
        gittracked.configure("index")
        check_records(repo, indexed_errors, git_env=git_env)
        for e in indexed_errors:
            failures.append(f"record lint wrongly flagged unstaged DEVLOG working-tree edit: {e}")

        run_git("add", "DEVLOG.md")
        staged_errors: list[str] = []
        check_records(repo, staged_errors, git_env=git_env)
        gittracked.configure(previous)
        if not staged_errors:
            failures.append("record lint did not expose a staged broken DEVLOG edit")

    if failures:
        print("record-file lint selftest: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"record-file lint selftest: OK (clean fixture passes; "
        f"{len(BROKEN_FIXTURES)} DEVLOG and {len(BROKEN_LESSON_FIXTURES)} LESSONS broken "
        f"fixtures each flagged, "
        f"tracked-content read ignores unstaged edits)"
    )
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
