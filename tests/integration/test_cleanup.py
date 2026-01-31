"""Integration tests for transcription cleanup (daemon/cleanup.py)."""

import subprocess
from unittest.mock import patch, MagicMock

from daemon.cleanup import TranscriptionCleaner


class TestCleanupPostProcessing:
    """Test the output post-processing in cleanup() — the pure logic part."""

    def _run_cleanup(self, stdout: str) -> str:
        """Run cleanup with mocked subprocess returning given stdout."""
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = stdout

        with patch("daemon.cleanup.subprocess.run", return_value=mock_result):
            return cleaner.cleanup("input text")

    def test_strips_output_prefix(self):
        result = self._run_cleanup("Output: Hello world")
        assert result == "Hello world"

    def test_strips_output_prefix_case_insensitive(self):
        result = self._run_cleanup("output: Hello world")
        assert result == "Hello world"

    def test_strips_double_quotes(self):
        result = self._run_cleanup('"Hello world"')
        assert result == "Hello world"

    def test_strips_single_quotes(self):
        result = self._run_cleanup("'Hello world'")
        assert result == "Hello world"

    def test_passthrough_normal_text(self):
        result = self._run_cleanup("Hello world")
        assert result == "Hello world"

    def test_empty_response_returns_original(self):
        result = self._run_cleanup("")
        assert result == "input text"

    def test_whitespace_only_returns_original(self):
        result = self._run_cleanup("   \n  ")
        assert result == "input text"


class TestCleanupGracefulDegradation:
    """Test that cleanup() returns original text on any failure."""

    def test_returns_original_on_nonzero_exit(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("daemon.cleanup.subprocess.run", return_value=mock_result):
            assert cleaner.cleanup("original") == "original"

    def test_returns_original_on_timeout(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        with patch("daemon.cleanup.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 10)):
            assert cleaner.cleanup("original") == "original"

    def test_returns_original_on_exception(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        with patch("daemon.cleanup.subprocess.run",
                   side_effect=OSError("command not found")):
            assert cleaner.cleanup("original") == "original"

    def test_skips_when_not_ready(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = False
        assert cleaner.cleanup("original") == "original"

    def test_skips_empty_input(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True
        assert cleaner.cleanup("") == ""


class TestEnsureReady:
    """Test ensure_ready() checks with mocked subprocess."""

    def test_ollama_not_installed(self):
        cleaner = TranscriptionCleaner()
        with patch("daemon.cleanup.subprocess.run",
                   side_effect=FileNotFoundError()):
            assert cleaner.ensure_ready() is False

    def test_model_available(self):
        cleaner = TranscriptionCleaner(model_name="qwen2.5:1.5b")

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if cmd[1] == "--version":
                result.stdout = "ollama 0.1.0"
            elif cmd[1] == "list":
                result.stdout = "qwen2.5:1.5b   abc123   1.0 GB"
            return result

        with patch("daemon.cleanup.subprocess.run", side_effect=fake_run):
            assert cleaner.ensure_ready() is True
            assert cleaner._ready is True

    def test_model_missing_triggers_pull(self):
        cleaner = TranscriptionCleaner(model_name="qwen2.5:1.5b")
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

        with patch("daemon.cleanup.subprocess.run", side_effect=fake_run):
            assert cleaner.ensure_ready() is True
        assert call_count == 3  # version + list + pull

    def test_version_check_timeout(self):
        cleaner = TranscriptionCleaner()
        with patch("daemon.cleanup.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 5)):
            assert cleaner.ensure_ready() is False
