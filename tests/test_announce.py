"""Snapshot baselines and accessible announcement tests."""

import sys

from discord import ChannelSnapshot, MessageEntry


def snapshot(channel="channel-1", *items):
    return ChannelSnapshot(
        channel_id=channel,
        messages=tuple(MessageEntry(("runtime", identity), text) for identity, text in items),
    )


def ui_message():
    return sys.modules["ui"].message


class TestSnapshotDiffing:
    def test_first_read_establishes_silent_baseline(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "alice: existing")))

        ui_message().assert_not_called()

    def test_new_runtime_id_is_announced_after_baseline(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "alice: first")))
        app_module._processSnapshot(snapshot("one", (1, "alice: first"), (2, "bob: second")))

        ui_message().assert_called_once_with("bob: second")

    def test_channel_change_establishes_silent_baseline(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "alice: first")))
        app_module._processSnapshot(snapshot("two", (2, "bob: existing")))

        ui_message().assert_not_called()

    def test_edit_and_delete_do_not_announce_existing_runtime_ids(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "alice: first"), (2, "bob: second")))
        app_module._processSnapshot(snapshot("one", (1, "alice: edited")))

        ui_message().assert_not_called()

    def test_repeated_identical_messages_with_distinct_ids_are_announced(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "alice: same")))
        app_module._processSnapshot(snapshot("one", (1, "alice: same"), (2, "alice: same")))

        ui_message().assert_called_once_with("alice: same")

    def test_fallback_identity_window_slide_does_not_reannounce_identical_messages(self, app_module):
        raw_entries = [(None, "alice: same", "alice: same")] * app_module.MAX_SNAPSHOT_MESSAGES
        first = ChannelSnapshot("one", app_module._identifyMessages(raw_entries))
        second_entries = [*raw_entries[1:], (None, "alice: same", "alice: same")]
        second = ChannelSnapshot("one", app_module._identifyMessages(second_entries))

        app_module._processSnapshot(first)
        app_module._processSnapshot(second)

        ui_message().assert_not_called()

    def test_ordered_burst_is_coalesced_into_one_message(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "existing")))
        app_module._processSnapshot(snapshot("one", (1, "existing"), (2, "first"), (3, "second"), (4, "third")))

        ui_message().assert_called_once_with("first\nsecond\nthird")

    def test_history_prepended_before_known_tail_is_not_announced(self, app_module):
        app_module._processSnapshot(snapshot("one", (2, "existing"), (3, "tail")))
        app_module._processSnapshot(snapshot("one", (1, "older history"), (2, "existing"), (3, "tail")))

        ui_message().assert_not_called()

    def test_zero_overlap_recovers_with_silent_baseline(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "first"), (2, "old tail")))
        app_module._processSnapshot(snapshot("one", (3, "replacement"), (4, "new tail")))
        ui_message().assert_not_called()

        app_module._processSnapshot(snapshot("one", (3, "replacement"), (4, "new tail"), (5, "later")))

        ui_message().assert_called_once_with("later")

    def test_repeated_empty_snapshots_are_stable_without_recovery_log(self, app_module):
        empty = snapshot("one")
        app_module._processSnapshot(empty)
        log = sys.modules["logHandler"].log
        log.debug.reset_mock()

        app_module._processSnapshot(empty)

        ui_message().assert_not_called()
        log.debug.assert_not_called()

    def test_unchanged_nonempty_snapshot_does_not_log_every_poll(self, app_module):
        unchanged = snapshot("one", (1, "existing"))
        app_module._processSnapshot(unchanged)
        log = sys.modules["logHandler"].log
        log.debug.reset_mock()

        app_module._processSnapshot(unchanged)

        ui_message().assert_not_called()
        log.debug.assert_not_called()

    def test_fallback_overlap_announces_only_suffix_after_known_tail(self, app_module):
        first = ChannelSnapshot(
            "one", app_module._identifyMessages([(None, "existing", "existing"), (None, "tail", "tail")])
        )
        second = ChannelSnapshot(
            "one",
            app_module._identifyMessages(
                [
                    (None, "older history", "older history"),
                    (None, "existing", "existing"),
                    (None, "tail", "tail"),
                    (None, "new suffix", "new suffix"),
                ]
            ),
        )

        app_module._processSnapshot(first)
        app_module._processSnapshot(second)

        ui_message().assert_called_once_with("new suffix")

    def test_ambiguous_duplicate_window_recovers_silently_until_overlap_returns(self, app_module):
        duplicates = [(None, "same", "same")] * app_module.MAX_SNAPSHOT_MESSAGES
        first = ChannelSnapshot("one", app_module._identifyMessages(duplicates))
        indistinguishable_replacement = ChannelSnapshot("one", app_module._identifyMessages(duplicates))
        changed_window_entries = [*duplicates[1:], (None, "new tail", "new tail")]
        changed_window = ChannelSnapshot("one", app_module._identifyMessages(changed_window_entries))
        later_entries = [*changed_window_entries, (None, "later", "later")]
        later = ChannelSnapshot("one", app_module._identifyMessages(later_entries))

        app_module._processSnapshot(first)
        app_module._processSnapshot(indistinguishable_replacement)
        app_module._processSnapshot(changed_window)
        ui_message().assert_not_called()

        app_module._processSnapshot(later)

        ui_message().assert_called_once_with("later")

    def test_unknown_snapshot_forces_next_successful_read_to_baseline(self, app_module):
        app_module._processSnapshot(snapshot("one", (1, "existing")))
        app_module._markBaselineRequired()
        app_module._processSnapshot(snapshot("one", (1, "existing"), (2, "arrived while unavailable")))

        ui_message().assert_not_called()

    def test_per_channel_snapshot_cache_is_bounded(self, app_module):
        for index in range(app_module.MAX_CHANNEL_SNAPSHOTS + 1):
            app_module._processSnapshot(snapshot(f"channel-{index}", (index, "existing")))

        assert len(app_module._channelSnapshots) == app_module.MAX_CHANNEL_SNAPSHOTS
        assert "channel-0" not in app_module._channelSnapshots


