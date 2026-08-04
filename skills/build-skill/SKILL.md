---
name: build-skill
description: "Author or sharpen a portable Agent Skill by doing the work first, then codifying it. Invoke build-skill explicitly with a skill name. Scope one task, drive three or more live practice runs, codify SKILL.md and tests.md from those runs, review against the predictability lens, and verify before promotion. Use when creating a reusable workflow or correcting an existing skill that mis-triggers or underperforms."
---

# build-skill — Author a skill by doing the work first

You are the **author's guide**, not a ghostwriter. Your one job is to stop this skill
being written from imagination and drive it out of **real work** instead. The single
most common way a skill goes wrong is being written on day one from someone's head —
it is then wrong in ways nobody can predict until the workflow has actually run. Every
step below exists to prevent that.

Invoke the `build-skill` skill (optionally naming `[skill-name]`).

A skill exists for one reason: to wrangle **predictability** out of a stochastic model
— the agent taking the same *process* every run (not the same output; a brainstorming
skill should predictably diverge). **Read `references/great-skills.md` now.** It is the
vocabulary — credit to Matt Pocock's *writing-great-skills* — you will use as the
**lens** to review every line you write in Steps 4–6. Keep it open.

## The spine

    Scope one task → do it live ×3 → codify from the runs → review against the lens
    → verify → promote → let it fail → stop touching it

Do not jump to codifying. If the user asks you to "just write the SKILL.md," push back
once: the practice runs are where the skill gets real. Proceed to imagination-first
authoring only if they insist after that push.

**Toolbox.** This workflow is self-contained — the bundled scaffold and
`references/checklist.md` stand alone. But if skill-kit or the skill-testing bench is
installed, prefer its tools where a step names them: `goal-new-skill` (Step 1) and
`check-skill` (Step 6).

## Step 1 — Scope one task

Pin **one task**: one coherent flow, one trigger audience, one output. Not "handle
PRs" — "turn a PR diff into a prioritized comment list."

Split into separate skills when **either** holds:

- **Distinct trigger audiences** — the phrasings that should fire it fall into
  unrelated buckets one description can't sharpen around without going generic.
- **Independent sub-procedures with separate outputs** — the steps branch into parts
  that don't share state and each emit their own deliverable.

