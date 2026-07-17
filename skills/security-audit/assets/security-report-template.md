# Security Audit Report — structure & worked example

The orchestrator writes every review in this shape. It leads with the **trust-boundary map** (the attack surface reasoned about), then **Findings** ordered most-severe-first — every `CRITICAL` before any `HIGH`, and so on. Each finding must carry a verified `Exploit path`; if it has no concrete, attacker-reachable path, it belongs in **Hardening**, not Findings.

## Structure

```
# Security Audit — <branch> vs <base>  (<N files, +X/−Y lines>)   [or: whole repository]

Verdict: <M> confirmed findings (<c> critical, <h> high, <m> medium, <l> low)

## Trust-boundary map
Entry points:   <untrusted-input surfaces in scope — routes, CLI, uploads, queues…>
Reaches:        <what changed/audited code sits downstream of those entry points>
Assets:         <what is privileged/sensitive behind a boundary — DB, secrets, FS, shell…>
Controls:       <existing defenses observed — auth middleware, parameterization, CSP…>

## Findings  (most severe first)

### <n>. [CRITICAL|HIGH|MEDIUM|LOW] <vulnerability class — one-line defect>
`<path>:<line>`
Exploit path: <who — attacker's starting position (unauth / any user / role)>
              <what they send — the triggering input/request>
              <the path — untrusted input → sink, traced with file:line>
              <what they get — data / access / execution they should not have>
Impact:       <what the attacker obtains and the blast radius>
Why:          <the actual cause in the code>
Fix direction: <one sentence; diagnosis only, never applied>

## Hardening (not findings)
Defense-in-depth gaps with no confirmed attacker-reachable path — worth doing, not counted as findings.
- <one line each: the gap, and why it is hardening rather than a vulnerability (which layer already defends)>

## Pre-existing (outside this diff)
Vulnerabilities noticed in passing that this change neither introduced nor exposed — surfaced, not scored. (Omit this section if none, or run /security-audit --full to audit them.)
- <one line each + file:line>

## Good practices observed
- <one line each: the defenses that were present and correct — so the reader sees the review looked at controls, not just holes>
```

## Worked example

This is the bar to hit — a named attacker, a traced path with real `file:line`, a concrete payoff, a one-line fix direction:

```
# Security Audit — add-report-export vs main  (3 files, +148/−12 lines)

Verdict: 2 confirmed findings (1 high, 1 medium)

## Trust-boundary map
Entry points:   POST /api/reports/export (authenticated, any user), body {reportId, format}
Reaches:        ReportService.export() → buildQuery() → db.raw() (new in this diff)
Assets:         Postgres (full app data), report files on local FS
Controls:       requireAuth middleware on the route; no per-row authz in buildQuery

## Findings  (most severe first)

### 1. [HIGH] SQL injection via `format` param concatenated into a raw query
`src/reports/ReportService.ts:74`
Exploit path: any authenticated user sends
              POST /api/reports/export {"reportId":"1","format":"csv'); DROP TABLE users;--"}
              → export() passes `format` unsanitized to buildQuery() (ReportService.ts:74)
              → buildQuery() interpolates it into db.raw(`... FORMAT '${format}'`) (ReportService.ts:91)
              → executes as SQL.
Impact:       full read/write to the Postgres database — exfiltrate or destroy all app data.
              Reachable by any logged-in user; no admin role required.
Why:          `format` is string-interpolated into a raw query instead of parameterized or
              whitelisted; the diff introduced the db.raw() sink.
Fix direction: whitelist `format` against the known export types, or bind it as a parameter.

### 2. [MEDIUM] IDOR — export returns any report by id, no ownership check
`src/reports/ReportService.ts:61`
Exploit path: any authenticated user sends {"reportId":"<someone-else's-id>"}
              → export() loads the report by id with no `WHERE owner_id = currentUser`
              (ReportService.ts:61) → returns another tenant's report contents.
Impact:       cross-tenant read of arbitrary reports (others' business data). Limited to read.
Why:          authorization stops at "is logged in" (route middleware); no per-object check
              was added when the export path was introduced.
Fix direction: scope the report lookup to the caller's owner_id, or assert ownership before export.

## Hardening (not findings)
- No Content-Security-Policy header on the report HTML view — reflected-XSS would be
  contained by one, but no reflected sink was found here, so this is hardening.

## Good practices observed
- The route is behind requireAuth; unauthenticated access is not possible.
- reportId is validated as a UUID before use, blocking a second injection vector.
```

## Clean bill of health

When nothing survives verification, the report body is this — the trust-boundary map still included (it shows what was examined), never padded with speculative findings. **If the run still surfaced Hardening items or Pre-existing notes, keep those sections** (after the map, before Good practices) — SKILL.md says they are reported whether or not any finding survives, so a clean *finding* count must not silently drop them. Reserve the bare shape below for a run with **no findings, no hardening, and no pre-existing notes**:

```
# Security Audit — <branch> vs <base>  (<N files, +X/−Y lines>)

Verdict: No exploitable vulnerabilities found in this change.

## Trust-boundary map
<the map — so the reader sees the attack surface that was examined and cleared>

## Good practices observed
- <the defenses that made it clean>
```
