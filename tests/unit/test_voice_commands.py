"""Tests for voice command recognition in daemon/main.py."""

import os
import sys
from unittest.mock import patch, MagicMock

# Mock only external libraries that need system resources at import time.
# Do NOT mock daemon submodules — that poisons them for other test files.
sys.modules.setdefault('sounddevice', MagicMock())
sys.modules.setdefault('pynput', MagicMock())
sys.modules.setdefault('pynput.keyboard', MagicMock())

from daemon.main import VoiceDaemon, _read_mode, _write_mode, SILENT_FLAG, MODE_FILE


class TestHandleVoiceCommand:
    """Test _handle_voice_command method for all known voice commands."""

    @staticmethod
    def _make_daemon():
        """Create a VoiceDaemon with mocked dependencies."""
        with patch.object(VoiceDaemon, '__init__', lambda self: None):
            d = VoiceDaemon()
            # Set up minimal attributes needed by _handle_voice_command
            d.config = MagicMock()
            d.config.afk.voice_commands_activate = ["going afk", "away from keyboard"]
            d.config.afk.voice_commands_deactivate = ["back at keyboard", "i'm back"]
            d.afk = MagicMock()
            # Mock AFK methods to avoid side effects (file I/O, cues, overlay)
            d._activate_afk = MagicMock()
            d._deactivate_afk = MagicMock()
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

    def test_switch_to_narrate(self, tmp_path):
        d = self._make_daemon()
        mode_file = tmp_path / ".mode"
        with patch("daemon.main.MODE_FILE", str(mode_file)):
            with patch("daemon.main._write_mode") as mock_write:
                assert d._handle_voice_command("switch to narrate mode") is True
                mock_write.assert_called_once_with("narrate")

    def test_switch_to_notify(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main._write_mode") as mock_write:
            assert d._handle_voice_command("switch to notify mode") is True
            mock_write.assert_called_once_with("notify")

    def test_switch_to_narration_mode(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main._write_mode") as mock_write:
            assert d._handle_voice_command("switch to narration mode") is True
            mock_write.assert_called_once_with("narrate")

    def test_afk_activate_command(self):
        d = self._make_daemon()
        assert d._handle_voice_command("going afk") is True
        d._activate_afk.assert_called_once()

    def test_afk_deactivate_command(self):
        d = self._make_daemon()
        assert d._handle_voice_command("i'm back") is True
        d._deactivate_afk.assert_called_once()

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
