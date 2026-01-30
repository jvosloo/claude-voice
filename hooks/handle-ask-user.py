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
import socket
import subprocess
import sys
import time

TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")
AFK_RESPONSE_TIMEOUT = 600  # 10 minutes
DEBUG_LOG = os.path.expanduser("/tmp/claude-voice/ask-user-debug.log")


def debug(msg: str) -> None:
    """Append a debug message to the log file."""
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG), exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def send_to_daemon(payload: dict) -> dict | None:
    """Send JSON to daemon and receive a JSON response."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        if data:
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    except Exception:
        pass
    return None


def main():
    # Only active in AFK mode
    mode = ""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                mode = f.read().strip()
        except Exception:
            return

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
        with open(ASK_USER_FLAG, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    # Spawn a background subprocess to wait for the Telegram response
    # and type it into the terminal. This hook returns immediately so
    # Claude Code can show the interactive prompt.
    typer_script = os.path.join(os.path.dirname(__file__), "_type_answer.py")
    first_options = questions[0].get("options", [])
    options_json = json.dumps(first_options)
    debug(f"Spawning typer: {typer_script} with response_path={response_path}")
    subprocess.Popen(
        [sys.executable, typer_script, response_path, options_json],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


if __name__ == "__main__":
    main()
