# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- NVDA no longer lags while Discord is in the foreground. Every poll, twice a
  second, re-read the full accessibility subtree of every visible message on
  NVDA's main thread: thousands of cross-process calls that held up speech,
  braille and keyboard input. A poll now walks back from the newest message and
  stops at the last one it already knows, so a quiet channel costs a handful of
  calls. Message list items are remembered by their UIA runtime ID and read
  again only when their content changes.
- The Friends page, settings and other pages without a channel no longer search
  the whole Discord window on every poll. Discord's document stays cached there,
  and repeated failed searches back off to one every four seconds.
- Alt+1 through Alt+0 read only the messages they need instead of the whole
  window. Edits and late embeds are still heard.
- Opening or switching channels no longer freezes NVDA for half a second.
  Baselines read only recent messages, and discovery finds Discord's message
  list directly instead of searching the whole window. Measured on NVDA 2026.2:
  a cold channel baseline went from about 810 ms to about 100 ms.
- Messages are identified by Discord's own message IDs. A new message is no
  longer lost when the previous newest message is deleted at the same moment,
  or when Discord re-renders a message, or when someone else posts while your
  own message is being sent.
- Your own message is announced once. Before, Discord replacing the message
  being sent with the delivered one forced a silent baseline that could swallow
  someone else's message.
- History is never announced as new: a message more than a minute old by its
  Discord timestamp stays silent, whether you scrolled to it, opened it from a
  link, or the add-on had forgotten the channel.
- Nothing is announced while NVDA is in sleep mode for Discord.
- Alt+1 through Alt+0 and the toggle speak in NVDA's on-demand speech mode.

### Changed

- Commands use NVDA's `@script` decorator, and every user-facing string is
  ready for translation.
- The add-on package no longer includes the developer README and threat model.
- Release versions must be `major.minor` or `major.minor.patch`, as the NVDA
  Add-on Store requires.
- Tested with NVDA 2026.2.

---

## [2.1.0] - 2026-08-29

### Fixed

- Incoming messages are announced again. Discord now appends a message id to the
  channel URL (`/channels/<guild>/<channel>/<message>`), which no longer matched
  the expected channel URL shape, so every poll found no channel document and
  silently established a baseline instead of announcing. Channel identity now
  ignores the trailing message id, so it also stays stable as that id changes.

- Grouped consecutive messages name their author again. Discord omits the header
  on a run of messages from one person, so those entries carried no author at
  all. The author of a run is now carried forward onto its continuations, which
  is what Discord shows visually.

### Changed

- Announcements are composed from Discord's own labelled message parts instead
  of a concatenation of every descendant. Both the list item name and the
  article name run the header, body, reactions and toolbar together; the parts
  are identified structurally by Discord's `message-username-`,
  `message-content-` and `message-timestamp-` automation IDs, so no presentation
  text is inspected.

- Announcements no longer read the timestamp. Both the visible short form and
  the hidden long form (`Friday, August 28, 2026 11:53 PM`) are dropped.

- Announcements no longer read embed and attachment chrome — `Remove all
  embeds`, `Play`, `Image`, `Open Link`, and the audio player's transport
  controls. Embed *content* is kept: a shared link still announces its platform,
  channel and title. Chrome is separated from content structurally, by whether
  an element carries a `description` child.

- Reaction shortcodes, "Click to react" labels and the hover toolbar
  (`Add Reaction`, `Edit`, `Forward`, `More`) are no longer announced.

- Structural discovery failures log a debug reason (`no-uia-root`,
  `no-documents`, `no-channel-document`, `no-message-list`) when the state
  changes, so a silent add-on can be diagnosed from the NVDA log. No Discord
  content is logged.

- A body-less message - an image, sticker or file post - no longer causes the
  messages after it to be announced under the wrong name. Its author is now
  recorded even though it has no text to compose, so the grouped run that
  follows is attributed correctly.

- Polling can no longer stop for good. An unexpected error inside one poll left
  the timer unscheduled, so the add-on went silent until NVDA restarted, with
  nothing to indicate it had stopped.

- A message detached by Discord's list virtualization mid-read no longer aborts
  the whole snapshot. Aborting turned the following poll into a silent baseline,
  so everything that arrived in between was never announced.

- Long messages scrolled partly out of view are no longer truncated. Hidden text
  is skipped only outside the message body, which still drops Discord's
  duplicated long-form date without swallowing real content.

- Repeated identical failures are logged once rather than twice a second.

### Security

- `pip` 26.1.2 to 26.2.1, resolving PYSEC-2026-3721.

- Workflows no longer persist credentials into the workspace
  (`persist-credentials: false` on every checkout), and the release job no longer
  restores a build cache, which closed a cache-poisoning path into published
  signed artifacts.

- Added zizmor, a GitHub Actions security scanner, to CI and the local suite.
  actionlint checks workflow syntax; zizmor checks for workflow vulnerabilities,
  and found both issues above.

### Removed

- Trivy. It scanned only `uv.lock`, which OSV-Scanner and pip-audit already
  cover; its secret scanner duplicates Gitleaks; its misconfiguration scanner had
  no infrastructure files to read; and it accounted for roughly 70% of the local
  suite's runtime.

- The unused `hypothesis` development dependency.

---

## [2.0.0] - 2026-08-02

### Added

- Discord PTB and Canary now load through package-relative imports, with regression coverage for NVDA's package loading behavior.
- Offline add-on help documents setup, gestures, privacy behavior, and known limitations.
- Release artifacts now include CycloneDX and SPDX SBOMs, checksums, and Sigstore signatures.
- Renovate configuration covers Python development dependencies, the uv lockfile, pre-commit hooks, and pinned GitHub Actions.

### Changed

