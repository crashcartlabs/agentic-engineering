# AGENTS.md: Field Notes on Getting a Language Model to Write Code You Will Not Rewrite

*A Short List of Rules, Earned by Watching the Same Mistakes Twice*

**Abstract.** This file exists because language models make predictable mistakes when they write code. Not random mistakes, just the same ones, over and over, often enough that it was worth writing them down. What follows is not a set of suggestions but a set of rules. The throughline is the same in every section: the model is fast at generating plausible code and slow to notice that plausible is not the same as correct, so the discipline has to come from the process around it.

**Index Terms.** LLM-assisted programming, code review, software craftsmanship, minimal diffs, debugging, dependency hygiene.

## I. Read Before You Write

The biggest source of bad model-written code is writing before reading the codebase. Read the files you are about to touch; read, not skim. Copy the patterns that already exist, and check the imports to see what the project actually depends on, so you do not reach for axios where everything is fetch. When you cannot find a pattern, ask instead of guessing. When a research pass is wide enough to bloat your own context—a broad codebase sweep or a multi-file investigation—delegate it to a fresh-context subagent when the active harness supports that safely, then work from its distilled result.

This applies to third-party dependencies too: when a package's actual behavior is not clear from its public API or docs, do not guess from training data. `opensrc` (installed globally on this machine—`opensrc path <package>`) fetches and caches a package's real source from npm, PyPI, crates.io, or GitHub, so you can read or grep the actual implementation, for example `rg "parse" $(opensrc path zod)` in a POSIX shell.

## II. Think Before You Code

Figure out what you are doing before you type. State your assumptions ("add authentication" is five different things, so name the one you picked) and name the tradeoffs. If something is genuinely confusing, stop and ask rather than filling the gap with plausible-looking code; that is exactly the code that passes a casual review and fails when it matters.

## III. Simplicity

Write the minimum code that solves the problem in front of you now, not the minimum that could solve every future version of it. Resist premature abstraction, skip error handling for errors that cannot occur, and hardcode values until there is a real reason to configure them. The test: if the only reason something is abstracted is "in case we need to," you have over-built it.

## IV. Surgical Changes

Your diff should be as small as the task allows. Do not touch what you were not asked to touch, match the existing style, and do not reformat; a formatter pass buries the three lines that matter inside three hundred that do not. The test is whether you can justify every changed line by the task. If a line is there because "while I was in there," revert it.

## V. Verification

The gap between code that works and code you think works is testing. For behavioral changes, write the test first. When fixing a bug, write the failing test, watch it fail, then fix it; that is the only proof you fixed the cause and not the symptom. Test behavior that can actually break, not that a constructor sets a field. If something is hard to test, that is information about the design, not permission to skip it.

## VI. Goal-Driven Execution

Every task needs a success criterion before code is written. "Add validation" becomes "reject a missing or malformed email, return 400 with a clear message, and test both cases." For anything multi-step, state the plan first so the user can catch a wrong approach before you spend an hour building it.

## VII. Debugging

When something breaks, investigate; do not guess. Read the whole error and the stack trace, reproduce the problem before you change anything, and change one thing at a time. Do not paper over an unexpected null with a null check; find out why it is null, or the bug just moves somewhere quieter.

## VIII. Dependencies

Every dependency is permanent code you do not control. Before adding one, ask whether the project or the standard library can already do it with `crypto.randomUUID()` over a uuid package. When you do add one, say why, so the choice is visible rather than smuggled into the manifest.

## IX. Communication

Say what you did and why, not just a block of code. Flag concerns even when you did exactly what was asked, and be precise about uncertainty: "I am not sure this library supports streaming" tells the user what to verify; "I think this should work" does not.

## X. Lessons

LESSONS.md is the repo-root **working list** of lessons from mistakes and corrections—a triage queue, not a permanent archive. Append a one-line entry (what went wrong → the rule that prevents it) whenever the user corrects course, a mistake surfaces, or a better approach is confirmed—and only then. Review the list to improve the process; once a lesson has been addressed—absorbed into AGENTS.md or the process, or discarded—**clear the entry**. LESSONS.md is for actionable lessons that should bind anyone working in this repo; permanent design rationale belongs in the relevant file, and preferences or facts about the user that travel across repos belong in memory, not here.

## XI. Environment

The user works across Windows, Ubuntu, and macOS, so do not assume a shell. Check what system you are actually running on and write commands for that environment (PowerShell on Windows, a POSIX shell on Ubuntu and macOS), minding the path and tooling differences that follow. The working languages are TypeScript and Python, with plain JavaScript only where it is needed. This is a meta-repo: it holds provider-neutral skills, agents, scripts, provider adapters, and supporting files for development work rather than a single application.

Provider-neutral skills live in `skills/`; canonical agent prompts live in `agents/`; provider-specific integration belongs in `providers/`, `.claude-plugin/`, `.codex-plugin/`, or the provider's required project configuration. Do not put shared behavior back under `.claude/`, `.codex/`, or `.pi/`.

## XII. Definition of Done

Code being written is not the same as a task being done. A task is done when it is verified against the success criterion from Section VI: the behavior actually happens when run, not just in theory; a behavioral change has a test that would fail without it; the diff is justified line by line; and you have said plainly what you did, what you verified, and what you are still unsure of. If a correction or a better approach surfaced along the way, LESSONS.md gets its one line before you call the task done.

## XIII. Development Log

DEVLOG.md is the repo-root chronological record of the work itself: what each session set out to do, what got done, the decisions and their reasons, and where work was left off so the next session resumes without re-deriving context. Entries are dated, newest first. It is distinct from the others—git history records what changed, LESSONS.md records what not to repeat, and DEVLOG.md records the narrative and the reasoning. Append an entry at the end of a substantive session.

## XIV. Backlog

GitHub issues are the repo-root backlog for work identified but deliberately deferred—one issue per work item, so agreed-upon next steps stay out of the conversation's head and out of DEVLOG's narrative. TODO.md is only a pointer and offline scratchpad for newly identified deferred work until it can be filed. When work is postponed, open or update an issue as soon as practical, then remove any local scratch note so TODO.md reflects only unfiled temporary items.

## XV. Application Lifecycle

Keep application code in the application repository from day one. Use this repository as the installed toolbelt. New application work follows the durable artifact chain in `docs/app-build-workflow.html`:

1. Create or open the application repository and add its local `AGENTS.md`.
2. Map a broad or foggy idea with `wayfinder` when needed.
3. Write and approve a product behavior contract with `spec`; the spec is mandatory.
4. Translate the approved spec into an executable technical plan with `plan`.
5. Execute only an approved plan, using test-first vertical slices through `execute` and `tdd`.
6. Verify the result against its plan and spec with `review-plan`.
7. Run correctness and security audits when the change's risk warrants them.
8. Commit and ship only with current verification evidence, then operate and clean up.

Do not collapse this into prompt-to-code. Preserve the spec, plan, review, release, and operational artifacts as the source of truth between sessions.
