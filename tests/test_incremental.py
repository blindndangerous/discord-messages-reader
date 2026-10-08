"""Polling cost tests: each list item is read once, and failed discovery backs off.

Every UIA call crosses into Discord's process and runs on NVDA's main thread, so
a poll that re-reads every visible article stalls speech and keyboard input.
"""

import sys
import time
from unittest.mock import MagicMock

import pytest

from tests.test_uia import (
    _AUTOMATION_ID,
    _CONTROL_TYPE,
    _NAME,
    _VALUE,
    Element,
    RawViewWalker,
    discord_message,
    install_uia,
    make_tree,
)

_SEPARATOR = 50038


def start(app_module, items, url="https://discord.com/channels/1/2"):
    root, document = make_tree(url, items)
    uia, foreground = install_uia(root)
    foreground.appModule = app_module
    sys.modules["api"].getForegroundObject.return_value = foreground
    return root, document, uia, foreground


def spoken():
    return [call.args[0] for call in sys.modules["ui"].message.call_args_list]


def authored(count):
    return [discord_message(mid=str(index), author="Alice", body=f"m{index}") for index in range(1, count + 1)]


class TestIncrementalPolling:
    def test_quiet_poll_reads_no_article_and_walks_no_siblings(self, app_module, mocker):
        items = [*authored(5), Element(control_type=_SEPARATOR, runtime_id=(3, 1))]
        _root, _document, uia, _foreground = start(app_module, items)
        app_module._uiaRead()
        uia.RawViewWalker = MagicMock(wraps=RawViewWalker())
        parts = mocker.spy(app_module, "_messageParts")

        app_module._uiaRead()

        assert parts.call_count == 0
        # The separator is the last child; its sibling is the known tail.
        assert uia.RawViewWalker.GetPreviousSiblingElement.call_count == 1
        sys.modules["ui"].message.assert_not_called()

    def test_new_message_is_read_once_and_announced_once(self, app_module, mocker):
        root, _document, _uia, _foreground = start(app_module, authored(5))
        app_module._uiaRead()
        parts = mocker.spy(app_module, "_messageParts")

        root.messages.append(discord_message(mid="6", author="Bob", body="new"))
        app_module._uiaRead()
        app_module._uiaRead()

        assert parts.call_count == 1
        assert spoken() == ["Bob, new"]

    def test_grouped_run_keeps_its_author_across_polls(self, app_module):
        root, _document, _uia, _foreground = start(app_module, authored(1))
        app_module._uiaRead()

        root.messages.append(discord_message(mid="2", body="more"))
        app_module._uiaRead()
        root.messages.append(discord_message(mid="3", body="again"))
        app_module._uiaRead()

        assert spoken() == ["Alice, more", "Alice, again"]

    def test_lost_tail_is_still_a_silent_recovery_baseline(self, app_module):
        root, _document, _uia, _foreground = start(app_module, authored(2))
        app_module._uiaRead()

        root.messages[:] = [root.messages[0], discord_message(mid="3", author="Bob", body="unordered")]
        app_module._uiaRead()
        sys.modules["ui"].message.assert_not_called()

        root.messages.append(discord_message(mid="4", author="Bob", body="ordered"))
        app_module._uiaRead()
        assert spoken() == ["Bob, ordered"]

    def test_item_filled_in_after_insertion_is_announced(self, app_module):
        """Discord can insert a list item before its content; empty reads are not cached."""
        root, _document, _uia, _foreground = start(app_module, authored(1))
        app_module._uiaRead()
        late = Element(runtime_id=(2, 9))
        root.messages.append(late)
        app_module._uiaRead()

        late.properties[_NAME] = "late text"
        app_module._uiaRead()

        assert spoken() == ["late text"]

    def test_new_message_without_runtime_id_reads_the_whole_window(self, app_module):
        root, _document, _uia, _foreground = start(app_module, authored(2))
        app_module._uiaRead()

        root.messages.append(Element(name="no runtime id"))
        app_module._uiaRead()

        assert spoken() == ["no runtime id"]

    def test_fingerprint_tail_reads_the_whole_window(self, app_module):
        root, _document, _uia, _foreground = start(app_module, [Element(name="first")])
        app_module._uiaRead()

        root.messages.append(Element(name="second"))
        app_module._uiaRead()

        assert spoken() == ["second"]

    def test_empty_channel_reads_the_whole_window(self, app_module):
        """With no known tail, ordering is unknown, so the first arrival stays a silent baseline."""
        root, _document, _uia, _foreground = start(app_module, [])
        app_module._uiaRead()

        root.messages.append(discord_message(mid="1", author="Alice", body="first"))
        app_module._uiaRead()
        sys.modules["ui"].message.assert_not_called()

        root.messages.append(discord_message(mid="2", author="Alice", body="second"))
        app_module._uiaRead()
        assert spoken() == ["Alice, second"]

    def test_extended_snapshot_stays_bounded(self, app_module):
        app_module.MAX_SNAPSHOT_MESSAGES = 3
        root, _document, _uia, _foreground = start(app_module, authored(3))
        app_module._uiaRead()

        root.messages.append(discord_message(mid="4", author="Bob", body="new"))
        app_module._uiaRead()

        (snapshot,) = app_module._channelSnapshots.values()
        assert [message.text for message in snapshot.messages] == ["Alice, m2", "Alice, m3", "Bob, new"]

    def test_item_cache_is_bounded(self, app_module):
        app_module.MAX_CACHED_ITEMS = 3
        start(app_module, authored(5))

        app_module._uiaRead()

        assert len(app_module._itemCache) == 3


