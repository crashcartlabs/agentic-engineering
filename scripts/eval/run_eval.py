#!/usr/bin/env python3
"""Run a skill's eval scenarios through a live agent CLI and record evidence.

    python3 scripts/eval/run_eval.py <skill> [scenario] --provider claude [--judge]
    agentic eval <skill> [scenario] --provider claude

Scenarios live at `skills/<skill>/evals/<scenario>.json` (JSON because the repo is
pure stdlib — no YAML parser). Each scenario declares a declarative fixture, the
prompt to drive the provider with, deterministic checks over the resulting fixture
state, and an optional LLM-judge rubric. The runner:

  1. builds the fixture in a fresh temp directory (files, optional git init +
     baseline commit, optional setup steps),
  2. invokes the provider adapter headlessly in that directory,
  3. runs the deterministic checks,
  4. optionally runs a judge pass (--judge) scoring the transcript against the
     scenario's rubric,
  5. writes an evidence record to `eval-results/` (gitignored — evidence is local;
     promotion is a human edit to toolbelt.json citing the record).

The runner never edits `toolbelt.json`: on an all-green run against a real provider
it prints the suggested `skillMaturity` promotion and the `tests.md` evidence line,
and stops there.

Scenario schema (schemaVersion 1):

    {
      "schemaVersion": 1,
      "skill": "<skill-name>",
      "scenario": "<scenario-name>",
      "fixture": {
        "files": {"relative/path.txt": "content"},
        "git": true,
        "shadow_commands": ["agentic"],
        "setup": [
          ["git", "checkout", "-b", "feature"],
          {"write": {"path": "file.txt", "content": "..."}},
          {"argv": ["git", "merge", "feature"], "check": false}
        ]
      },
      "prompt": "…",
      "checks": [
        {"type": "file_exists", "path": "AGENTS.md"},
        {"type": "file_absent", "path": "scratch/"},
        {"type": "file_contains", "path": "AGENTS.md", "pattern": "## "},
        {"type": "transcript_contains", "pattern": "(?i)installer"},
        {"type": "command", "argv": ["git", "diff", "--check"], "expect_exit": 0,
         "expect_empty_output": true, "expect_output": null},
        {"type": "git_clean"}
      ],
      "judge": {"enabled": false, "rubric": "…"}
    }

The declared `skill` must match the directory the file lives under and `scenario`
must match the file stem — evidence filenames and promotion suggestions are derived
from them. A scenario passes only when the provider exited 0, every check passed,
and (when judged) the judge exited 0 with a PASS verdict.

For the claude provider, the checkout's generated adapter
(`providers/claude/skills/<skill>/`) is copied into the fixture as a project-level
skill (`.claude/skills/<skill>/`) before the baseline commit, so the run exercises
the version under review — never whatever happens to be installed under `~/.claude`.

Fixture content is repo-owned trusted configuration; setup steps run inside the
throwaway fixture directory only. Exit 0 when every scenario's checks pass, 1
otherwise, 2 on configuration/environment errors.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from providers import EvalError, run_provider  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO / "eval-results"
GIT_IDENTITY = ("-c", "user.name=agentic-eval", "-c", "user.email=eval@invalid.example")


def fixture_path(root: pathlib.Path, relative: str) -> pathlib.Path:
    candidate = (root / relative).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise EvalError(f"fixture path escapes the fixture directory: {relative!r}")
    return candidate


def run_git(root: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *GIT_IDENTITY, *args], cwd=root, capture_output=True, text=True, timeout=60, check=False
    )
    if check and proc.returncode:
        raise EvalError(f"git {' '.join(args)} failed in fixture: {(proc.stderr or proc.stdout).strip()}")
    return proc


def build_fixture(scenario: dict, root: pathlib.Path) -> None:
    fixture = scenario.get("fixture", {})
    for relative, content in fixture.get("files", {}).items():
        target = fixture_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if fixture.get("git"):
        run_git(root, "init", "-q", "-b", "main")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "fixture baseline", "--allow-empty")
    for step in fixture.get("setup", []):
        if isinstance(step, dict) and "write" in step:
            spec = step["write"]
            target = fixture_path(root, spec["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(spec["content"], encoding="utf-8")
            continue
        if isinstance(step, dict):
            argv, check = step["argv"], step.get("check", True)
        else:
            argv, check = step, True
        if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
            raise EvalError(f"setup step must be an argv list of strings: {argv!r}")
        if argv and argv[0] == "git":
            run_git(root, *argv[1:], check=check)
            continue
        proc = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=120, check=False)
        if check and proc.returncode:
            raise EvalError(f"setup step failed ({' '.join(argv)}): {(proc.stderr or proc.stdout).strip()}")


def build_shadow_commands(root: pathlib.Path, names: list[str]) -> pathlib.Path:
    """Create PATH-shadowing stubs so named commands genuinely cannot succeed.

    A scenario that claims a tool is unavailable must make that true — the provider
    subprocess otherwise inherits the caller's PATH, where e.g. the `agentic`
    launcher normally resolves. Stubs are written for both POSIX (sh script) and
    Windows (.cmd), print an unavailability notice, and exit 127.
    """
    bin_dir = root / ".eval-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        posix_stub = bin_dir / name
        posix_stub.write_text(
            f'#!/bin/sh\necho "{name}: command unavailable in this eval fixture" >&2\nexit 127\n',
            encoding="utf-8",
        )
        posix_stub.chmod(0o755)
        (bin_dir / f"{name}.cmd").write_text(
            f"@echo {name}: command unavailable in this eval fixture 1>&2\r\n@exit /b 127\r\n",
            encoding="utf-8",
        )
    return bin_dir


def inject_claude_skill(skill: str, root: pathlib.Path) -> str:
    """Copy the checkout's generated Claude adapter into the fixture as a project skill.

    Without this, `claude -p` would load whatever version of the skill happens to be
    installed under the user's home — or none — and the evidence could promote source
    it never exercised.
    """
    source = REPO / "providers" / "claude" / "skills" / skill
    if not source.is_dir():
        raise EvalError(
            f"generated Claude skill missing: {source}; run `python3 scripts/toolbelt.py generate`"
        )
    target = root / ".claude" / "skills" / skill
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return str(source)


def run_check(check: dict, root: pathlib.Path, transcript: str) -> tuple[bool, str]:
    kind = check.get("type")
    if kind == "transcript_contains":
        found = re.search(check["pattern"], transcript) is not None
        return found, f"transcript_contains {check['pattern']!r}"
    if kind == "file_exists":
        target = fixture_path(root, check["path"])
        return target.exists(), f"file_exists {check['path']}"
    if kind == "file_absent":
        target = fixture_path(root, check["path"])
        return not target.exists(), f"file_absent {check['path']}"
    if kind == "file_contains":
        target = fixture_path(root, check["path"])
        if not target.is_file():
            return False, f"file_contains {check['path']} (file missing)"
        found = re.search(check["pattern"], target.read_text(encoding="utf-8")) is not None
        return found, f"file_contains {check['path']} ~ {check['pattern']!r}"
    if kind == "command":
        argv = check["argv"]
        proc = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=120, check=False)
        label = f"command {' '.join(argv)}"
        if proc.returncode != check.get("expect_exit", 0):
            return False, f"{label} (exit {proc.returncode})"
        if check.get("expect_empty_output") and proc.stdout.strip():
            return False, f"{label} (expected empty output)"
        expected = check.get("expect_output")
        if expected is not None and proc.stdout.strip() != expected.strip():
            return False, f"{label} (output {proc.stdout.strip()!r} != {expected.strip()!r})"
        return True, label
    if kind == "git_clean":
        proc = run_git(root, "status", "--porcelain", "--untracked-files=all", check=False)
        return proc.returncode == 0 and not proc.stdout.strip(), "git_clean"
    raise EvalError(f"unknown check type: {kind!r}")


def judge_prompt(scenario: dict, transcript: str) -> str:
    return (
        "You are grading one automated skill-eval run. Read the rubric and the agent "
        "transcript, then output a single line: VERDICT: PASS or VERDICT: FAIL, "
        "followed by one sentence of reasoning.\n\n"
        f"Rubric:\n{scenario['judge']['rubric']}\n\nTranscript:\n{transcript}"
    )


def parse_judge_verdict(transcript: str) -> bool | None:
    # First declaration wins: the judge is instructed to lead with its verdict, and
    # a failure explanation may quote "VERDICT: PASS" later in its reasoning — the
    # last-match reading would flip such a failure into a pass.
    match = re.search(r"VERDICT:\s*(PASS|FAIL)", transcript, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).upper() == "PASS"


def load_scenario_file(path: pathlib.Path, skill: str) -> dict:
    try:
        scenario = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalError(f"{path}: malformed scenario JSON: {exc}") from exc
    if scenario.get("schemaVersion") != 1:
        raise EvalError(f"{path}: unsupported schemaVersion {scenario.get('schemaVersion')!r}")
    for required in ("skill", "scenario", "prompt", "checks"):
        if required not in scenario:
            raise EvalError(f"{path}: missing required field {required!r}")
    # Evidence filenames and promotion suggestions derive from these fields, so a
    # copied/renamed file with stale identity must fail loudly, not run as-is.
    if scenario["skill"] != skill:
        raise EvalError(
            f"{path}: declares skill {scenario['skill']!r} but lives under skills/{skill}/evals"
        )
    if scenario["scenario"] != path.stem:
        raise EvalError(
            f"{path}: declares scenario {scenario['scenario']!r} but the file stem is {path.stem!r}"
        )
    return scenario


def load_scenarios(skill: str, only: str | None) -> tuple[list[tuple[pathlib.Path, dict]], int]:
    """Return (selected scenarios, total committed scenario count for the skill)."""
    evals_dir = REPO / "skills" / skill / "evals"
    if not evals_dir.is_dir():
        raise EvalError(f"no evals directory for skill {skill!r} ({evals_dir})")
    all_paths = sorted(evals_dir.glob("*.json"))
    out: list[tuple[pathlib.Path, dict]] = []
    for path in all_paths:
        if only and path.stem != only:
            continue
        out.append((path, load_scenario_file(path, skill)))
    if not out:
        raise EvalError(f"no matching scenarios for {skill}" + (f"/{only}" if only else ""))
    return out, len(all_paths)


def run_scenario(
    scenario: dict,
    *,
    provider: str,
    timeout: int,
    judge: bool,
    bypass_permissions: bool,
    fake_script: pathlib.Path | None = None,
    results_dir: pathlib.Path = RESULTS_DIR,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="agentic-eval-") as raw:
        root = pathlib.Path(raw)
        injected_skill_source = None
        if provider == "claude":
            # Before the baseline commit, so git_clean checks stay valid. The codex
            # and pi adapters must do the equivalent when they are implemented.
            injected_skill_source = inject_claude_skill(scenario["skill"], root)
        shadow_names = scenario.get("fixture", {}).get("shadow_commands", [])
        path_prepend = build_shadow_commands(root, shadow_names) if shadow_names else None
        build_fixture(scenario, root)
        result = run_provider(
            provider,
            scenario["prompt"],
            root,
            timeout=timeout,
            bypass_permissions=bypass_permissions,
            fake_script=fake_script,
            path_prepend=path_prepend,
        )
        checks = []
        for check in scenario["checks"]:
            passed, label = run_check(check, root, result.transcript)
            checks.append({"check": label, "passed": passed})
        judge_record = None
        if judge and scenario.get("judge", {}).get("rubric"):
            judge_result = run_provider(
                provider,
                judge_prompt(scenario, result.transcript),
                root,
                timeout=timeout,
                bypass_permissions=False,
                fake_script=fake_script,
            )
            judge_record = {
                "verdict": parse_judge_verdict(judge_result.transcript),
                "exit_code": judge_result.exit_code,
                "transcript": judge_result.transcript[-4000:],
            }
    # A crashed provider must never produce PASS evidence, even when the checks
    # happen to be satisfied by baseline state; same for a crashed judge.
    all_passed = (
        result.exit_code == 0
        and all(entry["passed"] for entry in checks)
        and (judge_record is None or (judge_record["verdict"] is True and judge_record["exit_code"] == 0))
    )
    evidence = {
        "schemaVersion": 1,
        "skill": scenario["skill"],
        "scenario": scenario["scenario"],
        "provider": provider,
        "injected_skill_source": injected_skill_source,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider_exit_code": result.exit_code,
        "checks": checks,
        "judge": judge_record,
        "passed": all_passed,
        "transcript_tail": result.transcript[-4000:],
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    # Never overwrite prior evidence: a record may already be cited in tests.md,
    # and reruns (other provider, judge mode, outcome) each deserve their own file.
    base_name = f"{date}-{scenario['skill']}-{scenario['scenario']}-{provider}"
    evidence_path = results_dir / f"{base_name}.json"
    suffix = 2
    while evidence_path.exists():
        evidence_path = results_dir / f"{base_name}-{suffix}.json"
        suffix += 1
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def print_summary(records: list[dict], provider: str, total_scenarios: int) -> None:
    for record in records:
        verdict = "PASS" if record["passed"] else "FAIL"
        print(f"{record['skill']}/{record['scenario']}: {verdict}")
        for entry in record["checks"]:
            print(f"  - [{'x' if entry['passed'] else ' '}] {entry['check']}")
        if record["judge"] is not None:
            print(f"  - judge verdict: {record['judge']['verdict']}")
        print(f"  evidence: {record['evidence_path']}")
    if provider == "fake" or not records or not all(record["passed"] for record in records):
        return
    skill = records[0]["skill"]
    if len(records) < total_scenarios:
        # Promoting a skill to live-verified from a subset would contradict the
        # maturity contract (mixed exercised/design-only scenarios = partially-live).
        print(
            f"\nSelected scenarios green, but only {len(records)} of {total_scenarios} "
            f"committed scenarios ran — partial coverage, no promotion suggestion. "
            f"Run `agentic eval {skill}` without a scenario filter for full coverage."
        )
        return
    date = datetime.date.today().isoformat()
    lines = [
        "",
        "All scenarios green. Suggested promotion (manual — the runner never edits "
        "toolbelt.json):",
        f'  - toolbelt.json skillMaturity."{skill}": consider "live-verified"',
        f"  - skills/{skill}/tests.md evidence lines (one per scenario):",
    ]
    for record in records:
        lines.append(
            f'      "Scenario {record["scenario"]!r} live-verified via eval '
            f'{pathlib.Path(record["evidence_path"]).name} on {date}."'
        )
    print("\n".join(lines))


def selftest() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agentic-eval-selftest-") as raw:
        base = pathlib.Path(raw)
        script = base / "fake_agent.py"
        script.write_text(
            "import pathlib\n"
            "pathlib.Path('artifact.txt').write_text('made by fake agent\\n', encoding='utf-8')\n"
            "print('VERDICT: PASS — rubric satisfied')\n",
            encoding="utf-8",
        )
        scenario = {
            "schemaVersion": 1,
            "skill": "selftest-skill",
            "scenario": "framework-roundtrip",
            "fixture": {
                "files": {"seed.txt": "seed\n"},
                "git": True,
                "setup": [{"write": {"path": "extra.txt", "content": "extra\n"}}],
            },
            "prompt": "create artifact.txt",
            "checks": [
                {"type": "file_exists", "path": "artifact.txt"},
                {"type": "file_contains", "path": "artifact.txt", "pattern": "fake agent"},
                {"type": "file_exists", "path": "extra.txt"},
                {"type": "transcript_contains", "pattern": "VERDICT"},
                {"type": "command", "argv": ["git", "log", "--oneline"], "expect_exit": 0},
            ],
            "judge": {"enabled": True, "rubric": "artifact.txt exists"},
        }
        record = run_scenario(
            scenario,
            provider="fake",
            timeout=60,
            judge=True,
            bypass_permissions=False,
            fake_script=script,
            results_dir=base / "results",
        )
        if not record["passed"]:
            failures.append(f"green scenario did not pass: {record['checks']!r}")
        if record["judge"] is None or record["judge"]["verdict"] is not True:
            failures.append(f"judge verdict not parsed as PASS: {record['judge']!r}")
        evidence_file = pathlib.Path(record["evidence_path"])
        if not evidence_file.is_file():
            failures.append("evidence record was not written")
        else:
            stored = json.loads(evidence_file.read_text(encoding="utf-8"))
            if stored["skill"] != "selftest-skill" or stored["passed"] is not True:
                failures.append(f"evidence record content wrong: {stored!r}")

        rerun = run_scenario(
            scenario,
            provider="fake",
            timeout=60,
            judge=False,
            bypass_permissions=False,
            fake_script=script,
            results_dir=base / "results",
        )
        if rerun["evidence_path"] == record["evidence_path"]:
            failures.append("rerun overwrote the prior evidence record")
        elif not rerun["evidence_path"].endswith("-2.json"):
            failures.append(f"rerun did not use a collision suffix: {rerun['evidence_path']}")

        failing = dict(scenario)
        failing["scenario"] = "framework-negative"
        failing["checks"] = [{"type": "file_exists", "path": "never-created.txt"}]
        record = run_scenario(
            failing,
            provider="fake",
            timeout=60,
            judge=False,
            bypass_permissions=False,
            fake_script=script,
            results_dir=base / "results",
        )
        if record["passed"]:
            failures.append("failing check was reported as passed")

        hanging_script = base / "hanging_agent.py"
        hanging_script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        hung = dict(scenario)
        hung["scenario"] = "framework-timeout"
        hung["checks"] = [{"type": "file_exists", "path": "seed.txt"}]  # satisfied by baseline
        record = run_scenario(
            hung,
            provider="fake",
            timeout=1,
            judge=False,
            bypass_permissions=False,
            fake_script=hanging_script,
            results_dir=base / "results",
        )
        if record["passed"] or "timed out" not in record["transcript_tail"]:
            failures.append(
                f"provider timeout did not record failed evidence: passed={record['passed']!r}"
            )

        crashing_script = base / "crashing_agent.py"
        crashing_script.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        crashed = dict(scenario)
        crashed["scenario"] = "framework-crash"
        crashed["checks"] = [{"type": "file_exists", "path": "seed.txt"}]  # satisfied by baseline
        record = run_scenario(
            crashed,
            provider="fake",
            timeout=60,
            judge=False,
            bypass_permissions=False,
            fake_script=crashing_script,
            results_dir=base / "results",
        )
        if record["passed"] or record["provider_exit_code"] != 7:
            failures.append(
                f"nonzero provider exit did not fail the verdict: {record['passed']!r}, "
                f"exit {record['provider_exit_code']!r}"
            )

        transcript_neg = dict(scenario)
        transcript_neg["scenario"] = "framework-transcript-negative"
        transcript_neg["checks"] = [{"type": "transcript_contains", "pattern": "never-printed-token"}]
        record = run_scenario(
            transcript_neg,
            provider="fake",
            timeout=60,
            judge=False,
            bypass_permissions=False,
            fake_script=script,
            results_dir=base / "results",
        )
        if record["passed"]:
            failures.append("transcript_contains matched text the provider never printed")

        bad_json = base / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        try:
            load_scenario_file(bad_json, "bad")
        except EvalError:
            pass
        else:
            failures.append("malformed scenario JSON did not raise EvalError")
        foreign = base / "expected.json"
        foreign.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skill": "foreign",
                    "scenario": "different",
                    "prompt": "p",
                    "checks": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            load_scenario_file(foreign, "requested")
        except EvalError:
            pass
        else:
            failures.append("mismatched scenario identity did not raise EvalError")

        probe_script = base / "probe_agent.py"
        probe_script.write_text(
            "import shutil, sys\nsys.exit(0 if shutil.which('agentic-eval-probe') else 3)\n",
            encoding="utf-8",
        )
        shadowed = dict(scenario)
        shadowed["scenario"] = "framework-shadow"
        shadowed["fixture"] = {"files": {}, "shadow_commands": ["agentic-eval-probe"]}
        shadowed["checks"] = []
        record = run_scenario(
            shadowed,
            provider="fake",
            timeout=60,
            judge=False,
            bypass_permissions=False,
            fake_script=probe_script,
            results_dir=base / "results",
        )
        if not record["passed"]:
            failures.append("shadow command stub was not resolvable on the provider PATH")

        injected = inject_claude_skill("spec", base / "inject-fixture")
        if not (base / "inject-fixture" / ".claude" / "skills" / "spec" / "SKILL.md").is_file():
            failures.append("claude skill injection did not copy the generated adapter")
        if "providers" not in injected:
            failures.append(f"injection source is not the generated adapter: {injected}")

        try:
            fixture_path(base, "../escape.txt")
        except EvalError:
            pass
        else:
            failures.append("fixture path traversal was not rejected")
        if parse_judge_verdict("nothing here") is not None:
            failures.append("missing judge verdict did not parse as None")
        if parse_judge_verdict("VERDICT: FAIL because x") is not False:
            failures.append("judge FAIL verdict misparsed")
        quoted = 'VERDICT: FAIL — the agent merely printed "VERDICT: PASS" without doing the work'
        if parse_judge_verdict(quoted) is not False:
            failures.append("a quoted later PASS overrode the judge's leading FAIL verdict")

    # Repo scenarios must satisfy the schema even though CI never drives a live
    # provider: validate every committed evals/*.json loads.
    for evals_dir in sorted((REPO / "skills").glob("*/evals")):
        skill = evals_dir.parent.name
        try:
            load_scenarios(skill, None)
        except EvalError as exc:
            failures.append(f"committed scenarios invalid for {skill}: {exc}")

    if failures:
        print("eval selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("eval selftest: OK (fixture, checks, judge parsing, and evidence records pinned)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skill", nargs="?", help="skill name under skills/")
    parser.add_argument("scenario", nargs="?", help="optional scenario name (file stem)")
    parser.add_argument("--provider", default="claude", help="claude | codex | pi | fake")
    parser.add_argument("--judge", action="store_true", help="run the LLM-judge pass where a rubric exists")
    parser.add_argument("--timeout", type=int, default=600, help="per-provider-run timeout in seconds")
    parser.add_argument(
        "--bypass-permissions",
        action="store_true",
        help="run the provider with permission checks bypassed (explicit unsafe choice; "
        "needed for scenarios whose skill must run shell commands — the fixture is a "
        "throwaway temp directory)",
    )
    parser.add_argument("--selftest", action="store_true", help="run embedded framework tests and exit")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.skill:
        parser.error("skill is required unless --selftest is given")
    try:
        scenarios, total_scenarios = load_scenarios(args.skill, args.scenario)
        records = [
            run_scenario(
                scenario,
                provider=args.provider,
                timeout=args.timeout,
                judge=args.judge,
                bypass_permissions=args.bypass_permissions,
            )
            for _, scenario in scenarios
        ]
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print_summary(records, args.provider, total_scenarios)
    return 0 if all(record["passed"] for record in records) else 1


if __name__ == "__main__":
    sys.exit(main())
