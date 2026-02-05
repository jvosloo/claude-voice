"""Integration tests for control server command handling (daemon/control.py)."""

from unittest.mock import MagicMock, patch

from daemon.control import ControlServer


def _make_server():
    """Create a ControlServer with a mocked daemon."""
    daemon = MagicMock()
    daemon.get_mode.return_value = "notify"
    daemon.get_voice_enabled.return_value = True
    daemon.is_ready.return_value = True
    daemon.recorder.is_recording = False
    server = ControlServer(daemon)
    return server, daemon


class TestHandleCommand:

    def test_status(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "status"})
        assert resp["daemon"] is True
        assert resp["mode"] == "notify"
        assert resp["voice"] is True
        assert resp["recording"] is False
        assert resp["ready"] is True

    def test_status_not_ready(self):
        server, daemon = _make_server()
        daemon.is_ready.return_value = False
        resp = server._handle_command({"cmd": "status"})
        assert resp["ready"] is False

    def test_set_mode(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "set_mode", "mode": "narrate"})
        assert resp == {"ok": True}
        daemon.set_mode.assert_called_once_with("narrate")

    def test_set_mode_defaults_to_notify(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "set_mode"})
        daemon.set_mode.assert_called_once_with("notify")

    def test_voice_on(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "voice_on"})
        assert resp == {"ok": True}
        daemon.set_voice_enabled.assert_called_once_with(True)

    def test_voice_off(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "voice_off"})
        assert resp == {"ok": True}
        daemon.set_voice_enabled.assert_called_once_with(False)

    def test_reload_config(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "reload_config"})
        assert resp == {"ok": True}
        daemon.reload_config.assert_called_once()

    def test_speak_returns_ok(self):
        server, daemon = _make_server()
        with patch("daemon.notify._get_phrase_path", return_value="/fake/done.wav"), \
             patch("os.path.exists", return_value=True), \
             patch("daemon.control.threading.Thread") as mock_thread:
            resp = server._handle_command({"cmd": "speak"})
        assert resp == {"ok": True}
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    def test_speak_missing_file_still_returns_ok(self):
        server, daemon = _make_server()
        with patch("daemon.notify._get_phrase_path", return_value="/fake/missing.wav"), \
             patch("os.path.exists", return_value=False), \
             patch("daemon.control.threading.Thread") as mock_thread:
            resp = server._handle_command({"cmd": "speak"})
        assert resp == {"ok": True}
        mock_thread.assert_not_called()

    def test_stop_triggers_shutdown(self):
        server, daemon = _make_server()
        with patch("daemon.control.threading.Thread") as mock_thread:
            resp = server._handle_command({"cmd": "stop"})
        assert resp == {"ok": True}
        mock_thread.assert_called_once()

    def test_subscribe(self):
        server, _ = _make_server()
        resp = server._handle_command({"cmd": "subscribe"})
        assert resp == {"subscribed": True}

    def test_unknown_command(self):
        server, _ = _make_server()
        resp = server._handle_command({"cmd": "invalid"})
        assert "error" in resp
        assert "unknown" in resp["error"]

    def test_missing_cmd_key(self):
        server, _ = _make_server()
        resp = server._handle_command({})
        assert "error" in resp


class TestEmit:

    def test_sends_to_subscribed_connections(self):
        server, _ = _make_server()
        conn = MagicMock()
        server._event_connections.append(conn)

        server.emit({"event": "test"})
        conn.sendall.assert_called_once()
        sent_data = conn.sendall.call_args[0][0]
        assert b"test" in sent_data

    def test_removes_dead_connections(self):
        server, _ = _make_server()
        dead = MagicMock()
        dead.sendall.side_effect = BrokenPipeError()
        alive = MagicMock()

        server._event_connections = [dead, alive]
        server.emit({"event": "test"})

        assert dead not in server._event_connections
        assert alive in server._event_connections
