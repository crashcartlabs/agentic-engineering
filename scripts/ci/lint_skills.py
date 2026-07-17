#!/usr/bin/env python3
"""Lint the skill set under skills/.

Hard checks (fail the build) — the invariants every skill here already holds:

- each skill dir has a SKILL.md,
- its frontmatter has a `name` and a `description`,
- `name` matches the directory name,
- every `assets/…` or `references/…` file the SKILL.md points at actually exists,
- each skill dir has a tests.md.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any hard violation. Uses the source
selected by the aggregate gate: working tree for interactive checks and Git index for
pre-commit.
"""

from __future__ import annotations

import pathlib
import re
import sys
import json

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO
SKILLS = REPO / "skills"

# Tokens like `assets/report-template.md` or a full `.../references/setup-hooks.md`,
# restricted to real file extensions so bare `references/` prose isn't flagged.
REF_RE = re.compile(
    r"((?:assets|references)/[A-Za-z0-9._/-]+\.(?:md|sh|py|ts|js|txt|json|ya?ml))"
)
SCENARIO_RE = re.compile(
    r"^#{2,4}\s+(?:Scenario\b|Golden\b|Edge\b|Error\b)",
    re.MULTILINE | re.IGNORECASE,
)
VERIFICATION_RE = re.compile(r"Last verified:|\b(?:live|design|static)-verified\b|\*\*Status:", re.IGNORECASE)


def frontmatter(text: str) -> dict[str, str] | None:
    """Minimal `key: value` frontmatter parse — no YAML dep needed for name/description."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def selftest() -> int:
    failures: list[str] = []
    valid = frontmatter('---\nname: demo\ndescription: "Useful skill"\n---\n')
    if valid != {"name": "demo", "description": '"Useful skill"'}:
        failures.append(f"valid frontmatter parsed incorrectly: {valid!r}")
    if frontmatter("# no frontmatter\n") is not None:
        failures.append("missing frontmatter was accepted")
    provider_specific = frontmatter(
        "---\nname: demo\ndescription: ok\ndisable-model-invocation: true\n---\n"
    ) or {}
    if not (set(provider_specific) - {"name", "description"}):
        failures.append("provider-specific frontmatter fixture was not detectable")
    tests = "## Scenario 1\n## Edge: two\n## Error: three\nLast verified: design-verified\n"
    if len(SCENARIO_RE.findall(tests)) != 3 or not VERIFICATION_RE.search(tests):
        failures.append("scenario/maturity fixture did not satisfy the contract")
    negative_tests = "## Scenario 1\n## Scenario 2\n"
    if len(SCENARIO_RE.findall(negative_tests)) >= 3 or VERIFICATION_RE.search(negative_tests):
        failures.append("short unverified tests fixture was accepted")
    if failures:
        print("skill lint selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("skill lint selftest: OK (frontmatter and verification negatives pinned)")
    return 0


def main() -> int:
    if not SKILLS.is_dir():
        print(f"skill lint: no skills dir at {SKILLS}")
        return 0

    tracked = set(gittracked.tracked_files("skills/"))
    # A tracked file directly under SKILLS (e.g. a root-level README.md) has only one
    # path component relative to SKILLS — that's the file itself, not a skill dir name.
    skill_names = sorted({
        p.relative_to(SKILLS).parts[0]
        for p in tracked
        if len(p.relative_to(SKILLS).parts) > 1
    })

    errors: list[str] = []
    missing_tests: list[str] = []
    manifest = json.loads((REPO / "toolbelt.json").read_text(encoding="utf-8"))
    explicit = set(manifest.get("skillPolicy", {}).get("explicit", []))

    for name in skill_names:
        d = SKILLS / name
        skill = d / "SKILL.md"
        if skill not in tracked:
            errors.append(f"{name}: no SKILL.md")
            continue

        text = gittracked.tracked_text(skill)
        if text is None:
            errors.append(f"{name}: SKILL.md missing from selected source")
            continue
        fm = frontmatter(text)
        if fm is None:
            errors.append(f"{name}: SKILL.md has no frontmatter block")
        else:
            if not fm.get("name"):
                errors.append(f"{name}: frontmatter missing `name`")
            elif fm["name"] != name:
                errors.append(f"{name}: frontmatter name {fm['name']!r} != dir {name!r}")
            if not fm.get("description"):
                errors.append(f"{name}: frontmatter missing `description`")
            extras = sorted(set(fm) - {"name", "description"})
            if extras:
                errors.append(
                    f"{name}: canonical frontmatter has provider-specific keys: "
                    + ", ".join(extras)
                )

        for ref in sorted(set(REF_RE.findall(text))):
            # Resolve from the ref's assets/ or references/ segment against the skill dir,
            # so both inline (`assets/x.md`) and full-path references resolve.
            seg = ref[ref.index("assets/") if "assets/" in ref else ref.index("references/"):]
            if (d / seg) not in tracked:
                errors.append(f"{name}: SKILL.md references missing file {seg}")

        tests_path = d / "tests.md"
        if tests_path not in tracked:
            missing_tests.append(name)
        else:
            tests_text = gittracked.tracked_text(tests_path) or ""
            scenarios = len(SCENARIO_RE.findall(tests_text))
            if scenarios < 3:
                errors.append(f"{name}: tests.md has {scenarios} scenario heading(s); need at least 3")
            if not VERIFICATION_RE.search(tests_text):
                errors.append(f"{name}: tests.md has no verification status/maturity marker")

        openai_path = d / "agents" / "openai.yaml"
        if openai_path not in tracked:
            errors.append(f"{name}: missing agents/openai.yaml")
        else:
            metadata = gittracked.tracked_text(openai_path) or ""
            implicit_disabled = bool(
                re.search(r"(?m)^\s*allow_implicit_invocation:\s*false\s*$", metadata)
            )
            if (name in explicit) != implicit_disabled:
                expected = "false" if name in explicit else "true/default"
                errors.append(
                    f"{name}: Codex implicit invocation policy does not match "
                    f"toolbelt.json (expected {expected})"
                )

    if missing_tests:
        errors.append(
            f"{len(missing_tests)} skill(s) without tests.md: "
            + ", ".join(missing_tests)
        )

    return print_lint_epilogue(
        "skill lint",
        errors,
        "portable frontmatter, metadata policy, references, and verification scenarios",
    )


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
