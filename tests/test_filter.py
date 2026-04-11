"""Unit tests for _filterAndAnnounce — message filtering logic.

These tests verify that the filter correctly passes real messages and
rejects noise (status changes, typing indicators, empty bodies, timestamps).
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_filter_spy(app_module):
    """Patch _scheduleAnnounce so we can assert whether a message was passed."""
    spy = MagicMock()
    app_module._scheduleAnnounce = spy
    return spy


# ---------------------------------------------------------------------------
# Status suffix filtering
# ---------------------------------------------------------------------------

class TestStatusSuffixes:
    @pytest.mark.parametrize("suffix", [
        ', Online', ', Offline', ', Idle', ', Do Not Disturb', ', Streaming',
    ])
    def test_status_suffix_is_filtered(self, app_module, suffix):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("SomeUser" + suffix)
        spy.assert_not_called()

    def test_non_status_message_is_not_filtered_by_suffix(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("hey can you come , online for a bit , 9:00 AM")
        spy.assert_called_once()


# ---------------------------------------------------------------------------
# Typing indicator filtering
# ---------------------------------------------------------------------------

class TestTypingIndicators:
    @pytest.mark.parametrize("text", [
        "Alice is typing...",
        "Alice and Bob are typing...",
        "ALICE IS TYPING",          # case-insensitive
    ])
    def test_typing_indicator_is_filtered(self, app_module, text):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce(text)
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# IAccessible format: "username , body , HH:MM AM"
# ---------------------------------------------------------------------------

class TestIAccessibleFormat:
    def test_valid_message_is_passed(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("alice , hello there , 9:04 AM")
        spy.assert_called_once_with("alice , hello there , 9:04 AM")

    def test_message_with_comma_in_body(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("alice , yes , no , maybe , 9:04 AM")
        spy.assert_called_once()

    def test_missing_timestamp_colon_is_filtered(self, app_module):
        """Last part must contain ':' to be a timestamp."""
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("alice , hello , notaTimestamp")
        spy.assert_not_called()

    def test_empty_body_is_filtered(self, app_module):
        """'user , , 9:04 AM' has an empty body."""
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("alice ,  , 9:04 AM")
        spy.assert_not_called()

    def test_two_part_with_no_body_is_filtered(self, app_module):
        """Two-part split where parts[1:-1] is empty."""
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("alice , 9:04 AM")
        # Only 2 parts, parts[1:-1] == [] → body == "" → filtered
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# Plain-text / UIA format
# ---------------------------------------------------------------------------

class TestPlainTextFormat:
    def test_short_string_is_filtered(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("hi")
        spy.assert_not_called()

    @pytest.mark.parametrize("ts", [
        "9:04 AM", "9:04", "12:30 PM", "12:30", "1:00am", "1:00 pm",
    ])
    def test_timestamp_only_is_filtered(self, app_module, ts):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce(ts)
        spy.assert_not_called()

    def test_plain_message_is_passed(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("hello from a friend")
        spy.assert_called_once_with("hello from a friend")

    def test_minimum_length_three_is_passed(self, app_module):
        spy = _make_filter_spy(app_module)
        app_module._filterAndAnnounce("hey")
        spy.assert_called_once()
