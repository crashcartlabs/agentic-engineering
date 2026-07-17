# Playbook — Configuration, dependencies & error handling

**You own:** insecure configuration and defaults, missing/weak security headers and CORS, known-vulnerable dependencies, and information leakage through errors. This lens is the most tool-assisted — you **may run read-only analyzers that already exist** and fold their output into findings; you must **never install a tool or mutate state**, and you note gaps instead of failing.

**Scanners (existing, read-only only):**
- Dependencies: `npm audit --json` / `yarn npm audit` / `pnpm audit --json`; `pip-audit` **pointed at the project's inputs** (`pip-audit -r requirements.txt`, a `pyproject.toml`/project path, or an activated project venv) — bare `pip-audit` audits the *host* Python environment, so in CI or this meta-repo it reports the agent host's CVEs while missing the audited project's `requirements.txt`/`pyproject.toml`; `osv-scanner -r .`; `trivy fs --skip-db-update --skip-java-db-update --skip-check-update .` — bare `trivy fs .` **downloads/updates its vulnerability DB into its cache** by default, which breaks the never-mutate rule, so require the skip-update flags (and if the DB is absent, note the gap rather than letting it fetch). These make an **outbound call to a public advisory DB** — that is expected and read-only; do not run anything that uploads code or hits non-advisory endpoints. A **nonzero exit is normally the "vulnerabilities found" signal, not a failure** (`npm audit` and `pip-audit` both exit nonzero on findings) — capture and parse the output regardless of exit code.
- If none is installed: report "no dependency scanner available" and fall back to reasoning about pinned versions — but reasoning alone cannot know CVEs, so say so rather than implying the deps are clean.

## Vulnerable dependencies
- Map scanner output to **reachability**: a CVE in a package the app actually calls on an untrusted path is a real finding; a CVE in a dev-only/unreached dependency is Hardening or LOW. Severity follows the CVE *and* whether the vulnerable code path is reachable in this app — do not blindly copy the scanner's CRITICAL for an unused transitive dep.
- Flag: lockfile pinned to a version with a known-exploited CVE; overly loose ranges (`"^"`/`"*"`) on security-sensitive libs; abandoned/unmaintained packages on the request path; a `postinstall` script from an untrusted dep (supply-chain).

## Security headers & CORS
- **CORS misconfig (high-signal):**
```ts
app.use(cors({ origin: true, credentials: true }))  // BAD — reflects any origin WITH creds
res.setHeader('Access-Control-Allow-Origin', req.headers.origin)  // BAD if creds allowed
```
Reflecting the request origin while `credentials:true` lets any site make authenticated cross-origin calls — a real account-data-theft finding. An allow-list of origins is the fix. `origin:'*'` **without** credentials is usually fine/Hardening.
- **Missing headers** (mostly Hardening unless they enable a *found* attack): `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options`/`frame-ancestors` (clickjacking on sensitive actions can be MEDIUM). Report a missing header as a *finding* only when it is the thing that makes a demonstrated attack work; otherwise Hardening.

## Insecure defaults & configuration
- Debug mode on in production (`DEBUG=True` Django, Flask debugger/Werkzeug console = RCE, `app.debug`), admin/default credentials, sample endpoints left enabled.
- Directory listing on, source maps or `.git`/`.env` served, verbose server banners.
- TLS: verification disabled (`rejectUnauthorized:false`, `verify=False`, `NODE_TLS_REJECT_UNAUTHORIZED=0`), weak protocol/cipher config, cleartext HTTP for auth/data (coordinate with secrets-crypto — report once).
- Missing **rate limiting / brute-force protection** on auth, OTP, and expensive endpoints — a finding when it enables a concrete attack (credential stuffing, OTP guessing), Hardening otherwise.

## Error handling & information leakage
- Stack traces, exception messages, SQL errors, or internal paths returned to the client:
```py
return jsonify(error=str(e)), 500                   # BAD — leaks internals
# GOOD: log the detail server-side, return a generic message + request id
```
- Different responses/timing that reveal whether an account exists (user enumeration) on login/reset.
- Errors that leak stack/SQL can also *chain* — they hand an injection attacker the feedback they need. Note that where relevant.

---
**Survival bar:** a misconfiguration is a *finding* only with a concrete attack it enables (reflect-origin-with-credentials → cross-site authenticated read; `DEBUG=True` → RCE console; a reachable CVE with a known exploit). Otherwise it is Hardening. Always state whether a CVE's vulnerable path is actually reachable.

**Extend per project:** record the app's deployment model (which headers the edge/proxy already sets, the real allowed origins, the prod config source) so hunters don't flag a control that lives one layer up.
