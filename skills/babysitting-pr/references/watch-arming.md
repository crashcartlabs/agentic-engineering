# Watch Arming Recipes

## Durable label

Resolve `<owner>/<repo>` from the PR argument before touching labels. Check for the
exact label in that repo:

```sh
gh label list -R <owner>/<repo> --search babysitting-active --json name --jq 'any(.[]; .name == "babysitting-active")'
```

Use `--search` because `gh label list` defaults to a 30-item page, which can miss an
existing label in a label-heavy repo and make a later create fail. The search matches
label names and description substrings, so the exact-name `--jq` filter is the real
existence test; a different label that merely mentions `babysitting-active` must not
count. Create only when that filter returns false:

```sh
gh label create -R <owner>/<repo> babysitting-active --description "A babysitting-pr watch is active on this PR" --color 0e8a16
```

Then add it to the watched PR:

```sh
gh pr edit <url> --add-label babysitting-active
```

Keep every repo-level label call scoped with `-R <owner>/<repo>` because `gh` otherwise
defaults to the repo resolved from the invoking shell's cwd, which may not be the
watched repo. The label is durable state: a dashboard or human scanning the PR list can
see that the PR is being watched after this session ends.

## Watch fallback

Map each missing capability independently — a harness may expose one native tool
but not the other:

- without `subscribe_pr_activity`: a persistent poll-stream over PR state using the
  harness's watch/monitor primitive (Claude Code: `Monitor`), emitting deltas for CI,
  submitted reviews, inline comments, conversation-level comments, mergeable
  transitions, and the merged/closed terminal states, at roughly a 60-second interval;
- without `send_later`: an hourly check-in on an off-minute using the harness's
  scheduled-wake primitive (Claude Code: `CronCreate`).

Never duplicate a native capability with its fallback. Tear down whatever fallbacks
you created at wind-down.

Seed the monitor's first previous-state value from the arm-time snapshot. Do not let
the first poll self-baseline: anything that lands between the arm read and the first
poll would otherwise be absorbed as "already seen" and never wake the watcher (caught
live when a review landed seconds after arming and only a human noticed). The watch is
armed only once the monitor is diffing against the arm-time state.

## Pagination and baselines

Read comment and review counts with `--paginate` and aggregate across pages. An
unpaginated `gh api` call pins at the 30-item default; paginated pages remain separate
JSON arrays, so a bare `--jq length` emits one number per page. Sum those page lengths:

```sh
gh api --paginate ... --jq length | paste -sd+ - | bc
```

Alternatively, slurp and flatten first:

```sh
gh api --paginate ... --slurp --jq 'flatten | length'
```

Build the seed by running the same extraction code the loop runs. A hand-written
baseline in a different shape guarantees a false first delta, and a wrong-field parse
can be worse than noisy: one live watch found a status parse that read check names and
would have stayed silent on a real CI failure.
