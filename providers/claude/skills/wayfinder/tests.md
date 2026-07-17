# tests — wayfinder

Scenarios for the `/wayfinder` skill, ported from mattpocock/skills
(`skills/engineering/wayfinder`) and adapted to GitHub Issues via the `gh` CLI. All
scenarios are design-verified against the skill text; none has yet been run live against a
real map issue. First live run should exercise Scenarios 1 and 4 end-to-end on a scratch
effort and update this header.

## Scenario 1 — Chart a foggy effort — design-verified

**Input:** `/wayfinder migrate the skills test harness to run tickets in CI` (a loose,
multi-session idea with open decisions).

**Expected:** A grilling pass names the destination first; a second breadth-first pass
surfaces open decisions. One map issue is created labelled `wayfinder:map` with
Destination, Notes, empty Decisions so far, fog in Not yet specified. Specifiable
questions become child issues (sub-issues of the map) labelled `wayfinder:<type>`, with
blocking edges wired in a second pass after all tickets have numbers. The session stops
after charting — no ticket is resolved in the same session.

## Scenario 2 — No fog: decline to build a map — design-verified

**Input:** `/wayfinder rename lint_skills.py to lint_skill_set.py` (way already clear,
fits one session).

**Expected:** The breadth-first grill surfaces no fog; the skill does not create a map.
It stops and asks the user how to proceed, suggesting a single `/plan` session — it does
not silently fall through into doing the work.

## Scenario 3 — Work through the map picks the frontier — design-verified

**Input:** `/wayfinder <map URL>` with no ticket named; the map has one closed ticket,
one open ticket blocked by an open blocker, and two open unblocked unassigned tickets.

**Expected:** The session loads only the map body, runs the frontier query (open,
unassigned, no open blocker), takes the first frontier ticket, and claims it with
`gh issue edit <n> --add-assignee @me` **before** any work. The blocked ticket and the
already-assigned ticket are never taken. Exactly one ticket is resolved this session.

## Scenario 4 — Resolution bookkeeping — design-verified

**Input:** A grilling ticket reaches its answer with the human.

**Expected:** The answer is posted as a resolution comment on the ticket, the ticket is
closed, and one line is appended to the map's Decisions so far as
a linked ticket title followed by a one-line gist — a name wrapping a link, never a bare `#42`. The map
body is fetched, edited, and written back (not regenerated), so concurrent edits from
parallel sessions survive. Newly-specifiable fog graduates into fresh tickets and is
removed from Not yet specified.

## Scenario 5 — Out of scope, not resolved — design-verified

**Input:** Resolving a ticket reveals another existing ticket sits past the destination.

**Expected:** That ticket is closed with `--reason "not planned"`, and one line (gist +
why, linking the closed ticket) is added to the map's Out of scope section. It does not
appear in Decisions so far, and nothing in Out of scope ever graduates back into tickets.

## Scenario 6 — HITL ticket never self-answers — design-verified

**Input:** A `wayfinder:grilling` ticket worked in a session where the human goes quiet.

**Expected:** The agent asks its questions and waits; it never supplies the human's side
of the exchange or closes the ticket with an answer the human didn't give. If the human
is unavailable, the ticket stays open and claimed-or-released, not fabricated-resolved.

## Scenario 7 — Does not mis-trigger against /plan — design-verified

**Input:** "Plan the refactor of the dashboard script" (single well-scoped change).

**Expected:** Wayfinder does not fire: toolbelt and provider policy mean it only runs
when explicitly invoked, and its description scopes it to multi-session foggy efforts
above the single-plan level, pointing single-plan work at `/plan`.
