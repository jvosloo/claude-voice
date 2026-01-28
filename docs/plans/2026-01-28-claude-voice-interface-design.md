# Claude Voice Interface Design

**Date**: 2026-01-28
**Status**: Approved
**Goal**: Two-way voice conversation with Claude Code using local AI models

## Overview

A hands-free voice interface for Claude Code CLI. Speak to Claude using push-to-talk (hold-to-record), and Claude speaks responses back via neural text-to-speech. All processing runs locally — no cloud APIs, no ongoing costs.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your Terminal                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Claude Code CLI                       │    │
│  │                                                          │    │
│  │  You: [transcribed text appears here]                    │    │
│  │                                                          │    │
│  │  Claude: [response spoken via Piper]                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
        ▲                                       │
        │ Simulated                             │ Hook triggers
        │ keyboard input                        │ on response
        │                                       ▼
┌───────┴───────────┐                 ┌─────────────────────┐
│  Voice Input      │                 │  Voice Output       │
│  Daemon (Python)  │                 │  Hook (Bash/Python) │
│                   │                 │                     │
│  • Hotkey listen  │                 │  • Receives text    │
│  • Audio capture  │                 │  • Piper TTS        │
│  • Whisper STT    │                 │  • Audio playback   │
└───────────────────┘                 └─────────────────────┘
        ▲
        │ Hold key + speak
        │
      [You]
```

**Voice Input Daemon**: A background Python process that monitors for your hotkey. When held, it records audio from your microphone, transcribes it using Whisper, and simulates typing the text into Claude Code.

**Voice Output Hook**: A Claude Code hook that fires after each response. It receives Claude's text and pipes it to Piper, which speaks it aloud.

## Component 1: Voice Input Daemon

### Hotkey Detection
- Uses `pynput` library to monitor global keyboard events
- Configurable hotkey (default: Right Option key `⌥`)
- Detects key-down (start recording) and key-up (stop recording, transcribe, send)

### Audio Capture
- Uses `sounddevice` library to record from default microphone
- Records at 16kHz (Whisper's preferred sample rate)
- Stores audio in memory as a NumPy array — no temp files needed

### Whisper Transcription
- Uses `faster-whisper` (CTranslate2-based, ~4x faster than original Whisper)
- Runs the `base.en` model by default (good balance of speed and accuracy)
- Can upgrade to `small.en` or `medium.en` for better accuracy if needed
- Transcription happens locally — nothing sent to the cloud

### Keyboard Simulation
- After transcription, uses `pynput` to simulate typing
- Types the transcribed text character-by-character into the active terminal
- Adds a small delay between characters to ensure Claude Code receives them properly
- Optionally auto-presses Enter to submit (configurable)

### Resource Usage
- Daemon idles at ~20MB RAM when not recording
- Whisper model loads on first use (~150MB for base.en)
- CPU spike only during transcription (~1-2 seconds for typical utterances)

## Component 2: Voice Output Hook

### Hook Configuration
- Configured in `~/.claude/settings.json` under the `hooks` section
- Triggers after every Claude response
- Receives the response text via stdin or environment variable

### Piper TTS
- Fast, local neural text-to-speech engine
- Runs as a simple command: `echo "text" | piper --model voice.onnx --output-raw | aplay`
- On macOS, we'll use `afplay` or `sox` for audio playback
- Voices are ONNX models (~50-100MB each) with various accents and styles

### Voice Selection
- Piper offers many voices: US English, British, Australian, etc.
- Default: clear, natural-sounding voice (e.g., `en_US-amy-medium`)
- Configurable in settings file

### Handling Long Responses
- For long responses, stream the audio (speak as it generates)
- Option to interrupt playback by pressing the hotkey again
- Option to limit spoken output to first N sentences for very long responses

### Hook Script Location
```
~/.claude/hooks/speak-response.sh
```
- Receives response text from Claude Code
- Filters out code blocks and markdown artifacts (optional)
- Pipes clean text to Piper
- Plays resulting audio

## Configuration

**Location**: `~/.claude-voice/config.yaml`

```yaml
# Hotkey settings
input:
  hotkey: "right_alt"          # Key to hold (right_alt, right_cmd, caps_lock, f18, etc.)
  auto_submit: true            # Press Enter after transcription?
  min_audio_length: 0.5        # Ignore recordings shorter than this (seconds)

