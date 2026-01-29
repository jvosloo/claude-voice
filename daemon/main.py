"""Main daemon for Claude Voice - ties all components together."""

import os
import sys
import subprocess
import threading
import numpy as np
import sounddevice as sd

# Add parent directory to path for imports
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.config import load_config
from daemon.audio import AudioRecorder
from daemon.transcribe import Transcriber
from daemon.keyboard import KeyboardSimulator
from daemon.hotkey import HotkeyListener
from daemon.cleanup import TranscriptionCleaner

SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")

def _play_cue(frequencies: list[int], duration: float = 0.05, sample_rate: int = 44100) -> None:
    """Play a short audio cue with the given frequency sequence.

    Args:
        frequencies: List of frequencies to play in sequence (e.g., [440, 880] for ascending)
        duration: Duration of each tone in seconds
        sample_rate: Audio sample rate
    """
    def _play():
        samples = []
        for freq in frequencies:
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            # Sine wave with quick fade in/out to avoid clicks
            tone = np.sin(2 * np.pi * freq * t)
            fade_samples = int(sample_rate * 0.005)  # 5ms fade
            tone[:fade_samples] *= np.linspace(0, 1, fade_samples)
            tone[-fade_samples:] *= np.linspace(1, 0, fade_samples)
            samples.append(tone)

        audio = np.concatenate(samples).astype(np.float32) * 0.3  # Low volume
        sd.play(audio, sample_rate)
        sd.wait()

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
        # Stop any TTS playback asynchronously
        threading.Thread(
            target=lambda: subprocess.run(['pkill', '-9', 'afplay'], stderr=subprocess.DEVNULL),
            daemon=True
        ).start()

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

        return False

    def _on_hotkey_release(self) -> None:
        """Called when hotkey is released - stop, transcribe, type."""
        audio = self.recorder.stop()
        # Play descending cue to signal recording stopped
        _play_cue([880, 440])
        duration = self.recorder.get_duration(audio)

        if duration < self.config.input.min_audio_length:
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

        # Check transcription cleanup if enabled
        if self.cleaner:
            if not self.cleaner.ensure_ready():
                self.cleaner = None  # Disable on failure

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
