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
_AUTOMATION_ID = 30011
_IS_OFFSCREEN = 30022

_GROUP = 50026
_HEADING = 50020
_BUTTON = 50000
_LINK = 50005
_IMAGE = 50006


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
        automation_id="",
        offscreen=False,
    ):
        self.properties = {
            _NAME: name,
            _VALUE: value,
            _ARIA_ROLE: aria_role,
            _CONTROL_TYPE: control_type,
            _AUTOMATION_ID: automation_id,
            _IS_OFFSCREEN: offscreen,
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
    def GetFirstChildElement(element):
        return element.children[0] if element.children else None

    @staticmethod
    def GetLastChildElement(element):
        return element.children[-1] if element.children else None

    @staticmethod
    def GetNextSiblingElement(element):
        siblings = element.parent.children
        index = siblings.index(element)
        return siblings[index + 1] if index + 1 < len(siblings) else None

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

    def test_prefers_article_summary_over_noisy_list_item_name(self, app_module):
        """The list item Name concatenates reactions and the hover toolbar."""
        article = Element(
            name="Bryn , what's this, AAC music? , 11:53 PM",
            aria_role="article",
            control_type=50026,
        )
        item = Element(
            name=(
                "Bryn11:53 PMFriday, August 28, 2026 11:53 PMwhat's this, AAC music?"
                ":pleading_face:Click to react:rofl:Click to reactAdd ReactionEditForwardMore"
            ),
            aria_role="listitem",
            runtime_id=(2, 1),
            children=[article],
        )
        root, _ = make_tree("https://discord.com/channels/1/2", [item])
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert [message.text for message in snapshot.messages] == ["Bryn , what's this, AAC music? , 11:53 PM"]

    def test_article_summary_restores_author_on_grouped_messages(self, app_module):
        """Consecutive messages from one author omit the header from the item Name."""
        article = Element(
            name="acerbt , this is the modern voice demo. , 11:52 PM",
            aria_role="article",
            control_type=50026,
        )
        item = Element(
            name="11:52 PMTuesday, August 25, 2026 11:52 PMthis is the modern voice demo.",
            aria_role="listitem",
            runtime_id=(2, 1),
            children=[article],
        )
        root, _ = make_tree("https://discord.com/channels/1/2", [item])
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot.messages[0].text.startswith("acerbt")

    def test_falls_back_to_list_item_name_without_article_child(self, app_module):
        item = Element(name="plain message", aria_role="listitem", runtime_id=(2, 1))
        root, _ = make_tree("https://discord.com/channels/1/2", [item])
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert [message.text for message in snapshot.messages] == ["plain message"]

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
            "https://discord.com/channels/@me/222222222222222222/333333333333333333",
            "https://discord.com/channels/1/2/3",
            "https://ptb.discord.com/channels/1/2/3",
        ],
    )
    def test_accepts_channel_urls_with_trailing_message_id(self, app_module, url):
        """Discord appends a message id when a message is focused or deep-linked."""
        root, _ = make_tree(url, [])
        _uia, foreground = install_uia(root)

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot is not None
        assert snapshot.channel_id == url.rsplit("/", 1)[0]

    def test_trailing_message_id_does_not_change_channel_identity(self, app_module):
        """A changing message id must not read as a channel change and re-baseline."""
        first = Element(name="alice: hi", aria_role="message", runtime_id=(2, 1))
        root, document = make_tree("https://discord.com/channels/1/2/100", [first])
        _uia, foreground = install_uia(root)
        foreground.appModule = app_module
        sys.modules["api"].getForegroundObject.return_value = foreground

        app_module._uiaRead()
        sys.modules["ui"].message.assert_not_called()

        document.properties[_VALUE] = "https://discord.com/channels/1/2/101"
        root.messages.append(Element(name="bob: new", aria_role="message", runtime_id=(2, 2)))
        app_module._uiaRead()

        sys.modules["ui"].message.assert_called_once_with("bob: new")

    @pytest.mark.parametrize(
        "url",
        [
            "http://discord.com/channels/1/2",
            "https://discord.com.evil.test/channels/1/2",
            "https://discord.com/not-channels/1/2",
            "https://discord.com//channels/1/2",
            "https://discord.com/channels/only-one-id",
            "https://discord.com:443/channels/1/2",
            "https://discord.com/channels/1/2/not-a-message-id",
            "https://discord.com/channels/1/2/3/4",
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


# ---------------------------------------------------------------------------
# Builders mirroring the real Discord UIA shapes captured from a live client.
# ---------------------------------------------------------------------------


def _timestamp_blocks(mid, short, long_form):
    """Discord renders the clock twice: a visible short form and a hidden long form."""
    return [
        Element(
            aria_role="group",
            control_type=_GROUP,
            children=[
                Element(
                    aria_role="time",
                    control_type=_HEADING,
                    automation_id=f"message-timestamp-{mid}",
                    children=[Element(aria_role="description", control_type=_HEADING, name=short)],
                )
            ],
        ),
        Element(
            aria_role="group",
            control_type=_GROUP,
            children=[
                Element(
                    aria_role="description",
                    control_type=_HEADING,
                    name=long_form,
                    offscreen=True,
                )
            ],
        ),
    ]


def _content_block(mid, body_children):
    return Element(
        aria_role="group",
        control_type=_GROUP,
        automation_id=f"message-content-{mid}",
        children=body_children,
    )


def _described_link(text):
    return Element(
        aria_role="link",
        control_type=_LINK,
        name=text,
        children=[Element(aria_role="description", control_type=_HEADING, name=text)],
    )


def youtube_embed(platform="YouTube", channel="wavywebsurf", title="Why This Mascot Punched"):
    """A link embed: content elements carry a description child, chrome does not."""
    return Element(
        aria_role="group",
        control_type=_GROUP,
        children=[
            Element(
                aria_role="article",
                control_type=_GROUP,
                children=[
                    Element(aria_role="button", control_type=_BUTTON, name="Remove all embeds"),
                    Element(
                        aria_role="group",
                        control_type=_GROUP,
                        children=[Element(aria_role="description", control_type=_HEADING, name=platform)],
                    ),
                    _described_link(channel),
                    Element(
                        aria_role="group",
                        control_type=_GROUP,
                        children=[_described_link(title)],
                    ),
                    Element(
                        aria_role="group",
                        control_type=_GROUP,
                        children=[
                            Element(
                                aria_role="button",
                                control_type=_BUTTON,
                                name="Image",
                                children=[Element(aria_role="img", control_type=_IMAGE, name="Image")],
                            ),
                            Element(aria_role="button", control_type=_BUTTON, name="Play"),
                            Element(
                                aria_role="link",
                                control_type=_LINK,
                                name="Open Link",
                                children=[Element(aria_role="img", control_type=_IMAGE, name="Open Link")],
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


def discord_message(
    *,
    mid,
    author=None,
    body="Test",
    short="1:04 PM",
    long_form="Saturday, August 29, 2026 1:04 PM",
    embed=None,
    article_name=None,
):
    """Build one message list item.

    `author=None` models a grouped continuation: Discord drops the header
    entirely, and the timestamp blocks are hoisted to the top of the article.
    """
    body_children = [Element(aria_role="description", control_type=_HEADING, name=body)] if body else []
    if author is None:
        article_children = [
            *_timestamp_blocks(mid, short, long_form),
            _content_block(mid, body_children),
        ]
    else:
        article_children = [
            Element(
                aria_role="heading",
                control_type=_HEADING,
                name=f"{author} {short}",
                children=[
                    Element(
                        aria_role="group",
                        control_type=_GROUP,
                        automation_id=f"message-username-{mid}",
                        children=[Element(aria_role="button", control_type=_BUTTON, name=author)],
                    ),
                    Element(
                        aria_role="group",
                        control_type=_GROUP,
                        children=_timestamp_blocks(mid, short, long_form),
                    ),
                ],
            ),
            _content_block(mid, body_children),
        ]
    if embed is not None:
        article_children.append(embed)

    if article_name is None:
        article_name = f"{author or 'someone'} , {body} , {short}"
    article = Element(
        aria_role="article",
        control_type=_GROUP,
        name=article_name,
        children=article_children,
    )
    return Element(
        aria_role="listitem",
        control_type=_LIST_ITEM,
        runtime_id=(2, int(mid)),
        name=f"{author or ''}{short}{long_form}{body}",
        children=[article],
    )


def texts_for(app_module, items):
    root, _document = make_tree("https://discord.com/channels/1/2", items)
    _uia, foreground = install_uia(root)
    snapshot = app_module._getSnapshotViaUIA(foreground)
    return [message.text for message in snapshot.messages]


class TestStructuralTextComposition:
    """Compose announcement text from Discord's own labelled message parts."""

    def test_composes_author_and_body_dropping_both_timestamps(self, app_module):
        items = [discord_message(mid="1", author="blindndangerous", body="Test")]

        assert texts_for(app_module, items) == ["blindndangerous, Test"]

    def test_drops_hidden_long_form_timestamp(self, app_module):
        """The long form is marked offscreen; it must never reach speech."""
        items = [
            discord_message(
                mid="1",
                author="Bryn",
                body="hello",
                long_form="Friday, August 28, 2026 11:53 PM",
            )
        ]

        (text,) = texts_for(app_module, items)

        assert "Friday" not in text
        assert "August" not in text

    def test_drops_visible_short_timestamp_by_automation_id(self, app_module):
        items = [discord_message(mid="1", author="Bryn", body="hello", short="11:53 PM")]

        (text,) = texts_for(app_module, items)

        assert "11:53" not in text
        assert text == "Bryn, hello"

    def test_carries_author_across_a_grouped_run(self, app_module):
        """Discord omits the header on consecutive messages from one author."""
        items = [
            discord_message(mid="1", author="acerbt", body="first"),
            discord_message(mid="2", author=None, body="second"),
            discord_message(mid="3", author=None, body="third"),
        ]

        assert texts_for(app_module, items) == [
            "acerbt, first",
            "acerbt, second",
            "acerbt, third",
        ]

    def test_new_author_ends_the_grouped_run(self, app_module):
        items = [
            discord_message(mid="1", author="acerbt", body="first"),
            discord_message(mid="2", author=None, body="second"),
            discord_message(mid="3", author="Bryn", body="third"),
            discord_message(mid="4", author=None, body="fourth"),
        ]

        assert texts_for(app_module, items) == [
            "acerbt, first",
            "acerbt, second",
            "Bryn, third",
            "Bryn, fourth",
        ]

    def test_leading_continuation_stays_unattributed_rather_than_guessing(self, app_module):
        """A run whose author sits above the snapshot window has no author to use."""
        items = [
            discord_message(mid="1", author=None, body="orphaned"),
            discord_message(mid="2", author="Bryn", body="named"),
        ]

        assert texts_for(app_module, items) == ["orphaned", "Bryn, named"]

    def test_keeps_embed_content_and_drops_embed_chrome(self, app_module):
        items = [
            discord_message(
                mid="1",
                author="blindndangerous",
                body="https://youtu.be/rKtRpLqd240",
                embed=youtube_embed(),
            )
        ]

        (text,) = texts_for(app_module, items)

        assert text == ("blindndangerous, https://youtu.be/rKtRpLqd240, YouTube, wavywebsurf, Why This Mascot Punched")
        for chrome in ("Remove all embeds", "Play", "Open Link", "Image"):
            assert chrome not in text

    def test_embed_chrome_dropped_on_grouped_message_too(self, app_module):
        items = [
            discord_message(mid="1", author="blindndangerous", body="first"),
            discord_message(mid="2", author=None, body="https://youtu.be/x", embed=youtube_embed()),
        ]

        second = texts_for(app_module, items)[1]

        assert second.startswith("blindndangerous, https://youtu.be/x, YouTube")
        assert "Remove all embeds" not in second

    def test_falls_back_to_article_name_when_no_parts_are_labelled(self, app_module):
        """If Discord drops the labelled parts, its own summary beats saying nothing."""
        article = Element(
            aria_role="article",
            control_type=_GROUP,
            name="Bryn , unlabelled shape , 11:53 PM",
        )
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["Bryn , unlabelled shape , 11:53 PM"]

    def test_message_without_a_text_body_uses_discord_summary(self, app_module):
        """An attachment-only message has no content element; the article name still describes it."""
        items = [
            discord_message(
                mid="1",
                author="Bryn",
                body="",
                article_name="Bryn , image.png , 1:04 PM",
            )
        ]

        assert texts_for(app_module, items) == ["Bryn , image.png , 1:04 PM"]

    def test_deeply_nested_body_is_still_reached(self, app_module):
        deep = Element(aria_role="description", control_type=_HEADING, name="buried")
        for _ in range(5):
            deep = Element(aria_role="group", control_type=_GROUP, children=[deep])
        article = Element(
            aria_role="article",
            control_type=_GROUP,
            name="fallback",
            children=[
                Element(
                    aria_role="group",
                    control_type=_GROUP,
                    automation_id="message-content-1",
                    children=[deep],
                )
            ],
        )
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["buried"]

    def test_walk_is_bounded_against_pathological_depth(self, app_module):
        """A runaway tree must fall back, not stall the 500ms poll."""
        deep = Element(aria_role="description", control_type=_HEADING, name="too deep")
        for _ in range(40):
            deep = Element(aria_role="group", control_type=_GROUP, children=[deep])
        article = Element(aria_role="article", control_type=_GROUP, name="bounded fallback", children=[deep])
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["bounded fallback"]

    def test_author_falls_back_to_a_named_descendant(self, app_module):
        """The username element is a wrapper; the name sits on a button inside it."""
        article = Element(
            aria_role="article",
            control_type=_GROUP,
            name="fallback",
            children=[
                Element(
                    aria_role="group",
                    control_type=_GROUP,
                    automation_id="message-username-1",
                    children=[
                        Element(
                            aria_role="group",
                            control_type=_GROUP,
                            children=[Element(control_type=_BUTTON, name="NestedName")],
                        )
                    ],
                ),
                _content_block("1", [Element(aria_role="description", control_type=_HEADING, name="hi")]),
            ],
        )
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["NestedName, hi"]


class TestStructuralEdgePaths:
    """Bounded-walk and parsing paths that only appear on malformed trees."""

    def test_author_lookup_gives_up_when_nothing_is_named(self, app_module):
        """A username wrapper whose whole subtree is unnamed yields no author."""
        article = Element(
            aria_role="article",
            control_type=_GROUP,
            name="fallback",
            children=[
                Element(
                    aria_role="group",
                    control_type=_GROUP,
                    automation_id="message-username-1",
                    children=[
                        Element(aria_role="group", control_type=_GROUP),
                        Element(aria_role="group", control_type=_GROUP),
                    ],
                ),
                _content_block("1", [Element(aria_role="description", control_type=_HEADING, name="hi")]),
            ],
        )
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["hi"]

    def test_author_lookup_stops_at_the_depth_bound(self, app_module):
        """A username subtree deeper than the bound must not be searched forever."""
        deep = Element(control_type=_BUTTON, name="TooDeepToUse")
        for _ in range(20):
            deep = Element(aria_role="group", control_type=_GROUP, children=[deep])
        article = Element(
            aria_role="article",
            control_type=_GROUP,
            name="fallback",
            children=[
                Element(
                    aria_role="group",
                    control_type=_GROUP,
                    automation_id="message-username-1",
                    children=[deep],
                ),
                _content_block("1", [Element(aria_role="description", control_type=_HEADING, name="hi")]),
            ],
        )
        item = Element(aria_role="listitem", runtime_id=(2, 1), children=[article])

        assert texts_for(app_module, [item]) == ["hi"]

    def test_list_item_with_no_named_descendant_is_skipped(self, app_module):
        """No article, no name, no named child: there is nothing to announce."""
        item = Element(
            aria_role="listitem",
            runtime_id=(2, 1),
            children=[
                Element(aria_role="group", control_type=_GROUP),
                Element(aria_role="group", control_type=_GROUP),
            ],
        )

        assert texts_for(app_module, [item]) == []

    @pytest.mark.parametrize("value", [None, 1234, b"https://discord.com/channels/1/2"])
    def test_channel_identity_rejects_non_string_values(self, app_module, value):
        assert app_module._channelIdentity(value) is None

    def test_channel_identity_rejects_unparseable_urls(self, app_module):
        """urlsplit raises on a malformed IPv6 literal rather than returning a result."""
        assert app_module._channelIdentity("https://[::1/channels/1/2") is None
