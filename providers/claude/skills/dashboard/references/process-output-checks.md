# Process and Output Checks

## Start checks

`dashboard.py` atomically acquires a separate watcher lock, performs its first render,
then writes `scripts/dashboard/dashboard.pid`. A target repo with several worktrees can
take longer than a few seconds even though PR/CI state is fetched once with a single
bounded `gh pr list` call, so `dashboard start` polls for the pidfile for up to roughly
30 seconds before treating startup as missing.

When the pidfile appears, confirm the path itself is a regular file, not a symlink:
`[ -L path ]` must be false. A pre-existing pidfile symlink could point at a file that
happens to contain some unrelated live process's PID; a bare `ps -p <pid>` would then
pass even though `run_watch` refused to start on that symlink and never touched it.

Next, confirm the PID names the actual dashboard watcher with the same `ps` command
used by `stop`: `ps -p <pid> -o command=`. Require the real
`scripts/dashboard/dashboard.py` path plus `--watch` as its own token, and reject any
`-c` flag.

If the pidfile still has not appeared after the polling window, check whether the
background process launched by `nohup`/`Start-Process` is still alive. If it is gone,
the first render failed outright, such as from a broken `repo_path`, and there is
nothing left to wait for.

## HTML output symlinks

Check the HTML output separately from the pidfile/process. A symlinked `output_path` is
non-fatal by design in `dashboard.py`'s `write_dashboard`: `--watch` keeps running with
a valid pidfile while every render fails. Since `dashboard start` redirects stderr to
`/dev/null`, a pidfile-and-PID check alone can report success for a watcher that will
never produce a dashboard.

An ordinary existence or mtime check (`[ -e path ]`, `stat`) follows symlinks and can
pass by inspecting the symlink target. Confirm the configured HTML path
(`scripts/dashboard/dashboard.html` by default) is itself a regular file and not a
symlink, for example:

```sh
test -f path -a ! -L path
```

Only then check that it has a recent mtime. If the pidfile/process check passed but
this one fails, report that the watcher is running but not producing output, and name
the HTML path so the user can inspect it for a pre-existing symlink.

## `ps` command parsing

A bare substring check for `dashboard.py` and `--watch` is not enough. A command such
as this can pass those strings as extra positional arguments to an inline script that
has nothing to do with the real watcher:

```sh
python3 -c '...' dashboard.py --watch
```

Require the command line to include `scripts/dashboard/dashboard.py` as the real
relative script path and `--watch` as its own token. Also reject any command containing
`-c`: a real `python3 scripts/dashboard/dashboard.py --watch` invocation never has it,
and it is the signature of the inline-script trick.

This narrows but does not eliminate every possible adversarial construction. A
`ps`-based text check cannot fully distinguish "the script being executed" from "an
argument that merely looks like it" without deeper process inspection. The residual
risk is bounded to a local, single-user, self-inflicted `SIGTERM`, not privilege
escalation.
