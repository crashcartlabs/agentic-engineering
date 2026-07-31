#!/usr/bin/env python3
"""Unit tests for toolbelt.py paths the embedded selftest does not cover.

The installer's own `--selftest` exercises install/uninstall/generate round-trips;
this file covers the smaller pure functions and dispatch plumbing that previously
had no witness at all: `resolve_base` fallback order, `parse_frontmatter` edge
cases, the pre-argparse forwarded-command interception, and `doctor` probing.

Runs as `test_toolbelt.py --selftest` under the aggregate gate; stdlib unittest,
cross-platform, hermetic (temp git repos only).
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

CI_DIR = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(CI_DIR.parents[0]))

import toolbelt  # noqa: E402


def _git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@invalid.example", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo_with_commit(root: pathlib.Path, name: str, branch: str = "work") -> pathlib.Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", branch)
    (repo / "file.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class ResolveBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="toolbelt-test-")
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_local_main_fallback(self) -> None:
        repo = _repo_with_commit(self.root, "local", branch="main")
        self.assertEqual(toolbelt.resolve_base(repo, github_branch=False), "main")

    def test_prefers_remote_tracking_over_local(self) -> None:
        upstream = _repo_with_commit(self.root, "upstream", branch="main")
        clone = self.root / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(upstream), str(clone)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(toolbelt.resolve_base(clone, github_branch=False), "origin/main")

    def test_github_branch_strips_remote_prefix(self) -> None:
        upstream = _repo_with_commit(self.root, "upstream2", branch="main")
        clone = self.root / "clone2"
        subprocess.run(
            ["git", "clone", "-q", str(upstream), str(clone)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(toolbelt.resolve_base(clone, github_branch=True), "main")

    def test_no_base_raises(self) -> None:
        repo = _repo_with_commit(self.root, "nobase", branch="feature-only")
        with self.assertRaises(toolbelt.ToolbeltError):
            toolbelt.resolve_base(repo, github_branch=False)


class ParseFrontmatterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="toolbelt-test-")
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, text: str) -> pathlib.Path:
        path = self.root / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_frontmatter_raises(self) -> None:
        with self.assertRaises(toolbelt.ToolbeltError):
            toolbelt.parse_frontmatter(self._write("# no frontmatter\n"))

    def test_unterminated_frontmatter_raises(self) -> None:
        with self.assertRaises(toolbelt.ToolbeltError):
            toolbelt.parse_frontmatter(self._write("---\nname: x\n"))

    def test_json_quoted_scalar_decodes_escapes(self) -> None:
        fields, body = toolbelt.parse_frontmatter(
            self._write('---\nname: demo\ndescription: "a \\"quoted\\" em\\u2014dash"\n---\nbody\n')
        )
        self.assertEqual(fields["description"], 'a "quoted" em—dash')
        self.assertEqual(body, "body\n")

    def test_single_quoted_scalar_strips_quotes(self) -> None:
        fields, _ = toolbelt.parse_frontmatter(
            self._write("---\nname: demo\ndescription: 'plain'\n---\n")
        )
        self.assertEqual(fields["description"], "plain")


class ForwardedCommandTests(unittest.TestCase):
    def test_forwarded_commands_bypass_argparse(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        original = toolbelt.run_repo_script
        toolbelt.run_repo_script = lambda path, args: calls.append((pathlib.Path(path).name, list(args))) or 7
        try:
            for command, script in (
                ("dashboard", "dashboard.py"),
                ("cmux-fleet", "spawn_fleet.py"),
                ("cmux-send", "send_task.py"),
                ("eval", "run_eval.py"),
            ):
                calls.clear()
                # --help must reach the target script, not toolbelt's argparse.
                self.assertEqual(toolbelt.main([command, "--help", "--extra"]), 7)
                self.assertEqual(calls, [(script, ["--help", "--extra"])])
        finally:
            toolbelt.run_repo_script = original


class DoctorTests(unittest.TestCase):
    def _run_doctor(self, availability: dict[str, str]) -> int:
        original_version = toolbelt.command_version
        original_validate = toolbelt.validate_source
        toolbelt.command_version = lambda name: (availability.get(name, "missing"), "")
        toolbelt.validate_source = lambda check_generated=True: []
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return toolbelt.doctor(pathlib.Path(tempfile.gettempdir()) / "toolbelt-test-home")
        finally:
            toolbelt.command_version = original_version
            toolbelt.validate_source = original_validate

    def test_missing_git_fails(self) -> None:
        self.assertEqual(self._run_doctor({"claude": "available"}), 1)

    def test_missing_all_providers_fails(self) -> None:
        self.assertEqual(self._run_doctor({"git": "available"}), 1)

    def test_git_plus_one_provider_passes(self) -> None:
        self.assertEqual(self._run_doctor({"git": "available", "codex": "available"}), 0)


def main() -> int:
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    if not result.wasSuccessful():
        print("toolbelt unit tests: FAIL")
        print(stream.getvalue())
        return 1
    print(f"toolbelt unit tests: OK ({result.testsRun} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
