"""Lifecycle, polling gates, and native NVDA event behavior."""

import sys
from unittest.mock import MagicMock, patch

from discord import ChannelSnapshot, MessageEntry


def snapshot(*items, channel="channel"):
    return ChannelSnapshot(
        channel,
        tuple(MessageEntry(("runtime", identity), text) for identity, text in items),
    )


def foreground_for(app_module):
    foreground = MagicMock(windowHandle=1)
    foreground.appModule = app_module
    sys.modules["api"].getForegroundObject.return_value = foreground
    return foreground


class TestLifecycle:
    def test_init_schedules_single_poll_without_winevent_hook(self):
        with patch("ctypes.windll") as windll, patch("core.callLater", return_value=MagicMock()) as call_later:
            from discord import AppModule

            module = AppModule()

        call_later.assert_called_once_with(500, module._pollTick)
        windll.user32.SetWinEventHook.assert_not_called()

    def test_terminate_stops_poll_timer(self, app_module):
        timer = MagicMock()
        app_module._pollTimer = timer

        app_module.terminate()

        timer.Stop.assert_called_once()
        assert app_module._pollTimer is None

    def test_terminate_is_idempotent(self, app_module):
        base_app_module = sys.modules["appModuleHandler"].AppModule
        with patch.object(base_app_module, "terminate", autospec=True) as base_terminate:
            app_module.terminate()
            app_module.terminate()

        base_terminate.assert_called_once_with(app_module)

    def test_poll_reschedules_after_read(self, app_module):
        app_module._uiaRead = MagicMock()
        app_module._schedulePoll = MagicMock()

        app_module._pollTick()

        app_module._uiaRead.assert_called_once()
        app_module._schedulePoll.assert_called_once()

    def test_poll_does_not_reschedule_after_termination(self, app_module):
        app_module._terminated = True
        app_module._uiaRead = MagicMock()
        app_module._schedulePoll = MagicMock()

        app_module._pollTick()

        app_module._uiaRead.assert_not_called()
        app_module._schedulePoll.assert_not_called()


class TestPollingGates:
    def test_background_does_not_read_private_content(self, app_module):
        sys.modules["api"].getForegroundObject.return_value = None
        app_module._getSnapshotViaUIA = MagicMock()

        app_module._uiaRead()

        app_module._getSnapshotViaUIA.assert_not_called()
        assert app_module._needsBaseline is True

    def test_foreground_poll_reads_structural_snapshot(self, app_module):
        foreground = foreground_for(app_module)
        current = snapshot((1, "existing"))
        app_module._getSnapshotViaUIA = MagicMock(return_value=current)

        app_module._uiaRead()

        app_module._getSnapshotViaUIA.assert_called_once_with(foreground)
        assert app_module._channelSnapshots[current.channel_id] == current

    def test_foreground_return_establishes_silent_baseline(self, app_module):
        foreground_for(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=snapshot((1, "existing")))
        app_module._uiaRead()
        app_module._getSnapshotViaUIA.return_value = snapshot((1, "existing"), (2, "announced"))
        app_module._uiaRead()
        sys.modules["ui"].message.assert_called_once_with("announced")

        sys.modules["ui"].message.reset_mock()
        sys.modules["api"].getForegroundObject.return_value = None
        app_module._uiaRead()
        foreground_for(app_module)
        app_module._getSnapshotViaUIA.return_value = snapshot(
            (1, "existing"), (2, "announced"), (3, "arrived in background")
        )
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_snapshot_failure_forces_next_success_to_baseline(self, app_module):
        foreground_for(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=snapshot((1, "existing")))
        app_module._uiaRead()
        app_module._getSnapshotViaUIA.return_value = None
        app_module._uiaRead()
        app_module._getSnapshotViaUIA.return_value = snapshot((1, "existing"), (2, "unknown interval"))
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_muted_poll_does_not_read_and_resume_baselines(self, app_module):
        foreground_for(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=snapshot((1, "existing")))
        app_module._uiaRead()

        app_module.script_toggleAnnounce(None)
        app_module._getSnapshotViaUIA.reset_mock()
        app_module._uiaRead()
        app_module._getSnapshotViaUIA.assert_not_called()

        app_module.script_toggleAnnounce(None)
        sys.modules["ui"].message.reset_mock()
        app_module._getSnapshotViaUIA.return_value = snapshot((1, "existing"), (2, "arrived muted"))
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()


class TestToggle:
    def test_toggle_uses_accessible_user_message(self, app_module):
        app_module.script_toggleAnnounce(None)

        assert app_module._announceEnabled is False
        sys.modules["ui"].message.assert_called_once_with("Discord announcements off")

    def test_toggle_output_failure_does_not_escape(self, app_module):
        sys.modules["ui"].message.side_effect = RuntimeError("output failed")

        app_module.script_toggleAnnounce(None)


class TestNativeNvdaBehavior:
    def test_does_not_override_native_event_handlers(self, app_module):
        class_dict = app_module.__class__.__dict__

        assert "event_valueChange" not in class_dict
        assert "event_liveRegionChange" not in class_dict
        assert "event_UIA_liveRegionChange" not in class_dict
        assert "event_alert" not in class_dict

    def test_does_not_force_browse_mode_off(self, app_module):
        assert "disableBrowseModeByDefault" not in app_module.__class__.__dict__
