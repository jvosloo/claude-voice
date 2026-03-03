"""Tests for live waveform RMS levels in AudioRecorder."""

import collections
import numpy as np
import threading
from daemon.audio import AudioRecorder


class TestGetLevels:
    """Test RMS level computation and normalization."""

    def _make_recorder(self):
        """Create an AudioRecorder without opening audio device."""
        recorder = AudioRecorder.__new__(AudioRecorder)
        recorder.sample_rate = 16000
        recorder.device = None
        recorder._recording = False
        recorder._audio_chunks = []
        recorder._stream = None
        recorder._lock = threading.Lock()
        recorder._device_error = False
        recorder._error_count = 0
        recorder._rms_levels = collections.deque(maxlen=7)
        recorder._rms_peak = 0.0
        return recorder

    def test_empty_levels_returns_seven_zeros(self):
        """get_levels() with no data should return 7 zeros."""
        recorder = self._make_recorder()
        levels = recorder.get_levels()
        assert levels == [0.0] * 7
        assert len(levels) == 7

    def test_levels_normalized_against_peak(self):
        """RMS values should be normalized relative to the tracked peak."""
        recorder = self._make_recorder()
        recorder._rms_peak = 0.1
        recorder._rms_levels.append(0.05)  # half of peak
        levels = recorder.get_levels()
        assert levels[-1] == 0.5

    def test_levels_clipped_at_one(self):
        """Normalized values above 1.0 should be clipped."""
        recorder = self._make_recorder()
        recorder._rms_peak = 0.05
        recorder._rms_levels.append(0.1)  # above peak
        levels = recorder.get_levels()
        assert levels[-1] == 1.0

    def test_noise_floor_prevents_silence_amplification(self):
        """Background noise should stay small thanks to the 0.01 floor."""
        recorder = self._make_recorder()
        # Simulate background noise: peak tracks noise, but floor = 0.01
        recorder._rms_peak = 0.001
        recorder._rms_levels.append(0.001)
        levels = recorder.get_levels()
        # 0.001 / 0.01 (floor) = 0.1 — small, not full-scale
        assert levels[-1] == 0.1

    def test_levels_padded_from_left(self):
        """Fewer than 7 values should be zero-padded from the left."""
        recorder = self._make_recorder()
        recorder._rms_peak = 0.1
        recorder._rms_levels.append(0.1)
        levels = recorder.get_levels()
        assert levels[:6] == [0.0] * 6
        assert levels[6] == 1.0

    def test_full_deque_returns_seven_values(self):
        """Full deque should return exactly 7 values."""
        recorder = self._make_recorder()
        recorder._rms_peak = 0.1
        for i in range(10):  # overflow deque (maxlen=7)
            recorder._rms_levels.append(0.1)
        levels = recorder.get_levels()
        assert len(levels) == 7
        assert all(v == 1.0 for v in levels)

    def test_callback_appends_rms_and_tracks_peak(self):
        """Audio callback should compute RMS and update the peak tracker."""
        recorder = self._make_recorder()
        recorder._recording = True
        # Create a sine wave chunk for predictable RMS
        t = np.linspace(0, 0.1, 1600, dtype=np.float32)
        chunk = (np.sin(2 * np.pi * 440 * t) * 0.1).reshape(-1, 1)
        recorder._audio_callback(chunk, 1600, None, None)
        assert len(recorder._rms_levels) == 1
        # RMS of sine wave with amplitude 0.1 ≈ 0.0707
        assert 0.05 < recorder._rms_levels[0] < 0.1
        # Peak should track the RMS value
        assert recorder._rms_peak == recorder._rms_levels[0]

    def test_start_clears_levels_and_peak(self):
        """start() should clear the RMS deque and reset peak."""
        recorder = self._make_recorder()
        recorder._rms_levels.append(0.1)
        recorder._rms_levels.append(0.2)
        recorder._rms_peak = 0.2
        from unittest.mock import patch
        with patch.object(recorder, '_ensure_stream'):
            recorder.start()
        assert len(recorder._rms_levels) == 0
        assert recorder._rms_peak == 0.0

    def test_silent_audio_gives_near_zero(self):
        """Silent audio should produce near-zero levels."""
        recorder = self._make_recorder()
        recorder._recording = True
        silent = np.zeros((1024, 1), dtype=np.float32)
        recorder._audio_callback(silent, 1024, None, None)
        levels = recorder.get_levels()
        assert levels[-1] == 0.0

    def test_peak_decays_over_time(self):
        """Peak should decay by 0.95x each callback when RMS drops."""
        recorder = self._make_recorder()
        recorder._recording = True
        # First: loud chunk to set peak
        loud = (np.ones((1024, 1), dtype=np.float32) * 0.1)
        recorder._audio_callback(loud, 1024, None, None)
        peak_after_loud = recorder._rms_peak
        # Then: silent chunk — peak decays
        silent = np.zeros((1024, 1), dtype=np.float32)
        recorder._audio_callback(silent, 1024, None, None)
        assert recorder._rms_peak < peak_after_loud
        assert recorder._rms_peak == peak_after_loud * 0.95
