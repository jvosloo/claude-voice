#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code hook to detect tool failures and notify in notify mode.

Uses the PostToolUseFailure hook with Bash matcher, which fires
when a Bash command exits with a non-zero status.
"""

import json
import os
import sys

ERROR_FLAG = os.path.expanduser("~/.claude-voice/.error_pending")
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

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    # Only flag errors from Bash tool, skip interrupts
    if hook_input.get("tool_name") != "Bash":
        return
    if hook_input.get("is_interrupt"):
        return

    # Write flag file for the daemon to pick up
    try:
        with open(ERROR_FLAG, "w") as f:
            pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
