# Claude Voice Interface

Push-to-talk voice input for macOS. Transcribes speech and types it into any focused application.

When used with Claude Code, two voice output modes are available:
- **Notify mode** (default) — plays short status phrases ("Over to you", "Permission needed", "Please choose an option")
- **Narrate mode** — reads Claude's full response aloud via neural TTS

**Platform:** macOS (uses `afplay` for audio playback)

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
  - [Commands](#commands)
  - [Voice Input](#voice-input-works-anywhere)
  - [With Claude Code](#with-claude-code-two-way-voice)
  - [Multilingual Dictation](#multilingual-dictation)
  - [Voice Toggle Hotkey](#voice-toggle-hotkey)
  - [Voice Commands](#voice-commands)
  - [AFK Mode](#afk-mode)
- [Setup](#setup)
- [Configuration](#configuration)
  - [Speech Settings](#speech-settings-tts-output)
  - [Transcription Settings](#transcription-settings)
  - [Word Replacements](#word-replacements)
  - [Input Settings](#input-settings)
  - [Audio Settings](#audio-settings)
- [Available Voices](#available-voices)
- [Testing](#testing)
- [Development](#development)
- [Components](#components)

---

## Prerequisites

- **macOS** (Apple Silicon recommended)
- **Python 3.12+** — install via [pyenv](https://github.com/pyenv/pyenv) (`pyenv install 3.13`) or Homebrew (`brew install python@3.13`)
- **ffmpeg** — required by mlx-audio; the installer will offer to install it via Homebrew if missing

---

## Installation

```bash
git clone https://github.com/jvosloo/claude-voice.git
cd claude-voice
./install.sh
```

The installer will:
- Create `~/.claude-voice/` with daemon files
- Set up a Python virtual environment with dependencies
- Install Kokoro TTS (via mlx-audio, Apple Silicon optimized)
- Install the Claude Code TTS hook
- Optionally install MLX Whisper (recommended for Apple Silicon)
- Check and prompt for Microphone and Accessibility permissions
- Optionally add shell aliases (`cv`, `cvf`, `cvs`)

**Required permissions** (the installer will guide you):
- **Microphone** — for voice recording
- **Accessibility** — for keyboard input simulation and hotkey detection

### Updating

To update to a new version, pull the latest code and re-run the installer:

```bash
cd claude-voice
git pull
./install.sh
```

The installer is idempotent — it will update daemon files and Python packages while preserving your `config.yaml`.

### Uninstalling

```bash
./uninstall.sh
```

This removes all installed components. You'll be prompted before deleting your config and downloaded voice models.

---

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `cvf` | Start daemon (foreground, Ctrl+C to stop) |
| `cvs` | Start daemon in silent mode (no voice output) |
| `cv stop` | Stop the daemon |
| `cv status` | Check if daemon is running |
| `cv voice-off` | Disable voice output |
| `cv voice-on` | Enable voice output |
| `cv mode notify` | Switch to notify mode (short status phrases) |
| `cv mode narrate` | Switch to narrate mode (read full responses) |

### Voice Input (Works Anywhere)

1. Hold **Right Alt** and speak
2. Release to transcribe — text is typed into the focused input
3. Works with any application: browsers, text editors, terminals, etc.

### With Claude Code (Two-Way Voice)

When the focused application is Claude Code:
- Your transcribed speech is sent to Claude
- Claude's response is spoken aloud via TTS
- **Press the hotkey to interrupt** Claude while speaking

### Multilingual Dictation

Switch between languages on the fly with a hotkey. Configure `language_hotkey` and `extra_languages` in your config:

```yaml
input:
  language_hotkey: "right_cmd"

transcription:
  language: "en"
  extra_languages: ["af"]
```

- Tap the language hotkey to cycle languages — the overlay flashes the active language code (e.g. "AF")
- Hold the recording hotkey to dictate in the active language — the overlay pill shows the language code when not using the default

### Voice Toggle Hotkey

Press **Left Alt + V** to toggle voice output on/off. You'll hear ascending tones when voice is enabled and descending tones when disabled, with an overlay flash confirming the change. Configure via `speech.hotkey` in config.yaml (set to `null` to disable).

### Voice Commands

Say these phrases to toggle voice output without leaving Claude:

| Say this | Effect |
|----------|--------|
| **"Stop speaking"** | Disable voice output |
| **"Start speaking"** | Enable voice output |
| **"Switch to notify mode"** | Short status phrases |
| **"Switch to narrate mode"** | Read full responses aloud |

Also accepts "stop/start talking" and "notification/narration mode".

### AFK Mode

AFK mode lets you interact with Claude Code from your phone via Telegram when you're away from your keyboard. When Claude needs permission or input, you get a Telegram message and can respond directly.

**Setup:**

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token
4. Search for **@userinfobot** to find your chat ID
5. Add both to your config:

```yaml
afk:
  telegram:
    bot_token: "123456:ABC-DEF..."
    chat_id: "987654321"
```

**Usage:**

| Action | Method |
|--------|--------|
| Activate | Say "going AFK", press Left Alt+A, or send `/afk` in Telegram |
| Deactivate | Say "back at keyboard", press Left Alt+A, or send `/back` or `/afk` in Telegram |
| Approve permission | Tap Yes / No button |
| Provide input | Type your reply in the Telegram chat |

**Telegram commands:**

| Command | Description |
|---------|-------------|
| `/afk` | Toggle AFK mode on/off |
| `/back` | Deactivate AFK mode |
| `/status` | Show active sessions and their state |
| `/sessions` | List sessions with context — tap to see last message and reply |
| `/queue` | Show pending requests |
| `/skip` | Skip current request |
| `/flush` | Clear all pending requests |
| `/help` | Show available commands |

**Security:**

- Messages are validated by chat ID (only your messages are accepted)
- No ports opened on your machine (uses outbound long-polling)
- Bot token stored in local config.yaml (gitignored)
- Telegram can see message content (not end-to-end encrypted)

---

## Setup

### Shell Aliases

The installer offers to add these aliases to your shell config. If you skipped that, add to `~/.zshrc` or `~/.bashrc`:
```bash
alias cv="~/.claude-voice/claude-voice-daemon"
alias cvf="~/.claude-voice/claude-voice-daemon foreground"
alias cvs="~/.claude-voice/claude-voice-daemon --silent foreground"
```

Then run `source ~/.zshrc` to load them.

### Quick Start

**Terminal 1:** Start the voice daemon
```bash
cvf
```

**Terminal 2:** Start Claude Code
```bash
claude
```

---

## Configuration

Edit `~/.claude-voice/config.yaml` to customize behavior.

### Speech Settings (TTS Output)

| Setting | Default | Description |
|---------|---------|-------------|
| `voice` | `af_heart` | Kokoro voice ID (see Available Voices below) |
| `speed` | `1.0` | Playback speed (1.0 = normal) |
| `lang_code` | `a` | Language code: `a` American, `b` British, `j` Japanese, `z` Chinese, `e` Spanish, `f` French |
| `mode` | `notify` | `notify` (status phrases) or `narrate` (read full responses) |
| `enabled` | `true` | Enable/disable TTS output |
| `max_chars` | `null` | Limit spoken output length (`null` = unlimited) |
| `skip_code_blocks` | `true` | Don't speak code blocks |
| `skip_tool_results` | `true` | Don't speak tool result output |
| `notify_phrases` | *(defaults)* | Custom phrase overrides per category (done, permission, question) |
| `hotkey` | `left_alt+v` | Combo hotkey to toggle voice on/off (`null` to disable) |

### Transcription Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `backend` | `mlx` | `mlx` (fast on Apple Silicon) or `faster-whisper` (CPU) |
| `model` | `large-v3` | Whisper model (see table below) |
| `language` | `en` | Default language code |
| `extra_languages` | `[]` | Additional languages to cycle through (e.g. `["af", "de"]`) |
| `device` | `cpu` | Compute device for faster-whisper: `cpu` or `cuda` |
| `word_replacements` | `{}` | Fix consistently misheard words (see below) |

**Available models:**

| Model | Size | Speed | Accuracy | Notes |
|-------|------|-------|----------|-------|
| `tiny.en` | ~40MB | Fastest | Basic | Good for quick tests |
| `base.en` | ~150MB | Fast | Good | Balanced |
| `small.en` | ~500MB | Medium | Better | Recommended |
| `medium.en` | ~1.5GB | Slower | Great | High accuracy |
| `large-v3` | ~3GB | Slowest | Best | Default, MLX recommended |

**Tip:** With MLX backend on Apple Silicon, even `large-v3` runs fast.

**Note:** The `.en` models (e.g. `base.en`) only support English. To use `extra_languages`, you need a multilingual model like `large-v3`.

### Word Replacements

Fix words that Whisper consistently gets wrong. Replacements are case-insensitive and match whole words only (so "taste" won't match "aftertaste"). Multi-word phrases are supported.

```yaml
transcription:
  word_replacements:
    "clawd": "Claude"              # included by default
    "clothes code": "Claude Code"
```

Replacements are applied immediately after transcription, before any LLM cleanup. Changes take effect on the next recording after `reload_config`.

### Input Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `hotkey` | `right_alt` | Key to hold for recording |
| `language_hotkey` | `null` | Key to cycle transcription languages (e.g. `right_cmd`) |
| `auto_submit` | `false` | Press Enter automatically after transcription |
| `min_audio_length` | `0.5` | Ignore recordings shorter than this (seconds) |
| `typing_delay` | `0` | Delay between keystrokes (seconds, e.g. `0.005` for a slight delay) |
| `transcription_cleanup` | `false` | Clean up transcription using local LLM (requires Ollama) |
| `cleanup_model` | `qwen2.5:1.5b` | Ollama model for transcription cleanup |

**Available hotkeys:** `right_alt`, `left_alt`, `right_cmd`, `left_cmd`, `right_ctrl`, `left_ctrl`, `right_shift`, `caps_lock`, `f18`, `f19`

### Audio Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `input_device` | `null` | Microphone device (`null` = system default) |
| `sample_rate` | `16000` | Sample rate in Hz (Whisper expects 16kHz) |

---

## Available Voices

Kokoro TTS provides 54 voice presets. The model downloads automatically on first use (~360MB).

**Voice ID format:** `{lang}{gender}_{name}` — e.g., `af_heart` = American female "heart"

### American English (`lang_code: "a"`)

| Voice | Description |
|-------|-------------|
| `af_heart` | Female (default, warmest rated) |
| `af_bella` | Female |
| `af_nova` | Female |
| `af_sky` | Female |
| `am_adam` | Male |
| `am_echo` | Male |

### British English (`lang_code: "b"`)

| Voice | Description |
|-------|-------------|
| `bf_alice` | Female |
| `bf_emma` | Female |
| `bm_daniel` | Male |
| `bm_george` | Male |

Full voice list: https://huggingface.co/mlx-community/Kokoro-82M-bf16/blob/main/VOICES.md

---

## Testing

Run the test suite:

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ -v
```

Run with coverage (shows which lines are missing tests):

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ --cov=daemon --cov=hooks --cov-report=term-missing
```

Generate an HTML coverage report (opens in browser):

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ --cov=daemon --cov=hooks --cov-report=html
open htmlcov/index.html
```

Run only unit or integration tests:

```bash
~/.claude-voice/venv/bin/python -m pytest tests/unit/ -v
~/.claude-voice/venv/bin/python -m pytest tests/integration/ -v
```

---

## Development

### Deployment

The local installation at `~/.claude-voice/` is separate from this repo. After making code changes, deploy with:

```bash
./deploy.sh
```

The script will:
- Copy changed files from `daemon/` to `~/.claude-voice/daemon/`
- Copy changed files from `hooks/` to `~/.claude/hooks/`
- Show what changed (+ for new, * for updated)
- Check if the daemon is running and advise whether restart is needed

**Quick workflow:**
```bash
# 1. Edit code in daemon/ or hooks/
# 2. Deploy changes
./deploy.sh

# 3. Restart daemon (if daemon files changed)
pkill -f claude-voice-daemon && claude-voice-daemon

# Or reload config only (if only config logic changed)
claude-voice-daemon reload
```

### Project Structure

```
claude-voice/                    # This repo (development)
├── daemon/                      # Daemon source code
├── hooks/                       # Hook scripts source code
├── tests/                       # Test suite
├── install.sh                   # Installer
├── deploy.sh                    # Deployment script
└── CLAUDE.md                    # Developer documentation

~/.claude-voice/                 # Local installation (runtime)
├── daemon/                      # Deployed daemon code
├── config.yaml                  # User configuration
├── venv/                        # Python virtualenv
└── models/                      # Downloaded AI models

~/.claude/hooks/                 # Deployed hooks
├── speak-response.py            # TTS hook (AFK: blocks for follow-up)
├── permission-request.py        # AFK permission approval hook
├── notify-permission.py         # Permission notification sound
├── handle-ask-user.py           # Question phrase in notify; AskUserQuestion to Telegram in AFK
└── _common.py                   # Shared utilities for hooks
```

---

## Components

### Voice Input (Daemon)
- `~/.claude-voice/daemon/` - Python modules
- `~/.claude-voice/claude-voice-daemon` - Launch script
- `~/.claude-voice/config.yaml` - Configuration file
- `~/.claude-voice/logs/` - Installation and daemon logs

### Voice Output (Hooks + Daemon)
- `~/.claude/hooks/speak-response.py` - Stop hook: sends response text to daemon for TTS; in AFK mode, blocks for Telegram follow-up
- `~/.claude/hooks/notify-permission.py` - Notification hook: plays "permission needed" audio cue
- `~/.claude/hooks/permission-request.py` - PermissionRequest hook: routes permissions through Telegram in AFK mode, returns programmatic allow/deny decisions
- `~/.claude/hooks/handle-ask-user.py` - PreToolUse hook: plays "question" phrase in notify mode; forwards to Telegram in AFK mode
- `~/.claude/hooks/_common.py` - Shared utilities: daemon communication, session keys, response polling
- `~/.claude/settings.json` - Hook configuration (Stop, Notification, PermissionRequest, PreToolUse)
- `~/.claude-voice/.tts.sock` - Unix socket for hook-to-daemon TTS communication (runtime)
- Kokoro TTS model cached at `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/`

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- Kokoro TTS model (auto-downloaded via Hugging Face on first use, ~360MB)
