# Kokoro TTS Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Piper TTS with Kokoro via mlx-audio, moving TTS into the daemon process with a Unix socket interface for the hook.

**Architecture:** The daemon loads Kokoro lazily and exposes a socket server. The hook sends cleaned text over the socket. Piper is fully removed.

**Tech Stack:** Python, mlx-audio, Kokoro-82M-bf16, Unix domain sockets

**Design doc:** `docs/plans/2026-01-29-kokoro-tts-design.md`

---

### Task 1: Update dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Update requirements.txt**

Replace the TTS section. Change:

```
# TTS
piper-tts>=1.2.0
```

To:

```
# TTS (Kokoro via mlx-audio, Apple Silicon optimized)
mlx-audio
```

**Step 2: Verify the dependency installs**

Run:
```bash
~/.claude-voice/venv/bin/pip install mlx-audio
```
Expected: installs successfully (pulls mlx, huggingface-hub, soundfile, etc.)

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "Replace piper-tts with mlx-audio in requirements"
```

---

### Task 2: Update SpeechConfig

**Files:**
- Modify: `daemon/config.py:28-35`

**Step 1: Update the SpeechConfig dataclass**

Replace lines 28-35 of `daemon/config.py`:

```python
@dataclass
class SpeechConfig:
    enabled: bool = True
    voice: str = "en_GB-alan-medium"
    speed: float = 1.0
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True
```

With:

```python
@dataclass
class SpeechConfig:
    enabled: bool = True
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True
```

Changes: `voice` default from `en_GB-alan-medium` to `af_heart`, added `lang_code` field with default `a` (American English).

**Step 2: Verify config loads**

Run:
```bash
~/.claude-voice/venv/bin/python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude-voice')
from daemon.config import load_config
c = load_config()
print(f'voice={c.speech.voice}, lang_code={c.speech.lang_code}')
"
```
Expected: prints voice and lang_code values (from config.yaml or defaults).

**Step 3: Commit**

```bash
git add daemon/config.py
git commit -m "Update SpeechConfig for Kokoro voice format"
```

---

### Task 3: Create TTS engine

**Files:**
- Create: `daemon/tts.py`

**Step 1: Create `daemon/tts.py`**

```python
"""Kokoro TTS engine via mlx-audio."""

import os
import subprocess
import tempfile
import threading

KOKORO_MODEL = "mlx-community/Kokoro-82M-bf16"
SAMPLE_RATE = 24000


class TTSEngine:
    """Kokoro text-to-speech engine. Lazy-loads model on first use."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._playback_proc = None

    def _ensure_model(self):
        """Load the Kokoro model if not already loaded."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            print("Loading Kokoro TTS model (first time may download ~160MB)...")
            from mlx_audio.tts.utils import load_model
            self._model = load_model(KOKORO_MODEL)
            print("Kokoro TTS model loaded.")

    def speak(self, text: str, voice: str = "af_heart", speed: float = 1.0, lang_code: str = "a") -> None:
        """Generate speech and play it.

        Args:
            text: Text to speak.
            voice: Kokoro voice ID (e.g., af_heart, bm_daniel).
            speed: Playback speed multiplier.
            lang_code: Language code (a=American, b=British, j=Japanese, etc.).
        """
        if not text:
            return

        self._ensure_model()

        try:
            import soundfile as sf

            # Generate audio chunks and concatenate
            audio_chunks = []
            for result in self._model.generate(text, voice=voice, speed=speed, lang_code=lang_code):
                audio_chunks.append(result.audio)

            if not audio_chunks:
                return

            import numpy as np
            # mlx arrays need to be converted to numpy for soundfile
            import mlx.core as mx
            audio = mx.concatenate(audio_chunks)
            audio_np = np.array(audio, dtype=np.float32)

            # Write to temp WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name

            sf.write(tmp_path, audio_np, SAMPLE_RATE)

            # Play audio
            self._playback_proc = subprocess.Popen(['afplay', tmp_path])
            self._playback_proc.wait()
            self._playback_proc = None

            # Clean up
            os.unlink(tmp_path)

        except Exception as e:
            print(f"TTS error: {e}")

    def stop_playback(self):
        """Stop current audio playback."""
        proc = self._playback_proc
        if proc is not None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            self._playback_proc = None
