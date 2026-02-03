#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code Notification hook for permission prompts.

Plays the "permission needed" audio cue when Claude Code shows a
permission dialog. Only fires in non-AFK mode — AFK permissions are
handled programmatically by permission-request.py (PermissionRequest hook).
"""

import json
import os
import sys

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    send_to_daemon, make_debug_logger, read_mode,
    SILENT_FLAG, ASK_USER_FLAG, get_session,
)

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/permission_hook.log"))


def main():
    mode = read_mode()

    if mode not in ("notify", "afk"):
        return

    # AFK mode is handled by permission-request.py (PermissionRequest hook)
    if mode == "afk":
        return

    if os.path.exists(SILENT_FLAG):
        return

    # Skip if AskUserQuestion hook is handling this prompt
    if os.path.exists(ASK_USER_FLAG):
        return

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    if hook_input.get("notification_type") != "permission_prompt":
        return

    session = get_session(hook_input)
    message = hook_input.get("message", "Permission needed")
    debug(f"Hook fired: session={session}, mode={mode}")

    # Send notification to daemon (plays "permission needed" phrase)
    send_to_daemon({
        "notify_category": "permission",
        "session": session,
        "prompt": message,
        "type": "permission",
    })


if __name__ == "__main__":
    main()
