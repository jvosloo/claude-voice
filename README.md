# Claude Voice Interface

Push-to-talk voice input for macOS. Transcribes speech and types it into any focused application.

When used with Claude Code, responses are spoken aloud via neural TTS — enabling two-way voice conversation.

**Platform:** macOS (uses `afplay` for audio playback)

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
- Download Piper TTS binary and default voice model
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

### Voice Input (Works Anywhere)

1. Hold **Right Alt** and speak
2. Release to transcribe — text is typed into the focused input
3. Works with any application: browsers, text editors, terminals, etc.

### With Claude Code (Two-Way Voice)

When the focused application is Claude Code:
- Your transcribed speech is sent to Claude
- Claude's response is spoken aloud via TTS
- **Press the hotkey to interrupt** Claude while speaking

### Voice Commands

Say these phrases to toggle voice output without leaving Claude:

| Say this | Effect |
|----------|--------|
| **"Stop speaking"** | Disable voice output |
| **"Start speaking"** | Enable voice output |

Also accepts "stop talking" / "start talking".

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
| `voice` | `en_GB-alan-medium` | Piper voice model |
| `speed` | `1.3` | Playback speed (1.0 = normal) |
| `enabled` | `true` | Enable/disable TTS output |
| `max_chars` | `null` | Limit spoken output length (`null` = unlimited) |
| `skip_code_blocks` | `true` | Don't speak code blocks |

### Transcription Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `backend` | `mlx` | `mlx` (fast on Apple Silicon) or `faster-whisper` (CPU) |
| `model` | `large-v3` | Whisper model (see table below) |
| `language` | `en` | Language code |
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

### Input Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `hotkey` | `right_alt` | Key to hold for recording |
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

Downloaded voices are stored in `~/.claude-voice/models/piper/`.

| Voice | Style |
|-------|-------|
| `en_GB-alan-medium` | British male |
| `en_US-ryan-high` | American male (high quality) |
| `en_US-ryan-medium` | American male |
| `en_US-amy-medium` | American female |

Browse more at: https://huggingface.co/rhasspy/piper-voices/tree/main/en

---

## Components

### Voice Input (Daemon)
- `~/.claude-voice/daemon/` - Python modules
- `~/.claude-voice/claude-voice-daemon` - Launch script
- `~/.claude-voice/config.yaml` - Configuration file
- `~/.claude-voice/logs/` - Installation and daemon logs

### Voice Output (Hook)
- `~/.claude-voice/piper/` - Piper TTS binary
- `~/.claude/hooks/speak-response.py` - TTS hook
- `~/.claude/settings.json` - Claude Code Stop hook config

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- `~/.claude-voice/models/piper/` - Piper TTS voice models
