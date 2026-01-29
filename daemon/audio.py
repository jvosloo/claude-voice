"""Audio recording functionality for Claude Voice daemon."""

import numpy as np
import sounddevice as sd
from typing import Optional
import threading
import os

# Suppress PortAudio debug messages on macOS
os.environ.setdefault('PA_ALSA_PLUGHW', '1')

class AudioRecorder:
    """Records audio from microphone while activated.

    Uses a persistent audio stream to avoid open/close errors on macOS.
    """

    def __init__(self, sample_rate: int = 16000, device: Optional[int] = None):
        self.sample_rate = sample_rate
        self.device = device
        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._stream_active = False

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        """Called by sounddevice for each audio chunk."""
        if status and self._recording:
            # Only print status warnings while actively recording
            print(f"Audio status: {status}")
        if self._recording:
            with self._lock:
                self._audio_chunks.append(indata.copy())

    def _ensure_stream(self) -> None:
        """Ensure the audio stream is open and running."""
        if self._stream is None or not self._stream_active:
            if self._stream:
                try:
                    self._stream.close()
                except:
                    pass

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.float32,
                device=self.device,
                callback=self._audio_callback,
                blocksize=1024,  # Explicit blocksize helps avoid macOS errors
            )
            self._stream.start()
            self._stream_active = True

    def start(self) -> None:
        """Start recording audio."""
        self._ensure_stream()

        with self._lock:
            self._audio_chunks = []
            self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording and return audio as numpy array."""
        self._recording = False

        # Close the stream to release the microphone
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except:
                pass
            self._stream = None
            self._stream_active = False

        with self._lock:
            if self._audio_chunks:
                audio = np.concatenate(self._audio_chunks, axis=0)
                return audio.flatten()
            return np.array([], dtype=np.float32)

    def shutdown(self) -> None:
        """Close the audio stream completely. Call on daemon exit."""
        self._recording = False
        self._stream_active = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except:
                pass
            self._stream = None

    def get_duration(self, audio: np.ndarray) -> float:
        """Get duration of audio in seconds."""
        return len(audio) / self.sample_rate
