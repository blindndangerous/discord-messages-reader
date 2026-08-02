# Discord Messages Reader audit hardening design

Date: 2026-08-02

## Decisions

- Support only current stable NVDA: minimum and last-tested API version 2026.1.
- Develop and verify against NVDA 2026.1.1's embedded Python 3.13 runtime.
- Fix confirmed correctness, privacy, accessibility, security, packaging, and CI defects first.
- Defer optional product features and settings expansion.
- Keep `main` untouched; work on `audit/defect-hardening` in an isolated worktree.

## Approaches considered

### Patch existing text deduplication

Smallest diff, but keeps global `_lastText`, duplicated filters, stale-message announcements, identical-message loss, English-only list matching, and whole-window event races. Rejected.

### Preserve WinEvent acceleration and add synchronization

Could reduce nominal latency, but requires strict hook-thread ownership, message-loop lifetime management, callback coalescing, and correlation with NVDA events. Existing 500 ms poll already supplies fallback. Complexity and privacy risk exceed measured value. Rejected.

### Structural UIA snapshots with one polling path

Selected. Discord exposes a channel document with a stable channel URL and a message list below its `main` landmark. Its `ListItem` children provide ordered messages and UIA runtime IDs. Each poll takes a bounded ordered snapshot, compares it with the previous snapshot for that channel, and announces only additions. One path removes hook lifecycle and duplicate-event behavior.

## Runtime architecture

`AppModule` owns one periodic reader. Reads occur only while Discord is foreground and announcements are enabled. Background, mute, channel change, cache recovery, and first activation establish a silent baseline.

Discovery uses structural UIA conditions:

- channel identity: current Discord channel document value/URL;
- message container: the UIA list below the `main` landmark;
- message entries: direct `ListItem` children of that container;
- item identity: UIA runtime ID, with occurrence-aware text fingerprints only as fallback.

Snapshots preserve visible order and use bounded storage. A burst is announced in order through one coalesced user-facing notification, capped for safe speech/braille length with an explicit overflow count. Existing history gestures read the current structural snapshot.

All automatic announcement paths share foreground and mute gates. User-facing output uses NVDA `ui.message`, providing speech and braille. Incoming content is normalized, strips speech-disrupting control and bidirectional formatting characters, and has length limits. Diagnostic logs contain counts and identities, never message bodies.

WinEvent hooks, broad `event_valueChange` suppression, and custom live-region/alert speech handlers are removed. NVDA handles native events normally; add-on polling handles incoming-message announcements once.

## Compatibility and packaging

- `requires-python`, Ruff, mypy, CI, and developer documentation target Python 3.13.
- Manifest minimum and tested NVDA versions both become 2026.1.
- PTB and Canary import the shared app module through package-relative imports.
- Build rejects symlinks, uses deterministic ZIP metadata/order, and includes `LICENSE` and user documentation.

## Delivery security

- Dependency installation uses the committed lockfile.
- Release tests run on Windows, matching Win32 imports.
- GitHub Actions are pinned to immutable commit SHAs.
- Release validation proves the tag commit descends from `origin/main`.
- Signing and publishing use separate least-privilege jobs.
- Release gates repeat lint, tests, dependency audit, and static security checks.
- Threat-model claims are changed to match implemented behavior; repository-setting gaps remain documented when code cannot enforce them.

## Verification

- Unit tests cover silent baselines, channel changes, foreground transitions, identical messages, bursts, structural filtering, sanitization, braille-capable output, imports, and deterministic builds.
- Static gates: Ruff, mypy, Bandit, pip-audit, OSV, Trivy, and Gitleaks where locally available.
- Package inspection verifies contents, paths, timestamps, and repeatable hash.
- Live NVDA MCP session verifies NVDA 2026.1.1 connection, focus, state, gesture execution, deterministic speech capture, and add-on behavior in Discord. Braille presentation uses `ui.message` and is captured when an active braille output is available.

## Deferred work

Settings UI, persistent per-channel mute, own-message suppression, localization catalogs, editable priority/rate/format, and broader Discord variant/E2E matrices remain separate product work unless required to close a confirmed defect.
