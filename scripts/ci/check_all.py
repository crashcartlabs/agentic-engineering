#!/usr/bin/env python3
"""Run every CI lint/selftest and aggregate the result — the repo's local gate command.

    python3 scripts/ci/check_all.py

Runs the record-file, plan, skill, and markdown-link lints plus embedded selftests (all
stdlib, hermetic) and exits non-zero if any fails. CI runs the same entry, so
`green here` == `green in CI` for the lint job. The secret scan runs only in CI (it needs
trufflehog installed).

Exit codes are tiered so a caller can tell "a lint found something" apart from "the gate
itself is broken": 0 pass, 1 a lint/selftest reported a real failure, 2 a lint/selftest
crashed (a bug in the check script, not a finding about the repo). The final stdout line is
a machine-readable verdict (`CI_VERDICT: PASS|FAIL|ERROR`) for scripts/watchers to parse
without re-deriving it from the human-readable output above it.
"""

from __future__ import annotations

import importlib
import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

CI_DIR = pathlib.Path(__file__).resolve().parent
REPO = CI_DIR.parents[1]

sys.dont_write_bytecode = True
sys.path.insert(0, str(CI_DIR))

LINT_MODULES = ("lint_records", "lint_plans", "lint_skills", "lint_links", "skill_catalog")
SELFTESTS = (
    ("toolbelt.py --selftest", REPO / "scripts" / "toolbelt.py", "toolbelt selftest: FAIL"),
    ("dashboard.py --selftest", REPO / "scripts" / "dashboard" / "dashboard.py", "dashboard selftest: FAIL"),
    ("spawn_fleet.py --selftest", REPO / "scripts" / "cmux" / "spawn_fleet.py", "spawn_fleet selftest: FAIL"),
    ("send_task.py --selftest", REPO / "scripts" / "cmux" / "send_task.py", "send_task selftest: FAIL"),
    ("janitor_preview.py --selftest", REPO / "scripts" / "maintenance" / "janitor_preview.py", "janitor preview selftest: FAIL"),
    (
        "weekly_janitor_report.py --selftest",
        REPO / "scripts" / "maintenance" / "weekly_janitor_report.py",
        "weekly janitor report selftest: FAIL",
    ),
    ("lint_plans.py --selftest", CI_DIR / "lint_plans.py", "plan lint selftest: FAIL"),
    ("lint_records.py --selftest", CI_DIR / "lint_records.py", "record-file lint selftest: FAIL"),
    ("lint_skills.py --selftest", CI_DIR / "lint_skills.py", "skill lint selftest: FAIL"),
    ("lint_links.py --selftest", CI_DIR / "lint_links.py", "markdown link selftest: FAIL"),
    ("test_check_all.py --selftest", CI_DIR / "test_check_all.py", "aggregate gate selftest: FAIL"),
    (
        "prepare_archive.py --selftest",
        REPO / "scripts" / "sandbox" / "prepare_archive.py",
        "sandbox archive selftest: FAIL",
    ),
    (
        "render_cmux_guide.py --selftest",
        REPO / "scripts" / "docs" / "render_cmux_guide.py",
        "generated docs check: FAIL",
    ),
)


def aggregate_verdict(check_failed: bool, crashed: bool) -> str:
    if crashed:
        return "ERROR"
    if check_failed:
        return "FAIL"
    return "PASS"


def _print_subprocess_output(text: str, *, file=sys.stdout) -> None:
    if text:
        print(text, end="" if text.endswith("\n") else "\n", file=file)


def run_selftest(name: str, script: pathlib.Path, failure_marker: str) -> int:
    if os.name == "nt" and script.name in {"spawn_fleet.py", "send_task.py"}:
        print(f"{script.name} selftest: SKIP (cmux orchestration is macOS-only)")
        return 0
    proc = subprocess.run(
        [sys.executable, str(script), "--selftest"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=180,
    )
    _print_subprocess_output(proc.stdout)
    _print_subprocess_output(proc.stderr, file=sys.stderr)
    if proc.returncode == 0:
        return 0
    if proc.returncode == 1 and failure_marker in proc.stdout:
        return 1
    raise RuntimeError(f"{name} exited {proc.returncode}")


def materialize_index(repo: pathlib.Path, destination: pathlib.Path) -> None:
    """Export one immutable view of the Git index for every staged-mode consumer."""
    destination.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "checkout-index", "--all", "--prefix", str(destination) + os.sep],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode:
        raise RuntimeError(f"git checkout-index failed: {(proc.stderr or '').strip()}")
    snapshot_env = {key: value for key, value in os.environ.items() if key != "GIT_INDEX_FILE"}
    initialized = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=destination,
        env=snapshot_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if initialized.returncode:
        raise RuntimeError(f"could not initialize index snapshot: {initialized.stderr.strip()}")
    staged = subprocess.run(
        ["git", "add", "-f", "-A"],
        cwd=destination,
        env=snapshot_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if staged.returncode:
        raise RuntimeError(f"could not index snapshot contents: {staged.stderr.strip()}")


def run_index_snapshot() -> int:
    """Run the entire gate, including subprocess selftests, against staged bytes."""
    with tempfile.TemporaryDirectory(prefix="agentic-index-gate-") as raw:
        snapshot = pathlib.Path(raw) / "repo"
        materialize_index(REPO, snapshot)
        script = snapshot / "scripts" / "ci" / "check_all.py"
        if not script.is_file():
            raise RuntimeError("staged snapshot does not contain scripts/ci/check_all.py")
        proc = subprocess.run(
            [sys.executable, str(script), "--worktree"],
            cwd=snapshot,
            env={
                **{key: value for key, value in os.environ.items() if key != "GIT_INDEX_FILE"},
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            check=False,
        )
        return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--index", action="store_true", help="lint the Git index")
    source.add_argument("--worktree", action="store_true", help="lint the working tree (default)")
    args = parser.parse_args(argv)
    if args.index:
        print("lint source: index snapshot")
        try:
            return run_index_snapshot()
        except Exception as exc:  # noqa: BLE001 - snapshot failure means the gate is broken
            print(f"index snapshot crashed: {exc!r}")
            print("\nCI_VERDICT: ERROR")
            return 2
    import gittracked

    gittracked.configure("worktree")
    print("lint source: worktree")
    check_failed = False
    crashed = False
    for name in LINT_MODULES:
        try:
            mod = importlib.import_module(name)
            if mod.main():
                check_failed = True
        except Exception as exc:  # noqa: BLE001 - a crashing lint is itself the finding
            crashed = True
            print(f"\n{name} crashed: {exc!r}")
    for name, script, failure_marker in SELFTESTS:
        try:
            if run_selftest(name, script, failure_marker):
                check_failed = True
        except Exception as exc:  # noqa: BLE001 - a crashing selftest is itself the finding
            crashed = True
            print(f"\n{name} crashed: {exc!r}")

    verdict = aggregate_verdict(check_failed, crashed)
    print(f"\nCI_VERDICT: {verdict}")
    return {"PASS": 0, "FAIL": 1, "ERROR": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
