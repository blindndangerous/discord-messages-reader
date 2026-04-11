"""Unit tests for _scheduleAnnounce (dedup) and _doAnnounce (formatting).

Covers:
- Identical text is not announced twice (indefinite content dedup)
- Different text IS announced
- IAccessible "username , body , time" formatted as "username: body"
- Multi-comma body preserved
- Plain-text passed through unchanged
- speech.speak called with the right arguments
"""

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Deduplication — _scheduleAnnounce
# ---------------------------------------------------------------------------


class TestScheduleAnnounce:
    def test_first_call_announces(self, app_module):
        spy = MagicMock()
        app_module._doAnnounce = spy
        app_module._scheduleAnnounce("hello world")
        spy.assert_called_once_with("hello world")

    def test_duplicate_is_suppressed(self, app_module):
        spy = MagicMock()
        app_module._doAnnounce = spy
        app_module._scheduleAnnounce("hello world")
        app_module._scheduleAnnounce("hello world")
        assert spy.call_count == 1

    def test_different_text_is_announced(self, app_module):
        spy = MagicMock()
        app_module._doAnnounce = spy
        app_module._scheduleAnnounce("first message")
        app_module._scheduleAnnounce("second message")
        assert spy.call_count == 2

    def test_dedup_is_indefinite(self, app_module):
        """Same text must be suppressed even after a long gap (no time window)."""
        spy = MagicMock()
        app_module._doAnnounce = spy
        app_module._scheduleAnnounce("repeated text , 9:00 AM")
        app_module._scheduleAnnounce("repeated text , 9:00 AM")
        app_module._scheduleAnnounce("repeated text , 9:00 AM")
        assert spy.call_count == 1

    def test_last_text_updated(self, app_module):
        app_module._doAnnounce = MagicMock()
        app_module._scheduleAnnounce("msg one")
        assert app_module._lastText == "msg one"
        app_module._scheduleAnnounce("msg two")
        assert app_module._lastText == "msg two"

    def test_disabled_does_not_update_last_text(self, app_module):
        """`_lastText` must NOT be updated while disabled — so re-enabling
        announces the message the user missed rather than suppressing it."""
        app_module._announceEnabled = False
        app_module._doAnnounce = MagicMock()
        original_last = app_module._lastText
        app_module._scheduleAnnounce("a new message while disabled")
        assert app_module._lastText == original_last

    def test_message_announced_after_re_enable(self, app_module):
        """A message received while disabled must be announced once re-enabled."""
        spy = MagicMock()
        app_module._doAnnounce = spy
        # Disable and receive a message — must NOT announce and must NOT update lastText
        app_module._announceEnabled = False
        app_module._scheduleAnnounce("hello from someone")
        spy.assert_not_called()
        assert app_module._lastText != "hello from someone"
        # Re-enable — same message arrives again via poll
        app_module._announceEnabled = True
        app_module._scheduleAnnounce("hello from someone")
        spy.assert_called_once_with("hello from someone")


# ---------------------------------------------------------------------------
# Formatting — _doAnnounce
# ---------------------------------------------------------------------------


class TestDoAnnounce:
    def _speak_arg(self, app_module, text):
        """Call _doAnnounce and return the string passed to speech.speak."""
        speech = sys.modules["speech"]
        speech.speak.reset_mock()
        app_module._doAnnounce(text)
        assert speech.speak.called
        spoken_list = speech.speak.call_args[0][0]
        return spoken_list[0]

    def test_iaccess_format_three_parts(self, app_module):
        result = self._speak_arg(app_module, "alice , hello there , 9:04 AM")
        assert result == "alice: hello there"

    def test_iaccess_format_body_with_comma(self, app_module):
        result = self._speak_arg(app_module, "alice , yes , no , 9:04 AM")
        assert result == "alice: yes , no"

    def test_iaccess_format_two_parts_returns_username(self, app_module):
        # Degenerate case: two-part string slips through (body was filtered but
        # caller passed it anyway). We return just the first part gracefully.
        result = self._speak_arg(app_module, "alice , 9:04 AM")
        assert result == "alice"

    def test_plain_text_passed_unchanged(self, app_module):
        result = self._speak_arg(app_module, "hello from a friend")
        assert result == "hello from a friend"

    def test_speech_speak_called_with_list(self, app_module):
        speech = sys.modules["speech"]
        speech.speak.reset_mock()
        app_module._doAnnounce("test message")
        args, _kwargs = speech.speak.call_args
        assert isinstance(args[0], list)

    def test_speech_priority_is_now(self, app_module):
        speech = sys.modules["speech"]
        speech.speak.reset_mock()
        app_module._doAnnounce("test")
        _, kwargs = speech.speak.call_args
        assert kwargs.get("priority") == speech.Spri.NOW
