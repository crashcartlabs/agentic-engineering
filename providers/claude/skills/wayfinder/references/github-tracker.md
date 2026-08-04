# Wayfinding operations on GitHub Issues (`gh` CLI)

How this repo expresses the wayfinder map, child tickets, claiming, blocking, and the
frontier query. All commands run against the current repo; add `-R <owner>/<repo>` when
operating from elsewhere.

## Labels (one-time setup per repo)

```sh
gh label create "wayfinder:map"       --color 5319e7 --description "Wayfinder map issue" 2>/dev/null || true
for t in research prototype grilling task; do
  gh label create "wayfinder:$t" --color c5def5 --description "Wayfinder ticket: $t" 2>/dev/null || true
done
```

## Create the map

```sh
gh issue create --title "<Effort name> — wayfinder map" --label "wayfinder:map" --body-file map.md
```

`map.md` holds the map body (Destination / Notes / Decisions so far / Not yet specified /
Out of scope). Update it later with `gh issue edit <map#> --body-file map.md` — fetch the
current body first (`gh issue view <map#> --json body -q .body`), edit, write back; never
regenerate it from memory, other sessions may have appended.

**Concurrent writers:** fetch-then-write only protects against a *stale* copy — two
sessions can each fetch, edit, and write within the same window, and the second write
silently overwrites the first's line (whole-body replacement, not an append). Immediately
before writing, re-fetch the body and diff it against the copy you edited from; if it
changed, reconcile by re-applying your one line (append or resolution edit) onto the fresh
body instead of writing your stale copy over it:

```sh
BEFORE=$(gh issue view <map#> --json body -q .body)   # fetched at edit time
# ...edit BEFORE into map.md...
NOW=$(gh issue view <map#> --json body -q .body)       # re-fetch just before writing
if [ "$NOW" != "$BEFORE" ]; then
  # someone else wrote in the meantime — reconcile: re-apply your one line to $NOW,
  # not to your edited copy of the stale $BEFORE
  :
fi
gh issue edit <map#> --body-file map.md
```

The re-read above still leaves a final write race. After the edit, fetch the body again
and verify both (a) the intended line is present exactly once and (b) the fresh `NOW`
content you did not intend to change is still present. If either check fails, re-fetch,
re-apply only the intended line, and retry the whole compare/write/verify sequence up to
three times. After three conflicts, stop and surface the competing edit; never declare
the map updated from the command's exit code alone.

## Create a ticket (child issue)

