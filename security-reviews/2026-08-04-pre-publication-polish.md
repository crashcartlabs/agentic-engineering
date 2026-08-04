# Security Audit — pre-publication-polish vs origin/main  (183 files, +2200/−650)

Verdict: 1 confirmed finding (1 medium) — fixed and verified; 4 lenses clean.

## Trust-boundary map
Entry points:
- **EP-A** — scheduled `weekly-janitor` Actions job (cron + workflow_dispatch). Input: repo-controlled DEVLOG.md/LESSONS.md (merged contributor text), remote branch names + commit subjects, GitHub API data (issue/PR titles, labels, notes). Runs `weekly_janitor_report.py --fetch` + `janitor_preview.build_preview`.
- **EP-B** — lint gate `check_all.py` (CI + pre-commit + local). Input: the whole repo tree (skills/, plans/, DEVLOG/LESSONS), env `AGENTIC_SEDIMENT_EXTRA` (CI secret).
- **EP-C** — cmux selftests via the gate; self-generated git repos/worktrees in the OS temp dir.
- **EP-D/E** — `publish_public.py` + `upstream-check.yml` — unchanged in this diff (context only).

Reaches: `read_repo_record` (weekly_janitor_report.py:46-101) ← DEVLOG.md/LESSONS.md reads (:477, :779); `janitor_preview.py:516-551` guarded LESSONS.md read; `render_markdown` (:844-982) → `$GITHUB_STEP_SUMMARY` (weekly-janitor.yml:38); lint gates over the repo tree (gittracked.py:55-113; lint_skills/lint_links/lint_records/lint_plans); the slash-sweep regexes (lint_skills.py:120-166); cmux mkdtemp roots.

Assets: `$GITHUB_STEP_SUMMARY` rendered HTML in the Actions run UI + artifact upload; GitHub token (weekly-janitor: contents/issues/pull-requests read — unchanged workflow); CI secret `AGENTIC_SEDIMENT_EXTRA` (never on fork PRs); repo tree; dev filesystem under `--fix`; /tmp.

Controls: `md_code_span` adaptive N+1-backtick fence at every free-text site (janitor_preview.py:578-590); `read_repo_record` lstat no-symlink → S_ISREG → O_NOFOLLOW|O_NONBLOCK open → fstat re-verify → 1 MiB bound → strict UTF-8; `tracked_text_or_none` (OSError|UnicodeDecodeError → None) at text-consuming lint sites; gittracked path containment + list-argv git/gh (no shell); pre-commit/index isolation (checkout-index snapshot); non-echoing sediment matches; tempfile.mkdtemp (unique 0700) for all selftest temp dirs.

## Findings  (most severe first)

### 1. [MEDIUM] Stored markdown/HTML injection into the step summary via the unwrapped clutter-path field
`scripts/maintenance/weekly_janitor_report.py:971` (sink), via `scan_clutter` (:729-756, `.pyc` match :752)
Exploit path: hostile contributor (merged content; the job runs on the default branch) merges a file whose **name** contains a backtick + newline + markdown payload, ending in `.pyc` — legal on Linux/git (CI is ubuntu-latest), e.g. `` a`⏎# Fake heading⏎- [x] merged `.pyc ``. Weekly cron → checkout → `build_report` always calls `scan_clutter` (:831) → file matches :752 → `ClutterCandidate(path=<name>)` → :971 renders `` f"- `{candidate.path}` (pyc_file): …" `` — the backtick inside the filename closes the code span early, ejecting the newline+payload as raw markdown → `cat >> $GITHUB_STEP_SUMMARY` (weekly-janitor.yml:38) → GitHub renders a fake H1, a fake checked "merged" task item, arbitrary links/lists/allowlisted HTML in the maintenance report. What they get: rendered-content spoofing of the report to maintainers + defeat of the adaptive-fence control this diff ships. (Script execution via `<script>` is conditional on GitHub's step-summary sanitizer, which normally strips it — content-injection/spoofing is the guaranteed impact; a sanitizer gap would upgrade to stored XSS.)
Why: the clutter `path` field was rendered in a plain single-backtick span — the one attacker-controlled free-text field the adaptive `md_code_span` was not applied to; the hostile-input selftest covered issue titles/labels but not clutter paths.
Fix direction: wrap `candidate.path` (and `detail`) in the adaptive fence and squash newlines (also closes the `::` workflow-command vector). **FIXED in `40e080b`** (newline-squash + `md_code_span` on both fields; hostile backtick/newline `.pyc`-filename fixture added to the selftest; janitor selftest + full gate green after the fix).

## Hardening (not findings)
- Unbounded lint reads: `tracked_text_or_none` reads whole files with no size cap — a ~100 MB tracked file costs ~7–10 s of CPU per gate run; bounded by GitHub's per-file cap, no wedge. Consider a cap consistent with the janitor's 1 MiB philosophy.
- `worktree_path` (:915-916) and the local-preview render (janitor_preview.py:616-638: subject/entry/reason/message raw) use plain backtick spans / no escaping — reachable only by a local developer's own worktree path or terminal output; no workflow consumes the preview.
- Echoed names in lint errors (slash-sweep `line[:100]`, sediment `rel:lineno:label`) could break the log prefix with newline-bearing names → forged Actions workflow commands; `set-env`/`set-output` are disabled on current runners, so cosmetic/DoS only.
- Pre-existing: lint_sediment DENYLIST errors print `pattern: {pattern.pattern}` — keep future denylist patterns generic.

## Pre-existing (outside this diff)
- `_env_int`/`_env_int_tuple` echo raw env values on parse failure (weekly_janitor_report.py:103,114) — non-secret `AGENTIC_JANITOR_*` integers, predates the diff.
- lint_sediment `read_text_or_none` PermissionError-crash/silent-skip asymmetry — predates the diff.

## Good practices observed
- Every free-text field in the step-summary report is fenced by the adaptive `md_code_span` (now including the clutter path) — the stored-markup surface is closed.
- `read_repo_record` is a model defensive read: symlink refusal, S_ISREG, O_NOFOLLOW + O_NONBLOCK + fstat re-verify (TOCTOU/FIFO), 1 MiB bound, strict UTF-8 — with a selftest covering each hostile fixture.
- The cmux selftests' fixed `/tmp` paths (predictable-path/symlink-race) were replaced with unique 0700 `mkdtemp` dirs.
- `gh`/`git` are invoked list-argv with no shell, 30s timeouts, captured output — no command injection, no token echo.
- The CI secret never reaches fork PRs; the diff adds no token reads, no new dependencies, and no workflow scope changes.
- ReDoS probes against the new regexes and scanners (up to 20 MB hostile inputs) found no catastrophic backtracking.
