# Discord Messages Reader

An NVDA add-on that automatically announces incoming Discord chat messages as they arrive, without requiring you to navigate away from what you are doing.

## How It Works

Discord is built on Chromium/Electron. NVDA's standard accessibility hooks become unreliable for the message list when focus is in the chat input field. This add-on bypasses that limitation by reading Discord's UI Automation (UIA) tree directly, polling every 500 milliseconds for new messages. When a new message appears, it is spoken immediately at the highest speech priority so it is never missed.

## Requirements

- NVDA 2024.1 or later
- Discord (stable, PTB, or Canary builds)
- Windows 10 or later

## Installation

1. Download the latest `discord_messages_reader-X.X.X.nvda-addon` file from the [Releases](../../releases) page.
2. Open the file. NVDA will prompt you to install it.
3. Restart NVDA when prompted.
4. Open Discord. The add-on activates automatically.

## Usage

No configuration is required. Once installed:

- Open a Discord channel or direct message conversation.
- Incoming messages are announced automatically as they arrive.
- Announcements only happen when Discord is the active (foreground) window.
- Typing indicators and status changes are filtered out silently.

## Known Limitations

- Messages are announced up to 500 milliseconds after they appear in Discord's UI, which is the polling interval.
- The add-on reads the most recently visible message. If several messages arrive in rapid succession during a polling gap, only the last one is announced.
- The add-on only announces messages when Discord is the foreground application. Messages received while you are in another application are not announced.

## Supported Discord Builds

- `Discord.exe` (stable)
- `DiscordPTB.exe` (public test build)
- `DiscordCanary.exe` (canary)

## Building From Source

Requires Python 3.x.

```
git clone https://github.com/blindndangerous/discord-messages-reader.git
cd discord-messages-reader
python build.py
```

The distributable add-on file is written to `dist/`.

### Running Tests

```
pip install pytest
pytest
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Authors

- **[blindndangerous](https://github.com/blindndangerous)** — concept, requirements, and testing
- **[Claude Sonnet](https://claude.ai)** (Anthropic) — implementation and architecture
