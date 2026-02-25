#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PreToolUse hook for AskUserQuestion.

Plays a "question" audio notification and sets a flag so the permission
notification hook skips the duplicate "permission needed" phrase.
"""

import json
import os
import sys
import tempfile
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import send_to_daemon, make_debug_logger, ASK_USER_FLAG, get_session

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/ask-user-debug.log"))


def main():
    debug("Hook fired")

    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        debug("Failed to parse hook input")
        return

    tool_input = hook_input.get("tool_input", {})
    if not tool_input.get("questions"):
        debug("No questions in input")
        return

    session = get_session(hook_input)
    debug(f"session={session}, sending question notification")

    # Set flag so notify-permission.py skips "permission needed"
    try:
        flag_dir = os.path.dirname(ASK_USER_FLAG)
        os.makedirs(flag_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=flag_dir, prefix=".flag_")
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        os.rename(tmp_path, ASK_USER_FLAG)
    except Exception as e:
        debug(f"Failed to write ASK_USER_FLAG: {e}")

    send_to_daemon({
        "notify_category": "question",
        "session": session,
        "type": "ask_user_question",
    })


if __name__ == "__main__":
    main()
