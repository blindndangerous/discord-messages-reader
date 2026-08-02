# Full project audit — 2026-08-02

## Outcome

This audit supports a 2.0.0 release. The add-on now targets NVDA 2026.1 as its minimum and last-tested API version, with live validation on NVDA 2026.1.1. Development and CI use Python 3.13.12, the interpreter version pinned by NVDA's 2026.1 release branch.

## Runtime and accessibility

- Replaced WinEvent callbacks and broad NVDA event suppression with one foreground-only UI Automation polling path.
- Added per-channel, bounded snapshots with stable message identities and ordered-tail comparison. Startup, channel changes, foreground returns, re-enabling announcements, and recovery establish silent baselines so old messages are not replayed.
- Limited discovery to the Discord message list under the locale-independent `main` landmark. Only list items are treated as messages; separators and unrelated navigation or complementary lists are ignored.
- Bound provider traversal, retained channels, snapshot size, burst size, message length, and announcement length.
- Routed output through `ui.message`, NVDA's standard speech-and-braille presentation API.
- Changed the announcement toggle to `NVDA+Alt+Shift+D`. The former `NVDA+Control+Shift+D` binding is owned globally by the Application Dictionary add-on and can prevent an AppModule command from running.
- Fixed Discord PTB and Canary loading by using package-relative imports.
- Made termination idempotent and ensured the polling timer is stopped once.

Live checks used NVDA 2026.1.1 and the screen-readers MCP bridge. Discord produced a 12-item silent baseline, the new toggle gesture ran in the Discord AppModule, deterministic speech capture received the status message, and re-enabling announcements created another silent baseline. This NVDA session had no active braille output, so the bridge had no braille cells to capture; unit tests verify use of `ui.message` rather than a speech-only API.

## Security and privacy

- Restricted channel identity to canonical HTTPS channel URLs on `discord.com`, `ptb.discord.com`, and `canary.discord.com`.
- Removed message bodies, usernames, and channel names from diagnostic logs. Channel identifiers are hashed before logging.
- Removed control characters and bidirectional formatting controls before retaining or presenting text.
- Documented nearby-listener disclosure, log-redaction guidance, trust boundaries, attack surfaces, and residual risks.
- Hardened packaging against missing inputs, unsafe archive paths, symlinks, junctions, partial output, and cleanup failures.
- Pinned GitHub Actions by immutable commit, locked Python dependencies, and added reproducible builds, SBOMs, checksums, and Sigstore signing to tagged releases.

No known dependency vulnerabilities, high or critical filesystem findings, hard-coded secrets, private keys, unsafe symlinks, or Bandit findings were detected.

## Build, maintenance, and release engineering

- Made add-on archives deterministic and limited them to the documented eight release files.
- Added offline help and connected it through `manifest.ini`.
- Removed the duplicate `requirements-dev.txt`; `pyproject.toml` and `uv.lock` are authoritative.
- Added Renovate configuration for Python metadata, the uv lockfile, pre-commit hooks, GitHub Actions digests, and weekly lock-file maintenance. No Dependabot configuration remains.
- Added release checks that require a matching tag, changelog entry, manifest version, and commit on `main`, followed by tests, security scans, two matching builds, SBOM generation, signing, and publication.

## Verification

- Python 3.13.12: 91 tests passed with 89.68% coverage.
- Ruff lint and format checks passed.
- Mypy passed.
- Bandit reported no issues.
- pip-audit and OSV-Scanner reported no known vulnerabilities.
- Trivy reported no high or critical vulnerabilities, secrets, or misconfigurations.
- All pre-commit hooks passed.
- Renovate 41.140.1 validated `renovate.json`.
- Two independent 2.0.0 builds matched at SHA-256 `FF8924668B07AC21BF23F2EED44538D6EBFC0EDA3DAC608AD0ED4DEA8EE057C7`.

## Remaining operational risks

- Discord can change its Chromium accessibility tree. Bounded structural discovery fails closed and silently re-baselines, but a future Discord update may still require selector maintenance.
- Automatic speech can disclose private message content to nearby people. The toggle and documentation reduce, but cannot remove, that physical disclosure risk.
- Repository rules currently require signed commits, but do not require pull-request reviews, status checks, or administrator enforcement. Those settings need a repository-owner policy decision.
- `renovate.json` is ready, but Renovate will not open updates until its GitHub App is installed or another Renovate runner is authorized for this repository.

No additional end-user features were added. Per-channel mute controls, own-message filtering, settings persistence, and broader localization remain possible future work, but were kept out of this security and reliability release.
