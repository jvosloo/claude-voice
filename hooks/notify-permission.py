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

TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")


def main():
    # Only fire in notify mode
    if not os.path.exists(MODE_FILE):
        return
    try:
        with open(MODE_FILE) as f:
            mode = f.read().strip()
    except Exception:
        return
    if mode != "notify":
        return

    # Check if silent
    if os.path.exists(SILENT_FLAG):
        return

    # Read hook input (Notification event provides message and notification_type)
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    # The matcher already filters for permission_prompt, but verify just in case
    if hook_input.get("notification_type") != "permission_prompt":
        return

    # Send "permission" signal to daemon
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps({
            "notify_category": "permission",
        }).encode())
        s.close()
    except (ConnectionRefusedError, FileNotFoundError):
        pass


if __name__ == "__main__":
    main()