class TestItemCacheValidity:
    def test_header_added_in_place_replaces_the_cached_author(self, app_module):
        """Deleting a run's first message makes Discord give the next one a header in place."""
        items = [
            discord_message(mid="1", author="Bob", body="above"),
            discord_message(mid="2", author="Alice", body="opens"),
            discord_message(mid="3", body="continues"),
        ]
        root, _document, _uia, _foreground = start(app_module, items)
        app_module._uiaRead()

        rerendered = discord_message(mid="3", author="Alice", body="continues")
        continuation = root.messages[2]
        continuation.children[:] = rerendered.children
        continuation.properties[_NAME] = rerendered.properties[_NAME]
        del root.messages[1]
        app_module._markBaselineRequired()
        app_module._uiaRead()

        root.messages.append(discord_message(mid="4", body="later"))
        app_module._uiaRead()

        assert spoken() == ["Alice, later"]

    def test_unchanged_item_is_not_parsed_again_on_a_baseline(self, app_module, mocker):
        start(app_module, authored(5))
        app_module._uiaRead()
        parts = mocker.spy(app_module, "_messageParts")

        app_module._markBaselineRequired()
        app_module._uiaRead()

        assert parts.call_count == 0

    def test_failed_control_type_read_is_not_cached(self, app_module):
        root, _document, _uia, _foreground = start(app_module, authored(1))
        app_module._uiaRead()
        busy = discord_message(mid="2", author="Bob", body="arrived while busy")
        real_read = busy.GetCurrentPropertyValue
        busy.GetCurrentPropertyValue = MagicMock(
            side_effect=lambda property_id: (
                (_ for _ in ()).throw(OSError("timeout")) if property_id == _CONTROL_TYPE else real_read(property_id)
            )
        )
        root.messages.append(busy)
        app_module._uiaRead()
        sys.modules["ui"].message.assert_not_called()

        busy.GetCurrentPropertyValue = real_read
        app_module._uiaRead()

        assert spoken() == ["Bob, arrived while busy"]

    def test_message_read_with_a_lost_property_is_not_cached(self, app_module, mocker):
        start(app_module, authored(2))

        def lossy(walker, element):
            app_module._propertyReadFailures += 1
            return real_parts(walker, element)

        real_parts = app_module._messageParts
        mocker.patch.object(app_module, "_messageParts", side_effect=lossy)
        app_module._uiaRead()

        assert app_module._itemCache == {}


