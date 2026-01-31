#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PermissionRequest hook for AFK mode.

Intercepts permission requests to route through Telegram for approval.
Returns JSON decision (allow/deny) instead of keyboard simulation.

MANUAL TEST PLAN:
1. Install this hook to ~/.claude/hooks/
2. Start daemon in AFK mode
3. In a Claude Code session, trigger a permission request (e.g., Bash tool)
4. Verify Telegram receives the request with [Yes] [Always] [No] buttons
5. Tap [Yes] → verify tool executes
6. Trigger same permission again, tap [Always] → verify rule stored
7. Trigger same permission third time → verify auto-approved (no Telegram message)
8. Send text question instead of button → verify deny + question typed to terminal
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    send_to_daemon, wait_for_response, make_debug_logger, read_mode,
    SILENT_FLAG, store_permission_rule, check_permission_rules,
)

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/permission_hook.log"))


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

    tool_input = hook_input.get("tool_input", {})
    message = str(tool_input)  # Permission message from Claude Code

    debug(f"Permission request: {message}")

    # Check permission rules first
    rule_decision = check_permission_rules(message)
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

    session = os.path.basename(os.getcwd())

    # Send to daemon
    debug("Sending to daemon...")
    response = send_to_daemon({
        "session": session,
        "type": "permission",
        "prompt": message,
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
                    store_permission_rule(message)
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
