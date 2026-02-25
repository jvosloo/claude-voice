# Claude Voice Interface

Push-to-talk voice input for macOS. Transcribes speech and types it into any focused application.

When used with Claude Code, two voice output modes are available:
- **Notify mode** (default) — plays short status phrases ("Over to you", "Permission needed", "Please choose an option")
- **Narrate mode** — summarizes Claude's response and speaks it aloud via neural TTS

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

Also accepts "stop/start talking".

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
| `engine` | `kokoro` | TTS engine: `kokoro` (local, free) or `openai` (cloud) |
| `voice` | `af_heart` | Voice ID (see Available Voices below) |
| `speed` | `1.0` | Playback speed (1.0 = normal) |
| `lang_code` | `a` | Language code: `a` American, `b` British, `j` Japanese, `z` Chinese, `e` Spanish, `f` French (Kokoro only) |
| `mode` | `notify` | `notify` (status phrases) or `narrate` (summarized responses) |
| `narrate_style` | `brief` | Summarization style: `brief`, `conversational`, or `bullets` |
| `summarize_model` | `qwen2.5:3b` | Ollama model for narrate summarization |
| `enabled` | `true` | Enable/disable TTS output |
| `max_chars` | `null` | Limit spoken output length (`null` = unlimited) |
| `skip_code_blocks` | `true` | Don't speak code blocks |
| `skip_tool_results` | `true` | Don't speak tool result output |
| `notify_phrases` | *(defaults)* | Custom phrase overrides per category (done, permission, question) |
| `hotkey` | `left_alt+v` | Combo hotkey to toggle voice on/off (`null` to disable) |
| `openai_api_key` | `""` | OpenAI API key (or set `OPENAI_API_KEY` env var) |
| `openai_model` | `tts-1` | OpenAI model: `tts-1` (fast) or `tts-1-hd` (higher quality) |

### Transcription Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `backend` | `mlx` | `mlx` (fast on Apple Silicon) or `faster-whisper` (CPU) |
| `model` | `large-v3-turbo` | Whisper model (see table below) |
| `language` | `en` | Default language code |
| `extra_languages` | `[]` | Additional languages to cycle through (e.g. `["af", "de"]`) |
| `device` | `cpu` | Compute device for faster-whisper: `cpu` or `cuda` |
| `word_replacements` | `{}` | Fix consistently misheard words (see below) |
| `language_backends` | `{}` | Per-language cloud backend overrides (see below) |

**Available models:**

| Model | Size | Speed | Accuracy | Notes |
|-------|------|-------|----------|-------|
| `tiny.en` | ~40MB | Fastest | Basic | Good for quick tests |
| `base.en` | ~150MB | Fast | Good | Balanced |
| `small.en` | ~500MB | Medium | Better | English only |
| `medium.en` | ~1.5GB | Slower | Great | English only, high accuracy |
| `large-v3-turbo` | ~1.6GB | Fast | Near-best | **Default**, multilingual, recommended |
| `large-v3` | ~3GB | Slowest | Best | Multilingual, highest accuracy |

**Tip:** With MLX backend on Apple Silicon, even `large-v3` runs fast. `large-v3-turbo` is 6x faster with nearly identical accuracy.

**Note:** The `.en` models (e.g. `base.en`) only support English. To use `extra_languages`, you need a multilingual model like `large-v3-turbo` or `large-v3`.

### Word Replacements

Fix words that Whisper consistently gets wrong. Replacements are case-insensitive and match whole words only (so "taste" won't match "aftertaste"). Multi-word phrases are supported.

```yaml
transcription:
  word_replacements:
    "clawd": "Claude"              # included by default
    "clothes code": "Claude Code"
```

Replacements are applied immediately after transcription, before any LLM cleanup. Changes take effect on the next recording after `reload_config`.

### Cloud Transcription Backends

Route specific languages to a cloud API while keeping English on free local Whisper. Useful when Whisper doesn't support a language well.

```yaml
transcription:
  language_backends:
    af:
      backend: "openai"              # Reuses your existing speech.openai_api_key
      # model: "gpt-4o-transcribe"   # or "gpt-4o-mini-transcribe" (cheaper)
```

**Available backends:**

| Backend | Setup | Pricing |
|---------|-------|---------|
| `openai` | Uses existing `speech.openai_api_key` — no extra setup | $0.006/min (gpt-4o-transcribe) or $0.003/min (mini) |
| `google` | Requires service account JSON + `pip install google-cloud-speech` | $0.024/min, 60 min/month free tier |

Languages not listed in `language_backends` use the local Whisper model (free). The config hot-reloads without a daemon restart.

### Input Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `hotkey` | `right_alt` | Key to hold for recording |
| `language_hotkey` | `null` | Key to cycle transcription languages (e.g. `right_cmd`) |
| `auto_submit` | `false` | Press Enter automatically after transcription |
| `min_audio_length` | `0.5` | Ignore recordings shorter than this (seconds) |
| `typing_delay` | `0` | Delay between keystrokes (seconds, e.g. `0.005` for a slight delay) |

**Available hotkeys:** `right_alt`, `left_alt`, `right_cmd`, `left_cmd`, `right_ctrl`, `left_ctrl`, `right_shift`, `caps_lock`, `f18`, `f19`

### Audio Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `input_device` | `null` | Microphone device (`null` = system default) |
| `sample_rate` | `16000` | Sample rate in Hz (Whisper expects 16kHz) |

---

## Available Voices

### Kokoro (Local)

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

### OpenAI (Cloud)

Set `engine: "openai"` to use OpenAI's TTS API. Requires an API key.

**Available voices:** `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`

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
├── speak-response.py            # TTS hook: sends response text to daemon
├── permission-request.py        # Permission rules check; returns allow/ask
├── notify-permission.py         # Permission notification sound
├── handle-ask-user.py           # Plays "question" phrase for AskUserQuestion
└── _common.py                   # Shared utilities: daemon communication, session keys
```

---

## Components

### Voice Input (Daemon)
- `~/.claude-voice/daemon/` - Python modules
- `~/.claude-voice/claude-voice-daemon` - Launch script
- `~/.claude-voice/config.yaml` - Configuration file
- `~/.claude-voice/logs/` - Installation and daemon logs

### Voice Output (Hooks + Daemon)
- `~/.claude/hooks/speak-response.py` - Stop hook: sends response text to daemon for TTS
- `~/.claude/hooks/notify-permission.py` - Notification hook: plays "permission needed" audio cue
- `~/.claude/hooks/permission-request.py` - PermissionRequest hook: checks stored rules, returns allow/ask decisions
- `~/.claude/hooks/handle-ask-user.py` - PreToolUse hook: plays "question" phrase for AskUserQuestion
- `~/.claude/hooks/_common.py` - Shared utilities: daemon communication, session keys, permission rules
- `~/.claude/settings.json` - Hook configuration (Stop, Notification, PermissionRequest, PreToolUse)
- `~/.claude-voice/.tts.sock` - Unix socket for hook-to-daemon TTS communication (runtime)
- Kokoro TTS model cached at `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/`

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- Kokoro TTS model (auto-downloaded via Hugging Face on first use, ~360MB)
