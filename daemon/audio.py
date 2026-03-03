"""Audio recording functionality for Claude Voice daemon."""

import collections
import numpy as np
import sounddevice as sd
from typing import Optional
import threading
import time
import os

# Suppress PortAudio debug messages on macOS
os.environ.setdefault('PA_ALSA_PLUGHW', '1')

class AudioRecorder:
    """Records audio from microphone while activated.

    Opens the audio stream on start() and closes it on stop() so the
    macOS microphone indicator turns off between recordings. Retries
    stream creation once with a brief delay to handle PortAudio AUHAL
    error -50 that can occur on rapid stop/start cycles.
    """

    def __init__(self, sample_rate: int = 16000, device: Optional[int] = None):
        self.sample_rate = sample_rate
        self.device = device
        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._device_error = False
        self._error_count = 0
        self._rms_levels: collections.deque[float] = collections.deque(maxlen=7)
        self._rms_peak: float = 0.0

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        """Called by sounddevice for each audio chunk."""
        if status and self._recording:
            print(f"Audio status: {status}")
            self._error_count += 1
            if self._error_count >= 3:
                print("Audio device error: too many consecutive errors, aborting recording")
                self._device_error = True
                self._recording = False
                return
        else:
            self._error_count = 0
        if self._recording:
            with self._lock:
                self._audio_chunks.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata ** 2)))
            self._rms_levels.append(rms)
            self._rms_peak = max(self._rms_peak * 0.95, rms)

    def _ensure_stream(self) -> None:
        """Ensure the audio stream is open and running.

        Retries once with a short delay if PortAudio fails, which
        handles the AUHAL error -50 on rapid stop/start cycles.
        """
        if self._stream is not None and self._stream.active:
            return

        if self._stream is not None:
            try:
                self._stream.close()
            except sd.PortAudioError:
                pass  # Device already closed or unavailable
            self._stream = None

        for attempt in range(2):
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype=np.float32,
                    device=self.device,
                    callback=self._audio_callback,
                    blocksize=1024,
                )
                self._stream.start()
                return
            except sd.PortAudioError:
                if attempt == 0:
                    time.sleep(0.1)
                else:
                    raise

    @property
    def is_recording(self) -> bool:
        """Return True if currently recording."""
        return self._recording

    @property
    def had_device_error(self) -> bool:
        """Return True if device error occurred during recording."""
        return self._device_error

    def get_levels(self) -> list[float]:
        """Return 7 normalized [0,1] RMS levels for waveform display."""
        levels = list(self._rms_levels)
        # Pad to 7 values
        while len(levels) < 7:
            levels.insert(0, 0.0)
        # Adaptive normalization: floor above typical mic noise so
        # silence doesn't get amplified to full-scale bars
        peak = max(self._rms_peak, 0.01)
        return [min(v / peak, 1.0) for v in levels]

    def start(self) -> None:
        """Start recording audio."""
        self._device_error = False
        self._error_count = 0
        self._rms_levels.clear()
        self._rms_peak = 0.0
        self._ensure_stream()

        with self._lock:
            self._audio_chunks = []
            self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording, close the stream, and return audio as numpy array."""
        self._recording = False

        with self._lock:
            if self._audio_chunks:
                audio = np.concatenate(self._audio_chunks, axis=0)
                result = audio.flatten()
            else:
                result = np.array([], dtype=np.float32)

        # Close stream so macOS mic indicator turns off
        if self._stream is not None:
            try:
                if not self._stream.active:
                    self._device_error = True
                self._stream.stop()
                self._stream.close()
            except Exception:
                self._device_error = True
            self._stream = None

        return result

    def shutdown(self) -> None:
        """Close the audio stream completely. Call on daemon exit."""
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except sd.PortAudioError:
                pass  # Device already closed or unavailable
            self._stream = None

    def get_duration(self, audio: np.ndarray) -> float:
        """Get duration of audio in seconds."""
        return len(audio) / self.sample_rate
