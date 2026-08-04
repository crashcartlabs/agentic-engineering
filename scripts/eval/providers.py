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


_GIT_ROUTING_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def is_command_scope_git_config(key: str) -> bool:
    """Command-scope Git config exported via env (GIT_CONFIG_COUNT/KEY_n/VALUE_n,
    GIT_CONFIG_PARAMETERS from `git -c`): it overrides even a silenced
    global/system config, so hermetic envs must strip it alongside routing vars.
    GIT_CONFIG_GLOBAL/SYSTEM are deliberately not matched — they are the
    silencing mechanism itself."""
    return key in ("GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS") or key.startswith(
        ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
    )


_GIT_IDENTITY_DATE_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
)


def _provider_env(path_prepend: pathlib.Path | None) -> dict[str, str]:
    # Strip repository-routing variables, command-scope config, and identity/
    # date overrides: the provider's own git commands must act on the fixture,
    # never on a repo the caller's environment points at, never shaped by
    # injected config, and always under the fixture's synthetic identity
    # (persisted in the fixture repo's local config) rather than an inherited
    # personal one.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _GIT_ROUTING_VARS
        and k not in _GIT_IDENTITY_DATE_VARS
        and not is_command_scope_git_config(k)
    }
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


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Best-effort kill of the provider and everything it spawned."""
    if os.name == "nt":
        # /T walks the Windows process tree rooted at the provider.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_process_tree_capped(
    command: list[str], cwd: pathlib.Path, timeout: int, env: dict[str, str]
) -> tuple[int, str, str] | None:
    """Run a provider CLI with the whole spawned tree bound to its lifetime.

    Returns (exit_code, stdout, stderr), or None on timeout. `subprocess.run`
    would kill only the direct child on timeout: a test server or shell child
    the agent started would keep running after the harness records timeout
    evidence — and could keep the stdout pipe open, hanging the cleanup wait
    forever. The provider gets its own process group (POSIX session / Windows
    process group) so the entire tree is terminated with it.
    """
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        env=env,
        **kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            # Reap and drain; bounded, in case something outside the group
            # still holds the pipes.
            proc.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None


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
    try:
        outcome = run_process_tree_capped(command, cwd, timeout, _provider_env(path_prepend))
    except OSError as exc:
        raise EvalError(f"claude CLI could not launch: {exc}") from exc
    if outcome is None:
        # A hung live agent is a failed run, not a broken harness: surface it as
        # nonzero-exit evidence so the scenario records FAIL instead of a traceback.
        return ProviderResult(124, f"provider timed out after {timeout}s")
    returncode, stdout, stderr = outcome
    return ProviderResult(returncode, stdout + ("\n" + stderr if stderr else ""))


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
    try:
        outcome = run_process_tree_capped(
            [sys.executable, str(fake_script)],
            cwd,
            timeout,
            {
                **_provider_env(path_prepend),
                "AGENTIC_EVAL_PROMPT": prompt,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except OSError as exc:
        raise EvalError(f"fake provider script could not launch: {exc}") from exc
    if outcome is None:
        return ProviderResult(124, f"provider timed out after {timeout}s")
    returncode, stdout, stderr = outcome
    return ProviderResult(returncode, stdout + ("\n" + stderr if stderr else ""))
