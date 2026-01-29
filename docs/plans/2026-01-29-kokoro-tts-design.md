# Replace Piper TTS with Kokoro via mlx-audio

## Overview

Replace the Piper TTS binary with Kokoro-82M via the mlx-audio Python library, and move TTS responsibility from the Claude Code hook into the daemon process. This gives higher quality speech, Apple Silicon optimization, and near-instant generation after first model load.

## Key Decisions

- **Integration**: mlx-audio (`mlx-community/Kokoro-82M-bf16`) — Apple Silicon optimized via MLX framework
- **Architecture**: TTS moves into the daemon process (model stays warm in memory)
- **Hook-to-daemon communication**: Unix domain socket at `~/.claude-voice/.tts.sock`
- **Piper**: Fully removed, no fallback
- **Model download**: Automatic via Hugging Face on first use

## Architecture

### Current flow

```
Claude responds -> Hook runs -> Hook loads Piper binary -> Piper writes WAV -> afplay plays it
```

### New flow

```
Claude responds -> Hook runs -> Hook sends text over Unix socket -> Daemon generates audio via Kokoro -> Daemon plays audio via afplay
```

The daemon gains two new responsibilities:

1. **TTS engine** -- Loads the Kokoro model lazily on first TTS request, generates audio on demand
2. **Socket server** -- Background thread listens on `~/.claude-voice/.tts.sock` for text from the hook

The hook becomes a thin client: it still extracts and cleans the assistant message from the transcript, but sends the cleaned text over the socket instead of calling Piper.

## Daemon Changes

### New file: `daemon/tts.py`

Wraps mlx-audio's Kokoro model:
- Loads `mlx-community/Kokoro-82M-bf16` lazily on first request
- Exposes a `speak(text, voice, speed, lang_code)` method
- Generates audio as numpy array at 24kHz
- Writes to temp WAV file, plays via `afplay`
- Tracks the `afplay` subprocess PID for interruption

### Modified: `daemon/main.py`

- Adds a background thread running the Unix socket server
- On connection, reads JSON `{"text": "...", "voice": "af_heart", "speed": 1.0}`
- Passes to TTS engine
- Runs alongside the existing hotkey listener
- On shutdown: removes socket file, cleans up model

### Interruption handling

"Stop speaking" still kills `afplay` processes. Kokoro generation is fast enough (~0.1-0.3s) that we don't need to interrupt mid-generation; killing playback is sufficient.

### Model loading

Lazy load on first TTS request. The daemon starts quickly even if you're only using voice input. Model stays in memory after first load.

## Hook Changes

`hooks/speak-response.py` keeps:
- Reading hook input from stdin
- Extracting last assistant message from transcript
- Cleaning text for speech (code blocks, markdown, etc.)
- Checking `.silent` flag and config `enabled` setting

The `speak()` function changes to a socket client:
- Connect to `~/.claude-voice/.tts.sock`
- Send JSON with text, voice, speed
- Close connection
- On `ConnectionRefusedError`: silent fail (daemon not running)

Removed: `PIPER_BIN`, `MODELS_DIR` constants, Piper subprocess calls, temp file management.

## Config Changes

`SpeechConfig` in `daemon/config.py`:

```python
@dataclass
class SpeechConfig:
    enabled: bool = True
    voice: str = "af_heart"        # Kokoro voice ID
    speed: float = 1.0
    lang_code: str = "a"           # Kokoro language code
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True
```

- `voice` default: `af_heart` (American female, warmest rated)
- `lang_code`: `a` (American English), `b` (British), `j` (Japanese), `z` (Chinese), `e` (Spanish), `f` (French)
- Migration: unrecognized Piper voice names fall back to `af_heart` with a logged warning

## Install/Uninstall Changes

### `install.sh`

- Remove Piper binary download section
- `mlx-audio` added to `requirements.txt`, installed via existing pip step
- No pre-download of Kokoro model (auto-downloads from HF on first use)

### `uninstall.sh`

- Remove `~/.claude-voice/piper/` cleanup
- Remove `~/.claude-voice/models/piper/` cleanup
- Add `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/` to existing large-download cleanup prompt
- Add cleanup of `~/.claude-voice/.tts.sock`

### `requirements.txt`

- Add `mlx-audio`

## Files Changed

| File | Change |
|---|---|
| `daemon/tts.py` | New -- Kokoro TTS engine wrapper |
| `daemon/main.py` | Add socket server thread + TTS integration |
| `daemon/config.py` | Update SpeechConfig defaults, add lang_code |
| `hooks/speak-response.py` | Replace Piper speak() with socket client |
| `requirements.txt` | Add mlx-audio |
| `install.sh` | Remove Piper download section |
| `uninstall.sh` | Replace Piper cleanup with HF cache cleanup |
| `config.yaml.example` | Update voice examples to Kokoro format |

## Files Not Changed

- `daemon/audio.py`, `daemon/transcribe.py`, `daemon/hotkey.py`, `daemon/keyboard.py`, `daemon/cleanup.py`
- `claude-voice-daemon` launcher script
- Text cleaning logic in hook (stays as-is)