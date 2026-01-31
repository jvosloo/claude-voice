"""Shared utilities for Claude Voice hook scripts."""

import json
import os
import socket
import time

# Shared paths
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")
AFK_RESPONSE_TIMEOUT = 600  # 10 minutes


def make_debug_logger(log_path: str):
    """Create a debug logging function that writes to the given log file."""
    def debug(msg: str) -> None:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass
    return debug


def send_to_daemon(payload: dict) -> dict | None:
    """Send JSON to daemon and receive a JSON response."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        if data:
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    except Exception:
        pass
    return None


def wait_for_response(response_path: str) -> str | None:
    """Poll for a response file. Returns response text or None on timeout."""
    deadline = time.time() + AFK_RESPONSE_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(response_path):
            try:
                with open(response_path) as f:
                    response = f.read().strip()
                os.remove(response_path)
                return response
            except Exception:
                pass
        time.sleep(1)
    return None


def read_mode() -> str:
    """Read the current TTS mode from the mode file."""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                return f.read().strip()
        except Exception:
            pass
    return ""
