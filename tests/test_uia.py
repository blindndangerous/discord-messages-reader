"""Structural UIA snapshot tests."""

import sys
from unittest.mock import MagicMock

import pytest

_NAME = 30005
_CONTROL_TYPE = 30003
_DOCUMENT = 50030
_LIST = 50008
_LIST_ITEM = 50007
_VALUE = 30045
_ARIA_ROLE = 30101


class ElementArray:
    def __init__(self, elements):
        self._elements = list(elements)
        self.Length = len(self._elements)

    def GetElement(self, index):
        return self._elements[index]


class ChildList(list):
    def __init__(self, owner, values=()):
        self.owner = owner
        super().__init__()
        self.extend(values)

    def append(self, value):
        value.parent = self.owner
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            value = list(value)
            for item in value:
                item.parent = self.owner
        else:
            value.parent = self.owner
        super().__setitem__(key, value)


class Element:
    def __init__(
        self,
        *,
        name="",
        value="",
        aria_role="",
        runtime_id=None,
        control_type=_LIST_ITEM,
        children=None,
    ):
        self.properties = {
            _NAME: name,
            _VALUE: value,
            _ARIA_ROLE: aria_role,
            _CONTROL_TYPE: control_type,
        }
        self.runtime_id = runtime_id
        self.documents = []
        self.lists = []
        self.children = ChildList(self, children or [])
        self.parent = None

    def GetCurrentPropertyValue(self, property_id):
        return self.properties.get(property_id, "")

    def GetRuntimeId(self):
        if self.runtime_id is None:
            raise OSError("runtime ID unavailable")
        return self.runtime_id

    def FindAll(self, _scope, condition):
        _kind, property_id, expected = condition
        if property_id == _CONTROL_TYPE and expected == _DOCUMENT:
            return ElementArray(self.documents)
        if property_id == _CONTROL_TYPE and expected == _LIST:
            return ElementArray(self.lists)
        return ElementArray([])


class RawViewWalker:
    @staticmethod
    def GetParentElement(element):
        return element.parent

    @staticmethod
    def GetLastChildElement(element):
        return element.children[-1] if element.children else None

    @staticmethod
    def GetPreviousSiblingElement(element):
        siblings = element.parent.children
        index = siblings.index(element)
        return siblings[index - 1] if index else None


class AttributeFallbackElement(Element):
    def __init__(self, *, current_name="", current_value="", current_control_type=_LIST_ITEM, **kwargs):
        super().__init__(**kwargs)
        self.CurrentName = current_name
        self.CurrentValue = current_value
        self.CurrentControlType = current_control_type

    def GetCurrentPropertyValue(self, _property_id):
        raise OSError("raw property unavailable")


def make_tree(channel_url, messages, *, document_runtime=(1, 10)):
    root = Element(control_type=0)
    document = Element(value=channel_url, runtime_id=document_runtime)
    main = Element(aria_role="main", control_type=50026)
    message_list = Element(control_type=_LIST, children=messages)
    message_list.parent = main
    main.parent = root
    root.messages = message_list.children
    root.lists = [message_list]
    root.documents = [document]
    return root, document


def install_uia(root):
    uia = MagicMock()
    uia.CreatePropertyCondition.side_effect = lambda property_id, expected: (
        "property",
        property_id,
        expected,
    )
    uia.ElementFromHandle.return_value = root
    uia.RawViewWalker = RawViewWalker()
    sys.modules["UIAHandler"].handler.clientObject = uia
    foreground = MagicMock(windowHandle=0x1234)
    return uia, foreground


