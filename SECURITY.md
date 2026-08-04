# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's security advisory
form for this repository ("Report a vulnerability" under the Security tab). If that
is unavailable, open an issue that says only that you have a security report and
how to reach you — do **not** include exploit details, secrets, or proof-of-concept
payloads in a public issue.

When reporting:

- Do not include live credentials or secrets in the report; name the file, line,
  and secret *type* instead.
- A concrete reach-and-impact path (who can trigger it, with what input, and what
  they get) makes a report actionable — the same bar this repo's own
  `/security-audit` skill applies.

## Scope notes

- This toolbelt's scripts are pure-stdlib and run locally; the highest-value
  reports concern the installer (`scripts/toolbelt.py`), the sandbox
  (`sandbox/`, `scripts/sandbox/`), and anything that could make a skill or agent
  prompt exfiltrate data or execute untrusted content.
- The Docker sandbox's threat model is documented in `sandbox/README.md`; reports
  that assume a stronger boundary than it claims will be triaged against that
  document.
- Public `main` is a snapshot of a private repository, so fixes may appear here
  only with the next snapshot even when they were addressed promptly in private.
