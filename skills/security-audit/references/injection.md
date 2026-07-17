# Playbook — Injection & output handling

**You own:** any place untrusted input crosses into an interpreter — SQL/NoSQL, the OS shell, an HTML/JS sink, a template engine, a filesystem path, an outbound URL, or a response/log header. The pattern is always the same: **untrusted data reaches a sink without the sink's escaping/parameterization/allow-listing.**

**How to hunt:** start from the trust-boundary map's entry points, follow each untrusted value forward to a sink. A sink is only a finding if a value the attacker controls actually reaches it — trace the path, cite the `file:line` at each hop. A hardcoded or fully-validated value reaching a "dangerous" API is not a finding.

## SQL / NoSQL injection
String-built queries are the tell. Look for interpolation/concatenation into query text, and for ORM "raw" escapes.
```ts
db.query(`SELECT * FROM users WHERE email = '${email}'`)   // BAD
db.query('SELECT * FROM users WHERE email = $1', [email])  // GOOD — parameterized
knex.raw(`... WHERE name = '${name}'`)                       // BAD — raw() defeats the builder
```
```py
cur.execute(f"SELECT * FROM users WHERE id = {uid}")        # BAD
cur.execute("SELECT * FROM users WHERE id = %s", (uid,))    # GOOD
```
- NoSQL: attacker-controlled **objects** (not just strings) — `{ "$gt": "" }` in a Mongo filter → auth bypass. Query built from `req.body` without shape validation.
- ORMs: `.whereRaw()`, `.orderByRaw()`, `sequelize.literal()`, `.extra()` (Django) with interpolation. `ORDER BY`/column names can't be parameterized — must be allow-listed.

## OS command injection
```ts
exec(`convert ${userFile} out.png`)                 // BAD — shell metachar injection
execFile('convert', [userFile, 'out.png'])          // GOOD — no shell, args as array
```
```py
os.system("ping " + host)                           # BAD
subprocess.run(["ping", host])                      # GOOD — no shell=True, list args
subprocess.run(f"ping {host}", shell=True)          # BAD — shell=True + interpolation
```
Flag: `shell=True`, `child_process.exec`, backticks/`eval` of shell strings, any string-built command line.

## XSS (reflected / stored / DOM)
```tsx
element.innerHTML = userInput                       // BAD
<div dangerouslySetInnerHTML={{__html: userInput}}/>// BAD unless sanitized (DOMPurify)
res.send(`<p>${userComment}</p>`)                   // BAD — server-side reflected
```
- Stored XSS is HIGH (hits every viewer); reflected/DOM is usually MEDIUM. Framework auto-escaping (React text nodes, Jinja/Django autoescape) defends the default path — the finding is where code *opts out* (`innerHTML`, `|safe`, `mark_safe`, `v-html`, `Markup()`).
- URL sinks: `href="javascript:..."`, `location = userInput`, `window.open(userInput)`.

## Template injection (SSTI)
User input used as the **template**, not the data: `render_template_string(user)`, Jinja/Handlebars/EJS built from input → often RCE. Data goes *through* a fixed template; the template itself is never attacker-controlled.

## Path traversal
```ts
fs.readFile(path.join(baseDir, req.query.name))     // BAD — name = "../../etc/passwd"
```
Require a **boundary-aware** containment check, not a prefix match: resolve to an absolute path, then confirm it stays under the intended root with `path.relative(root, resolved)` that is non-empty, does **not** start with `..`, and is **not** absolute (equivalently, `resolved === root || resolved.startsWith(root + path.sep)`). Reject `..`, absolute paths, null bytes. Flag `resolved.startsWith(root)` on its own as **insufficient** — a bare prefix match lets a sibling directory through (root `/srv/uploads`, resolved `/srv/uploads_evil/secret`), so a hunter must not accept it as a guard nor recommend it as the fix. Same for zip extraction (Zip Slip), file downloads, upload destinations.

## SSRF
Attacker controls a URL the server fetches (`fetch`, `axios`, `requests.get`, image/webhook/PDF fetchers). Impact: hit cloud metadata (`169.254.169.254`), internal services, `file://`. Allow-listing hosts defends it; blocklists and naive regexes do not (DNS rebinding, redirects, decimal IPs).

## Header / log / CRLF injection
User input in response headers (`Location`, `Set-Cookie`), in log lines (forged entries / log-forging), or in email headers. `\r\n` in a redirect target → response splitting.

---
**Survival bar:** a finding needs a traced path from a named attacker's input to the sink, with the concrete payoff (rows read, command run, script executed). A dangerous-looking API with only constant/validated input reaching it is not a finding — at most Hardening.

**Extend per project:** add app-specific sinks here (a custom query builder, a homegrown templating helper, an internal HTTP client) so future runs check them by name.
