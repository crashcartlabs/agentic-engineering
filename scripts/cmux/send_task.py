#!/usr/bin/env python3
"""Send a task to a cmux pane without the multi-line corruption bug.

cmux delivers `cmux send` text by typing it into the pane's shell as
keystrokes, not by exec'ing it as a process argument -- a literal newline in
the text is sent as a real Enter press, submitting a partial command before
any quoting closes. See skills/cmux/references/agent-launch-flags.md
for the full story (confirmed live across a real 4-agent fleet: one pane
hung forever in an open quote, two others launched with garbled prompts).

This is the safe replacement for typing a task straight into `cmux send`
during manual/ad-hoc driving: a multi-line task gets written to TASK.md in a
target directory and the pane receives a short one-line pointer instead; a
single-line task is sent unchanged. Optionally wraps the result in a fresh
agent launch line (matching spawn_fleet.py's own YOLO_LAUNCH table), for
starting a new agent rather than messaging one that's already running.

Usage:
  send_task.py --workspace <id> --surface <id> --dir <path> --text-file <path>
  send_task.py --workspace <id> --surface <id> --dir <path> --text "<task>"
  send_task.py --workspace <id> --surface <id> --dir <path> --text-file <path> \
    --launch claude --model opus
  send_task.py --selftest
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import AGENTS, agent_launch_line, write_text_exclusive

CMUX_BIN_CANDIDATES = ["cmux", "/Applications/cmux.app/Contents/Resources/bin/cmux"]
TASK_FILE_NAME = "TASK.md"
TASK_POINTER_PROMPT = "Read TASK.md in the current directory and do exactly what it says."

def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def find_cmux_bin() -> str:
    for candidate in CMUX_BIN_CANDIDATES:
        if "/" in candidate:
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    die("cmux CLI not found on PATH or at /Applications/cmux.app/Contents/Resources/bin/cmux")
    raise AssertionError("unreachable")  # die() exits; this satisfies type checkers


def cmux(bin_path: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CMUX_QUIET": "1"}
    return subprocess.run([bin_path, *args], capture_output=True, text=True, env=env)


def ensure_dir(target_dir: Path) -> None:
    if target_dir.exists() and not target_dir.is_dir():
        die(f"--dir exists and is not a directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)


def exclude_from_worktree_git(dir_path: Path, entry: str) -> None:
    """Add `entry` to dir_path's git info/exclude, so an untracked file (e.g.
    TASK.md) written into it doesn't show up in `git status`/`git add .` --
    without this, a launched agent using a broad staging command can
    accidentally commit the orchestration prompt into its own result
    (confirmed live). A worktree's `.git` is a file pointing at the real
    git-dir, not a directory, so `git rev-parse --git-path` is used to find
    the real info/exclude location instead of assuming `<dir>/.git/info/exclude`.
    Skips gracefully if dir_path isn't inside a git repo at all.
    The written pattern is anchored with a leading '/' -- gitignore/exclude
    semantics treat a slash-free pattern as matching that basename in every
    directory of the tree, not just the root where TASK.md is always
    written, so a bare pattern would also hide an unrelated same-named file
    nested elsewhere in the repo (confirmed live).
    Kept in sync with scripts/cmux/spawn_fleet.py's copy of this helper."""
    proc = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "--git-path", "info/exclude"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return
    exclude_path = Path(proc.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = dir_path / exclude_path
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    anchored_entry = entry if entry.startswith("/") else f"/{entry}"
    existing = exclude_path.read_text() if exclude_path.exists() else ""
    if anchored_entry not in existing.splitlines():
        with exclude_path.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(anchored_entry + "\n")
    warn_if_exclude_ineffective(dir_path, entry)


def entry_visible_in_git_status(dir_path: Path, entry: str) -> bool:
    """True if `entry` still shows up in `git status --porcelain` for
    dir_path -- meaning some higher-priority ignore source (a repo's own
    tracked .gitignore takes precedence over info/exclude) is overriding the
    info/exclude entry we just added."""
    proc = subprocess.run(
        ["git", "-C", str(dir_path), "status", "--porcelain", "--", entry],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def warn_if_exclude_ineffective(dir_path: Path, entry: str) -> None:
    """info/exclude is git's lowest-priority ignore source: a repo's own
    tracked .gitignore (e.g. a `!entry` negation, or a broad `!*` after a
    `*`) can still override it, leaving `entry` trackable/untracked despite
    the exclude entry just added -- silently defeating the whole point of
    excluding it. This is a soft convenience layer, not a correctness-critical
    guard (unlike the overwrite-refusal in resolve_task_text), so warn rather
    than die() -- aborting an otherwise-successful task launch over it would
    be the wrong tradeoff."""
    if entry_visible_in_git_status(dir_path, entry):
        print(
            f"warning: {entry} in {dir_path} is still visible to `git status` despite the "
            f"info/exclude entry just added -- a tracked .gitignore pattern in that repo may "
            f"be overriding it; {entry} could end up committed by an agent running a broad "
            "`git add`",
            file=sys.stderr,
        )


def resolve_task_text(text: str, target_dir: Path) -> str:
    if "\n" not in text:
        return text
    ensure_dir(target_dir)
    task_path = target_dir / TASK_FILE_NAME
    try:
        write_text_exclusive(task_path, text)
    except FileExistsError:
        die(f"{task_path} already exists (including a symlink); refusing to overwrite -- pass a different --dir")
    exclude_from_worktree_git(target_dir, TASK_FILE_NAME)
    return TASK_POINTER_PROMPT


def build_send_text(
    text: str,
    target_dir: Path,
    launch: str | None,
    model: str | None,
    *,
    unsafe_yolo: bool = False,
) -> str:
    if launch is not None:
        if launch not in AGENTS:
            die(f"unknown --launch agent {launch!r}; must be one of {sorted(AGENTS)}")
        if not model:
            die("--model is required with --launch")
        ensure_dir(target_dir)
    resolved = resolve_task_text(text, target_dir)
    if launch is None:
        if "\n" in text:
            # Messaging an already-running pane: no `cd` happens in this mode,
            # so nothing enforces that the pane's shell cwd matches --dir. A
            # bare "current directory" pointer silently fails if it doesn't;
            # an absolute path removes the dependency on that match.
            task_path = (target_dir / TASK_FILE_NAME).resolve()
            return f"Read {task_path} and do exactly what it says."
        return resolved
    return agent_launch_line(
        launch, model, resolved, cwd=target_dir.resolve(), unsafe_yolo=unsafe_yolo
    )


def validate_text_source(text: str | None, text_file: Path | None) -> None:
    if (text is None) == (text_file is None):
        die("exactly one of --text or --text-file is required")


def load_text_file(path: Path) -> str:
    try:
        raw = path.read_text()
    except OSError as e:
        die(f"could not read --text-file {path}: {e}")
        raise AssertionError("unreachable")  # die() exits; this satisfies type checkers
    return raw.rstrip("\n")


def send_task(bin_path: str, workspace: str, surface: str, send_text: str, submit: bool) -> None:
    proc = cmux(bin_path, "send", "--workspace", workspace, "--surface", surface, send_text)
    if proc.returncode != 0:
        die(f"cmux send failed: {proc.stderr.strip()}")
    if submit:
        proc = cmux(bin_path, "send-key", "--workspace", workspace, "--surface", surface, "enter")
        if proc.returncode != 0:
            die(f"cmux send-key failed: {proc.stderr.strip()}")


def selftest() -> int:
    ok = True
    root = Path(tempfile.mkdtemp(prefix="send-task-selftest-"))

    def check(cond: bool, label: str, *detail: object) -> None:
        nonlocal ok
        if not cond:
            print(f"selftest: {label} FAIL", *detail)
            ok = False

    try:
        d = root / "single-line"
        check(resolve_task_text("one line", d) == "one line", "single-line")
        check(not (d / TASK_FILE_NAME).exists(), "single-line wrote TASK.md")

        d = root / "multi-line"
        multi = "line one\nline two"
        resolved = resolve_task_text(multi, d)
        check(resolved == TASK_POINTER_PROMPT, "multi-line pointer", resolved)
        written = d / TASK_FILE_NAME
        check(written.exists() and written.read_text() == multi, "multi-line TASK.md contents")

        d = root / "no-launch"
        plain = build_send_text("one line", d, None, None)
        check(plain == "one line", "build_send_text no-launch", plain)

        # Finding 1: messaging an already-running pane (no --launch) with
        # multi-line text must point at TASK.md's absolute path, not a bare
        # "current directory" phrase -- nothing `cd`s the pane into --dir in
        # this mode, so the pane's actual cwd may not match it.
        d = root / "no-launch-multiline"
        no_launch_multi = build_send_text("line one\nline two", d, None, None)
        expected_path = str((d / TASK_FILE_NAME).resolve())
        check(
            expected_path in no_launch_multi and "current directory" not in no_launch_multi,
            "build_send_text no-launch multi-line must use absolute TASK.md path (Finding 1)",
            no_launch_multi,
        )

        d = root / "launch"
        launched = build_send_text("line one\nline two", d, "claude", "opus")
        check(
            launched.startswith(f"cd {shlex.quote(str(d.resolve()))} && claude --model opus")
            and "dangerously" not in launched,
            "build_send_text safe launch",
            launched,
        )
        unsafe_launched = build_send_text(
            "one line", d, "claude", "opus", unsafe_yolo=True
        )
        check(
            "claude --dangerously-skip-permissions --model opus" in unsafe_launched,
            "build_send_text unsafe launch requires flag",
            unsafe_launched,
        )
        check(TASK_POINTER_PROMPT in launched, "build_send_text launch pointer", launched)

        # Finding 1: --launch with a relative --dir must resolve it to an
        # absolute path before building the `cd` command -- the launch text
        # is typed into whatever cwd the cmux pane currently has, not this
        # script's own cwd, so a relative path there resolves against the
        # wrong base.
        cwd = os.getcwd()
        os.chdir(root)
        try:
            relative_launched = build_send_text("one line", Path("relative-launch-dir"), "claude", "opus")
        finally:
            os.chdir(cwd)
        expected_cd_target = str((root / "relative-launch-dir").resolve())
        check(
            relative_launched.startswith(f"cd {shlex.quote(expected_cd_target)} &&"),
            "build_send_text launch with relative --dir must use an absolute cd target (Finding 1)",
            relative_launched,
        )

        d = root / "unknown-agent"
        try:
            build_send_text("task", d, "nonexistent-agent", "m")
            check(False, "build_send_text unknown agent should have died")
        except SystemExit:
            pass

        # Finding D: --model validation must happen before any TASK.md write, so a
        # failed launch never has the side effect of writing/overwriting the file.
        d = root / "missing-model"
        try:
            build_send_text("line one\nline two", d, "claude", None)
            check(False, "build_send_text missing model should have died")
        except SystemExit:
            pass
        check(not (d / TASK_FILE_NAME).exists(), "missing-model must not write TASK.md before validation (Finding D)")

        # Finding B: --launch must create the target dir even when the text is
        # single-line, so the launch line's leading `cd <dir> &&` doesn't no-op.
        d = root / "launch-mkdir"
        build_send_text("one line", d, "claude", "opus")
        check(d.is_dir(), "build_send_text launch must create target dir (Finding B)")

        # Finding E: --dir pointing at an existing regular file must die() cleanly.
        d = root / "dir-is-file"
        d.write_text("not a directory")
        try:
            resolve_task_text("line one\nline two", d)
            check(False, "resolve_task_text on file-as-dir should have died (Finding E)")
        except SystemExit:
            pass
        except Exception as e:
            check(False, "resolve_task_text on file-as-dir raised instead of die() (Finding E)", repr(e))

        # Additional: must never silently overwrite a pre-existing TASK.md.
        d = root / "preexisting-task"
        d.mkdir(parents=True)
        (d / TASK_FILE_NAME).write_text("ORIGINAL CONTENT")
        try:
            resolve_task_text("line one\nline two", d)
            check(False, "resolve_task_text should refuse to overwrite existing TASK.md")
        except SystemExit:
            pass
        check((d / TASK_FILE_NAME).read_text() == "ORIGINAL CONTENT", "existing TASK.md must be untouched")

        # A dangling symlink returns false from Path.exists(); O_EXCL/O_NOFOLLOW must
        # still refuse it and leave the symlink target untouched.
        if hasattr(os, "symlink"):
            d = root / "dangling-task"
            d.mkdir(parents=True)
            outside = root / "outside-task"
            (d / TASK_FILE_NAME).symlink_to(outside)
            try:
                resolve_task_text("line one\nline two", d)
                check(False, "resolve_task_text should refuse dangling TASK.md symlink")
            except SystemExit:
                pass
            check(not outside.exists(), "dangling TASK.md symlink target must remain untouched")

        # Finding A: file-sourced text with a trailing newline (as any normally
        # saved single-line file has) must not be misclassified as multi-line.
        f = root / "single-line.txt"
        f.write_text("fix the typo in README\n")
        loaded = load_text_file(f)
        check(loaded == "fix the typo in README", "load_text_file must strip trailing newline (Finding A)", repr(loaded))
        check("\n" not in loaded, "single-line file text must not contain a newline after loading (Finding A)")

        # Interior newlines of a genuinely multi-line file must survive stripping.
        f = root / "multi-line.txt"
        f.write_text("line one\nline two\n")
        loaded = load_text_file(f)
        check(loaded == "line one\nline two", "load_text_file must preserve interior newlines", repr(loaded))

        # Finding F: a missing --text-file must die() cleanly, not raise.
        try:
            load_text_file(root / "does-not-exist.txt")
            check(False, "load_text_file on missing file should have died (Finding F)")
        except SystemExit:
            pass
        except Exception as e:
            check(False, "load_text_file on missing file raised instead of die() (Finding F)", repr(e))

        # Finding 2: writing TASK.md into a directory inside a git repo must
        # exclude it via that repo's git info/exclude, so it doesn't show up
        # in `git status`/`git add .` there.
        d = root / "git-repo"
        d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True)
        resolve_task_text("line one\nline two", d)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=d, capture_output=True, text=True, check=True).stdout
        check(TASK_FILE_NAME not in status, "resolve_task_text must exclude TASK.md from git status (Finding 2)", repr(status))
        exclude_file = d / ".git" / "info" / "exclude"
        check(
            exclude_file.exists() and f"/{TASK_FILE_NAME}" in exclude_file.read_text().splitlines(),
            "resolve_task_text must add an anchored '/TASK.md' to git info/exclude (Finding 3)",
        )

        # Finding 3: the exclude pattern must be anchored to the target dir's
        # root -- a bare `TASK.md` pattern would also hide an unrelated
        # nested `sub/TASK.md`, which is a real correctness gap for anyone
        # relying on `git status` to see all their real changes.
        (d / "sub").mkdir(parents=True, exist_ok=True)
        (d / "sub" / TASK_FILE_NAME).write_text("unrelated nested file\n")
        status_all = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=d, capture_output=True, text=True, check=True,
        ).stdout
        check("sub/TASK.md" in status_all, "anchored exclude pattern must not hide sub/TASK.md (Finding 3)", repr(status_all))
        check(
            "TASK.md" not in status_all.replace("sub/TASK.md", ""),
            "root TASK.md must remain excluded from git status (Finding 3)",
            repr(status_all),
        )

        # Finding 2, negation-override case: a repo whose tracked .gitignore
        # has a `!TASK.md`-style negation takes precedence over info/exclude
        # (info/exclude is git's lowest-priority ignore source), so TASK.md
        # stays visible to `git status` despite the exclude entry -- the
        # verification step must detect this and warn, not silently proceed.
        d = root / "git-repo-negated-gitignore"
        d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True)
        (d / ".gitignore").write_text("*\n!TASK.md\n")
        subprocess.run(["git", "add", "-f", ".gitignore"], cwd=d, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True)
        resolve_task_text("line one\nline two", d)
        check(
            entry_visible_in_git_status(d, TASK_FILE_NAME),
            "entry_visible_in_git_status must detect a .gitignore negation overriding info/exclude (Finding 2)",
        )

        # Finding 2, graceful-skip case: a --dir with no enclosing git repo at
        # all must not raise.
        d = root / "not-a-repo"
        try:
            resolved = resolve_task_text("line one\nline two", d)
            check(resolved == TASK_POINTER_PROMPT, "resolve_task_text outside a git repo (Finding 2)", resolved)
        except SystemExit:
            check(False, "resolve_task_text outside a git repo must not die (Finding 2)")

        # Finding C: the --text/--text-file guard must compare presence, not
        # truthiness, so an explicitly empty --text "" is not treated as absent.
        try:
            validate_text_source("", None)
        except SystemExit:
            check(False, "validate_text_source('', None) should not die (Finding C)")
        try:
            validate_text_source(None, None)
            check(False, "validate_text_source(None, None) should have died (Finding C)")
        except SystemExit:
            pass
        try:
            validate_text_source("x", Path("f"))
            check(False, "validate_text_source with both set should have died (Finding C)")
        except SystemExit:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("send_task selftest: OK" if ok else "send_task selftest: FAIL")
    return 0 if ok else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true", help="run embedded fixture checks and exit")
    parser.add_argument("--workspace", help="target workspace id/ref")
    parser.add_argument("--surface", help="target surface id/ref")
    parser.add_argument("--dir", type=Path, help="directory to write TASK.md into if the task is multi-line (and to cd into, with --launch)")
    parser.add_argument("--text", help="task text; prefer --text-file for anything beyond a short one-liner")
    parser.add_argument("--text-file", type=Path, help="read task text from this file instead of --text")
    parser.add_argument("--launch", choices=sorted(AGENTS), default=None, help="start a fresh agent instead of messaging an already-running one")
    parser.add_argument("--model", help="required with --launch")
    parser.add_argument(
        "--unsafe-yolo",
        action="store_true",
        help="explicitly disable Claude/Codex safeguards for a fresh launch",
    )
    parser.add_argument("--no-submit", action="store_true", help="send the text but don't press enter")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.workspace or not args.surface or not args.dir:
        die("--workspace, --surface, and --dir are required")
    validate_text_source(args.text, args.text_file)
    text = args.text if args.text is not None else load_text_file(args.text_file)

    bin_path = find_cmux_bin()
    send_text = build_send_text(
        text, args.dir, args.launch, args.model, unsafe_yolo=args.unsafe_yolo
    )
    send_task(bin_path, args.workspace, args.surface, send_text, submit=not args.no_submit)
    wrote_task_file = "\n" in text
    print("sent" + (" (TASK.md written)" if wrote_task_file else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
