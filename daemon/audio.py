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
