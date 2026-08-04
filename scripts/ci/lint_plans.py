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

# Per-phase TDD contract (plan SKILL.md "Mark each phase's TDD discipline"): every
# implementation phase carries exactly one `**TDD:**` line reading `strict` or
# `none — <reason>`, so the executor never guesses the testing contract.
# The full canonical shape — `### Phase <digits> — <name>` — matching what
# phase-driven tooling parses; anything looser is a noncanonical-heading error.
PHASE_HEADING = re.compile(r"^###\s+Phase\s+\d+\s+—\s+\S")
# Any other ATX heading naming a Phase is noncanonical: it would silently escape
# the per-phase TDD contract, so it is an error, not ignored. At most three
# leading spaces — four-plus is an indented code block in CommonMark (an example,
# not structure), same as the fence-opener rule below.
PHASE_HEADING_ANY = re.compile(r"^ {0,3}#{1,6}\s+Phase\b")
# Only a sibling-or-higher heading (H1-H3) closes a phase; an H4+ subsection
# such as `#### Notes` is nested content and its lines stay inside the phase.
SECTION_HEADING = re.compile(r"^ {0,3}#{1,3}\s")
TDD_LINE = re.compile(r"^\*\*TDD:\*\*\s*(.*)$")
TDD_VALID = re.compile(r"^(strict|none\s*[—-]\s*\S.*)$")

HTML_COMMENT_SPAN = re.compile(r"<!--.*?-->")


def strip_html_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """The visible (non-commented) text of one line, plus the carried state.

    A `**TDD:**` marker or `### Phase` heading inside an HTML comment is
    invisible in every renderer, so it must be an example for the structural
    parse too — neither satisfying nor tripping the phase contract.
    """
    if in_comment:
        end = line.find("-->")
        if end == -1:
            return "", True
        line = line[end + 3 :]
    line = HTML_COMMENT_SPAN.sub("", line)
    start = line.find("<!--")
    if start != -1:
        return line[:start], True
    return line, False


