"""Mock tests for _getLatestMessageViaUIA — UIA tree walking.

All COM/UIA objects are replaced with MagicMock so tests run without NVDA
or Windows UIAutomation. Each test builds a minimal fake UIA tree and
asserts that the walker returns the expected message text.
"""

import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers to build a fake UIA element array
# ---------------------------------------------------------------------------


def _make_elem(name):
    """Return a mock UIA element whose GetCurrentPropertyValue returns name."""
    elem = MagicMock()
    elem.GetCurrentPropertyValue.return_value = name
    return elem


def _make_elem_array(*elems):
    """Return a mock IUIAutomationElementArray wrapping the given elements."""
    arr = MagicMock()
    arr.Length = len(elems)
    arr.GetElement.side_effect = lambda i: elems[i]
    return arr


def _make_walker(child_map, prev_map):
    """Return a mock RawViewWalker.

    child_map: {parent_mock: first_child_mock | None}
    prev_map:  {elem_mock: previous_sibling_mock | None}
    """
    walker = MagicMock()
    walker.GetLastChildElement.side_effect = lambda e: child_map.get(id(e))
    walker.GetPreviousSiblingElement.side_effect = lambda e: prev_map.get(id(e))
    return walker


# ---------------------------------------------------------------------------
# Fixture: wired-up UIA mock
# ---------------------------------------------------------------------------


@pytest.fixture()
def uia_ctx(app_module):
    """Yield (app_module, mock_uia_client) with UIAHandler wired up."""
    uia_mod = sys.modules["UIAHandler"]
    uia = MagicMock()
    uia_mod.handler.clientObject = uia
    app_module._discordHwnd = 0x1234
    return app_module, uia


# ---------------------------------------------------------------------------
# No list found
# ---------------------------------------------------------------------------


