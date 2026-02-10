"""Control socket server for external app communication.

Provides a JSON command/event protocol over a Unix socket at
~/.claude-voice/.control.sock, separate from the existing TTS socket.

Commands (client → daemon):
    {"cmd": "status"}                    → current daemon state
    {"cmd": "set_mode", "mode": "..."}   → switch TTS mode
    {"cmd": "voice_on"}                  → enable voice output
    {"cmd": "voice_off"}                 → disable voice output
    {"cmd": "reload_config"}             → re-read config.yaml
    {"cmd": "speak"}                     → play "ready for input" phrase (voice preview)
    {"cmd": "stop"}                      → shutdown daemon
    {"cmd": "subscribe"}                 → keep connection open for events

Status response fields:
    daemon      bool    always True
    mode        str     "notify", "narrate", or "afk"
    voice       bool    True if voice output enabled
    recording   bool    True if currently recording
    ready       bool    True when fully initialized (models loaded, hotkey active)

Events (daemon → subscribed clients):
    {"event": "mode_changed", "mode": "..."}
    {"event": "voice_changed", "enabled": true/false}
    {"event": "recording_start"}
    {"event": "recording_stop"}
    {"event": "config_reloaded"}
    {"event": "error", "source": "openai_tts", "message": "...", "code": "..."}
    {"event": "error_cleared", "source": "openai_tts"}
"""

import json
import os
import socket
import stat
import threading

CONTROL_SOCK_PATH = os.path.expanduser("~/.claude-voice/.control.sock")


class ControlServer:
    """JSON command/event server over Unix socket."""

    def __init__(self, daemon):
        self.daemon = daemon
        self._shutting_down = False
        self._event_connections = []
        self._lock = threading.Lock()
        self._server = None

    def _handle_command(self, data: dict) -> dict:
        """Handle a command and return a response."""
        cmd = data.get("cmd")

        if cmd == "status":
            return {
                "daemon": True,
                "mode": self.daemon.get_mode(),
                "voice": self.daemon.get_voice_enabled(),
                "recording": self.daemon.recorder.is_recording,
                "ready": self.daemon.is_ready(),
            }

        if cmd == "set_mode":
            mode = data.get("mode", "notify")
            self.daemon.set_mode(mode)
            self.emit({"event": "mode_changed", "mode": mode})
            return {"ok": True}

        if cmd == "voice_on":
            self.daemon.set_voice_enabled(True)
            self.emit({"event": "voice_changed", "enabled": True})
            return {"ok": True}

        if cmd == "voice_off":
            self.daemon.set_voice_enabled(False)
            self.emit({"event": "voice_changed", "enabled": False})
            return {"ok": True}

        if cmd == "reload_config":
            self.daemon.reload_config()
            self.emit({"event": "config_reloaded"})
            return {"ok": True}

        if cmd == "speak":
            from daemon.notify import _get_phrase_path
            import subprocess
            path = _get_phrase_path("done", self.daemon.config.speech.notify_phrases)
            if os.path.exists(path):
                threading.Thread(
                    target=lambda: subprocess.run(["afplay", path]),
                    daemon=True,
                ).start()
            return {"ok": True}

        if cmd == "preview_overlay":
            from daemon import overlay
            import time
            def _preview():
                overlay.show_recording()
                time.sleep(1.5)
                overlay.show_transcribing()
                time.sleep(1.0)
                overlay.hide()
            threading.Thread(target=_preview, daemon=True).start()
            return {"ok": True}

        if cmd == "stop":
            threading.Thread(target=self.daemon._shutdown, daemon=True).start()
            return {"ok": True}

        if cmd == "subscribe":
            return {"subscribed": True}

        return {"error": f"unknown command: {cmd}"}

    def emit(self, event: dict):
        """Send event to all subscribed connections."""
        msg = json.dumps(event).encode() + b"\n"
        with self._lock:
            dead = []
            for conn in self._event_connections:
                try:
                    conn.sendall(msg)
                except (BrokenPipeError, OSError):
                    dead.append(conn)
            for conn in dead:
                self._event_connections.remove(conn)

    def run(self):
        """Run the control socket server (blocking)."""
        if os.path.exists(CONTROL_SOCK_PATH):
            os.unlink(CONTROL_SOCK_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(CONTROL_SOCK_PATH)
        os.chmod(CONTROL_SOCK_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600 - owner only
        server.listen(5)
        server.settimeout(1.0)
        self._server = server

        while not self._shutting_down:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            threading.Thread(
                target=self._handle_connection, args=(conn,), daemon=True
            ).start()

        server.close()
        if os.path.exists(CONTROL_SOCK_PATH):
            os.unlink(CONTROL_SOCK_PATH)

    def _handle_connection(self, conn):
        """Handle a single client connection."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    json.loads(data.decode())
                    break  # Valid JSON received
                except json.JSONDecodeError:
                    continue

            if not data:
                conn.close()
                return

            request = json.loads(data.decode())
            response = self._handle_command(request)

            # Subscribe: keep connection open for streaming events
            if request.get("cmd") == "subscribe":
                conn.sendall(json.dumps(response).encode() + b"\n")
                with self._lock:
                    self._event_connections.append(conn)
                return  # Don't close

            conn.sendall(json.dumps(response).encode())
            conn.close()
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"Control server: malformed request: {e}")
            try:
                conn.close()
            except OSError:
                pass
        except OSError as e:
            # Connection errors (client disconnected, etc.)
            try:
                conn.close()
            except OSError:
                pass

    def shutdown(self):
        """Stop the server and close all event connections."""
        self._shutting_down = True
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass  # Socket already closed
        with self._lock:
            for conn in self._event_connections:
                try:
                    conn.close()
                except OSError:
                    pass  # Connection already closed
            self._event_connections.clear()