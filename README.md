![CI](https://github.com/blindndangerous/discord-messages-reader/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/blindndangerous/discord-messages-reader/graph/badge.svg)](https://codecov.io/gh/blindndangerous/discord-messages-reader)

# Discord Messages Reader

An NVDA add-on that automatically announces incoming Discord chat messages as they arrive, without requiring you to navigate away from what you are doing.

## How It Works

Discord is built on Chromium/Electron. NVDA's standard accessibility hooks can become unreliable for the message list when focus is in the chat input field. This add-on reads Discord's UI Automation (UIA) tree every 500 milliseconds. It tracks structurally identified message nodes per channel, announces newly added entries in order, and establishes a silent baseline when Discord starts, changes channel, returns to the foreground, or is unmuted.

Announcements use NVDA's standard message API, so they are presented through both speech and braille without forcing highest-priority speech.

## Requirements

- NVDA 2026.1 (tested with NVDA 2026.1.1)
- Discord (stable, PTB, or Canary builds)
- A Windows version supported by NVDA 2026.1

## Installation

1. Download the latest `discord_messages_reader-X.X.X.nvda-addon` file from the [Releases](../../releases) page.
2. Open the file. NVDA will prompt you to install it.
3. Restart NVDA when prompted.
4. Open Discord. The add-on activates automatically.

See [SECURITY.md](SECURITY.md) for signature and checksum verification steps.

## Usage

No configuration is required. Once installed:

- Open a Discord channel or direct message conversation.
- Incoming messages are announced automatically as they arrive.
- Announcements only happen when Discord is the active (foreground) window.
- Discord controls that are not structurally exposed as messages are ignored.

### Keyboard Shortcuts

- `NVDA+Alt+Shift+D`: Toggle automatic announcements on or off.
- `Alt+1`: Read the most recent message.
- `Alt+2` through `Alt+9`: Read the 2nd through 9th most recent message.
- `Alt+0`: Read the 10th most recent message.

All gestures appear under **Discord Messages Reader** in NVDA's Input Gestures dialog and can be rebound there.

## Known Limitations

- Messages are announced up to 500 milliseconds after they appear in Discord's UI, which is the polling interval.
- Only messages currently exposed in Discord's UIA tree can be detected. Messages virtualized out of the visible accessibility tree are unavailable to the add-on.
- Automatic announcements only occur while Discord is the foreground application. Returning to Discord establishes a silent baseline so older messages are not mistaken for new arrivals. Use `Alt+1` through `Alt+0` to review currently exposed messages.
- Discord UI updates can change its accessibility structure. Please report regressions with the Discord and NVDA versions, but redact private content from logs before attaching them.

## Supported Discord Builds

- `Discord.exe` (stable)
- `DiscordPTB.exe` (public test build)
- `DiscordCanary.exe` (canary)

## Building From Source

Requires Python 3.13.12, matching NVDA 2026.1, and uv.

```
git clone https://github.com/blindndangerous/discord-messages-reader.git
cd discord-messages-reader
uv sync --locked
uv run python build.py
```

The distributable add-on file is written to `dist/`.

### Running Tests

```
uv sync --locked
uv run pytest
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Authors

- **[blindndangerous](https://github.com/blindndangerous)** - concept, requirements, and testing
- **[Claude Sonnet](https://claude.ai)** (Anthropic) - implementation and architecture
- **Codex** (OpenAI) - maintenance fixes and test updates
