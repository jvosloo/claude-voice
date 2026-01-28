# Claude Voice Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Two-way voice conversation with Claude Code — speak via push-to-talk, hear responses via neural TTS.

**Architecture:** A Python daemon handles voice input (hotkey → record → Whisper → type). A Claude Code `Stop` hook handles voice output (extract last response → Piper TTS → play audio). Both components run locally with no cloud dependencies.

**Tech Stack:** Python 3.9+, pynput, sounddevice, faster-whisper, Piper TTS, macOS arm64

---

## Task 1: Create Directory Structure and Configuration

**Files:**
- Create: `~/.claude-voice/config.yaml`
- Create: `~/.claude-voice/daemon/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p ~/.claude-voice/{daemon,models/whisper,models/piper,logs}
touch ~/.claude-voice/daemon/__init__.py
```

**Step 2: Create default configuration file**

Create `~/.claude-voice/config.yaml`:

```yaml
# Claude Voice Interface Configuration

input:
  hotkey: "right_alt"          # Key to hold for recording
  auto_submit: true            # Press Enter after transcription
  min_audio_length: 0.5        # Ignore recordings shorter than this (seconds)
  typing_delay: 0.01           # Delay between keystrokes (seconds)

transcription:
  model: "base.en"             # tiny.en, base.en, small.en, medium.en
  language: "en"
  device: "cpu"                # cpu or cuda

speech:
  voice: "en_US-amy-medium"    # Piper voice model
  speed: 1.0                   # Playback speed
  max_chars: null              # Limit spoken output (null = unlimited)
  skip_code_blocks: true       # Don't speak code blocks
  skip_tool_results: true      # Don't speak tool output

audio:
  input_device: null           # null = system default
  sample_rate: 16000           # Whisper expects 16kHz
```

**Step 3: Verify structure**

```bash
ls -la ~/.claude-voice/
```

Expected: Shows config.yaml, daemon/, models/, logs/

**Step 4: Commit**

```bash
# This is user home directory, not in git - no commit needed
```

---

## Task 2: Create Python Virtual Environment and Install Dependencies

**Files:**
- Create: `~/.claude-voice/venv/` (virtual environment)
- Create: `~/.claude-voice/requirements.txt`

**Step 1: Create requirements file**

Create `~/.claude-voice/requirements.txt`:

```
pynput>=1.7.6
sounddevice>=0.4.6
numpy>=1.24.0
faster-whisper>=0.10.0
pyyaml>=6.0
```

**Step 2: Create virtual environment and install dependencies**

```bash
cd ~/.claude-voice
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Expected: All packages install successfully. faster-whisper will pull in ctranslate2.

**Step 3: Verify installation**

```bash
source ~/.claude-voice/venv/bin/activate
python -c "import pynput; import sounddevice; import faster_whisper; print('All imports OK')"
```

Expected: "All imports OK"

---

## Task 3: Download Whisper Model

**Files:**
- Download to: `~/.claude-voice/models/whisper/`

**Step 1: Download base.en model via faster-whisper**

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
from faster_whisper import WhisperModel
import os

model_dir = os.path.expanduser("~/.claude-voice/models/whisper")
print(f"Downloading base.en model to {model_dir}...")

# This downloads and caches the model
model = WhisperModel("base.en", device="cpu", download_root=model_dir)
print("Model downloaded successfully!")
EOF
```

Expected: Model downloads (~150MB), prints success message.

**Step 2: Verify model files exist**

```bash
ls ~/.claude-voice/models/whisper/
```

Expected: Shows model files (models--Systran--faster-whisper-base.en or similar)

---

## Task 4: Download and Install Piper TTS

**Files:**
- Download to: `~/.claude-voice/piper` (binary)
- Download to: `~/.claude-voice/models/piper/` (voice model)

**Step 1: Download Piper binary for macOS ARM64**

```bash
cd ~/.claude-voice
curl -L -o piper_macos_arm64.tar.gz \
  "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_aarch64.tar.gz"
tar -xzf piper_macos_arm64.tar.gz
rm piper_macos_arm64.tar.gz
chmod +x piper/piper
```

**Step 2: Verify Piper runs**

```bash
~/.claude-voice/piper/piper --help
```

