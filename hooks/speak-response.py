#!/usr/bin/env -S bash -c '"$HOME/.claude-voice/venv/bin/python3" "$0" "$@"'
"""Claude Code hook to speak responses via Piper TTS."""

import json
import os
import re
import subprocess
import sys
import tempfile
import wave

# Paths
MODELS_DIR = os.path.expanduser("~/.claude-voice/models/piper")
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
    """Speak text using Piper TTS."""
    if not text:
        return

    voice_name = config.get('voice', 'en_US-amy-medium')
    voice_model = os.path.join(MODELS_DIR, f"{voice_name}.onnx")

    if not os.path.exists(voice_model):
        print(f"Voice model not found at {voice_model}", file=sys.stderr)
        return

    try:
        from piper import PiperVoice

        # Load voice model
        voice = PiperVoice.load(voice_model)

        # Create temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name

        # Synthesize to WAV file
        with wave.open(tmp_path, 'wb') as wav_file:
            voice.synthesize_wav(text, wav_file)

        # Play the audio (with speed adjustment)
        speed = config.get('speed', 1.0)
        subprocess.run(['afplay', '-r', str(speed), tmp_path], check=True)

        # Clean up
        os.unlink(tmp_path)

    except Exception as e:
        print(f"TTS error: {e}", file=sys.stderr)

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
        return

    # Extract and clean the last response
    text = extract_last_assistant_message(transcript_path)
    text = clean_text_for_speech(text, config)

    if text:
        speak(text, config)

if __name__ == "__main__":
    main()
