#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code Notification hook to notify when permission is needed.

Uses the Notification hook with permission_prompt matcher, which fires
only when Claude Code actually shows a permission dialog to the user.
"""

import json
import os
import socket
import sys
import time

TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
AFK_RESPONSE_TIMEOUT = 600  # 10 minutes


def send_to_daemon(payload: dict) -> dict | None:
    """Send JSON to daemon and receive a JSON response."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)  # Signal we're done sending
        # Read response
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


def type_response(text: str) -> None:
    """Type a response into the terminal using pynput."""
    from pynput.keyboard import Controller, Key
    kb = Controller()
    time.sleep(0.1)
    for char in text:
        kb.type(char)
        time.sleep(0.01)
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)


def main():
    # Check mode - only fire in notify or AFK-eligible modes
    mode = ""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                mode = f.read().strip()
        except Exception:
            return

    if mode not in ("notify", "afk"):
        return

    # Check if silent (but not in AFK mode - AFK overrides silent)
    if mode != "afk" and os.path.exists(SILENT_FLAG):
        return

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    if hook_input.get("notification_type") != "permission_prompt":
        return

    session = os.path.basename(os.getcwd())
    message = hook_input.get("message", "Permission needed")

    # Send to daemon with session info
    response = send_to_daemon({
        "notify_category": "permission",
        "session": session,
        "prompt": message,
        "type": "permission",
    })

    # If daemon says to wait (AFK mode), poll for response
    if response and response.get("wait"):
        response_path = response.get("response_path", "")
        if response_path:
            answer = wait_for_response(response_path)
            if answer and answer.lower() in ("yes", "y"):
                type_response("y")


if __name__ == "__main__":
    main()
