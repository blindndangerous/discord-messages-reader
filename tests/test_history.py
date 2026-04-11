"""Tests for Alt+1-0 history-reading feature.

Covers:
  _isValidMessage   — filtering predicate
  _getMessagesViaUIA — multi-message UIA walk
  _readNthLastMessage — index selection and speech output
"""
import sys
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Re-use UIA helpers from test_uia (duplicated locally to keep tests isolated)
# ---------------------------------------------------------------------------

def _make_elem(name):
    elem = MagicMock()
    elem.GetCurrentPropertyValue.return_value = name
    return elem


def _make_elem_array(*elems):
    arr = MagicMock()
    arr.Length = len(elems)
    arr.GetElement.side_effect = lambda i: elems[i]
    return arr


# ---------------------------------------------------------------------------
# _isValidMessage
# ---------------------------------------------------------------------------

class TestIsValidMessage:
    def test_ia_format_message_is_valid(self, app_module):
        assert app_module._isValidMessage("alice , hello , 9:04 AM") is True

    def test_ia_format_empty_body_is_invalid(self, app_module):
        # Only two segments → body would be empty
        assert app_module._isValidMessage("alice , 9:04 AM") is False

    def test_ia_format_no_timestamp_is_invalid(self, app_module):
        # Last segment has no colon → not a timestamp
        assert app_module._isValidMessage("alice , hello , notadate") is False

    def test_plain_text_short_is_invalid(self, app_module):
        assert app_module._isValidMessage("hi") is False

    def test_plain_text_message_is_valid(self, app_module):
        assert app_module._isValidMessage("This is a real message") is True

    def test_timestamp_only_is_invalid(self, app_module):
        assert app_module._isValidMessage("9:04 AM") is False

    @pytest.mark.parametrize("suffix", [
        ', Online', ', Offline', ', Idle', ', Do Not Disturb', ', Streaming',
    ])
    def test_status_suffixes_are_invalid(self, app_module, suffix):
        assert app_module._isValidMessage("someuser" + suffix) is False

    def test_typing_indicator_is_invalid(self, app_module):
        assert app_module._isValidMessage("alice is typing...") is False

    def test_are_typing_is_invalid(self, app_module):
        assert app_module._isValidMessage("alice and bob are typing...") is False


# ---------------------------------------------------------------------------
# Fixture: wired-up UIA mock (mirrors uia_ctx from test_uia.py)
# ---------------------------------------------------------------------------

@pytest.fixture()
def uia_ctx(app_module):
    uia_mod = sys.modules['UIAHandler']
    uia = MagicMock()
    uia_mod.handler.clientObject = uia
    app_module._discordHwnd = 0x1234
    return app_module, uia


def _build_linear_list(uia, msg_names):
    """Build a fake UIA message list with one named child per message.

    Returns (root, walker) mocked so that GetLastChildElement(msgList) returns
    the last element, and GetPreviousSiblingElement chains through them in order.
    """
    root = MagicMock()
    uia.ElementFromHandle.return_value = root
    uia.CreatePropertyCondition.return_value = MagicMock()

    msg_list = _make_elem("Messages in #general")
    root.FindAll.return_value = _make_elem_array(msg_list)

    elems = [_make_elem(n) for n in msg_names]

    walker = MagicMock()
    # GetLastChildElement(msgList) → last element
    walker.GetLastChildElement.side_effect = lambda e: (
        elems[-1] if e is msg_list else None
    )
    # GetPreviousSiblingElement walks backwards through elems
    prev = {}
    for i in range(len(elems) - 1, 0, -1):
        prev[id(elems[i])] = elems[i - 1]
    prev[id(elems[0])] = None
    walker.GetPreviousSiblingElement.side_effect = lambda e: prev.get(id(e))
    uia.RawViewWalker = walker

    return root, walker, msg_list


# ---------------------------------------------------------------------------
# _getMessagesViaUIA
# ---------------------------------------------------------------------------

