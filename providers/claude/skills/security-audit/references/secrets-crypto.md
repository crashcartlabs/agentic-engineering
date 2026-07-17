# Playbook — Secrets, sensitive data & cryptography

**You own:** credentials and keys that should not be in the code, sensitive data that leaks out through logs/responses/errors, and cryptography that is present but weak or misused. This lens may run **read-only secret scanners** that already exist (`gitleaks dir --redact .`, `trufflehog filesystem . --no-verification --no-update`) and fold their hits into findings — never install one; if absent, note the gap. Use `gitleaks dir` (working-tree/filesystem scan), **not** `gitleaks detect` — `detect`/git mode walks committed history via `git log -p` and would miss the uncommitted and untracked files this skill deliberately pulls into the pinned scope (scan committed history separately only if you need it). **Run them non-verifying:** TruffleHog's default validates each hit by calling the provider, which sends the discovered secret off-box — `--no-verification` prevents that; never enable verification. **Never write the raw secret value** into a finding, the report, or a `--comment` — only `file`, `line`, secret *type*, and rotation guidance. Reposting a live credential is the leak this lens exists to stop.

**How to hunt:** for secrets, scan added/changed code (and, under `--full`, the tree) for high-entropy strings and known key shapes. For data exposure, follow sensitive values (passwords, tokens, PII) *outward* — into logs, API responses, error bodies, URLs. For crypto, find each cryptographic call and check the primitive and its parameters.

## Hardcoded secrets
```ts
const stripe = new Stripe("sk_live_51H...")         // BAD — live key in source
const apiKey = process.env.STRIPE_KEY               // GOOD — from env
```
- Flag: API keys, DB/connection strings with passwords, private keys (`-----BEGIN ... PRIVATE KEY-----`), JWT signing secrets, cloud creds (`AKIA...`), OAuth client secrets, webhook signing secrets.
- Config/`.env` files committed; secrets in Dockerfiles, CI YAML, test fixtures, or default fallbacks (`process.env.SECRET || "dev-secret"` — the fallback ships to prod).
- **Impact/severity depends on reach:** a *live* credential to a real system is HIGH+; a rotated/example/localhost-only value is LOW or Hardening. Say which — do not report a placeholder as CRITICAL. A committed secret should be treated as compromised (needs rotation), note that in the fix direction.

## Sensitive data exposure
- **In responses:** serializing a whole user/DB row returns `passwordHash`, `mfaSecret`, internal ids, other users' fields. Look for `res.json(user)` / `return model_to_dict(user)` without a field allow-list (DTO/serializer).
- **In logs:** `console.log(req.body)`, logging tokens/passwords/PII/full request objects. Log-aggregation makes these durable and widely readable.
- **In URLs:** secrets/tokens in query strings (end up in logs, referer headers, browser history).
- **In errors:** returning raw exception text / stack traces / SQL to the client (overlaps config-deps error handling — coordinate; report once).

## Weak or misused cryptography
- **Password storage:** MD5/SHA1/SHA256 (fast hashes) or unsalted → cracking. Require bcrypt/scrypt/argon2.
```py
hashlib.md5(pw.encode()).hexdigest()                # BAD
bcrypt.hashpw(pw.encode(), bcrypt.gensalt())        # GOOD
```
- **Wrong randomness for security:** `Math.random()`, `random.random()`, predictable/time-seeded values used for tokens, session ids, password-reset codes, IVs. Require a CSPRNG: `crypto.randomBytes`/`crypto.randomUUID`, `secrets.token_urlsafe`, `os.urandom`.
- **Symmetric misuse:** AES-ECB (patterns leak), static/reused IV or nonce, key derived from a password without a KDF, encrypt-without-authenticate (use AES-GCM or encrypt-then-MAC).
- **Deprecated/broken:** DES/3DES/RC4, MD5/SHA1 for signatures, TLS/cert verification disabled (`rejectUnauthorized:false`, `verify=False`) — belongs here or config-deps; report once.
- **Home-rolled crypto:** custom "encryption"/XOR, custom token signing — almost always a finding.

---
**Survival bar:** for a secret, a **high-confidence match is enough** — a recognizable credential/key *shape* in a real, reachable location (source, committed config, a log/response path), named by type and with a plausible account of what it unlocks. You do **not** — and must not — validate it live against the provider; a committed, real-looking secret is treated as **compromised (rotate)**, not dropped for lack of live proof. (Rule out obvious placeholders/examples/localhost-only values, which are LOW or Hardening.) For data exposure, show the untrusted-reachable response/log path and what leaks to whom; for crypto, name the primitive, the misuse, and the concrete consequence (offline cracking, forgeable token, decryptable data). "Uses SHA256 somewhere" with no security dependency is not a finding.

**Extend per project:** list the app's real secret names/shapes and its sensitive fields (the PII columns, the token formats) so future runs flag them precisely.
