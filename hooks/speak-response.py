#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code hook to speak responses via Kokoro TTS daemon."""

import json
import os
import re
import socket
import sys

# Paths
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")

def load_config():
    """Load speech config."""
    try:
        import yaml
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        return config.get('speech', {})
    except Exception:
        return {}

def extract_last_assistant_message(transcript_path: str) -> str:
    """Extract the last assistant message from transcript."""
    if not os.path.exists(transcript_path):
        return ""

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
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            text_parts.append(block.get('text', ''))
                        elif isinstance(block, str):
                            text_parts.append(block)

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

def speak(text: str, config: dict) -> None:
    """Send text to the daemon's TTS server."""
    if not text:
        return

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps({
            "text": text,
            "voice": config.get("voice", "af_heart"),
            "speed": config.get("speed", 1.0),
            "lang_code": config.get("lang_code", "a"),
        }).encode())
        s.close()
    except (ConnectionRefusedError, FileNotFoundError):
        pass  # Daemon not running, silent fail

def send_with_context(text: str, config: dict) -> dict | None:
    """Send text to daemon with session context. Returns daemon response."""
    if not text:
        return None

    session = os.path.basename(os.getcwd())

    # Get last N lines as context
    context_lines = text.strip().split("\n")[-10:]
    context = "\n".join(context_lines)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps({
            "text": text,
            "voice": config.get("voice", "af_heart"),
            "speed": config.get("speed", 1.0),
            "lang_code": config.get("lang_code", "a"),
            "session": session,
            "context": context,
        }).encode())
        s.shutdown(socket.SHUT_WR)
        # Read response
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
        return
    if os.path.exists(SILENT_FLAG):
        # Check if in AFK mode (AFK overrides silent)
        mode = ""
        if os.path.exists(os.path.expanduser("~/.claude-voice/.mode")):
            try:
                with open(os.path.expanduser("~/.claude-voice/.mode")) as f:
                    mode = f.read().strip()
            except Exception:
                pass
        if mode != "afk":
            return

    # Extract and clean the last response
    text = extract_last_assistant_message(transcript_path)
    text = clean_text_for_speech(text, config)

    if text:
        send_with_context(text, config)

if __name__ == "__main__":
    main()
