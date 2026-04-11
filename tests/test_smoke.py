"""Smoke tests — lifecycle and integration paths.

These tests exercise the module's lifecycle (load, terminate) and the
high-level paths (_uiaRead foreground guard, WinEvent callback, NVDA event
handlers) without requiring a live Discord process or NVDA session.
"""
import sys
import time
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module load / terminate
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_init_registers_winevent_hook(self):
        with patch('ctypes.windll') as mock_windll, \
             patch('core.callLater', return_value=MagicMock()):
            mock_windll.user32.SetWinEventHook.return_value = 0xBEEF
            from discord import AppModule
            m = AppModule()
            assert mock_windll.user32.SetWinEventHook.called
            m._terminated = True
            m._hook = None
            m._pollTimer = None

    def test_init_starts_poll_timer(self):
        with patch('ctypes.windll') as mock_windll, \
             patch('core.callLater', return_value=MagicMock()) as mock_timer:
            mock_windll.user32.SetWinEventHook.return_value = 0xBEEF
            from discord import AppModule
            m = AppModule()
            assert mock_timer.called
            m._terminated = True
            m._hook = None
            m._pollTimer = None

    def test_terminate_unhooks_winevent(self, app_module):
        with patch('ctypes.windll') as mock_windll:
            mock_windll.user32.UnhookWinEvent.return_value = True
            app_module._hook = 0xDEAD
            app_module._terminated = False
            app_module.terminate()
            mock_windll.user32.UnhookWinEvent.assert_called_once_with(0xDEAD)
            assert app_module._hook is None

    def test_terminate_stops_poll_timer(self, app_module):
        mock_timer = MagicMock()
        app_module._pollTimer = mock_timer
        app_module._hook = None
        app_module._terminated = False
        app_module.terminate()
        mock_timer.Stop.assert_called_once()
        assert app_module._pollTimer is None

    def test_terminate_is_idempotent(self, app_module):
        """Calling terminate twice must not raise."""
        app_module._hook = None
        app_module._pollTimer = None
        app_module._terminated = False
        app_module.terminate()
        app_module.terminate()  # second call — should not crash


# ---------------------------------------------------------------------------
# Foreground guard in _uiaRead
# ---------------------------------------------------------------------------

class TestForegroundGuard:
    def test_skips_when_discord_not_foreground(self, app_module):
        api = sys.modules['api']
        other_app = MagicMock()
        other_app.appModule = MagicMock()  # a different appModule
        api.getForegroundObject.return_value = other_app

        spy = MagicMock(return_value=None)
        app_module._getLatestMessageViaUIA = spy
        app_module._uiaRead()
        spy.assert_not_called()

    def test_skips_when_foreground_is_none(self, app_module):
        sys.modules['api'].getForegroundObject.return_value = None
        spy = MagicMock(return_value=None)
        app_module._getLatestMessageViaUIA = spy
        app_module._uiaRead()
        spy.assert_not_called()

    def test_reads_when_discord_is_foreground(self, app_module):
        api = sys.modules['api']
        fg = MagicMock()
        fg.appModule = app_module
        api.getForegroundObject.return_value = fg

        spy = MagicMock(return_value=None)
        app_module._getLatestMessageViaUIA = spy
        app_module._uiaRead()
        spy.assert_called_once()

    def test_new_message_announced_when_foreground(self, app_module):
        api = sys.modules['api']
        fg = MagicMock()
        fg.appModule = app_module
        api.getForegroundObject.return_value = fg

        app_module._getLatestMessageViaUIA = MagicMock(
            return_value="alice , hi , 9:04 AM"
        )
        announce_spy = MagicMock()
        app_module._filterAndAnnounce = announce_spy
        app_module._uiaRead()
        announce_spy.assert_called_once_with("alice , hi , 9:04 AM")


# ---------------------------------------------------------------------------
# WinEvent callback
# ---------------------------------------------------------------------------

