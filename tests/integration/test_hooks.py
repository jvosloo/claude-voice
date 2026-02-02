"""Integration tests for hook utilities (hooks/_common.py)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))

from unittest.mock import patch, MagicMock

from _common import (
    log_error, read_mode, send_to_daemon, wait_for_response,
    load_permission_rules, store_permission_rule, check_permission_rules,
)


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

    def test_afk_mode(self, tmp_path):
        mode_file = tmp_path / ".mode"
        mode_file.write_text("afk")
        with patch("_common.MODE_FILE", str(mode_file)):
            assert read_mode() == "afk"


class TestSendToDaemon:

    def test_connection_refused_returns_none(self):
        with patch("_common.TTS_SOCK_PATH", "/nonexistent/sock"):
            result = send_to_daemon({"cmd": "status"})
        assert result is None

    def test_with_context_adds_session_fields(self):
        """with_context=True enriches the payload with session, tty, context."""
        sent_data = {}

        def mock_connect(self, path):
            raise ConnectionRefusedError("no daemon")

        def mock_sendall(self, data):
            sent_data["payload"] = json.loads(data.decode())

        # Patch socket to capture what would be sent, then fail on connect
        # We can't capture the payload this way since connect fails first.
        # Instead, test the payload construction by patching at a lower level.
        with patch("_common.TTS_SOCK_PATH", "/nonexistent/sock"):
            with patch("_common._get_tty_path", return_value="/dev/ttys001"):
                # Call with_context — it will fail to connect, but the payload
                # construction happens before the socket call
                result = send_to_daemon(
                    {"text": "hello world", "voice": "af_heart"},
                    with_context=True,
                    raw_text="line one\nline two\nline three",
                )
        assert result is None  # connection refused, but no crash

    def test_with_context_payload_construction(self):
        """Verify the payload is correctly enriched before sending."""
        import socket as socket_mod

        captured = {}

        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
            def sendall(self, data):
                captured["payload"] = json.loads(data.decode())
            def shutdown(self, how): pass
            def recv(self, size): return b""
            def close(self): pass

        with patch("_common.socket.socket", FakeSocket):
            with patch("_common._get_tty_path", return_value="/dev/ttys005"):
                send_to_daemon(
                    {"text": "test message", "voice": "af_heart"},
                    with_context=True,
                    raw_text="context line 1\ncontext line 2",
                )

        payload = captured["payload"]
        assert payload["text"] == "test message"
        assert payload["voice"] == "af_heart"
        assert payload["type"] == "context"
        assert payload["tty_path"] == "/dev/ttys005"
        assert "session" in payload
        assert "context line 1" in payload["context"]
        assert "context line 2" in payload["context"]

    def test_without_context_sends_plain_payload(self):
        """with_context=False (default) sends the payload as-is."""
        import socket as socket_mod

        captured = {}

        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
            def sendall(self, data):
                captured["payload"] = json.loads(data.decode())
            def shutdown(self, how): pass
            def recv(self, size): return b""
            def close(self): pass

        with patch("_common.socket.socket", FakeSocket):
            send_to_daemon({"notify_category": "permission"})

        payload = captured["payload"]
        assert payload == {"notify_category": "permission"}
        assert "session" not in payload
        assert "tty_path" not in payload

    def test_context_uses_raw_text_for_context_lines(self):
        """When raw_text is provided, context lines come from it, not text."""
        captured = {}

        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
            def sendall(self, data):
                captured["payload"] = json.loads(data.decode())
            def shutdown(self, how): pass
            def recv(self, size): return b""
            def close(self): pass

        with patch("_common.socket.socket", FakeSocket):
            with patch("_common._get_tty_path", return_value=None):
                send_to_daemon(
                    {"text": "cleaned text"},
                    with_context=True,
                    raw_text="raw line A\nraw line B",
                )

        context = captured["payload"]["context"]
        assert "raw line A" in context
        assert "raw line B" in context
        assert "cleaned text" not in context

    def test_unexpected_error_calls_log_error(self):
        """Exceptions beyond ConnectionRefused are logged, not silently swallowed."""
        class FakeSocket:
            def __init__(self, *a, **kw): pass
            def connect(self, path): pass
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

    def test_returns_response_even_if_remove_fails(self, tmp_path):
        """Response is returned even if os.remove raises OSError."""
        resp_file = tmp_path / "response"
        resp_file.write_text("allow")

        with patch("os.remove", side_effect=OSError("permission denied")):
            result = wait_for_response(str(resp_file))

        assert result == "allow"


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
