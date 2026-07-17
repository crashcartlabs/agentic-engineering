#!/usr/bin/env python3
"""Lint plans/ for unfilled plan-template residue.

Mechanizes the plan template's own rule ("Replace every <placeholder>. Leave no
placeholder behind") for every `plans/*.md` except `README.md`:

- Metadata rows: `**Status**` is one of draft/approved/in-progress/done; `**Created**`
  and `**Modified**` are real YYYY-MM-DD dates; `**Spec**`, `**Branch**`, and
  `**Related plans**` are non-empty and free of `<`-template tokens; all six rows are
  present. Approved and active plans name their deterministic `plan/<slug>` branch.
- Template tokens: a tight allowlist of tokens that only ever mean "the writer never
  filled this in", flagged with file:line. Deliberately NOT a generic `<...>` regex —
  plans legitimately contain angle-bracket pattern prose (`plan/<slug>`,
  `reviews/<YYYY-MM-DD>-<plan-slug>.md`). Tokens inside backtick code spans are
  exempt: that is prose *about* a token, while real template residue is always bare.

`--selftest` proves both directions on embedded fixtures (clean passes; leftover and
missing-row are flagged) without putting fixture files under `plans/` where they would
trip the lint.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any violation.

Uses the source selected by the aggregate gate: working tree for interactive checks and
Git index for pre-commit.
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import META_ROW, _parse_date, print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO

VALID_STATUS = {"draft", "approved", "in-progress", "done"}
META_FIELDS = ("Status", "Created", "Modified", "Spec", "Branch", "Related plans")

# Tokens that only ever mean "unfilled template" — extend as the template evolves.
RESIDUE_TOKENS = (
    "<placeholder>",
    "<Plan title>",
    "<task>",
    "<...>",
    "<reason>",
    "<one-line reason>",
    "<Decision>",
    '<e.g. "',
    "<name>",
    "<how this phase",
    "<claim/finding>",
    "<[VERIFIED: source] / [CITED: url] / [ASSUMED]>",
    "<url/path/tool output>",
    "<decision/constraint>",
    "<path/API/resource>",
    "<every open/write/delete/rename/exec call that can affect it>",
    '<each check-before-use, TOCTOU window, or "none">',
    "<who can write/read/replace inputs, paths, configs, pidfiles, temp files>",
)

CODE_SPAN = re.compile(r"`[^`]+`")


def check_plan(name: str, text: str, errors: list[str]) -> None:
    """Append a finding for every metadata-row violation or residue token in one plan."""
    seen: set[str] = set()
    values: dict[str, tuple[str, int]] = {}
    for i, line in enumerate(text.splitlines()):
        lineno = i + 1
        m = META_ROW.match(line)
        if m:
            field, value = m.group(1), m.group(2).strip()
            seen.add(field)
            values[field] = (value, lineno)
            if field == "Status":
                if value not in VALID_STATUS:
                    errors.append(
                        f"{name}:{lineno}: **Status** must be one of "
                        f"{'/'.join(sorted(VALID_STATUS))} — got {value!r}"
                    )
            elif field in ("Created", "Modified"):
                if _parse_date(value) is None:
                    errors.append(
                        f"{name}:{lineno}: **{field}** must be a real YYYY-MM-DD date — got {value!r}"
                    )
            else:  # Spec, Branch, Related plans
                if not value:
                    errors.append(f"{name}:{lineno}: **{field}** row is empty")
                elif "<" in value:
                    errors.append(
                        f"{name}:{lineno}: **{field}** still holds a template token — got {value!r}"
                    )
        # Residue tokens: bare occurrences only — backticked mentions are prose about
        # the token (the corpus quotes `<placeholder>` etc. legitimately).
        stripped = CODE_SPAN.sub("", line)
        for token in RESIDUE_TOKENS:
            if token in stripped:
                errors.append(f"{name}:{lineno}: unfilled template token {token!r}")
    for field in META_FIELDS:
        if field not in seen:
            errors.append(f"{name}: metadata row **{field}** is missing")

    status = values.get("Status", ("", 0))[0]
    branch, branch_line = values.get("Branch", ("", 0))
    filename = pathlib.PurePath(name).name
    slug = filename[:-3] if filename.endswith(".md") else filename
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
    expected = f"plan/{slug}"
    if status == "draft":
        if branch not in {"tbd", expected} and branch:
            errors.append(
                f"{name}:{branch_line}: draft **Branch** must be 'tbd' or {expected!r} — got {branch!r}"
            )
    elif status in {"approved", "in-progress", "done"} and branch:
        legacy_done = status == "done" and branch.startswith("legacy:")
        if branch != expected and not legacy_done:
            errors.append(
                f"{name}:{branch_line}: {status} **Branch** must be {expected!r} — got {branch!r}"
            )


def main() -> int:
    errors: list[str] = []
    plans_dir = REPO / "plans"
    # Top-level plans/*.md only, matching the original non-recursive scope: a git
    # pathspec's `*` crosses `/`, so "plans/*.md" would also match a nested
    # plans/archive/old.md -- filter by parent instead of relying on the pathspec.
    paths = sorted(
        p for p in gittracked.tracked_files("plans/")
        if p.parent == plans_dir and p.suffix == ".md" and p.name != "README.md"
    )
    for path in paths:
        text = gittracked.tracked_text(path)
        if text is None:
            errors.append(f"{path.name}: missing from selected source")
        else:
            check_plan(path.name, text, errors)
    return print_lint_epilogue(
        "plan lint",
        errors,
        f"metadata rows + template tokens across {len(paths)} plans",
    )


# --- selftest fixtures ------------------------------------------------------------

CLEAN_FIXTURE = """\
# A finished plan