```

**Step 2: Verify module imports**

Run:
```bash
~/.claude-voice/venv/bin/python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude-voice')
from daemon.tts import TTSEngine
engine = TTSEngine()
print('TTSEngine created (model not yet loaded)')
"
```
Expected: prints message without loading model (lazy load).

**Step 3: Test speech generation**

Run:
```bash
~/.claude-voice/venv/bin/python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude-voice')
from daemon.tts import TTSEngine
engine = TTSEngine()
engine.speak('Hello, this is Kokoro.')
"
```
Expected: downloads model on first run, then speaks "Hello, this is Kokoro." audibly.

**Step 4: Commit**

```bash
git add daemon/tts.py
git commit -m "Add Kokoro TTS engine wrapper using mlx-audio"
```

---

### Task 4: Add socket server to daemon

**Files:**
- Modify: `daemon/main.py`

This is the largest task. The daemon needs a socket server thread and TTS integration.

**Step 1: Add imports to `daemon/main.py`**

Add after the existing imports (after line 8 `import numpy as np`):

```python
import json
import socket
```

**Step 2: Add import of TTSEngine**

Add after the existing daemon imports (after line 32 `from daemon.cleanup import TranscriptionCleaner`):

```python
from daemon.tts import TTSEngine
```

**Step 3: Add TTS_SOCK_PATH constant**

Add after the `SILENT_FLAG` constant (after line 34):

```python
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
```

**Step 4: Add socket server method to VoiceDaemon**

Add the following method to the `VoiceDaemon` class, after the `_handle_voice_command` method (after line 128):

```python
    def _run_tts_server(self) -> None:
        """Run Unix socket server for TTS requests from the hook."""
        # Clean up stale socket file
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(TTS_SOCK_PATH)
        server.listen(1)
        server.settimeout(1.0)  # Allow periodic shutdown checks

        self._tts_server = server

        while not self._shutting_down:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                conn.close()

                request = json.loads(data.decode())
                text = request.get("text", "")
                voice = request.get("voice", self.config.speech.voice)
                speed = request.get("speed", self.config.speech.speed)
                lang_code = request.get("lang_code", self.config.speech.lang_code)

                if text:
                    self.tts_engine.speak(text, voice=voice, speed=speed, lang_code=lang_code)
            except Exception as e:
                print(f"TTS server error: {e}")

        server.close()
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)
```

**Step 5: Update `__init__` to add TTS engine and shutdown flag**

Add to the `__init__` method, after the cleaner setup (after line 95):

```python
        self.tts_engine = TTSEngine()
        self._tts_server = None
        self._shutting_down = False
```

**Step 6: Update `_on_hotkey_press` to use TTS engine for interruption**

Replace the `pkill` call in `_on_hotkey_press` (lines 105-108):

```python
        # Stop any TTS playback asynchronously
        threading.Thread(
            target=lambda: subprocess.run(['pkill', '-9', 'afplay'], stderr=subprocess.DEVNULL),
            daemon=True
        ).start()
```

With:

```python
        # Stop any TTS playback
        self.tts_engine.stop_playback()
```

**Step 7: Start socket server thread in `run()`**

Add before `self.hotkey_listener.start()` (before line 210):

```python
        # Start TTS socket server
        tts_thread = threading.Thread(target=self._run_tts_server, daemon=True)
        tts_thread.start()
        print(f"TTS server listening on {TTS_SOCK_PATH}")
