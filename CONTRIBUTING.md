# Contributing to Discord Messages Reader

Thanks for wanting to help! Here is everything you need to go from zero to a working development setup.

## Prerequisites

- Python 3.11 or later
- NVDA (any recent version) — only needed if you want to test the live add-on in Discord, not required for running unit tests
- Git

## Setting up

```
git clone https://github.com/blindndangerous/discord-messages-reader.git
cd discord-messages-reader
pip install -r requirements-dev.txt
```

## Running the tests

```
pytest
```

All 68 tests run without NVDA installed. They use lightweight stubs that mock every NVDA module. If you add new behaviour, add a test for it — the CI workflow will run your tests automatically on every pull request.

## Project layout

```
appModules/
  discord/__init__.py       — Main AppModule (stable Discord)
  discordptb/__init__.py    — Re-exports AppModule for Discord PTB
  discordcanary/__init__.py — Re-exports AppModule for Discord Canary
tests/
  conftest.py               — NVDA stub installation and app_module fixture
  test_filter.py            — _filterAndAnnounce unit tests
  test_announce.py          — _scheduleAnnounce / _doAnnounce unit tests
  test_uia.py               — _getLatestMessageViaUIA mock tests
  test_smoke.py             — Lifecycle and event handler smoke tests
manifest.ini                — NVDA add-on manifest
build.py                    — Creates dist/*.nvda-addon
```

## Building the add-on

```
python build.py
```

This writes `dist/discord_messages_reader-X.X.X.nvda-addon` — a ZIP file that NVDA can install directly.

## Testing your changes live in Discord

If you want to try a change in real Discord without a full reinstall:

1. Copy the changed file into the installed add-on:

```
cp appModules/discord/__init__.py \
   "$APPDATA/nvda/addons/discord_messages_reader/appModules/discord/__init__.py"
```

2. Restart NVDA with Ctrl+Alt+N.

Changes take effect immediately on the next NVDA start.

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Make your changes.
3. Run `pytest` — all tests must pass.
4. Push your branch and open a pull request. The PR template will give you a short checklist.

The CI workflow runs automatically on your PR. A passing green check is required before merging.

## Key design decisions

See `CLAUDE.md` for a full explanation of why the add-on works the way it does — UIA polling interval, WinEvent debounce, content dedup, foreground guard, log levels, and more. Read that before making structural changes so you understand the trade-offs that were already considered.
