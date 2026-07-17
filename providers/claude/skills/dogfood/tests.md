# tests — dogfood

Scenarios for the `/dogfood` skill (live-tests another skill in this repo).

Last verified: **Scenario 1 live-verified (typed run,
transcribed from the DEVLOG record); Scenarios 2–3 design-verified.** The SKILL.md has not changed since
`c38f932` (the Codex PR fixes), and the `/dogfood handoff` golden run
happened in the fresh session *after* that commit, so the recorded run matches the
current skill text. Transcription source: the DEVLOG entry "dogfood: `/dogfood
handoff` live run, both skills PASS."

## Scenario 1 — Golden: dogfood a registered explicit-trigger skill (live-verified)

**Input:** In a fresh session, invoked as `/dogfood handoff` — a real,
already-registered target skill (`/handoff`). Note: the DEVLOG shows no `[focus]`
argument passed to `/dogfood` itself; the `We are testing the handoff skill` text was
the argument to the `/handoff` run inside Step 4, not to `/dogfood`, so `/dogfood`'s
own focus-handling path is **not** exercised by this scenario.

**Expected output:** The pipeline runs in order: read the target SKILL.md and extract
type + contracts (Step 1); static validation — frontmatter/name-dir/references/no
self-contradiction (Step 2); invocation-policy probe — a Skill-tool self-invoke of a
an explicit-only target is absent from implicit selection and remains available through
the provider's explicit invocation path (Step 3);
a real happy-path run on a non-toy input (Step 4); per-type contract verification
(Step 5); a PASS/FAIL/PARTIAL verdict with concrete evidence (Step 6); and
record-keeping proposed as an offer, never auto-written (Step 7).

**Verify:** Observed in the live run. Static validation PASS; invocation-policy
probe PASS (Codex policy disabled implicit invocation while explicit invocation remained available—the
refusal is the pass, proving the flag is *honored*; per the skill's Step 3 this does
**not** prove user-facing `/`-menu registration, which only the user can confirm); live
run — invoked as `/handoff`, artifact landed at
`/tmp/handoff-claude-commit-skill-<date>.md` with the path printed, Workspace
section first (absolute path/branch/SHA/clean), focus honored, no secrets, and
`git status` clean after; the slugify edge (a slashed branch name → `-`) surfaced
for free from the real input; record-keeping stayed an offer until it was approved.

## Scenario 2 — Error: target skill does not exist (design-verified)

**Input:** `/dogfood definitely-not-a-real-skill` — a name that resolves to no
`skills/<name>/SKILL.md`.

**Expected output:** The skill stops at Step 1 and says the target does not exist —
it does not guess at a different skill or manufacture a pass.

**Verify:** Design-verified. The Step-1 stop *predicate* was confirmed —
`skills/definitely-not-a-real-skill/SKILL.md` resolves to no file — but
`dogfood` is explicit-only, so the skill itself could not be driven this session to
observe it emitting the Step-1 stop and declining to guess. Per build-skill Step 6
that makes this design-verified (the predicate traced by inspection), not live: a live
upgrade needs the actual typed `/dogfood <bad-name>` run and its observed stop message.

## Scenario 3 — Edge: a target with a distinct failure/edge path (design-verified)

**Input:** A registered target whose Step-4 edge path is genuinely separate from its
happy path and exercises a contract that can break — e.g. an orchestrator skill run
against a diff that produces a surviving finding, or a scanner-absent degradation,
where the edge run is not made redundant by the golden input.

**Expected output:** Both the happy and the edge/failure path run (Step 4's
two-path requirement), the contract table's row for that skill type is checked
against the observed behavior (Step 5), and any check that could not run this session
is listed explicitly as an untested gap, never counted as a pass (Step 6).

**Verify:** Design-traced only. In the golden run the planned distinct
edge path (a throwaway slashed branch) became *redundant* — the real input already
exercised slugify — so a genuinely separate edge path has not been observed. First
dogfood whose edge path is not subsumed by its golden input should upgrade this
scenario.