```

**Step 8: Update `_shutdown` to clean up socket**

Add at the beginning of `_shutdown()`, after the print statement (after line 168):

```python
        self._shutting_down = True
        if self._tts_server:
            try:
                self._tts_server.close()
            except Exception:
                pass
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)
```

**Step 9: Verify daemon starts with TTS server**

Run:
```bash
~/.claude-voice/venv/bin/python3 -m daemon.main
```
Expected: daemon starts, prints "TTS server listening on ~/.claude-voice/.tts.sock", hotkey listener works as before. Ctrl+C to stop.

**Step 10: Test socket communication**

With daemon running in one terminal, run in another:
```bash
~/.claude-voice/venv/bin/python3 -c "
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('$HOME/.claude-voice/.tts.sock')
s.sendall(json.dumps({'text': 'Socket test successful.'}).encode())
s.close()
print('Sent TTS request')
"
```
Expected: daemon speaks "Socket test successful." audibly.

**Step 11: Commit**

```bash
git add daemon/main.py
git commit -m "Add TTS socket server and Kokoro integration to daemon"
```

---

### Task 5: Update hook to use socket client

**Files:**
- Modify: `hooks/speak-response.py`

**Step 1: Replace Piper constants and speak function**

Remove these constants (lines 14-16):
```python
PIPER_BIN = os.path.expanduser("~/.claude-voice/piper/piper")
MODELS_DIR = os.path.expanduser("~/.claude-voice/models/piper")
```

Replace with:
```python
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
```

Add `socket` to the imports (after line 9 `import re`):
```python
import socket
```

Remove the `subprocess` and `tempfile` imports (lines 9-11) since they're no longer needed.

**Step 2: Replace the speak() function**

Replace the entire `speak()` function (lines 84-124) with:

```python
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
```

**Step 3: Verify the hook end-to-end**

With daemon running, simulate a hook invocation:
```bash
echo '{"transcript_path": "/dev/null"}' | ~/.claude-voice/venv/bin/python3 hooks/speak-response.py
```
Expected: exits silently (no transcript to read). No errors.

**Step 4: Commit**

```bash
git add hooks/speak-response.py
git commit -m "Replace Piper with socket client in TTS hook"
```

---

### Task 6: Update install.sh

**Files:**
- Modify: `install.sh`

**Step 1: Remove Piper directory from mkdir**

Change line 77:
```bash
mkdir -p "$INSTALL_DIR"/{daemon,models/whisper,models/piper,logs}
```
To:
```bash
mkdir -p "$INSTALL_DIR"/{daemon,models/whisper,logs}
```

**Step 2: Add mlx-audio to pip install**

Change line 121:
```bash
pip install --upgrade pynput sounddevice pyyaml -q
```
To:
```bash
pip install --upgrade pynput sounddevice pyyaml mlx-audio -q
```

**Step 3: Remove entire Piper download section**

Delete lines 171-207 (the Piper binary download and voice model download sections):
```bash
# Download Piper TTS binary (uses native binary instead of Python library for macOS compatibility)
...
fi
```

All the way through:
```bash
# Download default voice model
...
fi
```

**Step 4: Verify install.sh is valid bash**

Run:
```bash
bash -n install.sh
```
Expected: exits 0, no syntax errors.

**Step 5: Commit**

```bash
git add install.sh
git commit -m "Remove Piper from installer, add mlx-audio dependency"
```

---

### Task 7: Update uninstall.sh

**Files:**
- Modify: `uninstall.sh`

**Step 1: Update the models cleanup section**

Replace lines 112-124 (the models/piper section):

```bash
# Handle downloaded models
MODELS_SIZE=$(du -sh "$INSTALL_DIR/models" 2>/dev/null | cut -f1)
if [ -d "$INSTALL_DIR/models" ] && [ -n "$(ls -A "$INSTALL_DIR/models/piper" 2>/dev/null)" ]; then
    echo ""
    read -p "Delete downloaded voice models? ($MODELS_SIZE) [y/N]: " DEL_MODELS
    if [[ "$DEL_MODELS" =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR/models"
        echo "Deleted models"
    else
        echo "Keeping models at $INSTALL_DIR/models/"
        KEEP_MODELS=true
    fi
fi
```

With:

```bash
# Handle downloaded Kokoro TTS model (in Hugging Face cache)
KOKORO_CACHE="$HOME/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16"
if [ -d "$KOKORO_CACHE" ]; then
    KOKORO_SIZE=$(du -sh "$KOKORO_CACHE" 2>/dev/null | cut -f1)
    echo ""
    read -p "Delete downloaded Kokoro TTS model? ($KOKORO_SIZE) [y/N]: " DEL_KOKORO
    if [[ "$DEL_KOKORO" =~ ^[Yy]$ ]]; then
        rm -rf "$KOKORO_CACHE"
        echo "Deleted Kokoro model cache"
    else
        echo "Keeping Kokoro model at $KOKORO_CACHE"
    fi
fi
```

**Step 2: Remove piper from the cleanup section**

In the selective cleanup section (lines 127-148), remove line 134:
```bash
    rm -rf "$INSTALL_DIR/piper"
```

And update the `KEEP_MODELS` references: remove line 144:
```bash
    [ "$KEEP_MODELS" != true ] && rm -rf "$INSTALL_DIR/models"
```

And remove `$KEEP_MODELS` from the conditional on line 128:
```bash
if [ "$KEEP_CONFIG" = true ] || [ "$KEEP_MODELS" = true ]; then
```
Change to:
```bash
if [ "$KEEP_CONFIG" = true ]; then
```

**Step 3: Add socket file cleanup**

Add after the `.silent` cleanup (after `rm -f "$INSTALL_DIR/.silent"`):
```bash
    rm -f "$INSTALL_DIR/.tts.sock"
```

Also add this line in the full removal path, before `rm -rf "$INSTALL_DIR"` (as a safety measure in case it lingers):
```bash
    rm -f "$INSTALL_DIR/.tts.sock"
```

**Step 4: Verify uninstall.sh is valid bash**

Run:
```bash
bash -n uninstall.sh
```
Expected: exits 0, no syntax errors.

**Step 5: Commit**

```bash
git add uninstall.sh
git commit -m "Replace Piper cleanup with Kokoro cache cleanup in uninstaller"
```

---

### Task 8: Update config.yaml.example

**Files:**
- Modify: `config.yaml.example`

**Step 1: Replace speech section**

Replace lines 17-23:

```yaml
speech:
  enabled: true                # Set to false to disable TTS output
  voice: "en_GB-alan-medium"   # Piper voice model
  speed: 1.3                   # Playback speed
  max_chars: null              # Limit spoken output (null = unlimited)
  skip_code_blocks: true       # Don't speak code blocks
  skip_tool_results: true      # Don't speak tool output
```

With:

```yaml
speech:
  enabled: true                # Set to false to disable TTS output
  voice: "af_heart"            # Kokoro voice ID (see README for full list)
  speed: 1.0                   # Playback speed (1.0 = normal)
  lang_code: "a"               # Language: a=American, b=British, j=Japanese, z=Chinese, e=Spanish, f=French
  max_chars: null              # Limit spoken output (null = unlimited)
  skip_code_blocks: true       # Don't speak code blocks
  skip_tool_results: true      # Don't speak tool output
```

**Step 2: Commit**

```bash
git add config.yaml.example
git commit -m "Update config example for Kokoro voice format"
```

---

### Task 9: Update README.md

**Files:**
- Modify: `README.md`

**Step 1: Update installation description**

Replace line 23:
```
- Download Piper TTS binary and default voice model
```
With:
```
- Install Kokoro TTS (via mlx-audio, Apple Silicon optimized)
```

**Step 2: Update speech settings table**

Replace lines 126-133 (Speech Settings table):

```markdown
| Setting | Default | Description |
|---------|---------|-------------|
| `voice` | `en_GB-alan-medium` | Piper voice model |
| `speed` | `1.3` | Playback speed (1.0 = normal) |
| `enabled` | `true` | Enable/disable TTS output |
| `max_chars` | `null` | Limit spoken output length (`null` = unlimited) |
| `skip_code_blocks` | `true` | Don't speak code blocks |
```

With:

```markdown
| Setting | Default | Description |
|---------|---------|-------------|
| `voice` | `af_heart` | Kokoro voice ID (see Available Voices below) |
| `speed` | `1.0` | Playback speed (1.0 = normal) |
| `lang_code` | `a` | Language code: `a` American, `b` British, `j` Japanese, `z` Chinese, `e` Spanish, `f` French |
| `enabled` | `true` | Enable/disable TTS output |
| `max_chars` | `null` | Limit spoken output length (`null` = unlimited) |
| `skip_code_blocks` | `true` | Don't speak code blocks |
```

**Step 3: Replace Available Voices section**

Replace lines 177-188:

```markdown
## Available Voices

Downloaded voices are stored in `~/.claude-voice/models/piper/`.

| Voice | Style |
|-------|-------|
| `en_GB-alan-medium` | British male |
| `en_US-ryan-high` | American male (high quality) |
| `en_US-ryan-medium` | American male |
| `en_US-amy-medium` | American female |

Browse more at: https://huggingface.co/rhasspy/piper-voices/tree/main/en
```

With:

```markdown
## Available Voices

Kokoro TTS provides 54 voice presets. The model downloads automatically on first use (~160MB).

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
```

**Step 4: Update Components section**

Replace lines 200-207:

```markdown
### Voice Output (Hook)
- `~/.claude-voice/piper/` - Piper TTS binary
- `~/.claude/hooks/speak-response.py` - TTS hook
- `~/.claude/settings.json` - Claude Code Stop hook config

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- `~/.claude-voice/models/piper/` - Piper TTS voice models
```

With:

```markdown
### Voice Output (Hook + Daemon)
- `~/.claude/hooks/speak-response.py` - Hook sends text to daemon
- `~/.claude/settings.json` - Claude Code Stop hook config
- Kokoro TTS model cached at `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/`

### Models
- `~/.claude-voice/models/whisper/` - Whisper speech recognition models (auto-downloaded)
- Kokoro TTS model (auto-downloaded via Hugging Face on first use, ~160MB)
```

**Step 5: Commit**

```bash
git add README.md
git commit -m "Update README for Kokoro TTS"
```

---

### Task 10: End-to-end test

**No files changed — manual verification.**

**Step 1: Install updated dependencies**

Run:
```bash
cd ~/.claude-voice && source venv/bin/activate && pip install mlx-audio -q
```

**Step 2: Copy updated files to install dir**

Run from the repo root:
```bash
cp daemon/*.py ~/.claude-voice/daemon/
cp hooks/speak-response.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/speak-response.py
```

**Step 3: Start daemon and verify TTS**

Run:
```bash
~/.claude-voice/claude-voice-daemon foreground
```

Expected output includes:
- "TTS server listening on ~/.claude-voice/.tts.sock"
- "Ready! Hold the hotkey and speak."

**Step 4: Test socket TTS from another terminal**

```bash
~/.claude-voice/venv/bin/python3 -c "
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('$HOME/.claude-voice/.tts.sock')
s.sendall(json.dumps({'text': 'End to end test. Kokoro is working.'}).encode())
s.close()
"
```
Expected: spoken audio plays.

**Step 5: Test with Claude Code**

Start Claude Code in a separate terminal and send a message. On response, the hook should send text to the daemon and you should hear Kokoro speak the response.

**Step 6: Test interruption**

While Claude is speaking, press the hotkey. Playback should stop immediately.

**Step 7: Test voice commands**

Hold hotkey and say "stop speaking" — voice output should disable.
Hold hotkey and say "start speaking" — voice output should re-enable.

**Step 8: Commit all together if any fixes were needed**

If any fixes were applied during testing, commit them:
```bash
git add -A
git commit -m "Fix issues found during end-to-end testing"
```