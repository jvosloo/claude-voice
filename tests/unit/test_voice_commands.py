"""Tests for voice command recognition in daemon/main.py."""

import os
import sys
from unittest.mock import patch, MagicMock

# Mock only external libraries that need system resources at import time.
# Do NOT mock daemon submodules — that poisons them for other test files.
sys.modules.setdefault('sounddevice', MagicMock())
sys.modules.setdefault('pynput', MagicMock())
sys.modules.setdefault('pynput.keyboard', MagicMock())

from daemon.main import VoiceDaemon, _read_mode, SILENT_FLAG


class TestHandleVoiceCommand:
    """Test _handle_voice_command method for all known voice commands."""

    @staticmethod
    def _make_daemon():
        """Create a VoiceDaemon with mocked dependencies."""
        with patch.object(VoiceDaemon, '__init__', lambda self: None):
            d = VoiceDaemon()
            d.config = MagicMock()
            return d

    def test_stop_speaking(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", str(tmp_path / ".silent")):
            assert d._handle_voice_command("stop speaking") is True

    def test_stop_talking(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", str(tmp_path / ".silent")):
            assert d._handle_voice_command("stop talking") is True

    def test_start_speaking(self, tmp_path):
        d = self._make_daemon()
        silent = tmp_path / ".silent"
        silent.touch()
        with patch("daemon.main.SILENT_FLAG", str(silent)):
            assert d._handle_voice_command("start speaking") is True
            assert not silent.exists()

    def test_start_talking(self, tmp_path):
        d = self._make_daemon()
        silent = tmp_path / ".silent"
        silent.touch()
        with patch("daemon.main.SILENT_FLAG", str(silent)):
            assert d._handle_voice_command("start talking") is True

    def test_unrecognised_text_returns_false(self):
        d = self._make_daemon()
        assert d._handle_voice_command("I was speaking about code") is False

    def test_strips_trailing_period(self):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", "/tmp/test_silent"):
            assert d._handle_voice_command("stop speaking.") is True

    def test_case_insensitive(self):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", "/tmp/test_silent"):
            assert d._handle_voice_command("Stop Speaking") is True

    def test_empty_string_returns_false(self):
        d = self._make_daemon()
        assert d._handle_voice_command("") is False
