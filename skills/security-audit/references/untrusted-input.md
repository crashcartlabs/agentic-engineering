# Playbook — Untrusted input & unsafe deserialization

**You own:** what happens when the shape, size, or type of attacker input is trusted — unsafe deserialization, file uploads, mass assignment, prototype pollution, XXE, open redirects, and algorithmic-complexity DoS. The theme: the code assumes input is well-formed and benign, and an attacker breaks that assumption.

**How to hunt:** at each entry point, find where input is *parsed into structure* or *bound to a model* and ask what an attacker can put there that the code does not expect — extra fields, a giant payload, a crafted object, an unexpected type.

## Hardening threat-model checklist

For each defended surface before proposing or expanding hardening:

- Enumerate every `open`/write/delete/rename/exec call that can affect the surface,
  including temp files, pidfiles, generated outputs, uploads, and extraction targets.
- Enumerate every check-use ordering: validation before write, liveness check before
  signal, existence/type check before open, temp path before rename, parser check
  before binding, and any TOCTOU window between them.
- State the trust boundary: who can write, replace, or influence each path, payload,
  config, process id, archive member, redirect target, or structured field.
- **Rule:** state the trust boundary; stop hardening past it unless a new documented trust boundary expands the scope.

## Unsafe deserialization
Turning attacker bytes into live objects is frequently RCE.
```py
pickle.loads(request.data)                          # BAD — arbitrary code execution
yaml.load(user_input)                               # BAD — use yaml.safe_load
```
```ts
// node-serialize / eval-based revivers, or JSON.parse feeding a class hydrator
```
Flag: `pickle`/`marshal`/`shelve` on untrusted data, `yaml.load` (non-safe), Java/PHP native deserialization, `eval`/`Function`/`vm.runInContext` on input, reviver functions that instantiate classes from type tags.

## File uploads
Trace an uploaded file end to end:
- **Type/size not validated** — relying on client `Content-Type` or extension only; no max size (→ DoS/disk fill).
- **Path from filename** — user filename used as the storage path → path traversal / overwrite (sanitize to a generated name; see injection playbook).
- **Executable destination** — writing into a web-served or executable directory (upload `shell.php`/`.jsp` → RCE), or served back with a sniffable content-type enabling stored XSS (SVG/HTML).
- **Content confusion** — image parsers, zip extraction (Zip Slip), CSV formula injection on export.

## Mass assignment / over-posting
Binding a whole request body to a model lets the attacker set fields they should not:
```ts
User.update(req.params.id, req.body)                // BAD — body may carry {role:"admin"}
User.update(req.params.id, pick(req.body, ['name','email']))  // GOOD — allow-list
```
```py
form = UserForm(request.POST); user.__dict__.update(form.cleaned_data)  # BAD if unfiltered
```
Flag: `Object.assign(model, req.body)`, spreading `...req.body` into a create/update, Rails-style `params.permit!`, serializers without an explicit field list. Especially dangerous for `role`, `isAdmin`, `ownerId`, `balance`, `verified`.

## Prototype pollution (JS)
Merging attacker JSON into an object without guarding `__proto__`/`constructor`/`prototype` — `merge(target, req.body)`, `_.set(obj, userKey, val)`, unsafe deep-merge/`extend`. Impact ranges from DoS to RCE/authz-bypass depending on downstream reads. Flag recursive merges and dynamic key assignment from input.

## XXE
XML parsers with external entities enabled (default in some libs) → file read / SSRF. Disable DTD/external entities: `libxml_disable_entity_loader`, `defusedxml` (Python), `noent:false` and disabled DTD (Node parsers). Applies to XML, SVG, DOCX/XLSX ingestion, SOAP.

## Open redirect
`res.redirect(req.query.next)` / `redirect(request.GET["url"])` with no allow-list → phishing, OAuth token theft via redirect_uri. Require relative-path-only or a host allow-list.

## ReDoS & resource exhaustion
Attacker-controlled input against a catastrophic-backtracking regex (nested quantifiers `(a+)+`), or unbounded loops/allocations sized by input (huge JSON, deep nesting, decompression bombs). Flag input-driven regexes and missing size/depth caps.

---
**Survival bar:** show the specific malformed/oversized/crafted input and what it achieves (code executed, field elevated, file read, service wedged), traced to the parsing/binding site. "Deserializes JSON" is normal; `pickle.loads` on request data is a finding.

**Extend per project:** note the app's model-binding helpers, upload pipeline, and any custom parsers so future runs check them by name.
