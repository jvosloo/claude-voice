"""Tests for transcription word replacements and filler stripping."""

from daemon.transcribe import apply_word_replacements, strip_filler_words


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


class TestStripFillerWords:
    """Tests for strip_filler_words function."""

    def test_strips_um(self):
        assert strip_filler_words("I um need to test this") == "I need to test this"

    def test_strips_uh(self):
        assert strip_filler_words("uh I need to test this") == "I need to test this"

    def test_strips_ah(self):
        assert strip_filler_words("ah I need to test this") == "I need to test this"

    def test_strips_you_know(self):
        assert strip_filler_words("I you know need to test this") == "I need to test this"

    def test_strips_multiple_fillers(self):
        assert strip_filler_words("um I uh need to test this") == "I need to test this"

    def test_preserves_common_words(self):
        # Words like "like", "so", "well" are NOT stripped (too context-dependent)
        assert strip_filler_words("I like this so well") == "I like this so well"

    def test_case_insensitive(self):
        assert strip_filler_words("Um I need to test") == "I need to test"

    def test_empty_string(self):
        assert strip_filler_words("") == ""

    def test_no_fillers(self):
        assert strip_filler_words("I need to test this") == "I need to test this"

    def test_capitalizes_after_leading_filler(self):
        assert strip_filler_words("uh hello world") == "Hello world"

    def test_strips_filler_with_trailing_comma(self):
        assert strip_filler_words("um, I think so") == "I think so"

    def test_strips_i_mean(self):
        assert strip_filler_words("I mean it works fine") == "It works fine"

    def test_only_fillers(self):
        result = strip_filler_words("um uh er")
        assert result == ""