def check_plan(name: str, text: str, errors: list[str]) -> None:
    """Append a finding for every metadata-row violation or residue token in one plan."""
    seen: set[str] = set()
    values: dict[str, tuple[str, int]] = {}
    phase: tuple[str, int] | None = None  # (heading text, lineno) of the open phase
    phase_tdd = 0
    phase_count = 0

    def close_phase() -> None:
        nonlocal phase, phase_tdd
        if phase is not None and phase_tdd == 0:
            errors.append(f"{name}:{phase[1]}: {phase[0]!r} has no **TDD:** marker (strict or none — <reason>)")
        if phase is not None and phase_tdd > 1:
            errors.append(f"{name}:{phase[1]}: {phase[0]!r} has {phase_tdd} **TDD:** markers; expected one")
        phase, phase_tdd = None, 0

    fence: tuple[str, int] | None = None  # (delimiter char, opener length) of the open fence
    html_comment = False  # inside a multiline <!-- --> block (outside fences)
    for i, line in enumerate(text.splitlines()):
        lineno = i + 1
        # Fenced code blocks are examples, not plan structure: a fenced
        # `**TDD:**` line or `### Phase` heading must never satisfy (or trip)
        # the phase contract. Track the opener's delimiter — a ``` block that
        # *shows* tilde syntax must not be closed by the inner ~~~ line.
        # At most three leading spaces: four-plus is an indented code block in
        # CommonMark, not a fence opener.
        fence_match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence_match and not html_comment:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and line.strip() == marker:
                # A closing fence carries no info string (CommonMark) — an inner
                # ```python opener shown inside an outer ```markdown example is
                # content, not the outer block's close.
                fence = None
        else:
            in_content = fence is None
            if not in_content:
                continue
            visible, html_comment = strip_html_comments(line, html_comment)
            if PHASE_HEADING.match(visible):
                close_phase()
                phase = (visible.strip(), lineno)
                phase_count += 1
            elif PHASE_HEADING_ANY.match(visible):
                close_phase()
                errors.append(
                    f"{name}:{lineno}: noncanonical phase heading {visible.strip()!r} "
                    "— use an unindented '### Phase N — <name>' so the TDD contract applies"
                )
            elif SECTION_HEADING.match(visible):
                close_phase()
            elif phase is not None:
                tdd = TDD_LINE.match(visible)
                if tdd:
                    phase_tdd += 1
                    if not TDD_VALID.match(tdd.group(1).strip()):
                        errors.append(
                            f"{name}:{lineno}: **TDD:** marker must be 'strict' or 'none — <reason>' "
                            f"— got {tdd.group(1).strip()!r}"
                        )
            # Metadata and residue live in the same visible text: a metadata
            # table inside an HTML comment is invisible in every renderer and
            # must not satisfy the required-rows contract.
            m = META_ROW.match(visible)
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
            stripped = CODE_SPAN.sub("", visible)
            for token in RESIDUE_TOKENS:
                if token in stripped:
                    errors.append(f"{name}:{lineno}: unfilled template token {token!r}")
    close_phase()
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
    if status in {"approved", "in-progress", "done"} and phase_count == 0:
        # The executor is phase-driven: an approved plan with no canonical
        # phases has nothing to run and would read as instantly complete.
        errors.append(
            f"{name}: {status} plan has no '### Phase' implementation phases"
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
        text = gittracked.tracked_text_or_none(path)
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
| **Status** | done <!-- a template hint comment renders invisibly; "done" is the value --> |
| **Created** | 2026-07-03 |
| **Modified** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/clean |
| **Related plans** | none |

## Summary

The executor works on a plan/<slug> branch; reports go to
reviews/<YYYY-MM-DD>-<plan-slug>.md under <git-common-dir>. A quoted token like
`<placeholder>` or the row `| **Created** | <YYYY-MM-DD> |` is prose, not residue.

## Implementation phases

### Phase 1 — build the behavior

- [x] 1.1 write the failing test, then the code

An indented code block is an example too, not plan structure — it must neither
read as a noncanonical heading nor close this phase before its marker:

    ### Phase 97 — indented example, not a real phase
    **TDD:** whenever convenient

**TDD:** strict
**Validation:** run the test file.

```markdown
An example block quoting plan syntax — its markers are examples, not structure:
**TDD:** whenever convenient
### Phase 99 — not a real phase
```

~~~markdown
The tilde fence syntax is an example container too:
**TDD:** whenever convenient
### Phase 98 — also not a real phase
~~~

```markdown
An outer backtick block that itself shows tilde syntax:
~~~
**TDD:** whenever convenient
~~~
The inner tildes must not close the outer fence.
```

```markdown
An inner same-delimiter opener with an info string is content, not a close:
```python
**TDD:** whenever convenient
```

### Phase 2 — regenerate artifacts

- [x] 2.1 rerun the generator

<!--
A commented-out block is invisible to renderers and to the structural parse:
**TDD:** whenever convenient
### Phase 96 — commented example, not a real phase
-->

#### Notes

A nested H4 subsection stays inside the phase; the marker below still counts.

**TDD:** none — generated files, covered by the drift check
**Validation:** generator check passes.
"""

COMMENTED_MARKER_FIXTURE = """\
# A plan whose only TDD marker is commented out

| | |
|---|---|
| **Status** | approved |
| **Created** | 2026-07-03 |
| **Modified** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/commented |
| **Related plans** | none |

## Implementation phases

### Phase 1 — build the behavior

- [ ] 1.1 write the code

<!--
**TDD:** strict
#### Phase 95 — commented heading, not structure
-->

**Validation:** run the tests.
"""

LEFTOVER_FIXTURE = """\
# <Plan title>

| | |
|---|---|
| **Status** | pending <!-- an inline comment must not hide the invalid visible value --> |
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

### Phase 2 — has a bad marker

- [ ] 2.1 <task>

**TDD:** whenever convenient
**Validation:** <...>

#### Phase 3 — wrong heading level

- [ ] 3.1 <task>

### Phase banana

- [ ] 4.1 <task>

    ``` an indented code line, not a fence opener

### Phase 5 — after indented code

- [ ] 5.1 <task>

  # Appendix (a valid indented heading still closes the phase)

**TDD:** strict

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

## Implementation phases

### Phase 1 — finished work

- [x] 1.1 done task

**TDD:** none — documentation only
**Validation:** rendered output reviewed.
"""

# An approved plan with valid metadata but zero canonical phases — pins the
# phase-requirement rule for executor-bound statuses.
NO_PHASE_FIXTURE = """\
# A plan with no phases

| | |
|---|---|
| **Status** | approved |
| **Created** | 2026-07-03 |
| **Modified** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/no-phase |
| **Related plans** | none |

## Summary

Approved, but there is nothing for the executor to run.
"""

# The metadata table exists only inside a fenced example — it must not satisfy
# the required-rows contract.
FENCED_META_FIXTURE = """\
# A plan whose only metadata is an example

```markdown
| | |
|---|---|
| **Status** | done |
| **Created** | 2026-07-03 |
| **Modified** | 2026-07-03 |
| **Spec** | specs/2026-07-03-some-topic.md |
| **Branch** | plan/fenced-meta |
| **Related plans** | none |
```

## Summary

The fenced table above is documentation, not plan state.
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
    "has no **TDD:** marker",
    "**TDD:** marker must be 'strict' or 'none",
    "noncanonical phase heading",
    "Phase 5 — after indented code' has no **TDD:** marker",
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

    no_phase_errors: list[str] = []
    check_plan("no-phase.md", NO_PHASE_FIXTURE, no_phase_errors)
    if not any("has no '### Phase' implementation phases" in e for e in no_phase_errors):
        failures.append("approved zero-phase plan was not flagged")

    fenced_meta_errors: list[str] = []
    check_plan("fenced-meta.md", FENCED_META_FIXTURE, fenced_meta_errors)
    if "fenced-meta.md: metadata row **Status** is missing" not in fenced_meta_errors:
        failures.append("fenced example metadata satisfied the required-rows contract")

    commented_errors: list[str] = []
    check_plan("commented.md", COMMENTED_MARKER_FIXTURE, commented_errors)
    if not any("has no **TDD:** marker" in e for e in commented_errors):
        failures.append("a commented-out **TDD:** marker satisfied the phase contract")
    if any("noncanonical phase heading" in e for e in commented_errors):
        failures.append("a commented-out phase heading was treated as plan structure")

    commented_meta = (
        "# A plan whose metadata table is commented out\n\n"
        "<!--\n"
        "| | |\n|---|---|\n"
        "| **Status** | done |\n| **Created** | 2026-07-03 |\n| **Modified** | 2026-07-03 |\n"
        "| **Spec** | specs/x.md |\n| **Branch** | plan/x |\n| **Related plans** | none |\n"
        "-->\n"
    )
    commented_meta_errors: list[str] = []
    check_plan("commented-meta.md", commented_meta, commented_meta_errors)
    if "commented-meta.md: metadata row **Status** is missing" not in commented_meta_errors:
        failures.append("commented-out metadata satisfied the required-rows contract")

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
