"""Main daemon for Claude Voice - ties all components together."""

import os
import sys

# Ensure print output is unbuffered (visible in log files when running in background)
sys.stdout.reconfigure(line_buffering=True)
import signal
import threading
import json
import numpy as np
import socket

# Suppress multiprocessing resource_tracker warnings on forced shutdown
# This happens when sounddevice's internal semaphores aren't cleaned up
# Must be done BEFORE importing sounddevice which uses multiprocessing
try:
    from multiprocessing import resource_tracker
    # Monkey-patch to prevent the warning on unclean exit
    def _noop_warn(*args, **kwargs):
        pass
    resource_tracker._resource_tracker._warn = _noop_warn
except (ImportError, AttributeError):
    pass

import sounddevice as sd

# Add parent directory to path for imports
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.config import load_config
from daemon.audio import AudioRecorder
from daemon.transcribe import Transcriber
from daemon.keyboard import KeyboardSimulator
from daemon.hotkey import HotkeyListener
from daemon.cleanup import TranscriptionCleaner
from daemon.tts import TTSEngine
from daemon.notify import classify, play_phrase, stop_playback as stop_notify_playback, ERROR_FLAG

SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")

_cue_stream: sd.OutputStream | None = None
_cue_lock = threading.Lock()


def _read_mode() -> str:
    """Read the current TTS mode from the mode file. Defaults to narrate."""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                mode = f.read().strip()
            if mode in ("narrate", "notify"):
                return mode
        except Exception:
            pass
    return "narrate"


def _write_mode(mode: str) -> None:
    """Write the current TTS mode to the mode file."""
    with open(MODE_FILE, "w") as f:
        f.write(mode)