| | |
|---|---|
| **Status** | done |
| **Created** | 2026-07-03 |
| **Modified** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/clean |
| **Related plans** | none |

## Summary

The executor works on a plan/<slug> branch; reports go to
reviews/<YYYY-MM-DD>-<plan-slug>.md under <git-common-dir>. A quoted token like
`<placeholder>` or the row `| **Created** | <YYYY-MM-DD> |` is prose, not residue.
"""

LEFTOVER_FIXTURE = """\
# <Plan title>

| | |
|---|---|
| **Status** | draft <!-- draft → approved → in-progress → done --> |
| **Created** | <YYYY-MM-DD> |
| **Modified** | not-a-date |
| **Spec** | <path to spec> |
| **Branch** | <branch or "tbd"> |
| **Related plans** | |

## Success criteria

- [ ] <e.g. "A POST with a missing email returns 400 with a clear message">
- [ ] <...>

## Threat model & hardening boundary

| Defended surface | Open/write calls | Check-use orderings | Trust boundary |
|---|---|---|---|
| <path/API/resource> | <every open/write/delete/rename/exec call that can affect it> | <each check-before-use, TOCTOU window, or "none"> | <who can write/read/replace inputs, paths, configs, pidfiles, temp files> |

## Research findings

| Finding | Provenance | Source | Plan impact |
|---|---|---|---|
| <claim/finding> | <[VERIFIED: source] / [CITED: url] / [ASSUMED]> | <url/path/tool output> | <decision/constraint> |

## Relevant files

| File | Why |
|---|---|
| `path/to/file` | <reason> |

## Implementation phases

### Phase 1 — <name>

- [ ] 1.1 <task>

**Validation:** <how this phase proves itself — commands to run, behavior to observe.>

## Risks & rollback

N/A — <one-line reason>

## Decisions & tradeoffs

- **<Decision>** — replace every <placeholder>.
"""

# A plan valid in every way except one absent metadata row — pins the
# missing-metadata-row rule, so removing that rule turns the selftest red.
MISSING_ROW_FIXTURE = """\
# A plan missing a metadata row

| | |
|---|---|
| **Status** | done |
| **Created** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/missing-row |
| **Related plans** | none |

## Summary

Everything is filled in, but the Modified row is absent.
"""

# Each rule must be represented: (substring expected in some finding).
LEFTOVER_EXPECTED = (
    "**Status** must be one of",
    "**Created** must be a real YYYY-MM-DD date",
    "**Modified** must be a real YYYY-MM-DD date",
    "**Spec** still holds a template token",
    "**Branch** still holds a template token",
    "**Related plans** row is empty",
    "unfilled template token '<Plan title>'",
    "unfilled template token '<e.g. \"'",
    "unfilled template token '<...>'",
    "unfilled template token '<reason>'",
    "unfilled template token '<task>'",
    "unfilled template token '<one-line reason>'",
    "unfilled template token '<Decision>'",
    "unfilled template token '<placeholder>'",
    "unfilled template token '<name>'",
    "unfilled template token '<how this phase'",
    "unfilled template token '<claim/finding>'",
    "unfilled template token '<[VERIFIED: source] / [CITED: url] / [ASSUMED]>'",
    "unfilled template token '<url/path/tool output>'",
    "unfilled template token '<decision/constraint>'",
    "unfilled template token '<path/API/resource>'",
    "unfilled template token '<every open/write/delete/rename/exec call that can affect it>'",
    "unfilled template token '<each check-before-use, TOCTOU window, or \"none\">'",
    "unfilled template token '<who can write/read/replace inputs, paths, configs, pidfiles, temp files>'",
)


def selftest() -> int:
    failures: list[str] = []

    clean_errors: list[str] = []
    check_plan("clean.md", CLEAN_FIXTURE, clean_errors)
    for e in clean_errors:
        failures.append(f"clean fixture wrongly flagged: {e}")

    leftover_errors: list[str] = []
    check_plan("leftover.md", LEFTOVER_FIXTURE, leftover_errors)
    for expected in LEFTOVER_EXPECTED:
        if not any(expected in e for e in leftover_errors):
            failures.append(f"leftover fixture missed a rule: no finding contains {expected!r}")
    if not any(re.search(r"leftover\.md:\d+:", e) for e in leftover_errors):
        failures.append("leftover fixture findings carry no file:line")

    missing_errors: list[str] = []
    check_plan("missing-row.md", MISSING_ROW_FIXTURE, missing_errors)
    expected_missing = "missing-row.md: metadata row **Modified** is missing"
    if expected_missing not in missing_errors:
        failures.append(f"missing-row fixture missed a rule: no finding equals {expected_missing!r}")
    for e in missing_errors:
        if e != expected_missing:
            failures.append(f"missing-row fixture wrongly flagged: {e}")

    if failures:
        print("plan lint selftest: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"plan lint selftest: OK (clean fixture passes, leftover fixture flagged "
        f"{len(leftover_errors)} findings, missing-row fixture flagged)"
    )
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
