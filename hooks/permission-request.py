#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PermissionRequest hook.

Checks stored permission rules for auto-approval, otherwise returns "ask"
so the normal permission dialog appears.
"""

import json
import os
import sys

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import make_debug_logger, check_permission_rules

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

    # AskUserQuestion is handled by the PreToolUse hook (handle-ask-user.py).
    # Return early without output so Claude Code shows the question dialog
    # normally, while skipping the daemon call that would trigger the
    # "permission needed" notification chain.
    if hook_input.get("tool_name") == "AskUserQuestion":
        debug("Skipping AskUserQuestion (handled by PreToolUse hook)")
        return

    # Build rich prompt with tool details
    prompt = extract_tool_detail(hook_input)

    debug(f"Permission request: {prompt}")

    # Check permission rules — auto-approve if a stored rule matches
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

    # No rule matched — show local permission dialog
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "ask"}
        }
    }

    debug("Returning decision: ask")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
