#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PreToolUse hook for AskUserQuestion.

Intercepts AskUserQuestion tool calls in AFK mode to route them
through Telegram, allowing remote answering of multi-option prompts.

Spawns a background subprocess that waits for the Telegram response
and types the selection into the terminal once the interactive prompt appears.
"""

import json
import os
import subprocess
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import send_to_daemon, make_debug_logger, read_mode, ASK_USER_FLAG

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/ask-user-debug.log"))


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

    session = os.path.basename(os.getcwd())

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

    # Capture the controlling terminal path before spawning the background
    # process. The hook runs as a child of Claude Code's terminal, so
    # /dev/tty resolves to the actual PTY device (e.g., /dev/ttys005).
    # The background process uses this to inject keystrokes via TIOCSTI.
    tty_path = None
    try:
        tty_fd = os.open("/dev/tty", os.O_RDONLY)
        tty_path = os.ttyname(tty_fd)
        os.close(tty_fd)
        debug(f"Captured TTY path: {tty_path}")
    except OSError as e:
        debug(f"Could not capture TTY: {e}")

    # Spawn a background subprocess to wait for the Telegram response
    # and type it into the terminal. This hook returns immediately so
    # Claude Code can show the interactive prompt.
    typer_script = os.path.join(os.path.dirname(__file__), "_type_answer.py")
    first_options = questions[0].get("options", [])
    options_json = json.dumps(first_options)

    cmd = [sys.executable, typer_script, response_path, options_json]
    if tty_path:
        cmd.append(tty_path)

    debug(f"Spawning typer: {typer_script} with response_path={response_path} tty={tty_path}")
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # No start_new_session — child needs same session for TTY access
    )


if __name__ == "__main__":
    main()
