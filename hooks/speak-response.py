#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code hook to speak responses via Kokoro TTS daemon."""

import json
import os
import re
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import SILENT_FLAG, send_to_daemon, read_mode, wait_for_response, AFK_RESPONSE_TIMEOUT, make_debug_logger, get_session

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/stop_hook.log"))

# Paths
CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")

def load_config():
    """Load speech config."""
    try:
        import yaml
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        return config.get('speech', {})
    except ImportError:
        return {}
    except Exception as e:
        print(f"[speak-response] config load error: {e}", file=sys.stderr)
        return {}

def _wait_for_transcript_flush(transcript_path: str, timeout: float = 2.0) -> None:
    """Wait for the transcript file to receive new content and stabilise."""
    deadline = time.time() + timeout

    try:
        initial_size = os.path.getsize(transcript_path)
    except OSError:
        return

    # Phase 1: wait for new content (up to 500ms)
    growth_deadline = min(time.time() + 0.5, deadline)
    while time.time() < growth_deadline:
        time.sleep(0.1)
        try:
            cur_size = os.path.getsize(transcript_path)
        except OSError:
            return
        if cur_size > initial_size:
            break

    # Phase 2: wait for the file to stop growing
    prev_size = -1
    while time.time() < deadline:
        try:
            cur_size = os.path.getsize(transcript_path)
        except OSError:
            break
        if cur_size == prev_size:
            break
        prev_size = cur_size
        time.sleep(0.15)


def extract_last_assistant_message(transcript_path: str, skip_tool_results: bool = True) -> str:
    """Extract the last assistant message from transcript.

    Args:
        transcript_path: Path to the JSONL transcript file.
        skip_tool_results: If True, omit text blocks that immediately follow
            a tool_use block (these typically contain tool output summaries).
    """
    if not os.path.exists(transcript_path):
        return ""

    # The Stop hook can fire before Claude Code flushes the current
    # response to the transcript.  Wait for the file to stabilise.
    _wait_for_transcript_flush(transcript_path)

    last_message = ""
    with open(transcript_path, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get('type') == 'assistant':
                    # Get text content from message
                    message = entry.get('message', {})
                    content = message.get('content', [])

                    text_parts = []
                    prev_was_tool = False
                    for block in content:
                        if isinstance(block, dict):
                            if block.get('type') == 'tool_use':
                                prev_was_tool = True
                                continue
                            if block.get('type') == 'text':
                                text = block.get('text', '')
                                # Skip text immediately after tool_use (tool result summary)
                                if skip_tool_results and prev_was_tool:
                                    prev_was_tool = False
                                    continue
                                text_parts.append(text)
                                prev_was_tool = False
                        elif isinstance(block, str):
                            if not (skip_tool_results and prev_was_tool):
                                text_parts.append(block)
                            prev_was_tool = False

                    if text_parts:
                        last_message = '\n'.join(text_parts)
            except json.JSONDecodeError:
                continue

    return last_message

def clean_text_for_speech(text: str, config: dict) -> str:
    """Clean text for TTS - remove code blocks, markdown, etc."""

    # Remove code blocks if configured
    if config.get('skip_code_blocks', True):
        text = re.sub(r'```[\s\S]*?```', ' [code block omitted] ', text)
        text = re.sub(r'`[^`]+`', '', text)

    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # Italic
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # Headers
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)  # List items
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Limit length if configured
    max_chars = config.get('max_chars')
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "..."

    return text

def main():
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    transcript_path = hook_input.get('transcript_path')
    if not transcript_path:
        return

    # Load config
    config = load_config()

    # Check if TTS is enabled (config or silent flag)
    if not config.get('enabled', True):
        if read_mode() != "afk":
            return
    if os.path.exists(SILENT_FLAG):
        if read_mode() != "afk":
            return

    # Extract and clean the last response
    raw_text = extract_last_assistant_message(
        transcript_path,
        skip_tool_results=config.get('skip_tool_results', True),
    )
    text = clean_text_for_speech(raw_text, config)

    if not text:
        return

    # Send to daemon (with session context for AFK routing)
    response = send_to_daemon({
        "text": text,
        "raw_text": raw_text,
        "voice": config.get("voice", "af_heart"),
        "speed": config.get("speed", 1.0),
        "lang_code": config.get("lang_code", "a"),
    }, with_context=True, raw_text=raw_text, hook_input=hook_input)

    # In AFK mode, block waiting for a follow-up message from Telegram
    if not response or not response.get("wait"):
        return

    response_path = response.get("response_path", "")
    if not response_path:
        return

    debug(f"AFK: blocking for follow-up at {response_path}")
    answer = wait_for_response(response_path, timeout=AFK_RESPONSE_TIMEOUT)

    if not answer or answer in ("__back__", "__timeout__", "__flush__"):
        debug(f"AFK: unblocked with sentinel: {answer!r}")
        return

    # Return a Stop hook "block" decision -- Claude continues with this message
    debug(f"AFK: forwarding Telegram message to Claude: {answer[:100]!r}")
    output = {
        "decision": "block",
        "reason": f"The user sent this follow-up message via Telegram while in AFK mode: {answer}"
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