class TestGetMessagesViaUIA:
    def test_returns_empty_when_no_uia_client(self, uia_ctx):
        app_module, uia = uia_ctx
        sys.modules['UIAHandler'].handler.clientObject = None
        assert app_module._getMessagesViaUIA() == []

    def test_returns_empty_when_no_message_list(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        root.FindAll.return_value = _make_elem_array()
        assert app_module._getMessagesViaUIA() == []

    def test_single_message_returned(self, uia_ctx):
        app_module, uia = uia_ctx
        _build_linear_list(uia, ["alice , hi , 9:00 AM"])
        result = app_module._getMessagesViaUIA(count=10)
        assert result == ["alice , hi , 9:00 AM"]

    def test_messages_returned_oldest_first(self, uia_ctx):
        app_module, uia = uia_ctx
        names = [
            "alice , first , 9:00 AM",
            "bob , second , 9:01 AM",
            "carol , third , 9:02 AM",
        ]
        _build_linear_list(uia, names)
        result = app_module._getMessagesViaUIA(count=10)
        assert result == names  # oldest first

    def test_count_limits_results(self, uia_ctx):
        app_module, uia = uia_ctx
        names = ["alice , msg%d , 9:0%d AM" % (i, i) for i in range(1, 8)]
        _build_linear_list(uia, names)
        result = app_module._getMessagesViaUIA(count=3)
        # Should return the 3 most recent, oldest-first
        assert len(result) == 3
        assert result == names[-3:]

    def test_invalid_items_filtered_out(self, uia_ctx):
        app_module, uia = uia_ctx
        names = [
            "alice , hello , 9:00 AM",
            "alice is typing...",          # should be filtered
            "bob , world , 9:01 AM",
        ]
        _build_linear_list(uia, names)
        result = app_module._getMessagesViaUIA(count=10)
        assert "alice is typing..." not in result
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _readNthLastMessage
# ---------------------------------------------------------------------------

class TestReadNthLastMessage:
    def _setup_messages(self, app_module, uia, messages):
        app_module._getMessagesViaUIA = MagicMock(return_value=messages)
        speech_mod = sys.modules['speech']
        speech_mod.speak.reset_mock()

    def test_reads_most_recent_message(self, uia_ctx):
        app_module, uia = uia_ctx
        msgs = [
            "alice , first , 9:00 AM",
            "bob , second , 9:01 AM",
            "carol , third , 9:02 AM",
        ]
        self._setup_messages(app_module, uia, msgs)

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._readNthLastMessage(1)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "carol" in spoken
        assert "third" in spoken

    def test_reads_second_most_recent(self, uia_ctx):
        app_module, uia = uia_ctx
        msgs = [
            "alice , first , 9:00 AM",
            "bob , second , 9:01 AM",
            "carol , third , 9:02 AM",
        ]
        self._setup_messages(app_module, uia, msgs)

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._readNthLastMessage(2)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "bob" in spoken
        assert "second" in spoken

    def test_unavailable_index_speaks_not_available(self, uia_ctx):
        app_module, uia = uia_ctx
        self._setup_messages(app_module, uia, ["alice , only , 9:00 AM"])

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._readNthLastMessage(5)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "not available" in spoken

    def test_empty_list_speaks_no_messages(self, uia_ctx):
        app_module, uia = uia_ctx
        self._setup_messages(app_module, uia, [])

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._readNthLastMessage(1)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "No messages" in spoken

    def test_does_nothing_when_not_foreground(self, uia_ctx):
        app_module, uia = uia_ctx
        app_module._getMessagesViaUIA = MagicMock(return_value=["alice , hi , 9:00 AM"])
        sys.modules['speech'].speak.reset_mock()
        sys.modules['api'].getForegroundObject.return_value = None  # not foreground

        app_module._readNthLastMessage(1)
        sys.modules['speech'].speak.assert_not_called()


# ---------------------------------------------------------------------------
# Script method registration
# ---------------------------------------------------------------------------

class TestGestureRegistration:
    def test_all_ten_scripts_exist(self, app_module):
        for i in range(1, 11):
            assert hasattr(app_module, "script_readMessage%d" % i), (
                "missing script_readMessage%d" % i
            )

    def test_gestures_dict_maps_alt_keys(self, app_module):
        gestures = app_module.__class__.__dict__.get('_AppModule__gestures', {})
        assert "kb:alt+1" in gestures
        assert "kb:alt+0" in gestures
        assert gestures["kb:alt+1"] == "readMessage1"
        assert gestures["kb:alt+0"] == "readMessage10"

    def test_toggle_script_exists(self, app_module):
        assert hasattr(app_module, "script_toggleAnnounce")

    def test_toggle_gesture_registered(self, app_module):
        gestures = app_module.__class__.__dict__.get('_AppModule__gestures', {})
        assert "kb:NVDA+shift+d" in gestures
        assert gestures["kb:NVDA+shift+d"] == "toggleAnnounce"

    def test_script_category(self, app_module):
        assert app_module.__class__.scriptCategory == "Discord Messages Reader"


# ---------------------------------------------------------------------------
# Announce toggle
# ---------------------------------------------------------------------------

class TestAnnounceToggle:
    def test_enabled_by_default(self, app_module):
        assert app_module._announceEnabled is True

    def test_toggle_off_suppresses_announcements(self, app_module):
        app_module._announceEnabled = False
        sys.modules['speech'].speak.reset_mock()
        app_module._scheduleAnnounce("alice , hello , 9:00 AM")
        sys.modules['speech'].speak.assert_not_called()

    def test_toggle_off_stops_uia_polling(self, app_module):
        """When muted, _uiaRead must return before touching the UIA tree."""
        app_module._announceEnabled = False
        app_module._getLatestMessageViaUIA = MagicMock()

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._uiaRead()
        app_module._getLatestMessageViaUIA.assert_not_called()

    def test_toggle_on_allows_announcements(self, app_module):
        app_module._announceEnabled = True
        sys.modules['speech'].speak.reset_mock()
        app_module._scheduleAnnounce("alice , hello , 9:00 AM")
        sys.modules['speech'].speak.assert_called_once()

    def test_script_toggles_state(self, app_module):
        assert app_module._announceEnabled is True
        app_module.script_toggleAnnounce(None)
        assert app_module._announceEnabled is False
        app_module.script_toggleAnnounce(None)
        assert app_module._announceEnabled is True

    def test_script_speaks_state(self, app_module):
        sys.modules['speech'].speak.reset_mock()
        app_module.script_toggleAnnounce(None)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "off" in spoken

        sys.modules['speech'].speak.reset_mock()
        app_module.script_toggleAnnounce(None)
        spoken = sys.modules['speech'].speak.call_args[0][0][0]
        assert "on" in spoken

    def test_toggle_does_not_affect_history_reading(self, uia_ctx):
        """Alt+1-0 should always work regardless of toggle state."""
        app_module, uia = uia_ctx
        app_module._announceEnabled = False
        app_module._getMessagesViaUIA = MagicMock(return_value=["alice , hi , 9:00 AM"])
        sys.modules['speech'].speak.reset_mock()

        fg = MagicMock()
        fg.appModule = app_module
        sys.modules['api'].getForegroundObject.return_value = fg

        app_module._readNthLastMessage(1)
        sys.modules['speech'].speak.assert_called_once()
