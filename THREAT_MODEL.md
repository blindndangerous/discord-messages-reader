# Threat Model: discord-messages-reader

Last reviewed: 2026-08-02. Re-review every major release.

## Scope

NVDA add-on (`appModules/discord/`) that reads Discord text content through
UI Automation. Single-user, runs in-process inside NVDA. No network listener,
subprocess, or persistent service is included in the add-on.

## Threats and mitigations

- Crafted Discord content: Text is treated as untrusted data, never executed.
  Speech-disrupting control and bidirectional-formatting characters are removed,
  whitespace is normalized, and output length is bounded before presentation.
- Private-message disclosure: Automatic output requires Discord to be the
  foreground window and can be disabled globally with the add-on gesture.
  Diagnostic logs record counts and state, not message bodies.
- Speech denial of service: New entries are bounded and coalesced per polling
  cycle. Announcements use normal NVDA message priority instead of repeatedly
  forcing highest-priority speech.
- Stale or spoofed UI controls: Only list items from the UIA list below
  Discord's `main` landmark are accepted. Channel transitions and foreground
  returns establish a silent baseline rather than treating existing content as
  new.
- Add-on privilege: Code runs with the user's NVDA privileges. Runtime code does
  not use `eval`, `exec`, network access, subprocesses, or arbitrary file writes.
- Release tampering: Builds are deterministic, release actions are pinned to
  immutable revisions, and release artifacts are accompanied by keyless signing
  bundles and SBOMs. Users must still verify release provenance.

## Subprocess + filesystem

Runtime code does not spawn subprocesses or write files.

## Dependencies

- `pyproject.toml` and `uv.lock` are committed; CI installs with `--locked`.
- Bandit, pip-audit, OSV-Scanner, Trivy, and Gitleaks run in automation.
- Renovate is configured for Python, pre-commit, and GitHub Actions dependencies.
- GitHub Actions use immutable commit pins.

## Residual risks

- Speech can disclose private content to nearby people. Foreground gating and
  global mute reduce this risk but cannot determine who can hear the computer.
- No per-channel mute exists in this release.
- Discord controls its accessibility tree. A Discord update can temporarily
  hide messages or change structural properties.
- Repository branch protection, tag protection, and release-environment approval
  are GitHub settings and cannot be enforced by source files alone.
- Renovate must be installed and granted access to the repository. No Renovate
  pull request or Dependency Dashboard exists yet, so repository onboarding still
  needs external confirmation.
- Releases published before this hardening work may not contain signatures or
  SBOMs. Verify claims against assets attached to the specific release.

## Reporting a vulnerability

[`SECURITY.md`](SECURITY.md).
