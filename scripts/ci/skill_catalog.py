#!/usr/bin/env python3
"""Generate/check the declared skill maturity catalog."""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = REPO / "docs" / "skills.md"
VALID = {"experimental", "design-verified", "partially-live", "live-verified"}


def skill_description(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^description:\s*(.+)$', text, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    try:
        return str(json.loads(value))
    except json.JSONDecodeError:
        return value.strip('"\'')


def render() -> tuple[str, list[str]]:
    manifest = json.loads((REPO / "toolbelt.json").read_text(encoding="utf-8"))
    maturity = manifest.get("skillMaturity", {})
    explicit = set(manifest.get("skillPolicy", {}).get("explicit", []))
    skill_dirs = sorted(path.parent for path in (REPO / "skills").glob("*/SKILL.md"))
    names = {path.name for path in skill_dirs}
    errors: list[str] = []
    if set(maturity) != names:
        errors.append(
            "toolbelt.json skillMaturity keys must exactly match skills/: "
            f"missing={sorted(names - set(maturity))}, extra={sorted(set(maturity) - names)}"
        )

    rows: list[str] = []
    for directory in skill_dirs:
        name = directory.name
        state = maturity.get(name, "missing")
        if state not in VALID:
            errors.append(f"{name}: invalid or missing maturity {state!r}")
        tests_path = directory / "tests.md"
        tests = tests_path.read_text(encoding="utf-8").lower() if tests_path.exists() else ""
        has_design = "design-verified" in tests
        has_live = "live-verified" in tests
        if state == "design-verified" and not has_design:
            errors.append(f"{name}: design-verified requires design-verified evidence in tests.md")
        if state == "partially-live" and not (has_design and has_live):
            errors.append(f"{name}: partially-live requires both live and design evidence in tests.md")
        if state == "live-verified" and not has_live:
            errors.append(f"{name}: live-verified requires live-verified evidence in tests.md")
        invocation = "explicit" if name in explicit else "implicit allowed"
        description = skill_description(directory / "SKILL.md").replace("|", "\\|")
        rows.append(f"| `{name}` | {state} | {invocation} | {description} |")

    text = """# Skill catalog

Generated from `toolbelt.json`, canonical skill frontmatter, and each skill's candid
`tests.md` evidence. Do not hand-edit this file; run
`python3 scripts/ci/skill_catalog.py --generate`.

Maturity is a promotion contract, not a quality score: `experimental` has structural
tests only; `design-verified` has inspection evidence; `partially-live` mixes exercised
and design-only scenarios; `live-verified` has live evidence recorded in its test file.

| Skill | Maturity | Invocation | Purpose |
|---|---|---|---|
""" + "\n".join(rows) + "\n"
    return text, errors


def main() -> int:
    import sys

    expected, errors = render()
    if "--generate" in sys.argv[1:]:
        CATALOG.write_text(expected, encoding="utf-8")
    elif not CATALOG.exists() or CATALOG.read_text(encoding="utf-8") != expected:
        errors.append("docs/skills.md is stale; run scripts/ci/skill_catalog.py --generate")
    if errors:
        print("skill catalog: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"skill catalog: OK ({len(json.loads((REPO / 'toolbelt.json').read_text())['skillMaturity'])} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
