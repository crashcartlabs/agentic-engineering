"""Shared helpers for the repo's stdlib lint scripts."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence

META_ROW = re.compile(
    r"^\|\s*\*\*(Status|Created|Modified|Spec|Branch|Related plans)\*\*\s*\|(.*)\|\s*$"
)


def _parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def print_lint_epilogue(label: str, errors: Sequence[str], ok_summary: str) -> int:
    if errors:
        print(f"{label}: FAIL")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"{label}: OK ({ok_summary})")
    return 0