Expected: Shows Piper help text.

**Step 3: Download voice model (en_US-amy-medium)**

```bash
cd ~/.claude-voice/models/piper
curl -L -o en_US-amy-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
curl -L -o en_US-amy-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
```

**Step 4: Test Piper TTS**

```bash
echo "Hello, I am Claude. How can I help you today?" | \
  ~/.claude-voice/piper/piper \
    --model ~/.claude-voice/models/piper/en_US-amy-medium.onnx \
    --output_file /tmp/test_voice.wav

afplay /tmp/test_voice.wav
```

Expected: You hear "Hello, I am Claude. How can I help you today?" spoken aloud.

---

## Task 5: Implement Configuration Loader

**Files:**
- Create: `~/.claude-voice/daemon/config.py`

**Step 1: Write the config loader module**

Create `~/.claude-voice/daemon/config.py`:

```python
"""Configuration loader for Claude Voice daemon."""

import os
import yaml
from dataclasses import dataclass
from typing import Optional

CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")

@dataclass
class InputConfig:
    hotkey: str = "right_alt"
    auto_submit: bool = True
    min_audio_length: float = 0.5
    typing_delay: float = 0.01

@dataclass
class TranscriptionConfig:
    model: str = "base.en"
    language: str = "en"
    device: str = "cpu"

@dataclass
class SpeechConfig:
    voice: str = "en_US-amy-medium"
    speed: float = 1.0
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True

@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    sample_rate: int = 16000

@dataclass
class Config:
    input: InputConfig
    transcription: TranscriptionConfig
    speech: SpeechConfig
    audio: AudioConfig

def load_config() -> Config:
    """Load configuration from YAML file, with defaults for missing values."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    return Config(
        input=InputConfig(**data.get('input', {})),
        transcription=TranscriptionConfig(**data.get('transcription', {})),
        speech=SpeechConfig(**data.get('speech', {})),
        audio=AudioConfig(**data.get('audio', {})),
    )
```

**Step 2: Test the config loader**

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
import sys
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))
import os
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.config import load_config

config = load_config()
print(f"Hotkey: {config.input.hotkey}")
print(f"Whisper model: {config.transcription.model}")
print(f"Voice: {config.speech.voice}")
print("Config loaded successfully!")
EOF
```

Expected: Prints config values, "Config loaded successfully!"

---

## Task 6: Implement Audio Recording Module

**Files:**
- Create: `~/.claude-voice/daemon/audio.py`

**Step 1: Write the audio recording module**

Create `~/.claude-voice/daemon/audio.py`:

```python
"""Audio recording functionality for Claude Voice daemon."""

import numpy as np
import sounddevice as sd
from typing import Optional
import threading

