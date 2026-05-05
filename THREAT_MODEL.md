# Threat Model: discord-messages-reader

Last reviewed: 2026-05-05.  Re-review every major release.

## Scope

NVDA addon (`appModules/discord/`) that reads Discord text content
through screen readers.  Single-user, runs in-process inside NVDA.
No network listener.  No persistent server.

## STRIDE per surface

| STRIDE | Threat | Mitigation |
|---|---|---|
| Spoofing | n/a, local single user | OS + NVDA process boundary |
| Tampering | Discord text feed contains crafted content (RTL overrides, markdown injection, control chars) | Sanitise / strip control chars before passing to NVDA speech.  Treat all incoming text as untrusted |
| Repudiation | n/a | n/a |
| Information disclosure | Reading private messages aloud in shared spaces | User-controlled mute / opt-out per channel |
| Denial of service | Discord flood floods NVDA speech queue | Rate-limit / coalesce repeated messages |
| Elevation of privilege | Addon runs with NVDA user privileges | NVDA addon-store signing; no eval / exec on addon-loaded code |

## Subprocess + filesystem

Addon does not spawn subprocesses.  No file writes outside the NVDA
addon-data directory.

## Dependencies

- `pyproject.toml` + `uv.lock` committed.
- `pip-audit` runs in CI.
- Renovate opens PRs on dep bumps.

## Reporting a vulnerability

[`SECURITY.md`](SECURITY.md).
