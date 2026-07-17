# Waiting for an agent to finish (push, not poll)

Prefer `cmux events` over looping `read-screen`.

**Prerequisite, once:** `cmux hooks setup --yes` (wires `pi`, `codex`,
`opencode`, etc. to emit on turn-stop; Claude Code emits notifications
out of the box when launched inside cmux, no hook needed).

**What fires:** one `notification.requested` event per completed agent turn,
carrying `workspace_id` (always set) — `surface_id` is often `null` for
hook-emitted notifications, so match on `workspace_id`. Title/body are
redacted in the event itself — it's a signal, not the content; `read-screen`
the surface once it fires.

```bash
WS=<workspace-uuid-from-the-manifest>  # a fleet manifest's workspace_ref IS this UUID (spawn_fleet.py requests --id-format both); for ad-hoc driving, add --id-format both to your own workspace create/new-split call to get one
cmux events --name notification.requested --no-heartbeat --no-ack > /tmp/cmux.ev &
EV=$!
# ... send the task if not already running ...
until grep -q "\"workspace_id\":\"$WS\"" /tmp/cmux.ev; do sleep 1; done
kill $EV
cmux read-screen --workspace "$WS" --scrollback --lines 40
```

**Pitfall:** piping `cmux events | jq ... &` inline can stall on stdout
buffering — stream to a file and poll the file (above), or use `jq
--unbuffered`.

**Caveat:** a notification fires on turn-completion even when an agent
*declined* to do the work (e.g. Claude Code without bypass permissions). Always
`read-screen` after the event; never trust the event alone as "succeeded."

**Grid fleets — a shared `workspace_id` means "some pane," not "this pane."**
A `grid`-arranged fleet puts every entry in its own pane but **one shared
workspace** — so all of them emit notifications carrying the *same*
`workspace_id`. Matching on it (as above) only tells you *an* agent in that
grid finished a turn, not which one, and not that every agent is done —
`surface_id` is usually `null`, so there's no per-pane signal in the event
itself. Treat the event purely as a wakeup ("go check the grid again"), then
loop over **every entry's own `surface_ref`** from the manifest and
`read-screen` each individually to learn actual per-entry status. Don't
conclude a specific entry is finished just because *a* notification fired —
only a `tabs` fleet (one workspace per entry) gives you that precision for
free.