class TestHistoryCost:
    def test_history_reads_fresh_text_after_an_edit(self, app_module):
        item = Element(name="before", runtime_id=(2, 1))
        start(app_module, [item])
        app_module._uiaRead()

        item.properties[_NAME] = "after"
        app_module._readNthLastMessage(1)

        assert spoken() == ["after"]

    def test_history_stops_once_the_wanted_run_has_an_author(self, app_module, mocker):
        start(app_module, authored(20))
        parts = mocker.spy(app_module, "_messageParts")

        app_module._readNthLastMessage(2)

        assert parts.call_count == 2
        assert spoken() == ["Alice, m19"]

    def test_history_walks_up_to_the_author_of_a_grouped_run(self, app_module):
        items = [
            discord_message(mid="1", author="Alice", body="opens"),
            discord_message(mid="2", body="continues"),
            discord_message(mid="3", body="ends"),
        ]
        start(app_module, items)

        app_module._readNthLastMessage(1)

        assert spoken() == ["Alice, ends"]

    def test_history_bypasses_the_discovery_delay(self, app_module):
        start(app_module, authored(1))
        app_module._discoveryRetryAt = time.monotonic() + 100

        app_module._readNthLastMessage(1)

        assert spoken() == ["Alice, m1"]


class TestDiscoveryBackoff:
    def test_missing_message_list_is_not_searched_again_immediately(self, app_module):
        root, _document, _uia, foreground = start(app_module, [])
        root.lists = []
        root.FindAll = MagicMock(wraps=root.FindAll)

        assert app_module._getSnapshotViaUIA(foreground) is None
        searches = root.FindAll.call_count
        assert app_module._getSnapshotViaUIA(foreground) is None
        assert root.FindAll.call_count == searches

        app_module._discoveryRetryAt = 0.0
        app_module._getSnapshotViaUIA(foreground)
        assert root.FindAll.call_count == searches + 1

    def test_retry_delay_doubles_to_a_cap_and_resets_on_success(self, app_module, mocker):
        root, _document, _uia, foreground = start(app_module, authored(1))
        lists = root.lists
        root.lists = []
        clock = mocker.patch("discord.time.monotonic", return_value=1000.0)
        delays = []
        for _ in range(6):
            app_module._discoveryRetryAt = 0.0
            app_module._getSnapshotViaUIA(foreground)
            delays.append(app_module._discoveryRetryAt - clock.return_value)

        assert delays == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]

        root.lists = lists
        app_module._discoveryRetryAt = 0.0
        assert app_module._getSnapshotViaUIA(foreground) is not None
        assert app_module._discoveryFailures == 0

    def test_missing_documents_are_not_searched_again_immediately(self, app_module):
        root, _document, _uia, foreground = start(app_module, [])
        root.documents = []
        root.FindAll = MagicMock(wraps=root.FindAll)

        app_module._getSnapshotViaUIA(foreground)
        app_module._getSnapshotViaUIA(foreground)

        assert root.FindAll.call_count == 1

    def test_discord_page_without_channel_stays_cached(self, app_module):
        """Friends and settings pages must not trigger a window search every poll."""
        root, document, _uia, foreground = start(app_module, authored(1), url="https://discord.com/channels/@me")
        root.FindAll = MagicMock(wraps=root.FindAll)

        for _ in range(5):
            assert app_module._getSnapshotViaUIA(foreground) is None
        document.properties[_VALUE] = "https://discord.com/channels/1/2"
        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot is not None
        assert [call.args[1][2] for call in root.FindAll.call_args_list] == [50030, 50008]
        assert all(call.args[1][1] == _CONTROL_TYPE for call in root.FindAll.call_args_list)

    def test_non_discord_document_is_not_cached(self, app_module):
        _root, document, _uia, foreground = start(app_module, [], url="https://discord.com/channels/1/2")
        app_module._getSnapshotViaUIA(foreground)

        document.properties[_VALUE] = "https://example.test/"
        assert app_module._getSnapshotViaUIA(foreground) is None

        assert app_module._channelDocument is None

    def test_unparseable_document_value_is_not_a_discord_page(self, app_module):
        assert app_module._isDiscordPage("https://[broken") is False
        assert app_module._isDiscordPage(None) is False

    def test_missing_uia_handler_yields_no_snapshot(self, app_module, monkeypatch):
        monkeypatch.setattr(sys.modules["UIAHandler"], "handler", None)

        assert app_module._getSnapshotViaUIA(MagicMock(windowHandle=1)) is None


