# Security Policy

## Supported versions

Security fixes are evaluated for the current `main` branch and the latest
published release, when a release exists. Older development snapshots and
unmaintained releases may not receive fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability and do not include
secrets, tokens, private user data, or exploit details in public automation
logs.

Use GitHub Private Vulnerability Reporting for this repository when it is
enabled. If that feature is unavailable, contact the repository owner through
a private channel associated with the repository or project. This repository
does not publish or invent a security email address.

Include only the information needed to reproduce and assess the issue:

- affected revision and component;
- impact and prerequisites;
- minimal reproduction steps or proof of concept;
- known mitigations; and
- a safe way to continue private coordination.

Maintainers will assess reports according to severity, reproducibility, and
available capacity. They may request clarification, coordinate a fix and
disclosure, or explain why a report is out of scope. No acknowledgement,
resolution, or disclosure timeline is guaranteed.

## Secrets and sensitive data

Never commit credentials. Local development and tests use mock providers,
local JSON data, and fixture services. AWS access uses short-lived GitHub OIDC
credentials only in explicitly authorized deployment jobs. Production secret
values belong in the approved external secret store and must not appear in
GitHub variables, workflow artifacts, issue bodies, or test fixtures.
`task secrets:check` scans tracked files for credential shapes and hardcoded
account identifiers.

If a secret is exposed, stop using it and privately notify the owner so the
relevant provider can rotate or revoke it. Removing a value from Git history
does not make the credential safe again.
