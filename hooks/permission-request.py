#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PermissionRequest hook for AFK mode.

Intercepts permission requests to route through Telegram for approval.
Returns JSON decision (allow/deny) instead of keyboard simulation.

In AFK mode: sends rich prompt (tool name + command detail) to Telegram,
waits for user response, returns programmatic allow/deny.
In non-AFK mode: returns "ask" so the normal permission dialog appears.
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    send_to_daemon, wait_for_response, make_debug_logger, read_mode,
    SILENT_FLAG, store_permission_rule, check_permission_rules, get_session,
)

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/permission_hook.log"))

MAX_DETAIL_LENGTH = 200


def extract_tool_detail(hook_input: dict) -> str:
    """Build a human-readable prompt from the hook input's tool name and input.

    Returns e.g. "Bash: `cat /etc/hosts`" or "Read: /path/to/file".
    """
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if not isinstance(tool_input, dict):
        detail = str(tool_input)[:MAX_DETAIL_LENGTH]
        return f"{tool_name}: {detail}" if tool_name else detail

    # Extract the most relevant field based on tool type
    if tool_name == "Bash":
        detail = tool_input.get("command", str(tool_input))
    elif tool_name in ("Read", "Write", "Edit"):
        detail = tool_input.get("file_path", str(tool_input))
    elif tool_name in ("Grep", "Glob"):
        detail = tool_input.get("pattern", str(tool_input))
    else:
        detail = str(tool_input)

    if len(detail) > MAX_DETAIL_LENGTH:
        detail = detail[:MAX_DETAIL_LENGTH] + "…"

    if tool_name:
        return f"{tool_name}: {detail}"
    return detail


def main():
    # Check mode
    mode = read_mode()

    if mode not in ("notify", "afk"):
        return

    # Check if silent (but not in AFK mode - AFK overrides silent)
    if mode != "afk" and os.path.exists(SILENT_FLAG):
        return

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        debug("Failed to parse hook input")
        return

    # Log full input for debugging/verification
    log_dir = os.path.expanduser("/tmp/claude-voice/logs")
    os.makedirs(log_dir, exist_ok=True)
    try:
        with open(os.path.join(log_dir, "permission_hook_input.json"), "w") as f:
            json.dump(hook_input, f, indent=2, default=str)
    except Exception:
        pass

    # Build rich prompt with tool details
    prompt = extract_tool_detail(hook_input)

    debug(f"Permission request: {prompt}")

    # Check permission rules first
    rule_decision = check_permission_rules(prompt)
    if rule_decision:
        debug(f"Auto-approved by rule: {rule_decision}")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": rule_decision}
            }
        }
        print(json.dumps(output))
        return

    session = get_session(hook_input)

    # Send to daemon
    debug("Sending to daemon...")
    response = send_to_daemon({
        "session": session,
        "type": "permission",
        "prompt": prompt,
    })
    debug(f"Daemon response: {response}")

    # Default: ask (show local permission dialog)
    decision = "ask"

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
                    decision = "allow"
                    store_permission_rule(prompt)
                    debug("Stored 'always allow' rule")

                elif answer_lower in ("yes", "y"):
                    decision = "allow"
                    debug("Allowing once")

                elif answer_lower in ("no", "n", "deny"):
                    decision = "deny"
                    debug("Denying")

                elif answer == "deny_for_question":
                    # User asked a question, deny so Claude can explain
                    decision = "deny"
                    debug("Denying (user asked question)")
            else:
                debug("No answer received (timeout)")

    # Return programmatic decision
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": decision}
        }
    }

    debug(f"Returning decision: {decision}")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