NOW = 1_790_000_000.0


@pytest.fixture()
def fixed_clock(mocker):
    """Message IDs carry creation times, so the add-on's clock must be fixed."""
    mocker.patch("discord.time.time", return_value=NOW)


def sid(seconds_ago, sequence=0):
    """A Discord message ID created this many seconds before NOW."""
    from discord import _snowflakeAt

    return _snowflakeAt(NOW - seconds_ago) + sequence


def snowflake(message_id, author=None, body="Test", runtime=None, channel="2"):
    """A message list item carrying Discord's own IDs, as the live client does."""
    item = discord_message(mid="1", author=author, body=body)
    item.properties[_AUTOMATION_ID] = f"chat-messages-{channel}-{message_id}"
    item.runtime_id = runtime if runtime is not None else (7, message_id % 1_000_003)
    return item


def recent(count, author="Alice", start=20):
    """`count` messages from `author`, one second apart, the first `start` seconds ago."""
    return [snowflake(sid(start - index), author if index == 0 else None, f"m{index}") for index in range(count)]


@pytest.mark.usefixtures("fixed_clock")
class TestMessageIdIdentity:
    def test_items_are_identified_by_discord_message_and_channel_id(self, app_module):
        start(app_module, [snowflake(sid(5), "Alice", "hi")])

        app_module._uiaRead()

        (snapshot,) = app_module._channelSnapshots.values()
        assert snapshot.messages[0].identity == ("message", sid(5), "2")
        (marks,) = app_module._channelMarks.values()
        assert marks.high_water == sid(5)

    def test_deleted_tail_does_not_swallow_a_new_message(self, app_module):
        """Runtime-ID diffing lost this arrival to a silent recovery baseline."""
        root, _document, _uia, _foreground = start(app_module, recent(2))
        app_module._uiaRead()

        del root.messages[1]
        root.messages.append(snowflake(sid(1), "Bob", "new"))
        app_module._uiaRead()

        assert spoken() == ["Bob, new"]

    def test_pending_message_replaced_by_confirmed_is_announced_once(self, app_module):
        root, _document, _uia, _foreground = start(app_module, recent(1))
        app_module._uiaRead()

        root.messages.append(snowflake(sid(3), "Me", "sent"))
        app_module._uiaRead()
        root.messages[-1] = snowflake(sid(3, 5), "Me", "sent")
        root.messages.append(snowflake(sid(2), "Bob", "reply"))
        app_module._uiaRead()

        assert spoken() == ["Me, sent", "Bob, reply"]

    def test_reply_landing_between_pending_and_confirmed_does_not_repeat_mine(self, app_module):
        root, _document, _uia, _foreground = start(app_module, recent(1))
        app_module._uiaRead()

        root.messages.append(snowflake(sid(4), "Me", "sent"))
        app_module._uiaRead()
        root.messages.append(snowflake(sid(3), "Bob", "reply"))
        app_module._uiaRead()
        del root.messages[-2]
        root.messages.append(snowflake(sid(2), "Me", "sent"))
        app_module._uiaRead()

        assert spoken() == ["Me, sent", "Bob, reply"]

    def test_pending_id_from_a_fast_clock_does_not_hide_later_messages(self, app_module):
        """The client clock ran ahead, so the pending ID is larger than what follows."""
        root, _document, _uia, _foreground = start(app_module, recent(1))
        app_module._uiaRead()

        root.messages.append(snowflake(sid(-10), "Me", "sent"))
        app_module._uiaRead()
        root.messages[-1] = snowflake(sid(1), "Me", "sent")
        app_module._uiaRead()
        root.messages.append(snowflake(sid(0), "Bob", "after"))
        app_module._uiaRead()

        assert spoken() == ["Me, sent", "Bob, after"]

    def test_message_inserted_above_the_newest_is_announced(self, app_module):
        """Discord orders by ID, so a message created just before mine lands above it."""
        root, _document, _uia, _foreground = start(app_module, recent(1))
        app_module._uiaRead()

        root.messages.append(snowflake(sid(2), "Me", "sent"))
        app_module._uiaRead()
        root.messages[1:1] = [snowflake(sid(3), "Bob", "earlier")]
        app_module._uiaRead()

        assert spoken() == ["Me, sent", "Bob, earlier"]

    def test_same_text_twice_is_still_two_messages(self, app_module):
        root, _document, _uia, _foreground = start(app_module, [snowflake(sid(9), "Alice", "lol")])
        app_module._uiaRead()

        root.messages.append(snowflake(sid(1), body="lol"))
        app_module._uiaRead()

        assert spoken() == ["Alice, lol"]

    def test_rerendered_item_is_not_announced(self, app_module):
        root, _document, _uia, _foreground = start(app_module, [snowflake(sid(5), "Alice", "a", runtime=(2, 1))])
        app_module._uiaRead()

        root.messages[0] = snowflake(sid(5), "Alice", "a", runtime=(2, 99))
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_scrolling_away_and_back_announces_nothing_old(self, app_module):
        root, _document, _uia, _foreground = start(app_module, recent(6))
        app_module._uiaRead()

        hidden = root.messages[3:]
        del root.messages[3:]
        app_module._uiaRead()
        root.messages.extend(hidden)
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_message_that_arrived_while_scrolled_away_is_announced_once(self, app_module):
        root, _document, _uia, _foreground = start(app_module, recent(4))
        app_module._uiaRead()

        hidden = root.messages[2:]
        del root.messages[2:]
        app_module._uiaRead()
        root.messages.extend([*hidden, snowflake(sid(1), "Bob", "new")])
        app_module._uiaRead()
        app_module._uiaRead()

        assert spoken() == ["Bob, new"]

    def test_history_older_than_a_minute_is_never_new(self, app_module):
        """A jump link or a forgotten channel opens on history; scrolling down is not news."""
        root, _document, _uia, _foreground = start(app_module, [snowflake(sid(3600), "Alice", "old")])
        app_module._uiaRead()

        root.messages.extend(snowflake(sid(3500 - index), "Bob", f"later {index}") for index in range(3))
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()

    def test_marks_survive_snapshot_eviction(self, app_module):
        app_module.MAX_CHANNEL_SNAPSHOTS = 1
        root, document, _uia, _foreground = start(app_module, recent(3))
        app_module._uiaRead()

        document.properties[_VALUE] = "https://discord.com/channels/1/3"
        root.messages[:] = [snowflake(sid(30), "Carol", "elsewhere", channel="3")]
        app_module._uiaRead()
        document.properties[_VALUE] = "https://discord.com/channels/1/2"
        root.messages[:] = recent(3)
        app_module._uiaRead()
        app_module._uiaRead()

        assert "https://discord.com/channels/1/2" in app_module._channelMarks
        sys.modules["ui"].message.assert_not_called()

    def test_messages_from_another_channel_are_never_read_as_this_one(self, app_module):
        """The user switched channel between the URL read and the list walk."""
        root, _document, _uia, foreground = start(app_module, recent(2))
        app_module._uiaRead()

        root.messages[:] = [snowflake(sid(4), "Dave", "other channel", channel="5")]
        app_module._uiaRead()

        sys.modules["ui"].message.assert_not_called()
        assert app_module._getSnapshotViaUIA(foreground) is None

    def test_deleted_tail_does_not_lend_its_author(self, app_module):
        items = [snowflake(sid(55), "Alice", "first"), snowflake(sid(25), "Bob", "oops")]
        root, _document, _uia, _foreground = start(app_module, items)
        app_module._uiaRead()

        del root.messages[1]
        root.messages.append(snowflake(sid(1), body="continuing"))
        app_module._uiaRead()

        assert spoken() == ["Alice, continuing"]

    def test_quiet_channel_poll_walks_no_siblings(self, app_module):
        items = [snowflake(sid(600 - index), "Alice", f"m{index}") for index in range(10)]
        _root, _document, uia, _foreground = start(app_module, items)
        app_module._uiaRead()
        uia.RawViewWalker = MagicMock(wraps=RawViewWalker())

        app_module._uiaRead()

        assert uia.RawViewWalker.GetPreviousSiblingElement.call_count == 0

    def test_seen_ids_and_marked_channels_are_bounded(self, app_module):
        app_module.MAX_SEEN_PER_CHANNEL = 2
        app_module.MAX_MARKED_CHANNELS = 1
        root, document, _uia, _foreground = start(app_module, recent(4))
        app_module._uiaRead()
        (marks,) = app_module._channelMarks.values()
        assert len(marks.seen) == 2

        document.properties[_VALUE] = "https://discord.com/channels/1/3"
        root.messages[:] = [snowflake(sid(5), "Carol", "elsewhere", channel="3")]
        app_module._uiaRead()

        assert list(app_module._channelMarks) == ["https://discord.com/channels/1/3"]

    def test_non_message_identity_carries_no_message_id(self):
        from discord import _messageId

        assert _messageId(("runtime", 1, 2)) is None
        assert _messageId(None) is None


