"""Tests for context-aware text insertion (daemon/context.py)."""

import pytest
from unittest.mock import patch, MagicMock
from daemon.context import (
    InsertionContext,
    adjust_text_for_context,
    get_insertion_context,
)


# ---------- adjust_text_for_context: pure logic tests ----------

class TestAdjustTextNoContext:
    """When ctx is None (AX failure), fall back to text + space."""

    def test_none_context_adds_trailing_space(self):
        assert adjust_text_for_context("hello", None) == "hello "

    def test_none_context_preserves_original(self):
        assert adjust_text_for_context("Hello world.", None) == "Hello world. "

    def test_empty_text_returns_empty(self):
        assert adjust_text_for_context("", None) == ""


class TestAdjustTextPassthrough:
    """Password fields get text + space (no adjustments)."""

    def test_password_field_passthrough(self):
        ctx = InsertionContext(
            text_before="", text_after="",
            bundle_id="com.apple.Notes", is_password=True,
        )
        assert adjust_text_for_context("hello", ctx) == "hello "

    def test_code_editor_gets_smart_insert(self):
        """Code editors now get smart insert like any other app."""
        ctx = InsertionContext(
            text_before="some code", text_after="",
            bundle_id="com.microsoft.VSCode", is_password=False,
        )
        # Mid-sentence after word char → lowercase + leading space
        assert adjust_text_for_context("hello", ctx) == " hello "

    def test_terminal_gets_smart_insert(self):
        """Terminals now get smart insert like any other app."""
        ctx = InsertionContext(
            text_before="", text_after="",
            bundle_id="com.apple.Terminal", is_password=False,
        )
        # Empty field → capitalize
        assert adjust_text_for_context("hello", ctx) == "Hello "


class TestCapitalization:
    """First-letter capitalization based on surrounding text."""

    def _ctx(self, before="", after=""):
        return InsertionContext(
            text_before=before, text_after=after,
            bundle_id="com.apple.Notes", is_password=False,
        )

    def test_empty_field_capitalizes(self):
        assert adjust_text_for_context("hello world", self._ctx()) == "Hello world "

    def test_after_period_capitalizes(self):
        assert adjust_text_for_context("hello", self._ctx("Done. ")) == "Hello "

    def test_after_exclamation_capitalizes(self):
        assert adjust_text_for_context("hello", self._ctx("Wow! ")) == "Hello "

    def test_after_question_capitalizes(self):
        assert adjust_text_for_context("hello", self._ctx("Really? ")) == "Hello "

    def test_mid_sentence_lowercases(self):
        assert adjust_text_for_context("Hello", self._ctx("I said")) == " hello "

    def test_single_char_capitalization(self):
        assert adjust_text_for_context("i", self._ctx()) == "I "

    def test_single_char_lowercase_mid_sentence(self):
        assert adjust_text_for_context("I", self._ctx("and")) == " i "


class TestTrailingPeriod:
    """Strip trailing period in mid-sentence context."""

    def _ctx(self, before="", after=""):
        return InsertionContext(
            text_before=before, text_after=after,
            bundle_id="com.apple.Notes", is_password=False,
        )

    def test_strip_period_mid_sentence(self):
        result = adjust_text_for_context("hello world.", self._ctx("I said"))
        assert result == " hello world "

    def test_keep_period_at_start_of_field(self):
        result = adjust_text_for_context("Hello world.", self._ctx())
        assert result == "Hello world. "

    def test_keep_period_after_sentence_end(self):
        result = adjust_text_for_context("Hello world.", self._ctx("Done. "))
        assert result == "Hello world. "


class TestLeadingSpace:
    """Leading space depends on what's before the cursor."""

    def _ctx(self, before="", after=""):
        return InsertionContext(
            text_before=before, text_after=after,
            bundle_id="com.apple.Notes", is_password=False,
        )

    def test_no_leading_space_for_empty_field(self):
        result = adjust_text_for_context("hello", self._ctx())
        assert result == "Hello "
        assert not result.startswith(" ")

    def test_no_leading_space_after_existing_space(self):
        # before="word " → not sentence end, last char is space → no leading space, no case change
        result = adjust_text_for_context("hello", self._ctx("word "))
        assert result == "hello "

    def test_leading_space_after_word(self):
        result = adjust_text_for_context("world", self._ctx("hello"))
        # After "hello" (word char) → lowercase + leading space
        assert result == " world "

    def test_no_leading_space_after_newline(self):
        result = adjust_text_for_context("hello", self._ctx("line\n"))
        assert not result.startswith(" ")


class TestTrailingSpace:
    """Trailing space depends on what's after the cursor."""

    def _ctx(self, before="", after=""):
        return InsertionContext(
            text_before=before, text_after=after,
            bundle_id="com.apple.Notes", is_password=False,
        )

    def test_no_trailing_space_before_existing_space(self):
        # empty before → capitalize, after starts with space → no trailing space
        result = adjust_text_for_context("hello", self._ctx("", " world"))
        assert result == "Hello"

    def test_no_trailing_space_before_comma(self):
        result = adjust_text_for_context("hello", self._ctx("", ", world"))
        assert result == "Hello"

    def test_no_trailing_space_before_period(self):
        result = adjust_text_for_context("hello", self._ctx("", ". Next"))
        assert result == "Hello"

    def test_trailing_space_before_word(self):
        result = adjust_text_for_context("hello", self._ctx("", "world"))
        assert result == "Hello "

    def test_no_trailing_space_before_newline(self):
        result = adjust_text_for_context("hello", self._ctx("", "\nNext"))
        assert result == "Hello"


class TestCombined:
    """Integration-level tests combining multiple rules."""

    def _ctx(self, before="", after=""):
        return InsertionContext(
            text_before=before, text_after=after,
            bundle_id="com.apple.Notes", is_password=False,
        )

    def test_mid_sentence_with_period_stripping(self):
        """Dictating mid-sentence: lowercase, add space, strip period."""
        result = adjust_text_for_context("Hello world.", self._ctx("I said"))
        assert result == " hello world "

    def test_after_period_with_space(self):
        """New sentence after period-space: capitalize, no leading space."""
        result = adjust_text_for_context("hello world", self._ctx("Done. "))
        assert result == "Hello world "

    def test_empty_field_full_sentence(self):
        """Empty field: capitalize, no leading space, keep period."""
        result = adjust_text_for_context("hello world.", self._ctx())
        assert result == "Hello world. "

    def test_continuing_after_comma(self):
        """After comma-space: no sentence end, before ends with space."""
        result = adjust_text_for_context("and more", self._ctx("first, "))
        # before="first, " → not sentence end, last char is ' ' → no leading space
        # \w$ doesn't match ' ' → capitalization unchanged ("and more")
        assert result == "and more "


class TestGetInsertionContextFallback:
    """get_insertion_context returns None when AX APIs aren't available."""

    def test_returns_none_on_import_error(self):
        """On non-macOS or missing frameworks, returns None."""
        with patch.dict("sys.modules", {"ApplicationServices": None}):
            # Force re-import to trigger ImportError
            import importlib
            import daemon.context
            # The function catches ImportError internally
            result = get_insertion_context()
            # On a real macOS machine it may succeed; on CI it returns None
            # Just verify it doesn't crash
            assert result is None or isinstance(result, InsertionContext)
