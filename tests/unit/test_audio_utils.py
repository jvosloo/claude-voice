"""Tests for audio utility functions in daemon/audio.py."""

import numpy as np
from unittest.mock import MagicMock
import sys

# Mock sounddevice (requires PortAudio system library)
sys.modules.setdefault('sounddevice', MagicMock())

from daemon.audio import AudioRecorder


class TestGetDuration:

    def test_normal_audio(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.zeros(16000, dtype=np.float32)  # 1 second
        assert recorder.get_duration(audio) == 1.0

    def test_half_second(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.zeros(8000, dtype=np.float32)
        assert recorder.get_duration(audio) == 0.5

    def test_zero_length(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.array([], dtype=np.float32)
        assert recorder.get_duration(audio) == 0.0

    def test_different_sample_rate(self):
        recorder = AudioRecorder(sample_rate=44100)
        audio = np.zeros(44100, dtype=np.float32)
        assert recorder.get_duration(audio) == 1.0
