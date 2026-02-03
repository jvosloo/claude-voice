#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PreToolUse hook for AskUserQuestion.

In AFK mode, intercepts AskUserQuestion and routes it through Telegram.
Blocks synchronously until the user responds, then returns a deny decision
with the answer in the reason — Claude reads it and continues.

In non-AFK mode, returns nothing (tool runs normally with local picker).
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import send_to_daemon, make_debug_logger, read_mode, wait_for_response, ASK_USER_FLAG, get_session

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/ask-user-debug.log"))


def _deny(reason: str) -> None:
    """Print a deny decision with the given reason. Claude sees this reason."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))


def main():
    # Only active in AFK mode
    mode = read_mode()
    if mode != "afk":
        return

    debug("Hook fired in AFK mode")

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        debug("Failed to parse hook input")
        return

    tool_input = hook_input.get("tool_input", {})
    questions = tool_input.get("questions", [])
    if not questions:
        debug("No questions in tool_input")
        return

    debug(f"Got {len(questions)} questions")

    session = get_session(hook_input)

    # Build a readable prompt for Telegram
    prompt_lines = []
    for q in questions:
        prompt_lines.append(q.get("question", ""))
        for i, opt in enumerate(q.get("options", []), 1):
            prompt_lines.append(f"  {i}. {opt.get('label', '')} — {opt.get('description', '')}")

    # Send to daemon
    response = send_to_daemon({
        "session": session,
        "type": "ask_user_question",
        "prompt": "\n".join(prompt_lines),
        "questions": questions,
    })

    debug(f"Daemon response: {response}")

    if not response or not response.get("wait"):
        return

    response_path = response.get("response_path", "")
    if not response_path:
        return

    # Set flag so notify-permission.py skips the duplicate notification
    try:
        os.makedirs(os.path.dirname(ASK_USER_FLAG), exist_ok=True)
        with open(ASK_USER_FLAG, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    # Block until Telegram response arrives
    debug(f"Waiting for response at {response_path}")
    answer = wait_for_response(response_path)

    # Clear flag
    try:
        os.remove(ASK_USER_FLAG)
    except FileNotFoundError:
        pass

    if not answer:
        debug("Timed out waiting for response")
        _deny("AFK mode: the user did not respond in time. You may retry or move on.")
        return

    if answer == "__flush__":
        debug("Queue flushed, denying")
        _deny("AFK mode: the request queue was flushed. The question was cancelled.")
        return

    # Skip/Other — let the local picker handle it
    if answer in ("opt:__other__", "__other__"):
        debug("User chose Skip/Other, allowing local picker")
        return

    # Extract the actual answer text
    if answer.startswith("opt:"):
        answer_text = answer[4:]
        debug(f"Option selected: {answer_text}")
    else:
        answer_text = answer
        debug(f"Free-text answer: {answer_text}")

    _deny(
        f'The user is in AFK mode and already answered this question via Telegram. '
        f'Their answer was: "{answer_text}". '
        f'Please continue with this answer and do not retry the question.'
    )


if __name__ == "__main__":
    main()
