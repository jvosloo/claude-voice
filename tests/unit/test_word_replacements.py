"""Tests for transcription word replacements."""

from daemon.transcribe import apply_word_replacements


class TestApplyWordReplacements:
    """Tests for apply_word_replacements function."""

    def test_basic_replacement(self):
        result = apply_word_replacements("I need to taste this", {"taste": "test"})
        assert result == "I need to test this"

    def test_multiple_occurrences(self):
        result = apply_word_replacements("taste taste taste", {"taste": "test"})
        assert result == "test test test"

    def test_case_insensitive(self):
        result = apply_word_replacements("Taste the taste", {"taste": "test"})
        assert result == "test the test"

    def test_whole_word_only(self):
        result = apply_word_replacements("aftertaste is great", {"taste": "test"})
        assert result == "aftertaste is great"

    def test_multi_word_phrase(self):
        result = apply_word_replacements("open clothes code now", {"clothes code": "Claude Code"})
        assert result == "open Claude Code now"

    def test_multiple_rules(self):
        replacements = {"taste": "test", "clawed": "Claude"}
        result = apply_word_replacements("clawed wants to taste", replacements)
        assert result == "Claude wants to test"

    def test_empty_replacements(self):
        result = apply_word_replacements("hello world", {})
        assert result == "hello world"

    def test_empty_text(self):
        result = apply_word_replacements("", {"taste": "test"})
        assert result == ""

    def test_no_match(self):
        result = apply_word_replacements("hello world", {"taste": "test"})
        assert result == "hello world"

    def test_preserves_punctuation(self):
        result = apply_word_replacements("I need to taste.", {"taste": "test"})
        assert result == "I need to test."