class AudioRecorder:
    """Records audio from microphone while activated."""

    def __init__(self, sample_rate: int = 16000, device: Optional[int] = None):
        self.sample_rate = sample_rate
        self.device = device
        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        """Called by sounddevice for each audio chunk."""
        if status:
            print(f"Audio status: {status}")
        if self._recording:
            with self._lock:
                self._audio_chunks.append(indata.copy())

    def start(self) -> None:
        """Start recording audio."""
        with self._lock:
            self._audio_chunks = []
            self._recording = True

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return audio as numpy array."""
        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if self._audio_chunks:
                audio = np.concatenate(self._audio_chunks, axis=0)
                return audio.flatten()
            return np.array([], dtype=np.float32)

    def get_duration(self, audio: np.ndarray) -> float:
        """Get duration of audio in seconds."""
        return len(audio) / self.sample_rate
```

**Step 2: Test audio recording**

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.audio import AudioRecorder
import time

recorder = AudioRecorder(sample_rate=16000)

print("Recording for 2 seconds... speak now!")
recorder.start()
time.sleep(2)
audio = recorder.stop()

duration = recorder.get_duration(audio)
print(f"Recorded {duration:.2f} seconds of audio")
print(f"Audio shape: {audio.shape}")
print("Audio recording works!")
EOF
```

Expected: Records 2 seconds, prints duration and shape, "Audio recording works!"

---

## Task 7: Implement Whisper Transcription Module

**Files:**
- Create: `~/.claude-voice/daemon/transcribe.py`

**Step 1: Write the transcription module**

Create `~/.claude-voice/daemon/transcribe.py`:

```python
"""Whisper transcription functionality for Claude Voice daemon."""

import os
import numpy as np
from faster_whisper import WhisperModel
from typing import Optional

class Transcriber:
    """Transcribes audio using Whisper."""

    def __init__(self, model_name: str = "base.en", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model: Optional[WhisperModel] = None
        self._model_dir = os.path.expanduser("~/.claude-voice/models/whisper")

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model."""
        if self._model is None:
            print(f"Loading Whisper model: {self.model_name}...")
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                download_root=self._model_dir,
            )
            print("Whisper model loaded.")
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data as float32 numpy array
            sample_rate: Sample rate (must be 16000 for Whisper)

        Returns:
            Transcribed text string
        """
        if len(audio) == 0:
            return ""

        model = self._ensure_model()

        # Whisper expects float32 audio normalized to [-1, 1]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Transcribe
        segments, info = model.transcribe(
            audio,
            language="en",
            vad_filter=True,  # Filter out non-speech
        )

        # Combine all segments
        text_parts = [segment.text.strip() for segment in segments]
        return " ".join(text_parts).strip()
```

**Step 2: Test transcription**

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.audio import AudioRecorder
from daemon.transcribe import Transcriber
import time

recorder = AudioRecorder(sample_rate=16000)
transcriber = Transcriber(model_name="base.en")

print("Recording for 3 seconds... say something!")
recorder.start()
time.sleep(3)
audio = recorder.stop()

print(f"Recorded {recorder.get_duration(audio):.2f}s, transcribing...")
text = transcriber.transcribe(audio)
print(f"Transcription: '{text}'")
EOF
```

Expected: Say something, see your words transcribed.

---

## Task 8: Implement Keyboard Simulation Module

**Files:**
- Create: `~/.claude-voice/daemon/keyboard.py`

**Step 1: Write the keyboard simulation module**

Create `~/.claude-voice/daemon/keyboard.py`:

```python
"""Keyboard simulation for Claude Voice daemon."""

import time
from pynput.keyboard import Controller, Key
from typing import Optional

class KeyboardSimulator:
    """Types text by simulating keyboard input."""

    def __init__(self, typing_delay: float = 0.01, auto_submit: bool = True):
        self.typing_delay = typing_delay
        self.auto_submit = auto_submit
        self._keyboard = Controller()

    def type_text(self, text: str) -> None:
        """Type text character by character.

        Args:
            text: The text to type
        """
        if not text:
            return

        for char in text:
            self._keyboard.type(char)
            if self.typing_delay > 0:
                time.sleep(self.typing_delay)

        if self.auto_submit:
            time.sleep(0.1)  # Small pause before Enter
            self._keyboard.press(Key.enter)
            self._keyboard.release(Key.enter)
```

**Step 2: Test keyboard simulation (manual)**

Open a text editor or terminal, then run:

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.keyboard import KeyboardSimulator
import time

kb = KeyboardSimulator(typing_delay=0.02, auto_submit=False)

print("Typing in 3 seconds... focus a text input!")
time.sleep(3)
kb.type_text("Hello from Claude Voice!")
print("Done!")
EOF
```

Expected: "Hello from Claude Voice!" appears in your focused text field.

---

## Task 9: Implement Hotkey Listener Module

**Files:**
- Create: `~/.claude-voice/daemon/hotkey.py`

**Step 1: Write the hotkey listener module**

Create `~/.claude-voice/daemon/hotkey.py`:

```python
"""Hotkey detection for Claude Voice daemon."""

from pynput import keyboard
from typing import Callable, Optional
import threading

# Map config names to pynput keys
KEY_MAP = {
    "right_alt": keyboard.Key.alt_r,
    "left_alt": keyboard.Key.alt_l,
    "right_cmd": keyboard.Key.cmd_r,
    "left_cmd": keyboard.Key.cmd_l,
    "right_ctrl": keyboard.Key.ctrl_r,
    "left_ctrl": keyboard.Key.ctrl_l,
    "right_shift": keyboard.Key.shift_r,
    "caps_lock": keyboard.Key.caps_lock,
    "f18": keyboard.Key.f18,
    "f19": keyboard.Key.f19,
}

class HotkeyListener:
    """Listens for push-to-talk hotkey."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ):
        self.hotkey = KEY_MAP.get(hotkey, keyboard.Key.alt_r)
        self.on_press = on_press
        self.on_release = on_release
        self._listener: Optional[keyboard.Listener] = None
        self._pressed = False

    def _handle_press(self, key) -> None:
        """Handle key press event."""
        if key == self.hotkey and not self._pressed:
            self._pressed = True
            self.on_press()

    def _handle_release(self, key) -> None:
        """Handle key release event."""
        if key == self.hotkey and self._pressed:
            self._pressed = False
            self.on_release()

    def start(self) -> None:
        """Start listening for hotkey."""
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop listening."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        """Wait for listener thread to finish."""
        if self._listener:
            self._listener.join()
```

**Step 2: Test hotkey detection**

```bash
source ~/.claude-voice/venv/bin/activate
python3 << 'EOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.hotkey import HotkeyListener

def on_press():
    print("RIGHT ALT PRESSED - recording would start")

def on_release():
    print("RIGHT ALT RELEASED - recording would stop")

print("Hold and release RIGHT ALT key. Press Ctrl+C to exit.")
listener = HotkeyListener("right_alt", on_press, on_release)
listener.start()

try:
    listener.join()
except KeyboardInterrupt:
    listener.stop()
    print("\nStopped.")
EOF
```

Expected: Press/release right alt shows messages. Ctrl+C exits.

---

## Task 10: Implement Main Daemon

**Files:**
- Create: `~/.claude-voice/daemon/main.py`

**Step 1: Write the main daemon module**

Create `~/.claude-voice/daemon/main.py`:

```python
"""Main daemon for Claude Voice - ties all components together."""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.config import load_config
from daemon.audio import AudioRecorder
from daemon.transcribe import Transcriber
from daemon.keyboard import KeyboardSimulator
from daemon.hotkey import HotkeyListener

class VoiceDaemon:
    """Main voice input daemon."""

    def __init__(self):
        self.config = load_config()

        self.recorder = AudioRecorder(
            sample_rate=self.config.audio.sample_rate,
            device=self.config.audio.input_device,
        )

        self.transcriber = Transcriber(
            model_name=self.config.transcription.model,
            device=self.config.transcription.device,
        )

        self.keyboard = KeyboardSimulator(
            typing_delay=self.config.input.typing_delay,
            auto_submit=self.config.input.auto_submit,
        )

        self.hotkey_listener = HotkeyListener(
            hotkey=self.config.input.hotkey,
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
        )

    def _on_hotkey_press(self) -> None:
        """Called when hotkey is pressed - start recording."""
        print("🎤 Recording...")
        self.recorder.start()

    def _on_hotkey_release(self) -> None:
        """Called when hotkey is released - stop, transcribe, type."""
        audio = self.recorder.stop()
        duration = self.recorder.get_duration(audio)

        if duration < self.config.input.min_audio_length:
            print(f"⏭️  Too short ({duration:.1f}s), ignoring")
            return

        print(f"📝 Transcribing {duration:.1f}s of audio...")
        text = self.transcriber.transcribe(audio)

        if not text:
            print("❌ No speech detected")
            return

        print(f"⌨️  Typing: {text}")
        self.keyboard.type_text(text)

    def run(self) -> None:
        """Start the daemon."""
        print("=" * 50)
        print("Claude Voice Daemon")
        print("=" * 50)
        print(f"Hotkey: {self.config.input.hotkey} (hold to record)")
        print(f"Model: {self.config.transcription.model}")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        # Pre-load Whisper model
        print("Loading Whisper model (first time may take a moment)...")
        self.transcriber._ensure_model()
        print("Ready! Hold the hotkey and speak.")
        print()

        self.hotkey_listener.start()

        try:
            self.hotkey_listener.join()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.hotkey_listener.stop()

def main():
    daemon = VoiceDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
```

**Step 2: Test the complete daemon**

Open Claude Code in a terminal, then in another terminal run:

```bash
source ~/.claude-voice/venv/bin/activate
python ~/.claude-voice/daemon/main.py
```

Then hold right alt, speak a question, release. Your words should appear in Claude Code.

Expected: Speech is transcribed and typed into the focused application.

---

## Task 11: Create Daemon Launch Script

**Files:**
- Create: `~/.claude-voice/claude-voice-daemon`

**Step 1: Write the launch script**

Create `~/.claude-voice/claude-voice-daemon`:

```bash
#!/bin/bash

DAEMON_DIR="$HOME/.claude-voice"
VENV_DIR="$DAEMON_DIR/venv"
PID_FILE="$DAEMON_DIR/daemon.pid"
LOG_FILE="$DAEMON_DIR/logs/daemon.log"

start() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Daemon is already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "Starting Claude Voice daemon..."
    source "$VENV_DIR/bin/activate"

    nohup python "$DAEMON_DIR/daemon/main.py" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    echo "Daemon started (PID: $(cat $PID_FILE))"
    echo "Logs: $LOG_FILE"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Daemon is not running (no PID file)"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping daemon (PID: $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Daemon stopped"
    else
        echo "Daemon was not running, cleaning up PID file"
        rm -f "$PID_FILE"
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Daemon is running (PID: $(cat $PID_FILE))"
    else
        echo "Daemon is not running"
    fi
}

foreground() {
    echo "Running in foreground (Ctrl+C to stop)..."
    source "$VENV_DIR/bin/activate"
    python "$DAEMON_DIR/daemon/main.py"
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        status
        ;;
    foreground|fg)
        foreground
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|foreground}"
        exit 1
        ;;
esac
```

**Step 2: Make executable and test**

```bash
chmod +x ~/.claude-voice/claude-voice-daemon
~/.claude-voice/claude-voice-daemon status
```

Expected: "Daemon is not running"

**Step 3: Add to PATH (optional)**

```bash
ln -sf ~/.claude-voice/claude-voice-daemon /usr/local/bin/claude-voice-daemon
```

---

## Task 12: Implement TTS Hook Script

**Files:**
- Create: `~/.claude/hooks/speak-response.py`

**Step 1: Write the TTS hook script**

Create `~/.claude/hooks/speak-response.py`:

```python
#!/usr/bin/env python3
"""Claude Code hook to speak responses via Piper TTS."""

import json
import os
import re
import subprocess
import sys

# Paths
PIPER_BIN = os.path.expanduser("~/.claude-voice/piper/piper")
VOICE_MODEL = os.path.expanduser("~/.claude-voice/models/piper/en_US-amy-medium.onnx")
CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")

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

def speak(text: str) -> None:
    """Speak text using Piper TTS."""
    if not text:
        return

    if not os.path.exists(PIPER_BIN):
        print(f"Piper not found at {PIPER_BIN}", file=sys.stderr)
        return

    if not os.path.exists(VOICE_MODEL):
        print(f"Voice model not found at {VOICE_MODEL}", file=sys.stderr)
        return

    try:
        # Piper outputs WAV, pipe to afplay
        piper_cmd = [
            PIPER_BIN,
            '--model', VOICE_MODEL,
            '--output-raw',
        ]

        # afplay can play raw audio with correct format
        afplay_cmd = [
            'afplay',
            '-f', 'LEI16',  # Little-endian 16-bit integer
            '-r', '22050',  # Piper's default sample rate
            '-c', '1',      # Mono
            '-',            # Read from stdin
        ]

        # Pipe piper output to afplay
        piper_proc = subprocess.Popen(
            piper_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        afplay_proc = subprocess.Popen(
            afplay_cmd,
            stdin=piper_proc.stdout,
            stderr=subprocess.DEVNULL,
        )

        piper_proc.stdin.write(text.encode('utf-8'))
        piper_proc.stdin.close()
        piper_proc.stdout.close()

        afplay_proc.wait()
        piper_proc.wait()

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

    # Extract and clean the last response
    text = extract_last_assistant_message(transcript_path)
    text = clean_text_for_speech(text, config)

    if text:
        speak(text)

if __name__ == "__main__":
    main()
```

**Step 2: Make executable**

```bash
mkdir -p ~/.claude/hooks
chmod +x ~/.claude/hooks/speak-response.py
```

**Step 3: Test the hook script manually**

```bash
# Create a test transcript
echo '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello! I am Claude. How can I help you today?"}]}}' > /tmp/test_transcript.jsonl

# Test the hook
echo '{"transcript_path":"/tmp/test_transcript.jsonl"}' | python ~/.claude/hooks/speak-response.py
```

Expected: Hear "Hello! I am Claude. How can I help you today?" spoken aloud.

---

## Task 13: Configure Claude Code Hook

**Files:**
- Modify: `~/.claude/settings.json`

**Step 1: Read current settings**

```bash
cat ~/.claude/settings.json
```

**Step 2: Add the Stop hook**

Update `~/.claude/settings.json` to include the hooks configuration. Add this to the existing JSON:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/speak-response.py"
          }
        ]
      }
    ]
  }
}
```

Note: Merge this with existing settings, don't replace them.

**Step 3: Verify settings are valid JSON**

```bash
python3 -c "import json; json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('Valid JSON')"
```

Expected: "Valid JSON"

---

## Task 14: End-to-End Test

**Step 1: Start the voice daemon in foreground**

Terminal 1:
```bash
~/.claude-voice/claude-voice-daemon foreground
```

**Step 2: Start Claude Code**

Terminal 2:
```bash
claude
```

**Step 3: Test voice input**

- Hold Right Alt
- Say "What is the capital of France?"
- Release Right Alt
- Watch: Your speech is transcribed and typed into Claude Code

**Step 4: Test voice output**

- After Claude responds, you should hear the response spoken aloud

**Step 5: Test the full loop**

- Ask several questions via voice
- Verify responses are spoken
- Test interrupting speech by pressing the hotkey

---

## Task 15: Create Installation Script (Optional)

**Files:**
- Create: `~/.claude-voice/install.sh`

**Step 1: Write the installation script**

Create `~/.claude-voice/install.sh`:

```bash
#!/bin/bash

set -e

INSTALL_DIR="$HOME/.claude-voice"

echo "=================================="
echo "Claude Voice Interface Installer"
echo "=================================="

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"/{daemon,models/whisper,models/piper,logs}

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install pynput sounddevice numpy faster-whisper pyyaml

# Download Piper
echo "Downloading Piper TTS..."
cd "$INSTALL_DIR"
curl -L -o piper_macos_arm64.tar.gz \
  "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_aarch64.tar.gz"
tar -xzf piper_macos_arm64.tar.gz
rm piper_macos_arm64.tar.gz
chmod +x piper/piper

# Download voice model
echo "Downloading voice model..."
cd "$INSTALL_DIR/models/piper"
curl -L -o en_US-amy-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
curl -L -o en_US-amy-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"

# Download Whisper model
echo "Downloading Whisper model (this may take a minute)..."
python3 << 'EOF'
from faster_whisper import WhisperModel
import os
model_dir = os.path.expanduser("~/.claude-voice/models/whisper")
model = WhisperModel("base.en", device="cpu", download_root=model_dir)
print("Whisper model ready!")
EOF

echo ""
echo "=================================="
echo "Installation complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Copy the daemon files from the plan to ~/.claude-voice/daemon/"
echo "2. Copy config.yaml to ~/.claude-voice/"
echo "3. Copy speak-response.py to ~/.claude/hooks/"
echo "4. Add the hook config to ~/.claude/settings.json"
echo "5. Run: ~/.claude-voice/claude-voice-daemon foreground"
echo ""
```

**Step 2: Make executable**

```bash
chmod +x ~/.claude-voice/install.sh
```

---

## Summary

| Task | Component | Status |
|------|-----------|--------|
| 1 | Directory structure & config | |
| 2 | Python venv & dependencies | |
| 3 | Download Whisper model | |
| 4 | Download Piper TTS | |
| 5 | Config loader module | |
| 6 | Audio recording module | |
| 7 | Whisper transcription module | |
| 8 | Keyboard simulation module | |
| 9 | Hotkey listener module | |
| 10 | Main daemon | |
| 11 | Launch script | |
| 12 | TTS hook script | |
| 13 | Claude Code hook config | |
| 14 | End-to-end test | |
| 15 | Installation script (optional) | |