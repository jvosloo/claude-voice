"""Integration tests for hook utilities (hooks/_common.py)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))

from unittest.mock import patch, MagicMock

from _common import read_mode, send_to_daemon, wait_for_response


class TestReadMode:

    def test_valid_mode(self, tmp_path):
        mode_file = tmp_path / ".mode"
        mode_file.write_text("narrate")
        with patch("_common.MODE_FILE", str(mode_file)):
            assert read_mode() == "narrate"

    def test_missing_file_returns_empty(self):
        with patch("_common.MODE_FILE", "/nonexistent/.mode"):
            assert read_mode() == ""

    def test_empty_file_returns_empty(self, tmp_path):
        mode_file = tmp_path / ".mode"
        mode_file.write_text("")
        with patch("_common.MODE_FILE", str(mode_file)):
            assert read_mode() == ""


class TestSendToDaemon:

    def test_connection_refused_returns_none(self):
        with patch("_common.TTS_SOCK_PATH", "/nonexistent/sock"):
            result = send_to_daemon({"cmd": "status"})
        assert result is None


class TestWaitForResponse:

    def test_returns_response_when_file_appears(self, tmp_path):
        resp_file = tmp_path / "response"
        resp_file.write_text("yes")

        result = wait_for_response(str(resp_file))
        assert result == "yes"
        assert not resp_file.exists()  # file removed after read

    def test_timeout_returns_none(self, tmp_path):
        with patch("_common.AFK_RESPONSE_TIMEOUT", 0.1):
            with patch("_common.time.sleep"):  # don't actually sleep
                result = wait_for_response(str(tmp_path / "never"))
        assert result is None
