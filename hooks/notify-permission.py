#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code Notification hook to notify when permission is needed.

Uses the Notification hook with permission_prompt matcher, which fires
only when Claude Code actually shows a permission dialog to the user.
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    send_to_daemon, wait_for_response, make_debug_logger, read_mode,
    SILENT_FLAG, ASK_USER_FLAG,
)

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/permission_hook.log"))


def select_permission_option(index: int) -> None:
    """Navigate the permission TUI picker: press Down `index` times, then Enter.

    Permission picker options:
      0 = Allow once
      1 = Always allow
      2 = Don't allow
    """
    from pynput.keyboard import Controller, Key
    kb = Controller()
    debug(f"select_permission_option({index}): waiting 0.5s for picker")
    time.sleep(0.5)  # Wait for the picker to render
    for i in range(index):
        debug(f"  pressing Down ({i+1}/{index})")
        kb.press(Key.down)
        kb.release(Key.down)
        time.sleep(0.05)
    debug("  pressing Enter")
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)
    debug("  keystrokes sent")


def main():
    # Check mode - only fire in notify or AFK-eligible modes
    mode = read_mode()

    if mode not in ("notify", "afk"):
        return

    # Check if silent (but not in AFK mode - AFK overrides silent)
    if mode != "afk" and os.path.exists(SILENT_FLAG):
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

    session = os.path.basename(os.getcwd())
    message = hook_input.get("message", "Permission needed")
    debug(f"Hook fired: session={session}, mode={mode}")
    debug(f"Message: {message}")

    # Log full hook input for debugging
    log_dir = os.path.expanduser("/tmp/claude-voice/logs")
    os.makedirs(log_dir, exist_ok=True)
    try:
        with open(os.path.join(log_dir, "permission_hook_input.json"), "w") as f:
            json.dump(hook_input, f, indent=2, default=str)
    except Exception:
        pass

    # Send to daemon with session info
    debug("Sending to daemon...")
    response = send_to_daemon({
        "notify_category": "permission",
        "session": session,
        "prompt": message,
        "type": "permission",
    })
    debug(f"Daemon response: {response}")

    # If daemon says to wait (AFK mode), poll for response
    if response and response.get("wait"):
        response_path = response.get("response_path", "")
        debug(f"Waiting for response at: {response_path}")
        if response_path:
            answer = wait_for_response(response_path)
            debug(f"Got answer: {answer!r}")
            if answer:
                answer_lower = answer.lower()
                if answer_lower in ("always",):
                    debug("Selecting: Always allow (index 1)")
                    select_permission_option(1)
                elif answer_lower in ("yes", "y"):
                    debug("Selecting: Allow once (index 0)")
                    select_permission_option(0)
                elif answer_lower in ("no", "n"):
                    debug("Selecting: Don't allow (index 2)")
                    select_permission_option(2)
                else:
                    debug(f"Unknown answer: {answer!r}, not selecting anything")
                debug("Done selecting")
            else:
                debug("No answer received (timeout or empty)")
    else:
        debug(f"Not waiting (response={response})")


if __name__ == "__main__":
    main()