- NVDA 2026.1 is now both the minimum supported and last-tested API release, with live testing on NVDA 2026.1.1. Development and CI use Python 3.13.12, matching NVDA 2026.1.
- Message detection now uses bounded structural UIA snapshots keyed by Discord channel and message identity. Startup, channel changes, foreground returns, re-enabling announcements, and recovery from read failures establish silent baselines.
- Announcements use NVDA's standard message API, so output reaches speech and braille at normal priority.
- The announcement toggle is now `NVDA+Alt+Shift+D`, avoiding the global gesture used by the Application Dictionary add-on.
- Packaging is deterministic and rejects missing files, unsafe paths, symlinks, junctions, and partial writes.
- CI and release workflows use locked dependencies and immutable GitHub Actions revisions. Tag releases must come from `main`, pass tests and security checks, and reproduce the same add-on archive twice.

### Fixed

- Automatic announcements no longer depend on unreliable WinEvent callbacks or broad NVDA event suppression.
- Message text is stripped of control and bidirectional-formatting characters, normalized, and length-limited before presentation.
- Diagnostic logging no longer records Discord message bodies.
- AppModule shutdown is idempotent and cancels its poll timer once.

### Removed

- Support declarations for NVDA versions older than 2026.1.
- The duplicate `requirements-dev.txt`; `pyproject.toml` and `uv.lock` are now the only development dependency definitions.

---

## [1.1.6] - 2026-04-11

### Added
- Message list element caching (`_getMsgListViaUIA`): the expensive UIA `FindAll` tree walk is now skipped on subsequent polls when the element is still valid, eliminating lag in the Discord window. Cache is invalidated on COM errors or channel switch. (Contribution by aryanchoudharypro)
- `pytest-cov` with 70% coverage threshold, `pytest-mock`, `bandit`, and `pip-audit` added to the dev toolchain.
- CI now runs ruff format check (on `tests/`), bandit security scan, and pip-audit CVE scan as separate jobs.
- `CHANGELOG.md` added.

### Changed
- Toggle gesture changed from `NVDA+Shift+D` to `NVDA+Ctrl+Shift+D` to avoid conflict with NVDA's built-in "report formatting at the cursor" gesture.
- Timer scheduling switched from `wx.CallAfter` + `wx.CallLater` to `core.callLater` throughout — the NVDA-idiomatic thread-safe API, simpler than the two-method workaround introduced in v1.1.5.
- CI test job migrated from `pip install -r requirements-dev.txt` to `uv sync` + `uv run pytest`.
- Ruff rule set expanded to include `I` (isort), `B` (bugbear), `C4`, `SIM`, `RUF`; all new violations fixed.
- `try/except/pass` blocks replaced with `contextlib.suppress` throughout.

---

## [1.1.5] - 2026-04-11

### Fixed
- **Critical crash** (`wxAssertionError: timer can only be started from the main thread`) when Discord launches while NVDA is already running. NVDA creates the AppModule on a Dummy-N worker thread in this case; `wx.CallLater` is not safe to call from a non-main thread. Fixed by splitting `_schedulePoll` into two methods: `_schedulePoll` posts to the main thread via `wx.CallAfter`, and `_startPollTimer` creates the timer there.

---

## [1.1.4] - 2026-04-11

### Fixed
- Wrapped all `speech.speak` call sites in `try/except` so a synthesiser crash cannot propagate out of `_doAnnounce`, `script_toggleAnnounce`, or `_readNthLastMessage`.
- `_winEventCallback` now wrapped in `try/except`; an exception in the ctypes callback body no longer propagates to the Windows message pump.
- `_winEventCallback` no longer stores `hwnd=0`; zero is not a valid window handle and was causing spurious UIA lookups.

---

## [1.1.3] - 2026-04-11

### Fixed
- `_scheduleAnnounce` was updating `_lastText` before checking `_announceEnabled`, permanently deduplicating messages received while announcements were disabled. Fixed by checking the flag first.
- `_uiaRead` now returns immediately if `_terminated` is set, preventing a queued `wx.CallAfter` from firing after `terminate()`.
- `event_alert` now uses separate `try/except` blocks for `obj.name` and `obj.value` so a COM error on the name does not suppress the value fallback.
- Case-insensitive status suffix filtering (`_STATUS_SUFFIXES_LOWER`).

---

## [1.1.2] - 2026-04-11

### Fixed
- `COMError` crash in `event_UIA_liveRegionChange`, `event_liveRegionChange`, and `event_alert` during Discord startup when COM objects are not yet stable. All three handlers now wrap `obj.name` access in `try/except`.

---

## [1.1.1] - 2026-04-11

### Fixed
- Toggle (`NVDA+Shift+D`) was not actually stopping UIA polling — `_announceEnabled` was checked in `_scheduleAnnounce` but polling continued, wasting CPU. Fixed so the flag is honoured.

---

## [1.1.0] - 2026-04-11

### Added
- **History reading**: `Alt+1` through `Alt+0` read the 1st through 10th most recent messages from the UIA tree, oldest-first.
- **Announce toggle**: `NVDA+Shift+D` toggles automatic announcement on/off with spoken confirmation.
- Script category "Discord Messages Reader" for the NVDA Input Gestures dialog.

---

## [1.0.0] - 2026-04-10

### Added
- Initial release: automatic announcement of incoming Discord chat messages via UIA polling (500 ms interval).
- IAccessible WinEvent hook as a fast-path trigger when the message list is active.
- Message deduplication based on content.
- Foreground guard: announcements suppressed when Discord is not the active window.
- Support for Discord stable, PTB, and Canary via re-export modules.
- `event_valueChange` suppression to prevent the edit-field clear from cancelling announcements.
