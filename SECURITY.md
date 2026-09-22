# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |
| < 0.1 | ❌ |

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private security advisories
(Security tab → Report a vulnerability). Include: what you found, how to
reproduce it, and what you think the impact is. The maintainer will
acknowledge within a week and keep you posted on the fix.

## Scope

In scope: the harness, SDK, CLI, CI, and dataset tooling. Out of scope:
individual adapters' scores (a bad score is a measurement, not a
vulnerability) and the private holdout's *contents* — but the holdout's
*handling* (encryption, access controls) is in scope and treated as
critical.