def _play_cue(frequencies: list[int], duration: float = 0.05, sample_rate: int = 44100) -> None:
    """Play a short audio cue with the given frequency sequence."""
    global _cue_stream

    def _play():
        global _cue_stream
        samples = []
        for freq in frequencies:
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(2 * np.pi * freq * t)
            fade_samples = int(sample_rate * 0.005)  # 5ms fade
            tone[:fade_samples] *= np.linspace(0, 1, fade_samples)
            tone[-fade_samples:] *= np.linspace(1, 0, fade_samples)
            samples.append(tone)

        audio = np.concatenate(samples).astype(np.float32) * 0.3

        with _cue_lock:
            if _cue_stream is None or not _cue_stream.active:
                _cue_stream = sd.OutputStream(
                    samplerate=sample_rate, channels=1, dtype=np.float32,
                )
                _cue_stream.start()
            _cue_stream.write(audio.reshape(-1, 1))

    threading.Thread(target=_play, daemon=True).start()

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
            backend=self.config.transcription.backend,
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

        self.tts_engine = TTSEngine()
        self._tts_server = None
        self._shutting_down = False
        self._interrupted_tts = False

        # Optional transcription cleanup via LLM
        self.cleaner = None
        if self.config.input.transcription_cleanup:
            self.cleaner = TranscriptionCleaner(
                model_name=self.config.input.cleanup_model,
                debug=self.config.input.debug,
            )

    def _on_hotkey_press(self) -> None:
        """Called when hotkey is pressed - start recording."""
        # Start recording FIRST - minimize latency
        self.recorder.start()
        # Play ascending cue to signal recording started
        _play_cue([440, 880])
        print("Recording...")
        # Stop any TTS playback
        self._interrupted_tts = self.tts_engine.stop_playback()
        if not self._interrupted_tts:
            self._interrupted_tts = stop_notify_playback()

    def _handle_voice_command(self, text: str) -> bool:
        """Check for voice commands. Returns True if command was handled."""
        text_lower = text.lower().strip().rstrip('.')

        # Stop speaking commands
        if text_lower in ["stop speaking", "stop talking"]:
            with open(SILENT_FLAG, 'w') as f:
                pass
            print("Voice output disabled")
            return True

        # Start speaking commands
        if text_lower in ["start speaking", "start talking"]:
            if os.path.exists(SILENT_FLAG):
                os.remove(SILENT_FLAG)
            print("Voice output enabled")
            return True

        # Mode switching commands
        if text_lower in ["switch to narrate mode", "switch to narration mode"]:
            _write_mode("narrate")
            print("Switched to narrate mode")
            return True

        if text_lower in ["switch to notify mode", "switch to notification mode"]:
            _write_mode("notify")
            print("Switched to notify mode")
            return True

        return False

    def _run_tts_server(self) -> None:
        """Run Unix socket server for TTS requests from the hook."""
        # Clean up stale socket file
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(TTS_SOCK_PATH)
        server.listen(5)
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

                # Direct category from hooks (e.g. PreToolUse permission)
                notify_category = request.get("notify_category")
                if notify_category:
                    print(f"Notify: {notify_category}")
                    play_phrase(notify_category, self.config.speech.notify_phrases)
                    continue

                text = request.get("text", "")
                voice = request.get("voice", self.config.speech.voice)
                speed = request.get("speed", self.config.speech.speed)
                lang_code = request.get("lang_code", self.config.speech.lang_code)

                if text:
                    mode = _read_mode()
                    if mode == "notify":
                        category = classify(text)
                        print(f"Notify: {category}")
                        play_phrase(category, self.config.speech.notify_phrases)
                    else:
                        self.tts_engine.speak(text, voice=voice, speed=speed, lang_code=lang_code)
            except Exception as e:
                print(f"TTS server error: {e}")

        server.close()
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)

    def _on_hotkey_release(self) -> None:
        """Called when hotkey is released - stop, transcribe, type."""
        audio = self.recorder.stop()
        # Play descending cue to signal recording stopped
        _play_cue([880, 440])
        duration = self.recorder.get_duration(audio)

        if duration < self.config.input.min_audio_length:
            if duration > 0.1 and not self._interrupted_tts:
                print(f"Too short ({duration:.1f}s), ignoring")
            return

        print(f"Transcribing {duration:.1f}s of audio...")
        text = self.transcriber.transcribe(audio)

        if not text:
            print("No speech detected")
            return

        # Clean up transcription if enabled
        if self.cleaner:
            original = text
            text = self.cleaner.cleanup(text)
            print(f"Whisper: {original}")
            if text != original:
                print(f"Cleaned: {text}")
            else:
                print("Cleaned: (no changes)")

        # Check for voice commands first
        if self._handle_voice_command(text):
            return

        print(f"Typing:  {text}")
        print()
        self.keyboard.type_text(text + " ")

    def _shutdown(self) -> None:
        """Clean shutdown of the daemon."""
        print("\nShutting down...")
        self._shutting_down = True
        if self._tts_server:
            try:
                self._tts_server.close()
            except Exception:
                pass
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)
        self.hotkey_listener.stop()
        self.recorder.shutdown()

        # Kill the multiprocessing resource_tracker to prevent semaphore warnings
        # It's a separate subprocess that prints warnings after we exit
        try:
            from multiprocessing import resource_tracker
            tracker = resource_tracker._resource_tracker
            if tracker._pid is not None:
                os.kill(tracker._pid, signal.SIGKILL)
        except:
            pass

        # Exit immediately without Python's cleanup
        os._exit(0)

    def run(self) -> None:
        """Start the daemon."""
        # Handle SIGTERM (from kill command) gracefully
        signal.signal(signal.SIGTERM, lambda sig, frame: self._shutdown())

        print("=" * 50)
        print("Claude Voice Daemon")
        print("=" * 50)
        print(f"Hotkey: {self.config.input.hotkey} (hold to record)")
        print(f"Model: {self.config.transcription.model}")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        # Initialize mode from config (only if no mode file exists yet)
        if not os.path.exists(MODE_FILE):
            _write_mode(self.config.speech.mode)
        print(f"TTS mode: {_read_mode()}")

        # Clean up stale error flag from previous session
        if os.path.exists(ERROR_FLAG):
            os.remove(ERROR_FLAG)

        # Pre-load models
        self.transcriber._ensure_model()
        if self.config.speech.enabled:
            self.tts_engine._ensure_model()

            # Sound check (only in interactive/foreground mode)
            if sys.stdin.isatty():
                print('\nSound check: playing "Hello!! Can you hear me?"')
                self.tts_engine.speak(
                    "Hello!! Can you hear me?",
                    voice=self.config.speech.voice,
                    speed=self.config.speech.speed,
                    lang_code=self.config.speech.lang_code,
                )
                answer = input("Did you hear the test phrase? [Y/n] ").strip().lower()
                if answer in ("n", "no"):
                    print("Tip: check your audio output device and volume settings.")
                    print("Continuing startup anyway...\n")
                else:
                    print("Sound check passed.\n")

        # Regenerate custom notify phrases if needed
        if self.config.speech.mode == "notify" or self.config.speech.notify_phrases:
            from daemon.notify import regenerate_custom_phrases
            is_foreground = sys.stdin.isatty()
            regenerate_custom_phrases(
                self.config.speech.notify_phrases,
                voice=self.config.speech.voice,
                speed=self.config.speech.speed,
                lang_code=self.config.speech.lang_code,
                interactive=is_foreground,
            )

        # Check transcription cleanup if enabled
        if self.cleaner:
            if not self.cleaner.ensure_ready():
                self.cleaner = None  # Disable on failure

        print("Ready! Hold the hotkey and speak.")
        print()

        # Start TTS socket server
        tts_thread = threading.Thread(target=self._run_tts_server, daemon=True)
        tts_thread.start()
        print(f"TTS server listening on {TTS_SOCK_PATH}")

        self.hotkey_listener.start()

        try:
            self.hotkey_listener.join()
        except KeyboardInterrupt:
            self._shutdown()

def main():
    daemon = VoiceDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
