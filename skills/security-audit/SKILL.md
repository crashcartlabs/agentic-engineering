---
name: security-audit
description: "Exploitability review of the current worktree's changes — hunts for vulnerabilities the diff introduced or newly exposed, not correctness or style. Invoke as /security-audit [low|medium|high|max] [--full] [--comment]. Maps trust boundaries, fans out attack-class hunters, adversarially verifies every finding against a concrete exploit path, writes a read-only report to security-reviews/. Sibling to /code-audit (correctness); --full audits the whole repo. Explicit-trigger only."
---

# /security-audit — Exploitability Review

You are the **orchestrator**. You do not hunt the vulnerabilities yourself — you pin the scope, map the trust boundaries, fan out attack-class hunter subagents, adversarially verify what they find against a concrete exploit path, and compile the report. Your judgment lives in the *recon, the dispatch, and the verification*, not in a solo read-through. A single context skimming a diff for "security issues" produces plausible-sounding noise; a fan-out of focused hunters aimed by a real trust-boundary map, each finding then attacked by a skeptic, produces findings you can act on. That difference is the entire point of this skill.

Invoked as `/security-audit [effort] [--full] [--comment] [baseline] [paths...]`. Effort defaults to **high**.

This is the exploitability sibling of `/code-audit`. `/code-audit` asks *"is the code wrong?"*; this asks *"can an attacker make it do something it shouldn't?"* Run both on the same diff — they do not overlap and neither substitutes for the other.

## What this reviews — and what it does not

An **exploitability** review. It answers one question: **is there a vulnerability an attacker can actually reach and exploit, and did this change introduce or expose it?**

**In scope (diff mode):** a vulnerability is a finding only if the diff **introduced** it (added the vulnerable sink) **or newly exposed** it (made a pre-existing, previously-unreachable sink reachable by an attacker). Reachability is judged against the trust-boundary map from the recon phase — that map is exactly what tells "the diff opened a path to this" apart from "this was always here."

**Out of scope — do not raise these as findings:**
- **Correctness, style, performance, tests, structure** — those are `/code-audit`, the linter, or sibling skills. A logic bug with no security consequence is not yours.
- **Pre-existing vulnerabilities the diff neither introduced nor exposed** — that is what `--full` is for. When a hunter notices one in passing, it goes in a single trailing **"Pre-existing (outside this diff)"** note — surfaced so it is not lost, never dressed up as a finding *of this change*.
- **Theoretical concerns with no attacker-reachable exploit path** — "this could be unsafe if someone later…", missing defense-in-depth where another layer already prevents the attack, hardening that is not industry-mandatory. These are real but they are not findings: they go in the separate **"Hardening (not findings)"** bucket, which never inflates the finding count.

The survival bar below is what enforces this line. If you cannot show an attacker sending *something* and getting *something they should not have*, it is not a finding.

## Effort tiers

| Tier | Verification | Discovery | Thoroughness |
|------|--------------|-----------|--------------|
| `low` | 1 skeptic per finding | single pass | high-confidence findings only |
| `medium` | 1 skeptic per finding | single pass | standard sweep |
| **`high`** (default) | panel of 3, majority-kills | single pass | standard sweep |
| `max` | panel of 3, majority-kills | loop-until-dry | exhaustive sweep |

Effort scales *verification rigor + discovery persistence + how hard each hunter looks* — never the lens set. All five hunters always run; even `low` keeps one genuine skeptic per finding, because a false "you have an auth bypass" is costly and alarming in a way a false correctness nit is not. `--full` is **orthogonal** to effort — `/security-audit --full low` is a shallow whole-repo pass; `/security-audit max` is an exhaustive diff pass.

## Pipeline

### 1. Pin the scope — before reading any code

Everything resolves from the current worktree's directory, so sibling worktrees and the main repo stay invisible.

- **Resolve the base ref.** Run `agentic resolve-base` from the target worktree and use
  its output as `<base-ref>`. This is the shared policy for remote/local fallback order;
  do not copy a variant into this skill.
- **Compute the merge-base:** `git merge-base <base-ref> HEAD`.
- **Capture the review span** — everything this branch changed vs the base, *committed or not*:
  - committed branch work: `git diff <base-ref>...HEAD` (three-dot, from the merge-base)
  - uncommitted tracked changes: `git diff HEAD`
  - untracked new files: `git status --porcelain --untracked-files=all` — the `--untracked-files=all` is essential; the default mode collapses a newly added directory to a single `dir/` entry and hides every file inside it. Include the full contents of each new (`??`) file.
