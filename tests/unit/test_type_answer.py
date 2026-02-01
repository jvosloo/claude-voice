"""Tests for hooks/_type_answer.py — TIOCSTI injection and PID management."""

import os
import signal
from unittest.mock import patch, Mock, call

import pytest

# _type_answer.py adds its own dir to sys.path and imports from _common
# We need to make it importable from the test environment
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'hooks'))

from _type_answer import (
    _pid_file_for, kill_previous_typer, register_typer_pid, unregister_typer_pid,
    _inject_bytes, select_option, type_free_text,
    TIOCSTI, SEQ_DOWN, SEQ_RETURN, PID_DIR,
)


class TestPidFileManagement:

    def test_pid_file_for_path(self):
        """Produces safe filename by replacing slashes."""
        result = _pid_file_for("/tmp/claude-voice/sessions/test/response")
        assert "/" not in os.path.basename(result)
        assert result.startswith(PID_DIR)
        assert "typer" in os.path.basename(result)

    def test_register_and_unregister_pid(self, tmp_path):
        """Register writes PID, unregister removes it."""
        response_path = str(tmp_path / "response")

        with patch("_type_answer.PID_DIR", str(tmp_path / "pids")):
            from _type_answer import _pid_file_for as pf
            pid_path = str(tmp_path / "pids" / f"typer{response_path.replace('/', '_')}.pid")

            with patch("_type_answer.os.getpid", return_value=12345), \
                 patch("_type_answer._pid_file_for", return_value=pid_path):
                register_typer_pid(response_path)
                assert os.path.exists(pid_path)
                with open(pid_path) as f:
                    assert f.read().strip() == "12345"

                unregister_typer_pid(response_path)
                assert not os.path.exists(pid_path)

    def test_kill_previous_typer_sends_sigterm(self, tmp_path):
        """Reads PID from file and sends SIGTERM."""
        pid_path = str(tmp_path / "typer_test.pid")
        with open(pid_path, "w") as f:
            f.write("99999")

        with patch("_type_answer._pid_file_for", return_value=pid_path), \
             patch("_type_answer.os.kill") as mock_kill:
            kill_previous_typer("/test/response")
            mock_kill.assert_called_once_with(99999, signal.SIGTERM)

    def test_kill_previous_typer_handles_missing_process(self, tmp_path):
        """Handles ProcessLookupError gracefully."""
        pid_path = str(tmp_path / "typer_test.pid")
        with open(pid_path, "w") as f:
            f.write("99999")

        with patch("_type_answer._pid_file_for", return_value=pid_path), \
             patch("_type_answer.os.kill", side_effect=ProcessLookupError):
            # Should not raise
            kill_previous_typer("/test/response")

    def test_kill_previous_typer_no_pid_file(self, tmp_path):
        """Does nothing when no PID file exists."""
        pid_path = str(tmp_path / "nonexistent.pid")
        with patch("_type_answer._pid_file_for", return_value=pid_path), \
             patch("_type_answer.os.kill") as mock_kill:
            kill_previous_typer("/test/response")
            mock_kill.assert_not_called()


class TestTiocsti:

    def test_inject_bytes_calls_ioctl_per_byte(self):
        """Each byte triggers one ioctl call with TIOCSTI."""
        with patch("_type_answer.fcntl.ioctl") as mock_ioctl:
            _inject_bytes(3, b'\x1b[B')  # Down arrow escape sequence

        assert mock_ioctl.call_count == 3
        mock_ioctl.assert_any_call(3, TIOCSTI, b'\x1b')
        mock_ioctl.assert_any_call(3, TIOCSTI, b'[')
        mock_ioctl.assert_any_call(3, TIOCSTI, b'B')

    def test_select_option_injects_down_and_return(self):
        """Selecting option 2 injects Down twice then Return."""
        with patch("_type_answer.fcntl.ioctl") as mock_ioctl, \
             patch("_type_answer.time.sleep"):
            select_option(2, tty_fd=5)

        # 2 Down arrows (3 bytes each) + 1 Return (1 byte) = 7 ioctl calls
        assert mock_ioctl.call_count == 7
        # First 3: ESC [ B (down)
        assert mock_ioctl.call_args_list[0] == call(5, TIOCSTI, b'\x1b')
        assert mock_ioctl.call_args_list[1] == call(5, TIOCSTI, b'[')
        assert mock_ioctl.call_args_list[2] == call(5, TIOCSTI, b'B')
        # Next 3: ESC [ B (down again)
        assert mock_ioctl.call_args_list[3] == call(5, TIOCSTI, b'\x1b')
        # Last: Return
        assert mock_ioctl.call_args_list[6] == call(5, TIOCSTI, b'\r')

    def test_select_option_zero_just_returns(self):
        """Selecting option 0 (first item) only injects Return."""
        with patch("_type_answer.fcntl.ioctl") as mock_ioctl, \
             patch("_type_answer.time.sleep"):
            select_option(0, tty_fd=5)

        # Just 1 Return byte
        assert mock_ioctl.call_count == 1
        mock_ioctl.assert_called_once_with(5, TIOCSTI, b'\r')

    def test_type_free_text_injects_navigation_and_text(self):
        """Free text navigates to Other, types text, presses Return."""
        with patch("_type_answer.fcntl.ioctl") as mock_ioctl, \
             patch("_type_answer.time.sleep"):
            type_free_text("hi", num_options=2, tty_fd=5)

        # 2 Downs (3 bytes each) + Return (1) + "hi" (2 bytes) + Return (1) = 10
        assert mock_ioctl.call_count == 10


