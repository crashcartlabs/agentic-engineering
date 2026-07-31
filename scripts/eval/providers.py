"""Provider adapters for the skill eval runner.

Each adapter drives one agent CLI headlessly against a fixture directory and
returns a uniform ProviderResult. The interface is deliberately provider-pluggable
from day one: `claude` is implemented, `codex` and `pi` are explicit stubs that
fail with a clear message rather than guessing at CLI flags, and `fake` executes a
scenario-supplied local script so the framework can be exercised hermetically (CI,
selftests) with no agent CLI and no network.

Pure stdlib, cross-platform.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys


class EvalError(Exception):
    """A configuration or environment problem that should abort the eval run."""


@dataclasses.dataclass(frozen=True)
class ProviderResult:
    exit_code: int
    transcript: str


PROVIDERS = ("claude", "codex", "pi", "fake")


def _provider_env(path_prepend: pathlib.Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if path_prepend is not None:
        env["PATH"] = str(path_prepend) + os.pathsep + env.get("PATH", "")
    return env


def run_provider(
    provider: str,
    prompt: str,
    cwd: pathlib.Path,
    *,
    timeout: int,
    bypass_permissions: bool = False,
    fake_script: pathlib.Path | None = None,
    path_prepend: pathlib.Path | None = None,
) -> ProviderResult:
    if provider == "claude":
        return _run_claude(
            prompt, cwd, timeout=timeout, bypass_permissions=bypass_permissions,
            path_prepend=path_prepend,
        )
    if provider == "fake":
        return _run_fake(
            prompt, cwd, timeout=timeout, fake_script=fake_script, path_prepend=path_prepend
        )
    if provider in ("codex", "pi"):
        raise EvalError(
            f"the {provider} eval adapter is not implemented yet; run with --provider claude "
            "(or --provider fake for framework tests)"
        )
    raise EvalError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")


def _run_claude(
    prompt: str,
    cwd: pathlib.Path,
    *,
    timeout: int,
    bypass_permissions: bool,
    path_prepend: pathlib.Path | None = None,
) -> ProviderResult:
    executable = shutil.which("claude")
    if executable is None:
        raise EvalError(
            "claude CLI not found on PATH — install Claude Code or run with --provider fake"
        )
    # Flags verified against the live CLI: -p/--print runs headless;
    # --permission-mode acceptEdits lets the agent edit fixture files without
    # prompts. Scenarios whose skill must run shell commands (git, test runners)
    # need --bypass-permissions, which maps to --dangerously-skip-permissions —
    # an explicit unsafe choice per the repo safety model, acceptable only
    # because the fixture is a throwaway temp directory.
    command = [executable, "-p", prompt]
    if bypass_permissions:
        command.append("--dangerously-skip-permissions")
    else:
        command.extend(["--permission-mode", "acceptEdits"])
    proc = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_provider_env(path_prepend),
    )
    return ProviderResult(proc.returncode, proc.stdout + ("\n" + proc.stderr if proc.stderr else ""))


def _run_fake(
    prompt: str,
    cwd: pathlib.Path,
    *,
    timeout: int,
    fake_script: pathlib.Path | None,
    path_prepend: pathlib.Path | None = None,
) -> ProviderResult:
    if fake_script is None:
        raise EvalError("the fake provider needs a fake_script path (framework tests only)")
    if not fake_script.is_file():
        raise EvalError(f"fake_script does not exist: {fake_script}")
    proc = subprocess.run(
        [sys.executable, str(fake_script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={
            **_provider_env(path_prepend),
            "AGENTIC_EVAL_PROMPT": prompt,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    return ProviderResult(proc.returncode, proc.stdout + ("\n" + proc.stderr if proc.stderr else ""))
