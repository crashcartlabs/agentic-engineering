# tests — security-audit

Scenarios for the `/security-audit` orchestrator skill.

Last verified: 2026-07-05 — **Scenarios 1–2 live-verified; Scenario 3 (clean bill)
and the `--full` / `--comment` paths design-verified.** First live dogfood of this
skill (it had never been run — DEVLOG 2026-07-01 built it and explicitly deferred the
dogfood). The golden run drove the full documented pipeline — recon → five parallel
attack-class hunters → dedupe → adversarial verification → report — with real
subagents against a purpose-built fixture repo, at `low` effort (one verifier per
finding). The default `high` panel-of-3, `max` loop-until-dry, `--full`, and
`--comment` paths have not been observed.

Fixture: a throwaway git repo (`sec-audit-fixture`) — a small Express service whose
`feature/ping-diagnostics` branch adds a `POST /admin/ping` route that interpolates an
unvalidated `req.body.host` into `exec(\`ping -c 1 ${host}\`)` (a genuine,
attacker-reachable OS command-injection sink on an unauthenticated route).

## Scenario 1 — Golden: real vuln found, verified, and reported (live-verified 2026-07-05)

**Input:** `/security-audit low` run against the fixture's `feature/ping-diagnostics`
branch (base `main`) — a 1-file, +10/−0 diff introducing the command-injection sink.

**Expected output:** Scope pinned and stated (branch/base/file+line counts). A recon
subagent produces a trust-boundary map. Five hunter subagents fan out in parallel,
each reporting only in-lens, diff-introduced findings in the contract shape. Barrier +
dedupe collapse cross-hunter duplicates. Each deduped candidate goes through an
adversarial verifier whose default is "not exploitable"; a finding survives only with
a confirmed, attacker-reachable exploit path traced to real `file:line`. A
candidate whose value is *wholly subsumed* by a surviving finding — its only use is to
serve that exploit — is **deduped into that finding** as an aggravating factor, not
split out as its own LOW finding and not parked in Hardening; a reachable residual with
*independent* value is a finding at its own severity; only a genuinely path-less gap is
Hardening (see the skill's severity model). The report lands at `security-reviews/<date>-<slug>.md` in the
template shape (map → findings most-severe-first → Hardening → Good practices).

**Verify:** Observed 2026-07-05. Recon mapped the unauthenticated entry → shell sink.
Five hunters ran; they independently landed on the injection (1), the missing auth (2
hunters), and the verbose-error leak (2 hunters) — dedupe collapsed those to three
candidates. Three verifiers ran: the command injection was **CONFIRMED CRITICAL**;
the missing access control **CONFIRMED** as an independent MEDIUM (survives even if
the sink were fixed — unauthenticated server-side network probing); the error-leak
candidate was adjudicated **wholly subsumed by finding 1** — both its stderr read-back
(the injection's exfil channel) and its command-template disclosure (recon for crafting
the injection) serve only that exploit and vanish once it is fixed — so it was **deduped
into finding 1** as an aggravating detail, not a separate LOW finding and not a Hardening
item. Final report: **2 findings** (CRITICAL injection, MEDIUM access control).
Honest note on the run: the first draft parked the residual in Hardening; adjudicated per
the sharpened severity model (a subsumed disclosure deduplicates into its parent finding,
it does not become Hardening), this is the boundary case the dogfood surfaced — now
codified in the skill's severity model and LESSONS. Read-only contract held:
the audit changed nothing under review (`git diff HEAD` on the reviewed code was
empty). The tracked-reports change supersedes the old local-exclude detail from that run: future reports
remain visible to git under tracked `security-reviews/`; an old exact
`security-reviews/` local-exclude line is removed before report write, any broader
hiding pattern refuses, and `.gitignore` is still untouched.

## Scenario 2 — Edge: empty diff span (live-verified 2026-07-05)

**Input:** `/security-audit` run with base == HEAD (the fixture on `main`, nothing
changed), no `--full`.

**Expected output:** The skill reports an empty review span and stops — no recon, no
hunters spawn, no report is created, no work is manufactured.

**Verify:** Observed 2026-07-05 — on `main`, the committed (`main...HEAD`),
uncommitted (`diff HEAD`), and untracked spans were all empty, which is the documented
Step-1 stop condition. The pipeline does not proceed past scope-pinning.

## Scenario 3 — Weird: clean bill on a real diff with no reachable vuln (design-verified)

**Input:** A non-trivial diff that introduces no attacker-reachable vulnerability —
e.g. a refactor, or a new route whose input is properly validated/parameterized — so
every hunter returns nothing or every candidate is refuted at the gate.

**Expected output:** The clean-bill report body — `Verdict: No exploitable
vulnerabilities found in this change.` with the trust-boundary map still included (it
shows what was examined) and the Good-practices section — never padded with
speculative findings. Any Hardening / Pre-existing notes that did surface are kept.

**Verify:** Design-traced only. The golden run exercised the fan-out, the gate, and
the Hardening demotion, but every candidate that reached the gate either survived or
was demoted, not fully refuted-to-empty — so the no-findings report shape has not been
observed live. First run on a genuinely clean diff should upgrade this scenario.
