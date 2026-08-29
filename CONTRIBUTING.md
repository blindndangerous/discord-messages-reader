# Contributing to Discord Messages Reader

Use this setup for local development.

## Prerequisites

- Python 3.13.12
- uv
- NVDA 2026.1.1, only needed for live Discord testing
- Git

## Setting up

```
git clone https://github.com/blindndangerous/discord-messages-reader.git
cd discord-messages-reader
uv sync --locked
```

## Running the tests

```
uv run pytest
```

The test suite runs without NVDA installed. It uses stubs for the NVDA modules. If you add new behaviour, add a test for it. CI runs the tests on every pull request.

## Running the full check suite

`scripts/check.ps1` runs the same checks CI runs, in one pass:

```
powershell -NoProfile -File scripts/check.ps1
```

It runs ruff (lint and format check), mypy, pytest, bandit, pip-audit, osv-scanner, and a Trivy filesystem scan. Every check runs even if an earlier one fails, so one run shows everything that is broken. A summary table is printed at the end and the script exits non-zero if any check failed. The whole suite takes about 30 seconds.

osv-scanner and Trivy are external tools and are not installed by `uv sync`. Install them with:

```
winget install Google.OSVScanner
winget install AquaSecurity.Trivy
```

No tool versions are pinned. The script uses whatever `uv`, `osv-scanner`, and `trivy` are on your PATH. If a scanner is missing, its check is reported as `SKIPPED` with a loud banner rather than passing silently, and the rest of the suite still runs.

## Git hooks

The project uses `pre-commit` for both commit-time and push-time hooks. Install both:

```
pre-commit install
pre-commit install --hook-type pre-push
```

The commit hooks are the fast ones: whitespace and file checks, gitleaks, actionlint, ruff, bandit, and mypy. The pre-push hook is a single `local-ci` hook that runs `scripts/check.ps1`. It blocks the push if any check fails, so CI failures are caught before they reach GitHub. Nothing runs at both stages.

## Project layout

```
appModules/
  discord/__init__.py       - Main AppModule (stable Discord)
  discordptb/__init__.py    - Re-exports AppModule for Discord PTB
  discordcanary/__init__.py - Re-exports AppModule for Discord Canary
tests/
  conftest.py               - NVDA stub installation and app_module fixture
  test_filter.py            - content normalization and safety tests
  test_announce.py          - snapshot diff and announcement tests
  test_uia.py               - structural UIA snapshot tests
  test_history.py           - Alt+1-0 history-reading tests
  test_smoke.py             - Lifecycle and event handler smoke tests
manifest.ini                - NVDA add-on manifest
build.py                    - Creates dist/*.nvda-addon
pyproject.toml              - Test, lint, type-check, and dependency config
```

## Building the add-on

```
uv run python build.py
```

This writes `dist/discord_messages_reader-X.X.X.nvda-addon`, a ZIP file that NVDA can install directly.

## Testing your changes live in Discord

If you want to try a change in real Discord without a full reinstall:

1. Copy the changed file into the installed add-on:

```
Copy-Item appModules/discord/__init__.py `
  "$env:APPDATA\nvda\addons\discord_messages_reader\appModules\discord\__init__.py" -Force
```

2. Restart NVDA with Ctrl+Alt+N.

Changes take effect immediately on the next NVDA start.

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Make your changes.
3. Run `uv run pytest`. All tests must pass.
4. Push your branch and open a pull request. The PR template will give you a short checklist.

The CI workflow runs automatically on your PR. A passing green check is required before merging.

## Key design decisions

Read `docs/plans/2026-08-02-audit-hardening-design.md` before structural changes. It covers UIA polling, structural identity, per-channel snapshots, silent baselines, foreground privacy, and release hardening.