Create, then attach as a sub-issue of the map (GitHub's native parent/child relation):

Write the body to a file first, then reference it with `--body-file` — embedding arbitrary
ticket text inline in a `$'...'`-quoted command breaks the moment the text contains an
apostrophe (e.g. "What's the API shape?" closes the quote early):

```sh
gh issue create --title "<Ticket name>" --label "wayfinder:grilling" --body-file ticket.md
```

`ticket.md` holds `## Question\n\n<the question>`, written with the Write/Edit tool (or
equivalent), not composed inline in the shell command.

Attach as sub-issue (needs the numeric issue database IDs, not the numbers):

```sh
MAP_ID=$(gh api 'repos/{owner}/{repo}/issues/<map#>' --jq .id)
CHILD_ID=$(gh api 'repos/{owner}/{repo}/issues/<ticket#>' --jq .id)
gh api 'repos/{owner}/{repo}/issues/<map#>/sub_issues' -F sub_issue_id=$CHILD_ID
```

(`-F` sends `sub_issue_id` as a number, matching the API's documented integer type; `-f`
would send it as a string and can fail validation.)

If the sub-issues API is unavailable (older GHES), fall back to a task-list in the map
body (`- [ ] #<ticket#>`) — GitHub still renders these as tracked children.

## Blocking edges (second pass, after all tickets have numbers)

GitHub's native issue dependencies ("blocked by" relationships):

```sh
BLOCKER_ID=$(gh api 'repos/{owner}/{repo}/issues/<blocker#>' --jq .id)
gh api 'repos/{owner}/{repo}/issues/<blocked#>/dependencies/blocked_by' -F issue_id=$BLOCKER_ID
```

(`-F` sends `issue_id` as a number, matching the API's documented integer type; `-f` would
send it as a string and can fail validation.)

List what blocks a ticket:

```sh
gh api 'repos/{owner}/{repo}/issues/<ticket#>/dependencies/blocked_by' --jq '.[].number'
```

If the dependencies API is unavailable, fall back to the body convention: a
`Blocked by: #12, #34` line at the top of the ticket body, and check those issues'
states manually.

## Claim a ticket

Assign before any work — the assignee is the claim:

```sh
gh issue edit <ticket#> --add-assignee @me
```

An open, unassigned ticket is unclaimed. Skip anything already assigned.

`--add-assignee` succeeds even if another session claimed the ticket in the same window —
it doesn't fail on an already-assigned issue, so two parallel sessions can both believe they
claimed it. Verify exclusivity immediately after: re-fetch the assignee list and confirm it
contains exactly one login, yourself, before doing any work.

```sh
gh issue view <ticket#> --json assignees --jq '[.assignees[].login]'
```

If that list has more than one assignee, or its sole assignee isn't you, another session won
the race — abort and do not work the ticket; go pick a different frontier ticket instead.

That check alone doesn't distinguish two parallel sessions running under the *same* GitHub
account — both would see themselves as sole assignee and both proceed. Since parallel
sessions are explicitly allowed, add a session-unique claim marker: generate a random token
for this session, post it as a comment on the ticket right after assigning, then re-fetch
the ticket's comments and confirm your claim-marker comment is the *first* claim-marker
comment present (lowest comment ID / earliest timestamp) before doing any work:

```sh
TOKEN=$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')
gh issue comment <ticket#> --body "claim-marker: $TOKEN"
gh issue view <ticket#> --json comments --jq '[.comments[] | select(.body | startswith("claim-marker:"))][0].body'
```

If the first claim-marker comment's token isn't the one you just posted, another session's
claim landed first — abort and do not work the ticket, even though the assignee check
passed.

## Frontier query

Open, unassigned children of the **current map**, minus those with an open blocker. Scope
to the map first — a repo can hold more than one wayfinder map, and a repo-wide label
query would claim or resolve a ticket that belongs to a different map:

```sh
gh api --paginate 'repos/{owner}/{repo}/issues/<map#>/sub_issues' --jq '.[] | select(.state=="open" and .assignee==null) | {number,title,labels}'
```

`--paginate` alone is not enough: the sub-issues endpoint defaults `per_page` to 30, so a
map with more than 30 children needs every page fetched, not just the first. `gh api` does
not allow `--slurp` together with `--jq` (they're mutually exclusive), so don't try to
`flatten` pages into one array first — `--paginate` combined with `--jq` already runs the
filter against each page's array as it's fetched and emits matching results across all
pages, which is sufficient here since `select` doesn't need to see pages together.

(If the sub-issues API is unavailable, fall back to the map body's task-list convention —
`- [ ] #<ticket#>` — and check each listed ticket's state/assignee individually instead of
a repo-wide `gh issue list` label search.) Then drop any survivor whose `blocked_by` list
(above) contains an open issue — the remainder is the frontier.

## Resolve a ticket

If resolving this ticket surfaces a new prerequisite for an existing downstream ticket,
create that new ticket and wire it as a blocker on the downstream ticket **first** — before
closing the current issue. Because parallel sessions are allowed, closing early would open
a window where another session queries the frontier and claims the downstream ticket before
the new blocker exists to hold it back. Keep the downstream ticket blocked until the map is
consistent, then close:

```sh
gh issue comment <ticket#> --body-file resolution.md   # the answer, in full
gh issue close <ticket#>
```

Then append one line to the map's **Decisions so far** (fetch-edit-write, as above):

```markdown
- [<ticket title>](<ticket URL>) — <one-line gist of the answer>
```

## Rule a ticket out of scope

```sh
gh issue close <ticket#> --reason "not planned"
```

Then add one line to the map's **Out of scope** section: gist + why, linking the closed
ticket. It does not go in Decisions so far.
