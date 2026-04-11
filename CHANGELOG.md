# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
