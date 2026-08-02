"""Untrusted Discord text normalization tests."""

from discord import MessageEntry


class TestSanitizeText:
    def test_strips_c0_and_c1_controls(self, app_module):
        text = "hello\x00\x07\x1f world\x7f\x85"

        assert app_module._sanitizeText(text) == "hello world"

    def test_strips_bidirectional_formatting_controls(self, app_module):
        text = "safe\u202eevil\u202c\u2066text\u2069\u061c\u200f"

        assert app_module._sanitizeText(text) == "safeeviltext"

    def test_preserves_meaningful_zero_width_joiner(self, app_module):
        family = "👩\u200d👩\u200d👧\u200d👦"

        assert app_module._sanitizeText(family) == family

    def test_collapses_whitespace(self, app_module):
        assert app_module._sanitizeText("one\r\n\t two   three") == "one two three"

    def test_empty_sanitized_message_is_not_presented(self, app_module):
        app_module._presentMessages((MessageEntry(("runtime", 1), "\x00\u202e"),))

        import sys

        sys.modules["ui"].message.assert_not_called()
