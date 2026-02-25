"""Integration tests for hook utilities (hooks/_common.py)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))

from unittest.mock import patch, MagicMock

from _common import (
    log_error, send_to_daemon,
    load_permission_rules, store_permission_rule, check_permission_rules,
)


class TestSendToDaemon:

    def test_connection_refused_returns_none(self):
        with patch("_common.TTS_SOCK_PATH", "/nonexistent/sock"):
            result = send_to_daemon({"cmd": "status"})
        assert result is None

    def test_sends_plain_payload(self):
        """send_to_daemon sends the payload dict as-is."""
        captured = {}

        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
            def settimeout(self, timeout): pass
            def sendall(self, data):
                captured["payload"] = json.loads(data.decode())
            def shutdown(self, how): pass
            def recv(self, size): return b""
            def close(self): pass

        with patch("_common.socket.socket", FakeSocket):
            send_to_daemon({"notify_category": "permission"})

        payload = captured["payload"]
        assert payload == {"notify_category": "permission"}

    def test_unexpected_error_calls_log_error(self):
        """Exceptions beyond ConnectionRefused are logged, not silently swallowed."""
        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
            def settimeout(self, timeout): pass
            def sendall(self, data):
                raise TypeError("simulated bug")
            def shutdown(self, how): pass
            def recv(self, size): return b""
            def close(self): pass

        with patch("_common.socket.socket", FakeSocket):
            with patch("_common.log_error") as mock_log:
                result = send_to_daemon({"text": "hello"})

        assert result is None
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == "send_to_daemon"
        assert isinstance(mock_log.call_args[0][1], TypeError)


class TestLogError:

    def test_writes_to_file_and_stderr(self, tmp_path, capsys):
        log_file = tmp_path / "errors.log"
        with patch("_common._ERROR_LOG", str(log_file)):
            log_error("test_hook", ValueError("bad value"))

        # Check file was written
        content = log_file.read_text()
        assert "[test_hook] ValueError: bad value" in content

        # Check stderr output
        captured = capsys.readouterr()
        assert "[test_hook] ValueError: bad value" in captured.err

    def test_still_prints_to_stderr_when_file_unwritable(self, capsys):
        with patch("_common._ERROR_LOG", "/nonexistent/dir/errors.log"):
            log_error("test_hook", RuntimeError("oops"))

        captured = capsys.readouterr()
        assert "[test_hook] RuntimeError: oops" in captured.err


class TestPermissionRules:

    def test_load_missing_file_returns_empty(self):
        with patch("_common.PERMISSION_RULES_FILE", "/nonexistent/rules.json"):
            assert load_permission_rules() == []

    def test_load_valid_rules(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules = [{"pattern": "Bash", "behavior": "allow"}]
        rules_file.write_text(json.dumps(rules))

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            result = load_permission_rules()

        assert len(result) == 1
        assert result[0]["pattern"] == "Bash"

    def test_load_corrupt_json_returns_empty(self, tmp_path, capsys):
        rules_file = tmp_path / "rules.json"
        rules_file.write_text("{not valid json")

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            result = load_permission_rules()

        assert result == []
        captured = capsys.readouterr()
        assert "corrupt permission rules" in captured.err

    def test_store_creates_file(self, tmp_path):
        rules_file = tmp_path / "rules.json"

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            store_permission_rule("Bash: cat")

        rules = json.loads(rules_file.read_text())
        assert len(rules) == 1
        assert rules[0]["pattern"] == "Bash: cat"
        assert rules[0]["behavior"] == "allow"

    def test_store_deduplicates(self, tmp_path):
        rules_file = tmp_path / "rules.json"

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            store_permission_rule("Bash: cat")
            store_permission_rule("Bash: cat")  # duplicate

        rules = json.loads(rules_file.read_text())
        assert len(rules) == 1

    def test_store_survives_unwritable_path(self, tmp_path, capsys):
        """store_permission_rule doesn't crash when the file can't be written."""
        with patch("_common.PERMISSION_RULES_FILE", "/nonexistent/deep/rules.json"):
            with patch("os.makedirs", side_effect=OSError("read-only")):
                store_permission_rule("Bash: cat")  # should not raise

        captured = capsys.readouterr()
        assert "could not save permission rule" in captured.err

    def test_check_returns_matching_behavior(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules = [{"pattern": "Bash: cat", "behavior": "allow"}]
        rules_file.write_text(json.dumps(rules))

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            assert check_permission_rules("Bash: cat /etc/hosts") == "allow"

    def test_check_returns_none_when_no_match(self, tmp_path):
        rules_file = tmp_path / "rules.json"
        rules = [{"pattern": "Bash: cat", "behavior": "allow"}]
        rules_file.write_text(json.dumps(rules))

        with patch("_common.PERMISSION_RULES_FILE", str(rules_file)):
            assert check_permission_rules("Read: /etc/hosts") is None