class TestSleepMode:
    def test_sleep_mode_silences_polling_and_wakes_to_a_silent_baseline(self, app_module):
        """NVDA's sleep mode only gates scripts; the poll timer must honour it itself."""
        root, _document, _uia, _foreground = start(app_module, authored(1))
        app_module._uiaRead()

        app_module.sleepMode = True
        root.messages.append(discord_message(mid="2", author="Bob", body="while asleep"))
        app_module._uiaRead()
        app_module.sleepMode = False
        app_module._uiaRead()
        sys.modules["ui"].message.assert_not_called()

        root.messages.append(discord_message(mid="3", author="Bob", body="awake"))
        app_module._uiaRead()
        assert spoken() == ["Bob, awake"]


@pytest.mark.usefixtures("fixed_clock")
class TestLazyBaseline:
    def test_baseline_reads_only_recent_messages_and_the_newest_author(self, app_module, mocker):
        """Channel switches froze NVDA for half a second parsing history never presented."""
        items = [snowflake(sid(600 - index), f"Author{index}", f"m{index}") for index in range(30)]
        start(app_module, items)
        parts = mocker.spy(app_module, "_messageParts")

        app_module._uiaRead()

        assert parts.call_count == 1

    def test_baseline_reads_back_to_the_author_of_a_grouped_run(self, app_module, mocker):
        items = [snowflake(sid(600 - index), "Alice" if index == 0 else None, f"m{index}") for index in range(5)]
        root, _document, _uia, _foreground = start(app_module, items)
        parts = mocker.spy(app_module, "_messageParts")
        app_module._uiaRead()
        assert parts.call_count == 5

        root.messages.append(snowflake(sid(1), body="continues"))
        app_module._uiaRead()
        assert spoken() == ["Alice, continues"]

    def test_history_still_reads_unread_baseline_messages(self, app_module):
        items = [snowflake(sid(600 - index), f"Author{index}", f"m{index}") for index in range(5)]
        start(app_module, items)
        app_module._uiaRead()

        app_module._readNthLastMessage(3)

        assert spoken() == ["Author2, m2"]


