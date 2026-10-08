"""Alt+1 through Alt+0 structural history tests."""

import sys
from unittest.mock import MagicMock

import pytest

from discord import ChannelSnapshot, MessageEntry


def current_snapshot(*texts):
    return ChannelSnapshot(
        "channel",
        tuple(MessageEntry(("runtime", index), text) for index, text in enumerate(texts)),
    )


def bound_gestures(app_module):
    """Gesture bindings as NVDA's ScriptableType builds them from @script."""
    return {
        gesture: name.removeprefix("script_")
        for name, function in vars(type(app_module)).items()
        if name.startswith("script_")
        for gesture in getattr(function, "gestures", ())
    }


def make_foreground(app_module):
    foreground = MagicMock(windowHandle=1)
    foreground.appModule = app_module
    sys.modules["api"].getForegroundObject.return_value = foreground
    return foreground


class TestHistoryReading:
    def test_reads_most_recent_message(self, app_module):
        make_foreground(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("first", "second", "third"))

        app_module._readNthLastMessage(1)

        sys.modules["ui"].message.assert_called_once_with("third")

    def test_reads_nth_most_recent_message(self, app_module):
        make_foreground(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("first", "second", "third"))

        app_module._readNthLastMessage(2)

        sys.modules["ui"].message.assert_called_once_with("second")

    def test_reports_empty_snapshot_accessibly(self, app_module):
        make_foreground(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot())

        app_module._readNthLastMessage(1)

        sys.modules["ui"].message.assert_called_once_with("No messages found")

    def test_reports_unavailable_index_accessibly(self, app_module):
        make_foreground(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("only"))

        app_module._readNthLastMessage(5)

        sys.modules["ui"].message.assert_called_once_with("Message 5 is not available")

    def test_does_nothing_outside_foreground_discord(self, app_module):
        sys.modules["api"].getForegroundObject.return_value = None
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("secret"))

        app_module._readNthLastMessage(1)

        sys.modules["ui"].message.assert_not_called()
        app_module._getSnapshotViaUIA.assert_not_called()

    def test_history_remains_available_while_automatic_announcements_muted(self, app_module):
        make_foreground(app_module)
        app_module._announceEnabled = False
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("available"))

        app_module._readNthLastMessage(1)

        sys.modules["ui"].message.assert_called_once_with("available")

    def test_history_read_does_not_consume_automatic_snapshot_state(self, app_module):
        foreground = make_foreground(app_module)
        app_module._getSnapshotViaUIA = MagicMock(return_value=current_snapshot("new"))

        app_module._readNthLastMessage(1)

        assert app_module._channelSnapshots == {}
        app_module._getSnapshotViaUIA.assert_called_once_with(foreground, history=1)


class TestGestureRegistration:
    def test_all_ten_scripts_exist(self, app_module):
        for index in range(1, 11):
            assert hasattr(app_module, f"script_readMessage{index}")

    def test_alt_digit_gestures_are_preserved(self, app_module):
        gestures = bound_gestures(app_module)

        assert gestures["kb:alt+1"] == "readMessage1"
        assert gestures["kb:alt+0"] == "readMessage10"

    def test_toggle_gesture_is_preserved(self, app_module):
        gestures = bound_gestures(app_module)

        assert gestures["kb:NVDA+alt+shift+d"] == "toggleAnnounce"
        assert "kb:NVDA+control+shift+d" not in gestures

    def test_every_command_speaks_in_on_demand_speech_mode(self, app_module):
        """NVDA's on-demand mode silences scripts not marked speakOnDemand."""
        scripts = [getattr(type(app_module), f"script_{name}") for name in bound_gestures(app_module).values()]

        assert len(scripts) == 11
        assert all(script.speakOnDemand for script in scripts)
        assert all(script.__doc__ for script in scripts)


class TestReadMessageGestures:
    """Each alt+N gesture must map to the matching Nth-last message."""

    @pytest.mark.parametrize(
        ("script_index", "expected_n"),
        [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 8), (9, 9), (10, 10)],
    )
    def test_script_reads_the_matching_message(self, app_module, mocker, script_index, expected_n):
        read = mocker.patch.object(app_module, "_readNthLastMessage")

        getattr(app_module, f"script_readMessage{script_index}")(None)

        read.assert_called_once_with(expected_n)

    def test_alt_zero_is_bound_to_the_tenth_message(self, app_module):
        gestures = bound_gestures(app_module)

        assert gestures["kb:alt+0"] == "readMessage10"
        assert gestures["kb:alt+1"] == "readMessage1"
