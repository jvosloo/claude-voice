"""Unit tests for response summarization (daemon/summarize.py)."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from daemon.summarize import ResponseSummarizer, filter_for_summarization, MIN_TEXT_LENGTH


class TestFilterForSummarization:
    """Test the text filtering before summarization."""

    def test_removes_code_blocks(self):
        text = "I added a function:\n```python\ndef foo():\n    pass\n```\nDone."
        result = filter_for_summarization(text)
        assert "```" not in result
        assert "def foo" not in result
        assert "Done" in result

    def test_removes_inline_code(self):
        text = "I fixed the `calculate_total` function."
        result = filter_for_summarization(text)
        assert "`" not in result
        assert "calculate_total" not in result

    def test_removes_file_paths(self):
        text = "Updated /Users/johan/project/src/main.py to fix the issue."
        result = filter_for_summarization(text)
        assert "/Users" not in result
        assert "main.py" not in result

    def test_removes_relative_paths(self):
        text = "Changed daemon/config.py and tests/test_foo.py."
        result = filter_for_summarization(text)
        assert "config.py" not in result
        assert "test_foo.py" not in result

    def test_removes_stack_traces(self):
        text = "Got an error:\n  at Function.run (file.js:10)\n  File \"main.py\", line 42\nFixed it."
        result = filter_for_summarization(text)
        assert "at Function" not in result
        assert 'File "main.py"' not in result
        assert "Fixed it" in result

    def test_removes_markdown_formatting(self):
        text = "**Bold** and *italic* and # Header"
        result = filter_for_summarization(text)
        assert "**" not in result
        assert "*italic*" not in result
        assert "Bold" in result
        assert "italic" in result

    def test_empty_input(self):
        assert filter_for_summarization("") == ""

    def test_preserves_plain_text(self):
        text = "I fixed the login bug and added a test."
        result = filter_for_summarization(text)
        assert "I fixed the login bug and added a test" in result


class TestSummarizerPostProcessing:
    """Test the output post-processing in summarize() — the pure logic part."""

    def _run_summarize(self, stdout: str, style: str = "brief") -> str | None:
        """Run summarize with mocked subprocess returning given stdout."""
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = stdout

        # Input must be long enough to not trigger passthrough
        long_input = "This is a long enough input text that needs to be summarized properly."

        with patch("daemon.summarize.subprocess.run", return_value=mock_result):
            return summarizer.summarize(long_input, style=style)

    def test_strips_summary_prefix(self):
        result = self._run_summarize("Summary: I fixed the bug.")
        assert result == "I fixed the bug."

    def test_strips_output_prefix(self):
        result = self._run_summarize("output: I fixed the bug.")
        assert result == "I fixed the bug."

    def test_strips_heres_prefix(self):
        result = self._run_summarize("Here's the summary: I fixed the bug.")
        assert result == "the summary: I fixed the bug."  # Only strips "here's"

    def test_strips_double_quotes(self):
        result = self._run_summarize('"I fixed the bug."')
        assert result == "I fixed the bug."

    def test_strips_single_quotes(self):
        result = self._run_summarize("'I fixed the bug.'")
        assert result == "I fixed the bug."

    def test_passthrough_normal_text(self):
        result = self._run_summarize("I fixed the bug.")
        assert result == "I fixed the bug."

    def test_empty_response_returns_none(self):
        result = self._run_summarize("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        result = self._run_summarize("   \n  ")
        assert result is None


class TestSummarizerGracefulDegradation:
    """Test that summarize() returns None on any failure (caller handles fallback)."""

    def test_returns_none_on_nonzero_exit(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("daemon.summarize.subprocess.run", return_value=mock_result):
            assert summarizer.summarize("A long enough text for summarization.") is None

    def test_returns_none_on_timeout(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        with patch("daemon.summarize.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 10)):
            assert summarizer.summarize("A long enough text for summarization.") is None

    def test_returns_none_on_exception(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        with patch("daemon.summarize.subprocess.run",
                   side_effect=OSError("command not found")):
            assert summarizer.summarize("A long enough text for summarization.") is None

    def test_returns_none_when_not_ready(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = False
        assert summarizer.summarize("any text") is None


class TestShortTextPassthrough:
    """Test that short text is returned directly without LLM call."""

    def test_short_text_returned_directly(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        # Should not call subprocess for short text
        with patch("daemon.summarize.subprocess.run") as mock_run:
            result = summarizer.summarize("Done.")
            mock_run.assert_not_called()
            assert result == "Done."

    def test_short_filtered_text_passthrough(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        # After filtering code, remaining text is short
        text = "```python\nprint('hello')\n```\nDone."

        with patch("daemon.summarize.subprocess.run") as mock_run:
            result = summarizer.summarize(text)
            mock_run.assert_not_called()
            assert result == "Done."

    def test_empty_after_filter_returns_none(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        # Only code, nothing left after filtering
        text = "```python\nprint('hello')\n```"

        with patch("daemon.summarize.subprocess.run") as mock_run:
            result = summarizer.summarize(text)
            mock_run.assert_not_called()
            assert result is None


class TestStylePrompts:
    """Test that different styles use different prompts."""

    def test_brief_style_prompt(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Summary"

        with patch("daemon.summarize.subprocess.run", return_value=mock_result) as mock_run:
            summarizer.summarize("A long enough text that needs summarization.", style="brief")
            call_args = mock_run.call_args[0][0]
            prompt = call_args[3]  # ["ollama", "run", model, prompt]
            assert "1-2 short sentences" in prompt

    def test_conversational_style_prompt(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Summary"

        with patch("daemon.summarize.subprocess.run", return_value=mock_result) as mock_run:
            summarizer.summarize("A long enough text that needs summarization.", style="conversational")
            call_args = mock_run.call_args[0][0]
            prompt = call_args[3]
            assert "natural, spoken recap" in prompt

    def test_bullets_style_prompt(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Summary"

        with patch("daemon.summarize.subprocess.run", return_value=mock_result) as mock_run:
            summarizer.summarize("A long enough text that needs summarization.", style="bullets")
            call_args = mock_run.call_args[0][0]
            prompt = call_args[3]
            assert "bullet points" in prompt

    def test_unknown_style_defaults_to_brief(self):
        summarizer = ResponseSummarizer()
        summarizer._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Summary"

        with patch("daemon.summarize.subprocess.run", return_value=mock_result) as mock_run:
            summarizer.summarize("A long enough text that needs summarization.", style="unknown")
            call_args = mock_run.call_args[0][0]
            prompt = call_args[3]
            assert "1-2 short sentences" in prompt


class TestEnsureReady:
    """Test ensure_ready() checks with mocked subprocess."""

    def test_ollama_not_installed(self):
        summarizer = ResponseSummarizer()
        with patch("daemon.summarize.subprocess.run",
                   side_effect=FileNotFoundError()):
            assert summarizer.ensure_ready() is False

    def test_model_available(self):
        summarizer = ResponseSummarizer(model_name="qwen2.5:1.5b")

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if cmd[1] == "--version":
                result.stdout = "ollama 0.1.0"
            elif cmd[1] == "list":
                result.stdout = "qwen2.5:1.5b   abc123   1.0 GB"
            return result

        with patch("daemon.summarize.subprocess.run", side_effect=fake_run):
            assert summarizer.ensure_ready() is True
            assert summarizer._ready is True

    def test_model_missing_triggers_pull(self):
        summarizer = ResponseSummarizer(model_name="qwen2.5:1.5b")
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.returncode = 0
            if cmd[1] == "--version":
                result.stdout = "ollama 0.1.0"
            elif cmd[1] == "list":
                result.stdout = ""  # model not found
            elif cmd[1] == "pull":
                result.stdout = "success"
            return result

        with patch("daemon.summarize.subprocess.run", side_effect=fake_run):
            assert summarizer.ensure_ready() is True
        assert call_count == 3  # version + list + pull

    def test_version_check_timeout(self):
        summarizer = ResponseSummarizer()
        with patch("daemon.summarize.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 5)):
            assert summarizer.ensure_ready() is False