class TestNoList:
    def test_no_uia_client_returns_none(self, uia_ctx):
        app_module, _uia = uia_ctx
        sys.modules["UIAHandler"].handler.clientObject = None
        assert app_module._getLatestMessageViaUIA() is None

    def test_empty_list_array_returns_none(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        root.FindAll.return_value = _make_elem_array()  # empty
        assert app_module._getLatestMessageViaUIA() is None

    def test_no_messages_in_list_returns_none(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        # Two lists, neither named "messages in"
        dm = _make_elem("Direct Messages")
        act = _make_elem("Current activity")
        root.FindAll.return_value = _make_elem_array(dm, act)
        assert app_module._getLatestMessageViaUIA() is None

    def test_no_hwnd_returns_none(self, uia_ctx):
        app_module, _uia = uia_ctx
        app_module._discordHwnd = 0
        api_mod = sys.modules["api"]
        api_mod.getForegroundObject.return_value = None
        assert app_module._getLatestMessageViaUIA() is None


# ---------------------------------------------------------------------------
# List found — named child has content
# ---------------------------------------------------------------------------


class TestChildWithName:
    def test_last_child_name_returned(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(msg_list)

        last_child = _make_elem("alice , hello there , 9:04 AM")
        walker = MagicMock()
        walker.GetLastChildElement.return_value = last_child
        uia.RawViewWalker = walker

        result = app_module._getLatestMessageViaUIA()
        assert result == "alice , hello there , 9:04 AM"

    def test_correct_list_chosen_among_multiple(self, uia_ctx):
        """Direct Messages list must be skipped; Messages in … must be chosen."""
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        dm_list = _make_elem("Direct Messages")
        msg_list = _make_elem("Messages in @friend")
        root.FindAll.return_value = _make_elem_array(dm_list, msg_list)

        last_child = _make_elem("bob , hey , 10:00 AM")
        walker = MagicMock()
        walker.GetLastChildElement.side_effect = lambda e: last_child if e is msg_list else None
        uia.RawViewWalker = walker

        result = app_module._getLatestMessageViaUIA()
        assert result == "bob , hey , 10:00 AM"


# ---------------------------------------------------------------------------
# Grandchild fallback — container has empty name
# ---------------------------------------------------------------------------


class TestGrandchildFallback:
    def test_grandchild_name_returned_when_child_empty(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(msg_list)

        # Container child has empty name; grandchild has the content
        container = _make_elem("")
        grandchild = _make_elem("carol , hey there , 11:30 AM")

        walker = MagicMock()
        # GetLastChildElement(msg_list) → container
        # GetLastChildElement(container)  → grandchild
        walker.GetLastChildElement.side_effect = lambda e: (
            container if e is msg_list else grandchild if e is container else None
        )
        walker.GetPreviousSiblingElement.return_value = None
        uia.RawViewWalker = walker

        result = app_module._getLatestMessageViaUIA()
        assert result == "carol , hey there , 11:30 AM"

    def test_walks_previous_siblings_when_all_empty(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(msg_list)

        # Last child is empty with no grandchildren; previous sibling has name
        empty_child = _make_elem("")
        named_child = _make_elem("dave , sup , 12:00 PM")

        walker = MagicMock()
        walker.GetLastChildElement.side_effect = lambda e: empty_child if e is msg_list else None
        walker.GetPreviousSiblingElement.side_effect = lambda e: named_child if e is empty_child else None
        uia.RawViewWalker = walker

        result = app_module._getLatestMessageViaUIA()
        assert result == "dave , sup , 12:00 PM"

    def test_returns_none_after_ten_empty_children(self, uia_ctx):
        """Walker must not loop forever — capped at 10 iterations."""
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(msg_list)

        # Chain of 15 empty children — we must stop at 10
        empties = [_make_elem("") for _ in range(15)]
        walker = MagicMock()
        walker.GetLastChildElement.side_effect = lambda e: empties[0] if e is msg_list else None
        # Each empty's prev sibling is the next empty
        prev_map = {id(empties[i]): empties[i + 1] for i in range(14)}
        prev_map[id(empties[14])] = None
        walker.GetPreviousSiblingElement.side_effect = lambda e: prev_map.get(id(e))
        uia.RawViewWalker = walker

        result = app_module._getLatestMessageViaUIA()
        assert result is None


# ---------------------------------------------------------------------------
# hwnd fallback from api
# ---------------------------------------------------------------------------


class TestHwndFallback:
    def test_hwnd_learned_from_api_when_zero(self, uia_ctx):
        app_module, uia = uia_ctx
        app_module._discordHwnd = 0

        fg = MagicMock()
        fg.appModule = app_module
        fg.windowHandle = 0xABCD
        sys.modules["api"].getForegroundObject.return_value = fg

        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        root.FindAll.return_value = _make_elem_array()

        app_module._getLatestMessageViaUIA()
        assert app_module._discordHwnd == 0xABCD


# ---------------------------------------------------------------------------
# _getMsgListViaUIA — caching behaviour
# ---------------------------------------------------------------------------


class TestGetMsgListViaUIACache:
    def test_cache_miss_populates_cache(self, uia_ctx):
        app_module, uia = uia_ctx
        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()

        msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(msg_list)

        assert app_module._cachedMsgList is None
        result = app_module._getMsgListViaUIA(uia)
        assert result is msg_list
        assert app_module._cachedMsgList is msg_list
        assert app_module._cachedMsgListName == "Messages in #general"
        uia.ElementFromHandle.assert_called_once()

    def test_cache_hit_bypasses_tree_walk(self, uia_ctx):
        app_module, uia = uia_ctx
        cached_elem = _make_elem("Messages in #general")
        app_module._cachedMsgList = cached_elem
        app_module._cachedMsgListName = "Messages in #general"

        result = app_module._getMsgListViaUIA(uia)
        assert result is cached_elem
        uia.ElementFromHandle.assert_not_called()

    def test_cache_invalidation_on_com_error(self, uia_ctx):
        app_module, uia = uia_ctx
        broken_elem = MagicMock()
        broken_elem.GetCurrentPropertyValue.side_effect = Exception("COM error")
        app_module._cachedMsgList = broken_elem
        app_module._cachedMsgListName = "Messages in #general"

        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        new_msg_list = _make_elem("Messages in #general")
        root.FindAll.return_value = _make_elem_array(new_msg_list)

        result = app_module._getMsgListViaUIA(uia)
        assert result is new_msg_list
        assert app_module._cachedMsgList is new_msg_list
        uia.ElementFromHandle.assert_called_once()

    def test_cache_invalidation_on_name_mismatch(self, uia_ctx):
        """Channel switch: cached name no longer matches the live element name."""
        app_module, uia = uia_ctx
        stale_elem = _make_elem("Messages in #random")
        app_module._cachedMsgList = stale_elem
        app_module._cachedMsgListName = "Messages in #general"  # stale

        root = MagicMock()
        uia.ElementFromHandle.return_value = root
        uia.CreatePropertyCondition.return_value = MagicMock()
        new_msg_list = _make_elem("Messages in #random")
        root.FindAll.return_value = _make_elem_array(new_msg_list)

        result = app_module._getMsgListViaUIA(uia)
        assert result is new_msg_list
        assert app_module._cachedMsgListName == "Messages in #random"
        uia.ElementFromHandle.assert_called_once()