Many rubric *areas* over one input is still one task (a PR review checks correctness,
tests, security, style — one diff in, one list out: don't split). "Review my PR and
also deploy it" is two tasks — split it.

Optionally anchor a measurable end state: interview the user into a verifiable
`goal.md` (or invoke the `goal-new-skill` skill with `<name>` if installed).

**Completion criterion:** a one-sentence task statement, action verb first, that the
user agrees is a single task by the split test above.

## Step 2 — Do it live, at least 3 times

Do the task *with* the user, in this session, on **real, diverse inputs** — a golden
path, an edge case, and something weird (empty / malformed / oversized). Not
hypotheticals. Correct mistakes as they surface, add the steps you forgot, confirm
what actually works. This is where the skill gets real; the edge cases you hit here
are the ones the codified skill will handle.

**Completion criterion:** at least 3 real runs done — one per input archetype (golden,
edge, weird) — each captured with its actual input and actual output, the raw material
for `tests.md`'s ≥3 scenarios. If a run revealed the task is really two tasks, return
to Step 1.

## Step 3 — Codify from the runs

Only now write files, and write them **from the runs, not theory**. Copy the scaffold
bundled with this skill (adjust the source path to wherever build-skill is installed):

    cp -r skills/build-skill/assets/skill-skeleton <target>/<name>   # e.g. staging/<name> or skills/<name>

**Drop the `.template` suffix** on each scaffold file you keep — `SKILL.md.template` →
`SKILL.md`, `tests.md.template` → `tests.md` — or the skill never registers and the
harness fails the hard gate. Then fill `SKILL.md` and `tests.md` from what you did in
Step 2. Arrange content on **the
ladder** (`great-skills.md`): ordered **steps** for what the agent does; **reference**
for what it consults on demand; push reference that only some runs need behind a
pointer into `references/`. Give each step a **completion criterion** the agent can
actually check. Strip every scaffold sidecar you don't need — an unused file is just
maintenance surface.

**Completion criterion:** `SKILL.md` + `tests.md` (≥3 scenarios from real runs) exist;
every section traces to something you did in Step 2, not something you imagined.

## Step 4 — Write the description

Make it **pushy and sharp** (`references/writing-descriptions.md`): what it does *and*
when to use it, third-person imperative, intent not implementation, and at least two
concrete trigger conditions generalized to intent categories. Keep canonical
frontmatter limited to `name` and `description`. Put explicit-only invocation policy in
the target harness's adapter metadata; in this repository that means `toolbelt.json`
and, for Codex, `agents/openai.yaml`.

**Completion criterion:** the description names the skill's job and, for a
model-invoked skill, at least two concrete conditions that should fire it — and you can
name a near-miss it should *decline*.

## Step 5 — Review against the lens and prune

Read the draft against `great-skills.md`. Then **prune**: run the no-op test on every
sentence in isolation — does it change behaviour versus the model's default? If not,
delete the whole sentence. Hunt the five failure modes: premature completion,
duplication, sediment, sprawl, no-op. Refactor restated triads into a single **leading
word** where a pretrained one fits.

**Completion criterion:** no sentence in `SKILL.md` fails the no-op test; every
meaning has a single source of truth; the body is as short as the task allows.

## Step 6 — Verify

Run the ≥3 `tests.md` scenarios *through the skill* the way it will actually be
invoked — **every authored scenario, individually**: verification is per-scenario,
and a pass that exercised only a subset is not complete evidence. Where the `dogfood` skill
is available **and the skill already sits at its registered location**
(`skills/<name>` — the sharpen-an-existing-skill path), invoke the `dogfood` skill with `<skill-name>`
instructing it to drive **each `tests.md` scenario** and record a per-scenario
verdict; any scenario its pass did not run must still be replayed by hand before
this step completes. A **staged draft** (`staging/<name>`) is not registrable yet — the `dogfood` skill
resolves only live skills — so verify it by replaying each scenario against the
skill's steps by hand, then invoke the `dogfood` skill immediately after Step 7's promotion as
the confirming live pass. Same quality as your manual runs? Fix the skill, not the
output, when they diverge. **If your harness only registers a freshly built skill
after a reload or new session**, run this step after that boundary—that restart *is*
the dogfood. Then clear the mechanical gate: `check-skill <skill-dir>` if installed,
else walk `references/checklist.md` by hand. Zero hard-gate failures required.

**Status vocabulary — `live-verified` vs `design-verified` (the whole `tests.md` corpus
uses these; here is what they mean).** A scenario is **live-verified** only when *its own
Input fixture was actually run through the skill and its Verify clause observed*. It is
**design-verified** when traced against the skill's steps by inspection, not run. The trap
to avoid (it recurs in review after review): a verdict or output that
appeared via a **different** fixture, or a scenario **sub-path** that was never exercised
(a delegated fix, a re-arm, an error branch), is **not** live-verified for that scenario —
it is design-verified, with a one-line note saying which part ran. Match the evidence to
the scenario's specific Input/Verify, not merely to its output verdict. When only part of a
scenario ran, split it: name the live part live and the unrun part design-verified, rather
than marking the whole scenario either way.

**Completion criterion:** every `tests.md` scenario passes — through the skill, or by
hand when it can't register until reload — and the pre-ship checklist has zero
hard-gate failures.

## Step 7 — Promote, let it fail, stop touching it

Move the skill to its live home if it was staged, stripping any staging-only working
files (`goal.md`, evidence logs). Before you rely on it, confirm what the harness
can't: it was built from real runs, and — for a generative/judgment skill — that it
beats just asking the model (the value-add check). Then **let it fail**: use it for
real, and when it breaks, fix the *skill* so that failure can't recur — don't just
patch the one output. When it just works, stop touching it.

**Completion criterion:** the skill lives in its target directory, and you have told
the user plainly what you verified and what is still unproven — citing the Step 6
the `dogfood` skill's verdict, or, for a skill that was staged, the manual-replay record plus
the post-promotion `dogfood` run confirming pass, as the promotion evidence.

## Step 8 — Later: sharpen it

To improve an existing skill rather than build a new one, re-enter this workflow at
Step 2 to re-run the task and re-codify what broke. Don't polish a skill that was never
built from real work — polish can't substitute for the practice runs.

---

*The predictability vocabulary in `references/great-skills.md` is adapted from Matt
Pocock's `writing-great-skills`. The do-the-work-first process and the pre-ship
checklist are distilled from the skill-testing bench and skill-kit.*
