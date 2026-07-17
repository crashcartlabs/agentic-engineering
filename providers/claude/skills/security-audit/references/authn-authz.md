# Playbook — Authentication & Authorization

**You own:** *who are you* (authentication) and *are you allowed to do this* (authorization). Broken access control is consistently the highest-impact, most common web vulnerability class — and the one static scanners miss most, because it is about intent, not syntax. The trust-boundary map tells you which routes/handlers are behind which boundary; your job is to find where the boundary is missing or wrong.

**How to hunt:** for each state-changing or data-returning entry point, ask four questions — *Is it authenticated? Is the caller authorized for **this specific object**? Can the check be skipped or forged? And — for anything a browser sends with ambient credentials — can another site trigger it (CSRF)?* An endpoint that only checks "logged in" before touching another user's data is the classic finding.

## Missing / broken access control (authorization)
- **Missing check** — a route mutates or returns data with no authz at all, or only route-level `requireAuth` (authentication) mistaken for authorization.
- **IDOR (object-level)** — the killer. Lookup by an attacker-supplied id with no ownership/tenant scoping:
```ts
// BAD — any logged-in user reads any invoice
app.get('/invoices/:id', requireAuth, (req, res) =>
  res.json(db.invoices.find(req.params.id)))
// GOOD — scoped to the caller
res.json(db.invoices.find({ id: req.params.id, ownerId: req.user.id }))
```
```py
# BAD
Order.objects.get(pk=request.GET["id"])
# GOOD
Order.objects.get(pk=request.GET["id"], customer=request.user)
```
- **Function/field-level** — admin-only actions reachable by normal users (guard is only a hidden UI button); mass-assignment letting a user set `role`/`isAdmin` (see untrusted-input playbook).
- **Path/method gaps** — authz on `GET` but not `DELETE`; on the HTML route but not the JSON API; middleware ordering that lets a route run before the guard.

## Authentication bypass
- Comparisons that fail open: `if (user.token = token)` (assignment), truthy checks on `undefined`, `==` type-juggling, timing-unsafe token compare (use `crypto.timingSafeEqual` / `hmac.compare_digest`).
- Auth decisions from **client-controlled** data — a `userId`/`role` from the request body, header, or a non-verified cookie instead of the session.
- JWT: `alg: none` accepted, signature not verified, secret weak/hardcoded, `verify` vs `decode` confusion, expiry (`exp`) ignored, HS/RS confusion (public key used as HMAC secret).
- Password reset / OTP: guessable or non-expiring tokens, no rate limit, token leaked in a redirect/referer, user-supplied email→token binding not checked.

## Session & token handling
- Cookies missing `HttpOnly` / `Secure` / `SameSite`; tokens in `localStorage` (XSS-readable); session id not rotated on login (fixation).
- No server-side invalidation on logout/password-change; overly long/absent expiry; secret used to sign sessions hardcoded or shared across environments.

## Cross-site request forgery (CSRF)
A route can be correctly authenticated **and** object-authorized and still be exploitable: if the browser attaches credentials **ambiently** (a session cookie, HTTP Basic, a client cert), a malicious page can make the victim's browser fire the request. Auth answers *who*; it does not answer *did the user intend this*.
- **Scope:** any state-changing request (`POST`/`PUT`/`PATCH`/`DELETE`, or a `GET` with side effects) reached with cookie/ambient credentials. Pure token-in-header APIs (`Authorization: Bearer …` read from JS, not auto-sent) are not CSRF-able — the browser won't attach the token cross-site.
- **The finding** is a state-changing, cookie-authenticated route with **no** anti-CSRF control: no CSRF token (synchronizer/double-submit), no `SameSite=Lax|Strict` on the session cookie, and no Origin/Referer check.
```ts
app.post('/account/email', requireAuth, (req, res) => updateEmail(req.user, req.body.email)) // BAD if session is a cookie with no SameSite + no CSRF token
```
- **What defends it — but mind the method:** a verified CSRF token or a strict Origin/Referer allow-list defends any request. `SameSite` on the session cookie is method-sensitive: `SameSite=Lax` is **still sent on top-level cross-site `GET` navigations**, so it only defends *unsafe methods* (POST/PUT/PATCH/DELETE) — a **state-changing `GET`** is not covered by Lax and needs `SameSite=Strict`, a token/Origin check, or (better) to stop having side effects on GET. `SameSite=Strict` closes the cross-site case for all methods. Note which control is present, and for which methods, before clearing a route.
- **Severity:** CSRF causing a state change is MEDIUM per the model (higher only if the changed state is itself a privilege/account takeover, e.g. change-email-then-reset).

## Privilege escalation
Trace whether a lower-privileged actor can reach a higher-privileged action: role derived from mutable input, "become tenant/impersonate" without a check, admin API sharing a handler with a scoping bug.

---
**Survival bar:** name the attacker's role and show the request that crosses the boundary — "any authenticated user calls `DELETE /users/:id` with another id and it succeeds (no ownership check at `users.ts:88`)." A boundary that *is* enforced elsewhere in the path is a Good-practice, not a finding.

**Extend per project:** record the app's real authz model here (roles, tenancy key, the canonical `requireOwner`-style helper) so hunters can spot where it is *not* applied.
