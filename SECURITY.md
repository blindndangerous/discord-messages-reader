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

## Scope

In scope:

- The NVDA addon code in `appModules/`.
- The build / packaging pipeline (`build.py`, manifest).
- Anything that processes Discord text content reaching NVDA.

Out of scope:

- Third-party deps.  Report those upstream.
- Discord-side issues.  Report to Discord.
- NVDA core issues.  Report to nvaccess.org.