class TestNarrowDiscovery:
    def test_embedded_document_first_falls_back_to_all_documents(self, app_module):
        root, document, _uia, foreground = start(app_module, authored(1))
        root.documents = [Element(value="https://example.test/embed"), document]

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot is not None
        assert snapshot.channel_id == "https://discord.com/channels/1/2"

    def test_embedded_document_first_still_finds_a_discord_page(self, app_module):
        root, document, _uia, foreground = start(app_module, authored(1), url="https://discord.com/channels/@me")
        root.documents = [Element(value="https://example.test/embed"), document]

        assert app_module._getSnapshotViaUIA(foreground) is None
        assert app_module._channelDocument is document

    def test_foreign_first_document_and_no_others_is_reported(self, app_module):
        root, _document, _uia, foreground = start(app_module, authored(1))
        root.FindFirst = MagicMock(return_value=Element(value="https://example.test/embed"))
        root.FindAll = MagicMock(return_value=None)

        assert app_module._getSnapshotViaUIA(foreground) is None
        assert app_module._lastDiscoveryState == "no-documents"

    def test_replaced_message_list_is_found_again(self, app_module):
        _root, _document, _uia, foreground = start(app_module, authored(1))
        app_module._getSnapshotViaUIA(foreground)
        stale = app_module._messageList
        stale.properties[_CONTROL_TYPE] = 0

        snapshot = app_module._getSnapshotViaUIA(foreground)

        assert snapshot is not None
        assert app_module._messageList is stale