class TestAccessiblePresentation:
    def test_uses_ui_message_for_speech_and_braille(self, app_module):
        app_module._presentMessages((MessageEntry(("runtime", 1), "hello"),))

        ui_message().assert_called_once_with("hello")

    def test_burst_count_is_bounded_with_explicit_overflow(self, app_module):
        entries = tuple(
            MessageEntry(("runtime", index), f"message {index}") for index in range(app_module.MAX_BURST_MESSAGES + 3)
        )

        app_module._presentMessages(entries)

        output = ui_message().call_args.args[0]
        assert "message 0" in output
        assert f"{3} more messages" in output
        assert len(output) <= app_module.MAX_ANNOUNCEMENT_CHARS

    def test_single_hidden_message_uses_singular_overflow(self, app_module):
        entries = tuple(
            MessageEntry(("runtime", index), f"message {index}") for index in range(app_module.MAX_BURST_MESSAGES + 1)
        )

        app_module._presentMessages(entries)

        assert ui_message().call_args.args[0].endswith("1 more message")

    def test_single_long_message_is_bounded(self, app_module):
        app_module._presentMessages((MessageEntry(("runtime", 1), "x" * 5000),))

        output = ui_message().call_args.args[0]
        assert output.endswith("…")
        assert len(output) <= app_module.MAX_MESSAGE_CHARS

    def test_user_interface_failure_does_not_escape(self, app_module):
        ui_message().side_effect = RuntimeError("output failed")

        app_module._presentMessages((MessageEntry(("runtime", 1), "hello"),))

    def test_logs_never_include_message_content(self, app_module):
        secret = "private secret body"
        app_module._processSnapshot(snapshot("one", (1, "existing")))
        app_module._processSnapshot(snapshot("one", (1, "existing"), (2, secret)))

        log = sys.modules["logHandler"].log
        assert secret not in str(log.method_calls)
