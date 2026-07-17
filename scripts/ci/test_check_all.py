#!/usr/bin/env python3
"""Negative fixtures for the aggregate gate's verdict and crash classification."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

import check_all


def main() -> int:
    fixtures = {
        (False, False): "PASS",
        (True, False): "FAIL",
        (False, True): "ERROR",
        (True, True): "ERROR",
    }
    failures = [
        f"{inputs}: expected {expected}, got {check_all.aggregate_verdict(*inputs)}"
        for inputs, expected in fixtures.items()
        if check_all.aggregate_verdict(*inputs) != expected
    ]
    with tempfile.TemporaryDirectory(prefix="aggregate-index-selftest-") as raw:
        repo = pathlib.Path(raw) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
        candidate = repo / "candidate.txt"
        candidate.write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "add", "candidate.txt"], cwd=repo, check=True)
        candidate.write_text("unstaged\n", encoding="utf-8")
        snapshot = pathlib.Path(raw) / "snapshot"
        check_all.materialize_index(repo, snapshot)
        if (snapshot / "candidate.txt").read_text(encoding="utf-8") != "staged\n":
            failures.append("materialized index used working-tree bytes")
    batch = (check_all.REPO / "scripts" / "ci" / "run_gate.cmd").read_text(encoding="utf-8")
    if "goto use_py" not in batch or "goto use_python" not in batch or "if %errorlevel% equ 0 (" in batch:
        failures.append("Windows gate wrapper does not preserve the runtime Python exit status")
    if failures:
        print("aggregate gate selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("aggregate gate selftest: OK (pass, finding, and crash tiers pinned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
