# Discord Messages Reader - Development Notes

## Project Layout

```
appModules/
  discord/__init__.py       - Main AppModule (stable Discord)
  discordptb/__init__.py    - Re-exports AppModule for Discord PTB
  discordcanary/__init__.py - Re-exports AppModule for Discord Canary
tests/
  conftest.py               - NVDA stub installation + app_module fixture
  test_filter.py            - Content normalization and safety tests
  test_announce.py          - Snapshot diff and announcement tests
  test_uia.py               - Structural UIA snapshot tests
  test_history.py           - Alt+1-0 history-reading tests
  test_incremental.py       - Poll cost: incremental reads and discovery backoff
  test_smoke.py             - Lifecycle and event handler smoke tests
  test_build.py             - Packaging and path-safety tests
  test_compatibility.py     - PTB/Canary re-export tests
  test_release_workflow.py  - Release workflow guard tests
manifest.ini                - NVDA add-on manifest
build.py                    - Creates dist/*.nvda-addon (ZIP)
pyproject.toml              - Runs tests from tests/ directory and configures tooling
```

## Build and Test

```bash
powershell -NoProfile -File scripts/check.ps1   # everything CI runs, locally
python build.py             # produces dist/discord_messages_reader-X.X.X.nvda-addon
uv run pytest               # full unit suite
uv run ruff check .         # lint
uv run mypy appModules/discord/  # type check
```

`scripts/check.ps1` is the canonical pre-push gate: it runs every CI check that
can run locally and reports a loud `SKIPPED` banner for any scanner that is not
installed, because a skipped check is not a passed one. Install it as a blocking
hook with `pre-commit install --hook-type pre-push`.

Coverage is a ratchet. `fail_under` is currently 98 and must never be lowered;
raise it when real coverage rises.

Use Python 3.13, matching NVDA 2026.1. Install the locked environment with
`uv sync --locked`. Tool versions are deliberately unpinned so we track latest;
the only pins that stay are GitHub Action commit digests, which Renovate
maintains for supply-chain reasons.

## GitHub Attribution

For commits, PR descriptions, and release notes created with Codex, credit
blindndangerous and Codex (OpenAI). Keep existing Claude attribution when it
applies to older work.

## Installed Location (for rapid iteration)

```
C:\Users\<username>\AppData\Roaming\nvda\addons\discord_messages_reader\appModules\discord\__init__.py
```

After editing, deploy with PowerShell:
```bash
Copy-Item appModules/discord/__init__.py `
  "$env:APPDATA\nvda\addons\discord_messages_reader\appModules\discord\__init__.py" -Force
```
Then restart NVDA (Ctrl+Alt+N) to reload.

## Key Design Decisions

- **UIA polling (500ms)** is the only automatic message-detection path.
- **Poll cost** is the main performance constraint. Polls run on NVDA's main
  thread and every UIA call crosses into Discord's process, so a slow poll lags
  all of NVDA. A poll walks back from the newest list item and stops at the
  first message older than the recheck floor; parsed items are cached by
  identity. Never reintroduce a per-poll read of the whole window. Baselines
  read articles only for recent messages and back to the newest run's author;
  older history is recorded by identity alone. Discovery uses `FindFirst` for
  the document, the `main` landmark and the list in it; consecutive failures
  back off up to `_DISCOVERY_RETRY_MAX_SECONDS`. Cached items are revalidated
  by the list item `Name` (a change detector only, never announced), and a
  read that lost a property is never cached. Alt+1-0 read only the messages
  they need. Measured live on 2026-10-07: about 2 ms per quiet poll, about
  100 ms for a cold channel baseline.
- **Structural discovery** selects the UIA list below Discord's `main` landmark
  and accepts only its `ListItem` children. Text heuristics must not determine
  whether a control is a message, nor which parts of a message are announced.
- **Announcement composition** reads Discord's own automation IDs
  (`message-username-`, `message-content-`, `message-timestamp-`) to select parts
  structurally. These are identifiers, not presentation text, so they survive
  locale changes and Discord restyling. Never announce a bare `Name` from the
  list item or the article: both are Chromium concatenations of every descendant
  and carry the header, a duplicated timestamp, reaction labels and the hover
  toolbar. The timestamp subtree is dropped by ID; the long-form date Discord
  duplicates for tooltips is dropped as offscreen. Embed and attachment *chrome*
  ("Remove all embeds", "Play", "Image", "Open Link", audio transport controls)
  is separated from *content* by whether an element carries a `description`
  child - never by matching label text. Do not reintroduce text matching here.
- **Grouped messages** carry no author element at all: Discord omits the header
  on a run from one author and hoists the timestamp blocks to the top of the
  article, so the two shapes differ structurally. The author of a run is carried
  forward onto its continuations. A run whose author sits above the snapshot
  window stays unattributed rather than guessing.
- **Message identity** is Discord's own message ID from the list item
  AutomationId `chat-messages-<channel>-<message>`, which survives re-renders.
  An item from another channel aborts the snapshot. UIA runtime IDs and then
  occurrence-aware content fingerprints are fallbacks only.
- **What counts as new**: a message ID never seen in this channel and above
  the recheck floor, which is the later of 30 s before the newest ID seen and
  60 s before now (IDs encode creation time). Seen IDs and the newest ID live
  in `_channelMarks`, which outlive snapshot eviction. Discord replaces a
  message being sent with a new list item carrying a larger ID; a seen message
  that vanished while an unseen one with identical text appeared is that
  replacement and is not announced again.
- **Silent baselines** apply on startup, channel changes, foreground return,
  unmute, and recovery. Existing content must never be announced as new.
- **`core.callLater`** is used for all timer scheduling. It is thread-safe
  (internally posts to the main thread), so `_schedulePoll` can be called from
  any thread, including the Dummy-N worker thread NVDA uses when Discord
  launches while NVDA is already running.
- **Foreground, mute and sleep-mode guards** apply before every automatic
  read/output. NVDA's sleep mode only gates scripts and focus events, so the
  poll must check `self.sleepMode` itself.
- **Scripts** use `@script(..., speakOnDemand=True)`; legacy `__gestures`
  scripts are silent in NVDA's on-demand speech mode. All user-facing strings
  go through `_()` / `ngettext()` with translator comments after
  `addonHandler.initTranslation()`.
- **`ui.message`** presents user-facing output in speech and braille at normal
  priority. Do not call `speech.speak(..., Spri.NOW)` for incoming content.
- **Diagnostics** may log state, counts, and opaque identity only. Never log
  Discord message text.
- **Native NVDA events** continue normally. Do not broadly suppress value,
  live-region, or alert events.

## Log Level

The add-on uses debug logging for state and counts only. Load/terminate events
and errors use info or warning levels. Message bodies are never logged.

## Discord PTB / Canary

`discordptb/__init__.py` and `discordcanary/__init__.py` re-export through
`from ..discord import AppModule`. NVDA matches add-on AppModules by executable
name without extension, lowercase.

Full design and audit rationale:
`docs/plans/2026-08-02-audit-hardening-design.md`.