class TestWinEventCallback:
    def test_learns_hwnd_on_first_fire(self, app_module):
        app_module._discordHwnd = 0
        app_module._winEventCallback(None, None, 0xCAFE, None, None, None, None)
        assert app_module._discordHwnd == 0xCAFE

    def test_does_not_overwrite_known_hwnd(self, app_module):
        app_module._discordHwnd = 0x1111
        app_module._winEventCallback(None, None, 0x2222, None, None, None, None)
        assert app_module._discordHwnd == 0x1111

    def test_updates_last_hook_time(self, app_module):
        before = time.time()
        app_module._winEventCallback(None, None, 0xABC, None, None, None, None)
        assert app_module._lastHookTime >= before

    def test_triggers_immediate_uia_read_when_not_debounced(self, app_module):
        core = sys.modules['core']
        core.callLater.reset_mock()
        app_module._lastUiaRead = 0.0  # no recent read — debounce inactive
        app_module._winEventCallback(None, None, 0xABC, None, None, None, None)
        core.callLater.assert_called_once_with(0, app_module._uiaRead)

    def test_debounce_suppresses_rapid_winevent_triggers(self, app_module):
        core = sys.modules['core']
        core.callLater.reset_mock()
        app_module._lastUiaRead = time.time()  # read just ran
        app_module._winEventCallback(None, None, 0xABC, None, None, None, None)
        core.callLater.assert_not_called()


# ---------------------------------------------------------------------------
# NVDA event handlers
# ---------------------------------------------------------------------------

class TestEventHandlers:
    def test_value_change_suppressed_within_two_seconds(self, app_module):
        app_module._lastHookTime = time.time()
        next_handler = MagicMock()
        app_module.event_valueChange(MagicMock(), next_handler)
        next_handler.assert_not_called()

    def test_value_change_allowed_after_two_seconds(self, app_module):
        app_module._lastHookTime = time.time() - 3.0
        next_handler = MagicMock()
        app_module.event_valueChange(MagicMock(), next_handler)
        next_handler.assert_called_once()

    @pytest.mark.parametrize("handler_name", [
        'event_UIA_liveRegionChange',
        'event_liveRegionChange',
    ])
    def test_live_region_announces_real_message(self, app_module, handler_name):
        obj = MagicMock()
        obj.name = "some real message content"
        spy = MagicMock()
        app_module._filterAndAnnounce = spy
        next_handler = MagicMock()
        getattr(app_module, handler_name)(obj, next_handler)
        spy.assert_called_once_with("some real message content")
        next_handler.assert_called_once()

    @pytest.mark.parametrize("handler_name", [
        'event_UIA_liveRegionChange',
        'event_liveRegionChange',
    ])
    def test_live_region_skips_typing(self, app_module, handler_name):
        obj = MagicMock()
        obj.name = "Alice is typing..."
        spy = MagicMock()
        app_module._filterAndAnnounce = spy
        getattr(app_module, handler_name)(obj, MagicMock())
        spy.assert_not_called()

    @pytest.mark.parametrize("handler_name", [
        'event_UIA_liveRegionChange',
        'event_liveRegionChange',
    ])
    def test_live_region_skips_empty_message_sentinel(self, app_module, handler_name):
        obj = MagicMock()
        obj.name = "(empty message)"
        spy = MagicMock()
        app_module._filterAndAnnounce = spy
        getattr(app_module, handler_name)(obj, MagicMock())
        spy.assert_not_called()

    def test_alert_event_announces_name(self, app_module):
        obj = MagicMock()
        obj.name = "You have a new message"
        obj.value = ""
        spy = MagicMock()
        app_module._filterAndAnnounce = spy
        app_module.event_alert(obj, MagicMock())
        spy.assert_called_once_with("You have a new message")

    def test_alert_event_falls_back_to_value(self, app_module):
        obj = MagicMock()
        obj.name = ""
        obj.value = "fallback text"
        spy = MagicMock()
        app_module._filterAndAnnounce = spy
        app_module.event_alert(obj, MagicMock())
        spy.assert_called_once_with("fallback text")