class TestStructuralSnapshots:
    def test_discovers_list_items_under_main_landmark(self, app_module):
        messages = [
            Element(name="alice: hi", aria_role="message", runtime_id=(2, 1)),
            Element(name="bob: ok", aria_role="message", runtime_id=(2, 2)),
        ]
        root, document = make_tree("https://discord.com/channels/1/2", messages)
        document.FindAll = MagicMock(wraps=document.FindAll)
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.channel_id == "https://discord.com/channels/1/2"
        assert [message.text for message in snapshot.messages] == ["alice: hi", "bob: ok"]
        assert [message.identity for message in snapshot.messages] == [
            ("runtime", 2, 1),
            ("runtime", 2, 2),
        ]
        document.FindAll.assert_not_called()

    def test_ignores_lists_outside_main_landmark(self, app_module):
        root, _document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="channel message", runtime_id=(2, 1))],
        )
        navigation = Element(aria_role="navigation", control_type=50026)
        sidebar = Element(
            control_type=_LIST,
            children=[Element(name="sidebar item", runtime_id=(8, 1))],
        )
        sidebar.parent = navigation
        navigation.parent = root
        root.lists.insert(0, sidebar)
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert [message.text for message in snapshot.messages] == ["channel message"]

    def test_reads_named_message_grandchild_and_skips_list_text(self, app_module):
        message = Element(
            runtime_id=(2, 1),
            children=[Element(name="alice: nested message", control_type=50026)],
        )
        separator = Element(name="date separator", control_type=50038)
        root, _document = make_tree(
            "https://discord.com/channels/1/2",
            [message, separator],
        )
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert [entry.text for entry in snapshot.messages] == ["alice: nested message"]
        assert snapshot.messages[0].identity == ("runtime", 2, 1)

    def test_channel_identity_uses_document_url_not_runtime_id(self, app_module):
        first_root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="first", aria_role="message", runtime_id=(2, 1))],
            document_runtime=(10,),
        )
        uia, foreground = install_uia(first_root)
        foreground.windowHandle = 1
        first = app_module._getSnapshotViaUIA(foreground)

        second_root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="second", aria_role="message", runtime_id=(2, 2))],
            document_runtime=(99,),
        )
        uia.ElementFromHandle.side_effect = lambda handle: first_root if handle == 1 else second_root
        foreground.windowHandle = 2
        second = app_module._getSnapshotViaUIA(foreground)

        assert first.channel_id == second.channel_id
        assert [message.text for message in second.messages] == ["second"]
        assert uia.ElementFromHandle.call_args.args == (2,)

    def test_document_without_channel_url_is_rejected(self, app_module):
        root, _ = make_tree("", [], document_runtime=(4, 5))
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot is None

    def test_second_snapshot_reuses_cached_channel_document(self, app_module):
        messages = [Element(name="first", aria_role="message", runtime_id=(2, 1))]
        root, _ = make_tree("https://discord.com/channels/1/2", messages)
        root.FindAll = MagicMock(wraps=root.FindAll)
        _uia, foreground = install_uia(root)

        app_module._getSnapshotViaUIA(foreground)
        app_module._getSnapshotViaUIA(foreground)

        property_ids = [call.args[1][1] for call in root.FindAll.call_args_list]
        assert property_ids == [_CONTROL_TYPE, _CONTROL_TYPE]

    def test_cached_document_value_detects_channel_navigation(self, app_module):
        root, document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="first", aria_role="message", runtime_id=(2, 1))],
        )
        root.FindAll = MagicMock(wraps=root.FindAll)
        _uia, foreground = install_uia(root)
        app_module._getSnapshotViaUIA(foreground)
        document.properties[_VALUE] = "https://discord.com/channels/1/3"
        root.messages[:] = [Element(name="second", aria_role="message", runtime_id=(2, 2))]

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.channel_id == "https://discord.com/channels/1/3"
        assert [message.text for message in snapshot.messages] == ["second"]
        property_ids = [call.args[1][1] for call in root.FindAll.call_args_list]
        assert property_ids == [_CONTROL_TYPE, _CONTROL_TYPE]

    def test_cached_document_property_failure_triggers_rediscovery(self, app_module):
        root, document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="first", aria_role="message", runtime_id=(2, 1))],
        )
        root.FindAll = MagicMock(wraps=root.FindAll)
        _uia, foreground = install_uia(root)
        app_module._getSnapshotViaUIA(foreground)

        document.GetCurrentPropertyValue = MagicMock(side_effect=OSError("detached"))
        replacement = Element(value="https://discord.com/channels/1/3", runtime_id=(9, 9))
        root.documents = [replacement]
        root.messages[:] = [Element(name="second", aria_role="message", runtime_id=(2, 2))]

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.channel_id == "https://discord.com/channels/1/3"
        property_ids = [call.args[1][1] for call in root.FindAll.call_args_list]
        assert property_ids == [_CONTROL_TYPE, _CONTROL_TYPE, _CONTROL_TYPE, _CONTROL_TYPE]

    def test_replaced_uia_client_forces_silent_baseline(self, app_module):
        first_root, _first_document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="existing", aria_role="message", runtime_id=(2, 1))],
        )
        _first_uia, foreground = install_uia(first_root)
        foreground.appModule = app_module
        sys.modules["api"].getForegroundObject.return_value = foreground
        app_module._uiaRead()
        first_root.messages.append(Element(name="announced", aria_role="message", runtime_id=(2, 2)))
        app_module._uiaRead()
        sys.modules["ui"].message.reset_mock()

        replacement_root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="existing replacement", aria_role="message", runtime_id=(9, 1))],
        )
        _replacement_uia, replacement_foreground = install_uia(replacement_root)
        replacement_foreground.appModule = app_module
        sys.modules["api"].getForegroundObject.return_value = replacement_foreground

        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_foreground_window_change_does_not_read_cached_background_document(self, app_module):
        first_root, _first_document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="first window", aria_role="message", runtime_id=(2, 1))],
        )
        second_root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="second window", aria_role="message", runtime_id=(8, 1))],
        )
        uia, foreground = install_uia(first_root)
        uia.ElementFromHandle.side_effect = lambda handle: first_root if handle == 1 else second_root
        foreground.windowHandle = 1
        foreground.appModule = app_module
        sys.modules["api"].getForegroundObject.return_value = foreground
        app_module._uiaRead()

        first_root.messages.append(Element(name="private background message", aria_role="message", runtime_id=(2, 2)))
        foreground.windowHandle = 2
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()
        assert uia.ElementFromHandle.call_args.args == (2,)

    def test_detached_cached_document_recovery_is_silent(self, app_module):
        root, document = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name="existing", aria_role="message", runtime_id=(2, 1))],
        )
        _uia, foreground = install_uia(root)
        foreground.appModule = app_module
        sys.modules["api"].getForegroundObject.return_value = foreground
        app_module._uiaRead()

        document.GetCurrentPropertyValue = MagicMock(side_effect=OSError("detached"))
        replacement = Element(value="https://discord.com/channels/1/2", runtime_id=(9, 9))
        root.documents = [replacement]
        root.messages[:] = [Element(name="replacement", aria_role="message", runtime_id=(9, 1))]
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    @pytest.mark.parametrize("host", ["discord.com", "ptb.discord.com", "canary.discord.com"])
    def test_accepts_supported_exact_discord_channel_hosts(self, app_module, host):
        root, _ = make_tree(f"https://{host}/channels/1/2", [])
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.channel_id == f"https://{host}/channels/1/2"

    @pytest.mark.parametrize(
        "url",
        [
            "http://discord.com/channels/1/2",
            "https://discord.com.evil.test/channels/1/2",
            "https://discord.com/not-channels/1/2",
            "https://discord.com//channels/1/2",
            "https://discord.com/channels/only-one-id",
            "https://discord.com:443/channels/1/2",
        ],
    )
    def test_rejects_noncanonical_discord_channel_urls(self, app_module, url):
        root, _ = make_tree(url, [])
        _uia, foreground = install_uia(root)

        assert app_module._getSnapshotViaUIA(foreground) is None

    def test_current_property_attributes_are_supported_as_fallback(self, app_module):
        root = Element(control_type=0)
        document = AttributeFallbackElement(
            current_value="https://discord.com/channels/7/8",
            runtime_id=(4, 5),
        )
        main = Element(aria_role="main", control_type=50026)
        message_list = Element(
            control_type=_LIST,
            children=[
                AttributeFallbackElement(current_name="fallback message", aria_role="message", runtime_id=(6, 7))
            ],
        )
        message_list.parent = main
        main.parent = root
        root.lists = [message_list]
        root.documents = [document]
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.channel_id == "https://discord.com/channels/7/8"
        assert snapshot.messages[0].text == "fallback message"

    def test_identical_text_fallback_is_occurrence_aware(self, app_module):
        root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [
                Element(name="same", aria_role="message"),
                Element(name="same", aria_role="message"),
            ],
        )
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.messages[0].identity != snapshot.messages[1].identity
        assert snapshot.messages[0].identity[:-1] == snapshot.messages[1].identity[:-1]

    def test_snapshot_keeps_structurally_valid_short_and_typing_text(self, app_module):
        root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [
                Element(name="hi", aria_role="message", runtime_id=(1,)),
                Element(name="alice: Bob is typing fast", aria_role="message", runtime_id=(2,)),
                Element(name="yes , no", aria_role="message", runtime_id=(3,)),
            ],
        )
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert [message.text for message in snapshot.messages] == [
            "hi",
            "alice: Bob is typing fast",
            "yes , no",
        ]

    def test_snapshot_storage_is_bounded_to_recent_messages(self, app_module):
        messages = [
            Element(name=f"message {index}", aria_role="message", runtime_id=(index,))
            for index in range(app_module.MAX_SNAPSHOT_MESSAGES + 5)
        ]
        root, _ = make_tree("https://discord.com/channels/1/2", messages)
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert len(snapshot.messages) == app_module.MAX_SNAPSHOT_MESSAGES
        assert snapshot.messages[0].text == "message 5"

    def test_snapshot_sanitizes_and_bounds_text_before_retaining_it(self, app_module):
        raw_text = "x" * 1000 + "\x00\u202e"
        root, _ = make_tree(
            "https://discord.com/channels/1/2",
            [Element(name=raw_text, aria_role="message", runtime_id=(1,))],
        )
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.messages[0].text == "x" * 499 + "…"

    def test_returns_none_without_channel_document(self, app_module):
        root = Element()
        _uia, foreground = install_uia(root)

        assert app_module._getSnapshotViaUIA(foreground) is None

    def test_returns_none_when_uia_is_unavailable(self, app_module):
        sys.modules["UIAHandler"].handler.clientObject = None

        assert app_module._getSnapshotViaUIA(MagicMock(windowHandle=1)) is None
