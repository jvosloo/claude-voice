"""Tests for audio device disconnect protection."""

import collections
import numpy as np
from unittest.mock import patch, MagicMock
from daemon.audio import AudioRecorder


class TestDeviceDisconnect:
    """Test graceful handling of audio device disconnects."""

    def _make_recorder(self):
        """Create an AudioRecorder with stream mocked."""
        recorder = AudioRecorder.__new__(AudioRecorder)
        recorder.sample_rate = 16000
        recorder.device = None
        recorder._recording = False
        recorder._audio_chunks = []
        recorder._stream = None
        recorder._lock = __import__('threading').Lock()
        recorder._device_error = False
        recorder._error_count = 0
        recorder._rms_levels = collections.deque(maxlen=7)
        recorder._rms_peak = 0.0
        return recorder

    def test_start_resets_error_state(self):
        """start() should clear error flags."""
        recorder = self._make_recorder()
        recorder._device_error = True
        recorder._error_count = 5
        with patch.object(recorder, '_ensure_stream'):
            recorder.start()
        assert recorder._device_error is False
        assert recorder._error_count == 0

    def test_callback_counts_errors(self):
        """Callback should increment error count on status flags."""
        recorder = self._make_recorder()
        recorder._recording = True
        # Simulate 2 errors — shouldn't trigger device_error yet
        recorder._audio_callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, "input overflow")
        assert recorder._error_count == 1
        assert recorder._device_error is False
        recorder._audio_callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, "input overflow")
        assert recorder._error_count == 2
        assert recorder._device_error is False

    def test_callback_triggers_error_after_three(self):
        """Three consecutive errors should set _device_error and stop recording."""
        recorder = self._make_recorder()
        recorder._recording = True
        for _ in range(3):
            recorder._audio_callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, "input overflow")
        assert recorder._device_error is True
        assert recorder._recording is False

    def test_callback_resets_count_on_success(self):
        """Successful callback should reset error count."""
        recorder = self._make_recorder()
        recorder._recording = True
        recorder._error_count = 2
        # No status = successful callback
        recorder._audio_callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, None)
        assert recorder._error_count == 0

    def test_stop_detects_inactive_stream(self):
        """stop() should set _device_error if stream is inactive."""
        recorder = self._make_recorder()
        recorder._recording = True
        mock_stream = MagicMock()
        mock_stream.active = False
        recorder._stream = mock_stream
        recorder.stop()
        assert recorder._device_error is True

    def test_stop_detects_portaudio_error(self):
        """stop() should set _device_error on audio errors during close."""
        recorder = self._make_recorder()
        recorder._recording = True
        mock_stream = MagicMock()
        mock_stream.active = True
        mock_stream.stop.side_effect = RuntimeError("PortAudio: Device removed")
        recorder._stream = mock_stream
        recorder.stop()
        assert recorder._device_error is True

    def test_stop_detects_os_error(self):
        """stop() should set _device_error on OSError during close."""
        recorder = self._make_recorder()
        recorder._recording = True
        mock_stream = MagicMock()
        mock_stream.active = True
        mock_stream.stop.side_effect = OSError("Device gone")
        recorder._stream = mock_stream
        recorder.stop()
        assert recorder._device_error is True

    def test_had_device_error_property(self):
        """had_device_error property should reflect _device_error flag."""
        recorder = self._make_recorder()
        assert recorder.had_device_error is False
        recorder._device_error = True
        assert recorder.had_device_error is True

    def test_normal_stop_no_error(self):
        """Normal stop should not set _device_error."""
        recorder = self._make_recorder()
        recorder._recording = True
        mock_stream = MagicMock()
        mock_stream.active = True
        recorder._stream = mock_stream
        recorder.stop()
        assert recorder._device_error is False