- **Honor the args:** a `baseline` arg (SHA / branch / tag) overrides `<base-ref>`; `paths...` scope the diff to those files.
- **`--full` overrides all of the above:** ignore the diff entirely and treat the **whole repository** as the scope (see [`--full` mode](#full-mode)).
- **If the diff span is empty (and not `--full`), stop** and say so — there is nothing to review. Do not manufacture work.
- **State plainly what is under review:** branch, base ref, file count, `+`/`−` line counts (or "whole repository" under `--full`). This assembled diff is the **pinned scope** — every hunter sees exactly this.

### 2. Recon — map the trust boundaries (first-class phase, not a warmup)

A security hunter is useless if it does not know where untrusted input enters and what
sits behind a trust boundary. Before any fan-out, build the map. Spawn one or more
read-only recon subagents through the active harness (read access to the whole
worktree—recon is *not* limited to the diff, because a diff's sink may be reached from
untouched code) to produce a **trust-boundary map**:

- **Entry points** — where untrusted input enters: HTTP routes/handlers, CLI arg/stdin parsing, message-queue consumers, webhook receivers, file/upload ingestion, deserialization points, env/config read from untrusted sources, IPC.
- **Reachability** — for the pinned scope, what does each entry point *reach*? Which changed (or, in `--full`, which) code is downstream of untrusted input, directly or transitively.
- **Assets behind boundaries** — what is privileged or sensitive: the database and its credentials, secrets/keys, the filesystem, subprocess/shell execution, SSRF-reachable internal services, auth/session state, other users' data.
- **Existing controls** — the auth middleware, input validation, parameterization, sandboxing, CSP already in place — so a hunter can tell a real hole from a layer that is already defended (defense-in-depth: if layer A prevents the attack, layer B's absence is *hardening*, not a vulnerability).

In **diff mode**, the map's job is to answer the reachability question that defines scope: is each changed sink reachable from an untrusted entry point, and did this diff create or open that path? In **`--full`**, the map is the whole application's attack surface.

Save this map — it goes at the **top of the report** so a reader can see the attack surface you reasoned about, and hand it to every hunter as required context.

### 3. Fan out the five attack-class hunters — in parallel

Spawn five read-only hunter subagents concurrently through the active harness. Give each:
the pinned scope, the trust-boundary map, **read access to the worktree for surrounding
context** (a vulnerability is judged along its whole data-flow path, not from one hunk),
its lens brief, its `references/` playbook, and the findings contract below. Each hunter
reads **only its own playbook** and reports **only** findings within its lens, in the
contract's shape, returning nothing (not filler) if its lens is clean.

1. **Injection & output handling** — SQL/NoSQL injection, OS-command injection, XSS (reflected/stored/DOM), template injection, path traversal, SSRF, header/log/CRLF injection. Playbook: `references/injection.md`.
2. **AuthN & AuthZ** — authentication bypass, missing or broken access control, IDOR, privilege escalation, insecure session/token handling and lifecycle. Playbook: `references/authn-authz.md`.
3. **Secrets, sensitive data & crypto** — hardcoded credentials/keys, secrets in logs or responses, PII/sensitive-data exposure, weak or misused cryptography (MD5/SHA1 for passwords, ECB, static/reused IV, `Math.random()` for tokens). Playbook: `references/secrets-crypto.md`.
4. **Untrusted input & unsafe deserialization** — unsafe deserialization, file-upload handling, mass assignment, prototype pollution, XXE, open redirects, ReDoS, unvalidated size/type/shape of input. Playbook: `references/untrusted-input.md`.
5. **Configuration, dependencies & error handling** — insecure defaults, missing/weak security headers & CORS, known-vulnerable dependencies (CVEs), TLS/verbose-error/debug/stack-trace leakage. Playbook: `references/config-deps.md`.

**Scanners (this lens may run existing read-only tools).** The config/deps and secrets hunters *may* invoke non-mutating analyzers that already exist in the environment — `npm audit`, `pip-audit`, `osv-scanner`, `gitleaks dir --redact .`, `trufflehog filesystem . --no-verification --no-update` — and fold their output into findings. They must **never install anything, never modify the project, never mutate state**. If a tool is not installed, note the gap ("no dependency scanner available — `npm audit` not installed") rather than failing. Two hard constraints on the secret scanners specifically:
- **Run them non-verifying.** TruffleHog's *default* verifies a hit by making a live request to the provider (AWS/GitHub/Slack/…) to see if the credential is valid — that would send discovered secrets off-box, breaking the read-only guarantee. Always pass `--no-verification --no-update` (and equivalents on any other secret scanner). Never enable verification.
- **Redact before folding in.** Prefer redacting flags (`gitleaks --redact`) and, regardless, **never carry the raw secret value into a finding, the report, or a `--comment` post** — record only `file`, `line`, secret *type*, and rotation guidance. Writing the live secret into a report or reposting it to GitHub is the exact leakage this audit exists to catch.

Be aware: `npm audit` / `pip-audit` make an **outbound network call** to a public advisory database — that is the one place this skill is not hermetic; it is read-only and expected, but do not run scanners that would exfiltrate code, verify secrets against their provider, or hit non-advisory endpoints. And read the exit code correctly: `npm audit` and `pip-audit` **exit nonzero when they find vulnerabilities** — that is the *findings-present* signal, not a tool failure, so capture and parse stdout/stderr regardless of exit status rather than treating a nonzero exit as "scanner unavailable."

### 4. Barrier, then dedupe

Wait for all five to return. Merge duplicates — the injection and untrusted-input hunters will both land on the same deserialization sink; collapse them into one finding, keeping the clearest exploit path. Dedupe *before* verification so you never spend skeptics on the same vuln twice.

### 5. Adversarial verification — the gate

For each deduped finding, spawn verifier subagent(s). A verifier's **only** job is to **refute** the finding — its default verdict is *"not exploitable."* A finding **survives only if the verifier confirms a concrete, attacker-reachable exploit path, traced against the real source.** Concretely, the verifier must be able to state:

- **who** — the attacker's starting position (unauthenticated? any logged-in user? a specific role?),
- **what they send** — the specific input/request that triggers it,
- **the path** — the data flow from that untrusted input to the sink, cited with accurate `file:line` that **actually exist in the source** (verify them — a cited line that does not connect the path kills the finding),
- **what they get** — the concrete impact: data, access, or execution they should not have, **or, for DoS/ReDoS/resource-exhaustion, a loss of availability** (the cheap input that makes the service unusable). Availability is a valid impact here — the DoS and untrusted-input lenses and the severity model all include it, so the gate must not kill a confirmed DoS just because nothing is read or run.

No such path, no survival. "Looks dangerous," "could be unsafe," a scanner hit with no reachable route, or any claim whose `file:line` does not hold up is dropped — or, if it is a genuine but path-less weakness, moved to the **Hardening** bucket. This folds factual verification into the survival bar: the verifier cannot confirm an exploit it cannot locate and trace in the actual code.

- `low` / `medium`: one verifier per finding.
- `high` / `max`: a **panel of three** verifiers per finding; the finding dies unless a majority confirm the exploit path.
- `max` only — **loop-until-dry:** after verifying, re-run recon-informed hunters on the same pinned scope; keep going until a full round surfaces nothing new, then stop.

### 6. Compile and write the report

Write the report to **`security-reviews/<YYYY-MM-DD>-<slug>.md`** in the worktree, in the shape defined by **`assets/security-report-template.md`** (structure + worked example + clean-bill variant). Get today's date at runtime — `Get-Date -Format yyyy-MM-dd` on Windows, `date +%F` on POSIX. `<slug>` is the current branch lowercased with `/` and non-kebab characters replaced by `-`, or `full-audit` under `--full`. If the file already exists (a same-day re-review), append `-2`, `-3`, ….

Security reports are tracked project evidence. Do **not** add `security-reviews/` to `.gitignore` or `<git-common-dir>/info/exclude`; after writing the report, leave it visible to `git status` so it can be committed with the reviewed work or with the evidence-chain update.

Before treating the report as durable, migrate old local state from the pre-tracked-report flow: resolve `<git-common-dir>` with `git rev-parse --git-common-dir` and inspect `<git-common-dir>/info/exclude`. If it contains an exact stale line that ignores this report directory (`security-reviews/` or `/security-reviews/`), remove just that line before writing the report. If a broader local pattern would still hide `security-reviews/` and cannot be narrowed mechanically, refuse with the offending pattern and tell the user to remove it; a security finding report hidden from `git status` is not durable evidence.

The report leads with the **trust-boundary map**, then findings ordered **most-severe-first** (every `CRITICAL` before any `HIGH`, and so on), then the **Hardening (not findings)** bucket, the **Pre-existing (outside this diff)** note if any, and a brief **Good practices observed** section.

Then surface a concise result in chat: the **Verdict** line (counts by severity), one line per finding (severity + defect + `file:line`), and the report path — not the whole file.

If nothing survives verification, say so plainly ("No exploitable vulnerabilities found in this change") — both in chat and as the report body. Never invent findings to look thorough; a short report with 2 real vulnerabilities is worth more than a long one with 20 theoretical ones.

**`--comment` (optional):** when passed, also post each surviving finding to the PR using `gh`. A finding whose `file:line` falls **within the PR's diff** is posted as an inline review comment on that line; a finding **outside the diff** — common under `--full`, or a "newly exposed" pre-existing sink whose source line this PR never touched — cannot be an inline diff comment, so post it as a normal top-level PR comment that names the `file:line` instead of letting the inline post fail. Off by default. This is the skill's only outward-facing action — it posts findings; it never edits code.

## Findings contract

Each finding — as it leaves a hunter, through verification, and into the report — carries:

- `severity` — `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` (see [severity model](#severity-model))
- `file`, `line`
- `title` — one line, the vulnerability class + what is wrong
- `exploit_path` — **the survival bar**: who → what they send → the traced data flow (with `file:line`) → what they get
- `impact` — what the attacker obtains (data / access / execution / loss of availability) and its blast radius
- `cause` — the actual reason in the code (missing parameterization, absent authz check, …)
- `fix_direction` — one sentence; for the report only, **never acted on**

## Severity model

Severity combines **likelihood** (how reachable, how many preconditions) and **impact** (blast radius). Calibrate against comparable applications and the deployment model — not an OWASP checklist.

- **CRITICAL** — unauthenticated RCE, full data dump, or admin/account takeover **without credentials**.
- **HIGH** — authenticated RCE, SQL injection with exfiltration, stored XSS affecting all users, authentication bypass, or defeating an explicit RBAC/authz boundary.
- **MEDIUM** — conditional/reflected XSS, CSRF causing a state change, credential or secret disclosure to a party who should not have it, business-logic bypass with limited scope.
- **LOW** — non-secret information disclosure, sustained DoS, or a hardening gap with a narrow, high-precondition path.

A weakness with **no** attacker-reachable path is not assigned a severity at all — it goes in the Hardening bucket.

**Reachable-but-low-impact is a finding, not Hardening — unless it is subsumed.** Do not demote a reachable weakness to Hardening merely because its impact is small: an attacker-reachable disclosure with any *independent* value is a **LOW finding** (Hardening is for the *path-less*). But when a candidate's only value is to serve a *different* surviving finding — a verbose-error channel whose sole use is to exfiltrate or to help craft the injection it sits beside — it is **deduped into that finding** as an aggravating factor, not split out as its own LOW finding and not parked in Hardening. Three distinct outcomes: independent reachable impact → its own severity; value wholly subsumed by another finding → deduped into it; no reachable path → Hardening.

## <a id="full-mode"></a>`--full` — whole-repo audit

`--full` swaps the diff scope for the entire repository: recon maps the whole application's attack surface, the five hunters sweep everything (not just changed code), and the "introduced or newly exposed" scope rule does not apply — every reachable vulnerability is in scope regardless of when it was introduced. Everything else — the hunters, the adversarial gate, the severity model, the report shape — is identical. The report slug is `<date>-full-audit`. `--full` is non-incremental in v1: it does not track or skip findings from prior runs (deferred — see repo `TODO.md`).

## Hard rules

- **Explicit-trigger only.** Never auto-run.
- **You orchestrate; the subagents hunt and verify.** Do not substitute a solo read-through for the recon + fan-out + adversarial gate.
- **Read-only on the code. No `--fix`, ever.** Never edit, stage, or apply a fix to the code under review — not even an obvious one. Auto-"fixing" a security finding is exactly the high-stakes, easy-to-get-subtly-wrong edit that can *create* the vulnerability it claims to close; a wrong crypto or auth change is worse than the original. Fixing is a separate act by a separate caller reading this report. The skill's filesystem writes are limited to: the report under `security-reviews/`, removal of an exact stale `security-reviews/` local-exclude line that would hide the tracked report, and (only with `--comment`) PR comments via `gh`. Never edit reviewed code or `.gitignore`.
- **No finding without a verifier-confirmed exploit path.** That rule is the whole point — it is what makes the report trustworthy instead of an alarming pile of maybes. Path-less weaknesses go to Hardening, not Findings.
- **Stay in scope:** exploitability only. No correctness, style, performance, or test-writing as findings — those are `/code-audit` and sibling skills. In diff mode, only what the change introduced or newly exposed; pre-existing vulns go in the trailing note.
- **Scanners are read-only and existing-only.** Never install a tool; never mutate state; run secret scanners non-verifying (`--no-verification`) so a discovered credential is never sent to its provider; note gaps instead of failing.
- **Never persist a raw secret.** A secret finding names `file`, `line`, secret *type*, and rotation guidance — never the credential's value, in the report or a `--comment`. A leak-prevention audit must not become the thing that copies a live secret into a durable, shareable place.
- **Everything resolves from the worktree cwd.** Never reach into another worktree or the main repo.