@pytest.mark.usefixtures("fixed_clock")
class TestUnreadStopPoint:
    def test_unread_history_at_the_stop_point_reads_back_to_its_author(self, app_module):
        items = [snowflake(sid(600), "Alice", "old"), snowflake(sid(590), "Bob", "older reply")]
        root, _document, _uia, _foreground = start(app_module, items)
        app_module._uiaRead()

        del root.messages[1]
        root.messages.append(snowflake(sid(1), body="continuing"))
        app_module._uiaRead()

        assert spoken() == ["Alice, continuing"]


# Proofs from the lazy-baseline review: a missing author and repeated full reads.


@pytest.mark.usefixtures("fixed_clock")
def test_lazy_review_inserted_continuation_below_newer_header(app_module):
    items = [snowflake(sid(120), "Alice", "hdr"), snowflake(sid(30), None, "c1"), snowflake(sid(5), "Bob", "bob")]
    root, *_ = start(app_module, items)
    app_module._uiaRead()
    # Alice's message created just before Bob's lands above it, grouped into her run
    root.messages[2:2] = [snowflake(sid(6), None, "c2")]
    app_module._uiaRead()
    assert spoken() == ["Alice, c2"]


@pytest.mark.usefixtures("fixed_clock")
def test_lazy_review_two_authors_in_one_poll_after_placeholder_tail(app_module):
    items = [snowflake(sid(600), "Alice", "old"), snowflake(sid(590), "Bob", "older reply")]
    root, *_ = start(app_module, items)
    app_module._uiaRead()
    del root.messages[1]
    root.messages.append(snowflake(sid(2), None, "continuing"))
    root.messages.append(snowflake(sid(1), "Bob", "new"))
    app_module._uiaRead()
    assert spoken() == ["Alice, continuing\nBob, new"]


@pytest.mark.usefixtures("fixed_clock")
def test_lazy_review_parsed_stop_point_with_lost_author(app_module, mocker):
    items = [snowflake(sid(120), "Alice", "hdr"), snowflake(sid(50), None, "c1"), snowflake(sid(45), "Bob", "bob")]
    root, *_ = start(app_module, items)
    app_module._uiaRead()
    mocker.patch("discord.time.time", return_value=NOW + 20)
    del root.messages[2]
    root.messages.append(snowflake(sid(-19), None, "continuing"))
    app_module._uiaRead()
    assert spoken() == ["Alice, continuing"]


@pytest.mark.usefixtures("fixed_clock")
def test_lazy_review_quiet_poll_after_baseline_with_recent_header(app_module):
    items = [snowflake(sid(600 - i), f"A{i}", f"m{i}") for i in range(30)] + [snowflake(sid(10), "Bob", "b")]
    _root, _d, uia, _f = start(app_module, items)
    app_module._uiaRead()
    uia.RawViewWalker = MagicMock(wraps=RawViewWalker())
    app_module._uiaRead()
    app_module._uiaRead()
    assert uia.RawViewWalker.GetPreviousSiblingElement.call_count <= 4