# Whisper settings
transcription:
  model: "base.en"             # Options: tiny.en, base.en, small.en, medium.en
  language: "en"               # Language code
  device: "cpu"                # "cpu" or "cuda" (if you have GPU)

# Piper settings
speech:
  voice: "en_US-amy-medium"    # Voice model name
  speed: 1.0                   # Playback speed multiplier
  max_sentences: null          # Limit spoken output (null = speak all)
  skip_code_blocks: true       # Don't speak code blocks
  interrupt_key: "right_alt"   # Same as hotkey - press to stop playback

# Audio settings
audio:
  input_device: null           # null = system default microphone
  sample_rate: 16000           # Whisper expects 16kHz
```

### First-Run Setup Wizard
- Detects available audio devices
- Tests microphone levels and offers adjustments
- Downloads selected Whisper and Piper models if not present

### Model Storage
**Location**: `~/.claude-voice/models/`
- Whisper models: ~75MB (tiny) to ~1.5GB (medium)
- Piper voices: ~50-100MB each

## Installation

### System Requirements
- macOS (Darwin 24.5.0+ compatible)
- Python 3.9+
- ~2GB disk space for models

### Python Dependencies
```
pynput          # Global hotkey detection
sounddevice     # Audio recording
numpy           # Audio processing
faster-whisper  # Speech-to-text (includes CTranslate2)
pyyaml          # Config file parsing
```

### External Tools
- **Piper**: Download pre-built binary from GitHub releases
- **sox** (optional): For audio playback — `brew install sox`
  - Alternative: use macOS built-in `afplay`

### Installation Script
**Location**: `~/.claude-voice/install.sh`

The script will:
1. Create the `~/.claude-voice/` directory structure
2. Set up a Python virtual environment
3. Install Python dependencies via pip
4. Download Piper binary for macOS ARM64
5. Download default Whisper model (`base.en`)
6. Download default Piper voice (`en_US-amy-medium`)
7. Generate default `config.yaml`
8. Install the Claude Code hook to `~/.claude/settings.json`
9. Create a launch script: `claude-voice-daemon`

### Running It
```bash
# Start the daemon (runs in background)
claude-voice-daemon start

# Check status
claude-voice-daemon status

# Stop it
claude-voice-daemon stop
```

## Error Handling

### Microphone Errors
- If microphone access is denied, daemon shows macOS permission prompt instructions
- If no audio device found, logs error and exits gracefully with helpful message
- If recording is too quiet (below threshold), ignores it instead of sending empty text

### Transcription Errors
- If Whisper can't transcribe (noise, unclear speech), shows subtle desktop notification
- Does not type anything to Claude — avoids sending gibberish
- Logs failed transcriptions for debugging

### TTS Errors
- If Piper fails, falls back to macOS `say` command (basic but works)
- If audio playback fails, logs error but doesn't interrupt Claude Code

### Hotkey Conflicts
- If chosen hotkey is already in use, daemon warns on startup
- Suggests alternative keys in the warning message

### Long Response Handling
- Speaking very long responses can be tedious
- Pressing hotkey during playback interrupts immediately
- Config option `max_sentences` to auto-truncate spoken output

### Daemon Lifecycle
- Auto-restarts if it crashes (launchd plist for macOS)
- Graceful shutdown on `SIGTERM` — finishes current operation
- PID file prevents running multiple instances

### Offline Operation
- Everything runs locally — works without internet
- No API keys, no cloud dependencies
- Models are downloaded once during installation

## File Structure

```
~/.claude-voice/
├── config.yaml              # User configuration
├── install.sh               # Installation script
├── claude-voice-daemon      # Launch script
├── daemon/
│   ├── __init__.py
│   ├── main.py              # Daemon entry point
│   ├── hotkey.py            # Hotkey detection
│   ├── audio.py             # Audio capture
│   ├── transcribe.py        # Whisper integration
│   └── keyboard.py          # Keyboard simulation
├── models/
│   ├── whisper/             # Whisper models
│   └── piper/               # Piper voices
└── logs/
    └── daemon.log           # Debug logs

~/.claude/
├── settings.json            # Claude Code settings (hook config added here)
└── hooks/
    └── speak-response.sh    # TTS hook script
```