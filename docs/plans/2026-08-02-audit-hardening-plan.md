# Discord Messages Reader audit hardening implementation plan

> Execute each task test-first. Keep commits small enough for independent review.

**Goal:** Close confirmed audit defects while supporting only NVDA 2026.1+ and leaving a reproducible, hardened release path.

**Architecture:** Replace mixed WinEvent/event/polling behavior with one structural UIA snapshot poller. Use stable channel and message identities, silent baselines, safe coalesced speech+braille output, and privacy-preserving diagnostics.

**Runtime:** Python 3.13, NVDA 2026.1.1, UI Automation, pytest, uv, Ruff, mypy.

---

## Task 1: Compatibility and package imports

**Files:** `pyproject.toml`, `.tool-versions`, `manifest.ini`, `README.md`, `appModules/discordptb/__init__.py`, `appModules/discordcanary/__init__.py`, `tests/test_smoke.py`, `tests/conftest.py`, `uv.lock`.

1. Add failing package-namespace import tests for PTB and Canary.
2. Change imports to `from ..discord import AppModule`.
3. Change Python tooling to 3.13 and NVDA manifest range to 2026.1 through 2026.1.
4. Regenerate lockfile under Python 3.13.
5. Run namespace tests, full pytest, Ruff, and mypy.

## Task 2: Structural snapshots and silent baselines

**Files:** `appModules/discord/__init__.py`, `tests/conftest.py`, `tests/test_uia.py`, `tests/test_announce.py`, `tests/test_history.py`, `tests/test_smoke.py`.

1. Add failing tests for message-list discovery below the `main` landmark, stable channel identity, first-read silence, channel-change silence, foreground-return silence, repeated identical messages, and ordered bursts.
2. Add immutable message/snapshot data structures and runtime-ID fallback identities.
3. Replace duplicated text filters with structural snapshot extraction.
4. Replace global `_lastText` with bounded per-channel snapshot state.
5. Make history gestures consume current structural snapshot.
6. Run focused tests, full pytest, Ruff, and mypy.

## Task 3: Privacy, accessibility, and event simplification

**Files:** `appModules/discord/__init__.py`, `tests/test_announce.py`, `tests/test_filter.py`, `tests/test_smoke.py`, `README.md`, `THREAT_MODEL.md`.

1. Add failing tests for background silence, mute/resume baselines, control/Bidi sanitization, bounded burst output, speech+braille presentation, and normal NVDA event chaining.
2. Route user-facing output through `ui.message`.
3. Add normalization and bounded coalescing.
4. Remove WinEvent hook lifecycle, broad value-change suppression, and duplicate custom live-region handlers.
5. Remove private message bodies from logs.
6. Update README and threat model to match actual behavior.
7. Run focused tests, full pytest, Ruff, mypy, and Bandit.

## Task 4: Deterministic safe packaging

**Files:** `build.py`, `tests/test_build.py`, `README.md`.

1. Add failing tests for required files, symlink rejection, normalized ZIP metadata, path safety, stable ordering, and identical repeated-build hashes.
2. Refactor build into testable functions.
3. Include `LICENSE`, `README.md`, and `THREAT_MODEL.md` in package.
4. Normalize timestamps, permissions, compression, and archive paths.
5. Run build tests twice and compare SHA-256.

## Task 5: CI and release security

**Files:** `.github/workflows/ci.yml`, `.github/workflows/security.yml`, `.github/workflows/release.yml`, `renovate.json`, `requirements-dev.txt`, `CONTRIBUTING.md`, `SECURITY.md`.

1. Pin all actions to verified full commit SHAs with version comments.
2. Use Python 3.13 and `uv sync --locked` everywhere.
3. Run release tests on Windows and repeat security gates for tag builds.
4. Remove broken manual release dispatch or require explicit validated tag input.
5. Prove tag ancestry from `origin/main`.
6. Separate keyless signing from GitHub release publishing permissions.
7. Remove duplicate release globs and stale CVE exceptions.
8. Add dependency update configuration and document repository-setting requirements.
9. Parse workflow YAML and run local equivalents of every gate.

## Task 6: Integrated and live verification

**Files:** candidate add-on artifact and installed development copy; no source changes unless a defect is reproduced.

1. Run pytest with coverage, Ruff, format check, mypy, Bandit, pip-audit, OSV, Trivy, and Gitleaks.
2. Build twice and confirm identical hashes and safe archive contents.
3. Install candidate into NVDA development add-on directory and reload/restart NVDA as required.
4. Use screen-reader MCP in live mode to record version, focus, state, speech, and braille behavior in Discord.
5. Exercise startup, channel switch, burst, identical message, mute, background, history, PTB, and Canary paths where available.
6. Restore user focus and disconnect MCP cleanly.

## Task 7: Review and clean handoff

1. Run code simplification review without behavior changes.
2. Run independent correctness, accessibility, and security reviews.
3. Fix confirmed review findings test-first.
4. Run final verification from clean state.
5. Commit changes; ensure branch and worktree show no untracked or modified files.
6. Report remaining external repository settings and deferred product features.