class TestMainRouting:

    def test_routes_opt_label_to_select_option(self):
        """'opt:Blue' finds matching option and calls select_option."""
        options = [{"label": "Red"}, {"label": "Blue"}, {"label": "Green"}]
        with patch("_type_answer.wait_for_response", return_value="opt:Blue"), \
             patch("_type_answer.select_option") as mock_select, \
             patch("_type_answer.kill_previous_typer"), \
             patch("_type_answer.register_typer_pid"), \
             patch("_type_answer.unregister_typer_pid"), \
             patch("_type_answer.clear_flag"), \
             patch("sys.argv", ["_type_answer.py", "/tmp/resp", '[]']):
            import json
            with patch("sys.argv", ["_type_answer.py", "/tmp/resp", json.dumps(options)]):
                from _type_answer import main
                main()

        mock_select.assert_called_once_with(1, None)  # Index 1 = Blue, no tty_fd

    def test_routes_free_text_to_type_free_text(self):
        """Plain text (no 'opt:' prefix) calls type_free_text."""
        options = [{"label": "A"}, {"label": "B"}]
        import json
        with patch("_type_answer.wait_for_response", return_value="my custom answer"), \
             patch("_type_answer.type_free_text") as mock_type, \
             patch("_type_answer.kill_previous_typer"), \
             patch("_type_answer.register_typer_pid"), \
             patch("_type_answer.unregister_typer_pid"), \
             patch("_type_answer.clear_flag"), \
             patch("sys.argv", ["_type_answer.py", "/tmp/resp", json.dumps(options)]):
            from _type_answer import main
            main()

        mock_type.assert_called_once_with("my custom answer", 2, None)

    def test_opt_other_does_nothing(self):
        """'opt:__other__' returns early without calling select or type."""
        import json
        options = [{"label": "A"}]
        with patch("_type_answer.wait_for_response", return_value="opt:__other__"), \
             patch("_type_answer.select_option") as mock_select, \
             patch("_type_answer.type_free_text") as mock_type, \
             patch("_type_answer.kill_previous_typer"), \
             patch("_type_answer.register_typer_pid"), \
             patch("_type_answer.unregister_typer_pid"), \
             patch("_type_answer.clear_flag"), \
             patch("sys.argv", ["_type_answer.py", "/tmp/resp", json.dumps(options)]):
            from _type_answer import main
            main()

        mock_select.assert_not_called()
        mock_type.assert_not_called()

    def test_fallback_to_osascript_on_tiocsti_failure(self):
        """OSError from TIOCSTI triggers osascript fallback."""
        import json
        options = [{"label": "X"}]
        with patch("_type_answer.wait_for_response", return_value="opt:X"), \
             patch("_type_answer.os.open", return_value=5), \
             patch("_type_answer.os.close"), \
             patch("_type_answer.kill_previous_typer"), \
             patch("_type_answer.register_typer_pid"), \
             patch("_type_answer.unregister_typer_pid"), \
             patch("_type_answer.clear_flag"), \
             patch("_type_answer.time.sleep"), \
             patch("_type_answer.fcntl.ioctl", side_effect=OSError("not supported")), \
             patch("_type_answer._osascript_key") as mock_osascript, \
             patch("sys.argv", ["_type_answer.py", "/tmp/resp", json.dumps(options), "/dev/ttys005"]):
            from _type_answer import main
            main()

        # Should have fallen back to osascript (Return key code 36)
        mock_osascript.assert_called()
