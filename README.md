# Claude Voice Interface

Push-to-talk voice input for macOS. Transcribes speech and types it into any focused application.

When used with Claude Code, two voice output modes are available:
- **Notify mode** (default) — plays short status phrases ("Ready for input", "Something failed", "Permission needed")
- **Narrate mode** — reads Claude's full response aloud via neural TTS

**Platform:** macOS (uses `afplay` for audio playback)

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

### Voice Commands

Say these phrases to toggle voice output without leaving Claude:

| Say this | Effect |
|----------|--------|
| **"Stop speaking"** | Disable voice output |
| **"Start speaking"** | Enable voice output |
| **"Switch to notify mode"** | Short status phrases |
| **"Switch to narrate mode"** | Read full responses aloud |

Also accepts "stop/start talking" and "notification/narration mode".

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
| `notify_phrases` | *(defaults)* | Custom phrase overrides per category (permission, done, error) |

### Transcription Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `backend` | `mlx` | `mlx` (fast on Apple Silicon) or `faster-whisper` (CPU) |
| `model` | `large-v3` | Whisper model (see table below) |
| `language` | `en` | Default language code |
| `extra_languages` | `[]` | Additional languages to cycle through (e.g. `["af", "de"]`) |
| `device` | `cpu` | Compute device for faster-whisper: `cpu` or `cuda` |

**Available models:**

| Model | Size | Speed | Accuracy | Notes |
|-------|------|-------|----------|-------|
| `tiny.en` | ~40MB | Fastest | Basic | Good for quick tests |
| `base.en` | ~150MB | Fast | Good | Balanced |
| `small.en` | ~500MB | Medium | Better | Recommended |
| `medium.en` | ~1.5GB | Slower | Great | High accuracy |
| `large-v3` | ~3GB | Slowest | Best | MLX recommended for this |

**Tip:** With MLX backend on Apple Silicon, even `large-v3` runs fast.

**Note:** The `.en` models (e.g. `base.en`) only support English. To use `extra_languages`, you need a multilingual model like `large-v3`.

### Input Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `hotkey` | `right_alt` | Key to hold for recording |
| `language_hotkey` | `null` | Key to cycle transcription languages (e.g. `right_cmd`) |
| `auto_submit` | `false` | Press Enter automatically after transcription |
| `min_audio_length` | `0.5` | Ignore recordings shorter than this (seconds) |
| `typing_delay` | `0.01` | Delay between keystrokes (seconds) |
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

## Components

### Voice Input (Daemon)
- `~/.claude-voice/daemon/` - Python modules
- `~/.claude-voice/claude-voice-daemon` - Launch script
- `~/.claude-voice/config.yaml` - Configuration file
- `~/.claude-voice/logs/` - Installation and daemon logs

### Voice Output (Hooks + Daemon)
- `~/.claude/hooks/speak-response.py` - Stop hook: sends response text to daemon
- `~/.claude/hooks/notify-permission.py` - Notification hook: signals permission prompts
- `~/.claude/hooks/notify-error.py` - PostToolUseFailure hook: signals Bash errors
- `~/.claude/settings.json` - Hook configuration (Stop, Notification, PostToolUseFailure)
- `~/.claude-voice/.tts.sock` - Unix socket for hook-to-daemon TTS communication (runtime)
- Kokoro TTS model cached at `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/`

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- Kokoro TTS model (auto-downloaded via Hugging Face on first use, ~360MB)
