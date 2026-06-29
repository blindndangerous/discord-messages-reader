# Contributing to Discord Messages Reader

Use this setup for local development.

## Prerequisites

- Python 3.14
- uv
- NVDA (any recent version), only needed if you want to test the live add-on in Discord
- Git

## Setting up

```
git clone https://github.com/blindndangerous/discord-messages-reader.git
cd discord-messages-reader
uv sync --all-extras
```

## Running the tests

```
uv run pytest
```

The test suite runs without NVDA installed. It uses stubs for the NVDA modules. If you add new behaviour, add a test for it. CI runs the tests on every pull request.

## Project layout

```
appModules/
  discord/__init__.py       - Main AppModule (stable Discord)
  discordptb/__init__.py    - Re-exports AppModule for Discord PTB
  discordcanary/__init__.py - Re-exports AppModule for Discord Canary
tests/
  conftest.py               - NVDA stub installation and app_module fixture
  test_filter.py            - _filterAndAnnounce unit tests
  test_announce.py          - _scheduleAnnounce / _doAnnounce unit tests
  test_uia.py               - _getLatestMessageViaUIA mock tests
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

Read `CLAUDE.md` before structural changes. It covers UIA polling, WinEvent debounce, content dedup, foreground guard, log levels, and the trade-offs behind them.
