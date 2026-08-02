# Security Policy

## Supported versions

Only the latest tagged release on `main` receives security updates.

## Reporting a vulnerability

Do not open a public issue for security reports.  Use GitHub's private
vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe what you found, how to reproduce, and the impact.

You can expect:

- An acknowledgement within 7 days.
- A fix or status update within 30 days for confirmed reports.
- Credit in release notes if you'd like to be named (anonymous
  reports also welcome).

## Verifying release assets

Releases produced by the hardened release workflow include the add-on, two SBOM
files, `SHA256SUMS`, and a Sigstore bundle and detached signature for each file.
Older releases may not include these files.

Install Cosign, download the release assets, and verify the checksum manifest:

```powershell
cosign verify-blob `
  --bundle SHA256SUMS.bundle `
  --certificate-identity-regexp '^https://github\.com/blindndangerous/discord-messages-reader/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' `
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' `
  SHA256SUMS
```

Compare the add-on's local hash with its line in the verified checksum file:

```powershell
Get-FileHash .\discord_messages_reader-*.nvda-addon -Algorithm SHA256
Get-Content .\SHA256SUMS
```

You can also run the same `cosign verify-blob` command against an individual
asset by replacing `SHA256SUMS` and `SHA256SUMS.bundle` with that asset and its
bundle.

## Scope

In scope:

- The NVDA addon code in `appModules/`.
- The build / packaging pipeline (`build.py`, manifest).
- Anything that processes Discord text content reaching NVDA.
- Vulnerable dependency or GitHub Actions revisions used by this repository.

Out of scope:

- Vulnerabilities in third-party software that this repository does not use.
- Discord-side issues.  Report to Discord.
- NVDA core issues.  Report to nvaccess.org.
