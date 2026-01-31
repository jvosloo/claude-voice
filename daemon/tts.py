"""Kokoro TTS engine via mlx-audio."""

import logging
import os
import subprocess
import tempfile
import threading

# Suppress phonemizer "words count mismatch" warnings (harmless espeak quirk)
logging.getLogger("phonemizer").setLevel(logging.ERROR)

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
            print("Loading Kokoro TTS model (first time may download ~360MB)...")
            from mlx_audio.tts import load
            self._model = load(KOKORO_MODEL)
            # Warm up: first generate creates the KokoroPipeline (which prints to stdout)
            for _ in self._model.generate(".", voice="af_heart", lang_code="a"):
                pass
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

    def stop_playback(self) -> bool:
        """Stop current audio playback. Returns True if playback was active."""
        from daemon import kill_playback_proc
        was_active = kill_playback_proc(self._playback_proc)
        self._playback_proc = None
        return was_active
