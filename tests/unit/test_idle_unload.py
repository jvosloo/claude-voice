"""Tests for transcription engine idle unload."""

import time
from unittest.mock import patch, MagicMock
from daemon.transcribe import Transcriber


class TestIdleUnload:
    """Test idle model unloading in Transcriber."""

    def _make_transcriber(self, idle_unload=1):
        """Create a Transcriber with idle unload enabled, timer mocked."""
        with patch("daemon.transcribe.threading") as mock_threading:
            mock_threading.Timer.return_value = MagicMock()
            t = Transcriber(model_name="base.en", idle_unload=idle_unload)
        return t

    def test_idle_timer_starts_when_enabled(self):
        """Timer should start when idle_unload > 0."""
        with patch("daemon.transcribe.threading") as mock_threading:
            mock_timer = MagicMock()
            mock_threading.Timer.return_value = mock_timer
            Transcriber(model_name="base.en", idle_unload=5)
            mock_threading.Timer.assert_called_once()
            args = mock_threading.Timer.call_args
            assert args[0][0] == 60.0  # interval
            mock_timer.start.assert_called_once()

    def test_idle_timer_not_started_when_disabled(self):
        """Timer should not start when idle_unload is 0."""
        with patch("daemon.transcribe.threading") as mock_threading:
            Transcriber(model_name="base.en", idle_unload=0)
            mock_threading.Timer.assert_not_called()

    def test_check_idle_unloads_model(self):
        """Model should be unloaded when idle exceeds timeout."""
        t = self._make_transcriber(idle_unload=1)
        t._model = "fake_model"
        t._last_used = time.time() - 120  # 2 minutes ago, threshold is 1 minute
        with patch.object(t, '_start_idle_timer'):
            t._check_idle()
        assert t._model is None

    def test_check_idle_keeps_model_when_recent(self):
        """Model should remain loaded when recently used."""
        t = self._make_transcriber(idle_unload=5)
        t._model = "fake_model"
        t._last_used = time.time()  # just now
        with patch.object(t, '_start_idle_timer'):
            t._check_idle()
        assert t._model == "fake_model"

    def test_check_idle_no_op_when_no_model(self):
        """No-op when model is already unloaded."""
        t = self._make_transcriber(idle_unload=1)
        t._model = None
        t._last_used = time.time() - 120
        with patch.object(t, '_start_idle_timer'):
            t._check_idle()
        assert t._model is None

    def test_check_idle_reschedules_timer(self):
        """Timer should reschedule itself after checking."""
        t = self._make_transcriber(idle_unload=1)
        t._model = None
        with patch.object(t, '_start_idle_timer') as mock_start:
            t._check_idle()
            mock_start.assert_called_once()

    def test_stop_idle_timer_cancels(self):
        """stop_idle_timer should cancel the pending timer."""
        t = self._make_transcriber(idle_unload=5)
        mock_timer = MagicMock()
        t._idle_timer = mock_timer
        t.stop_idle_timer()
        mock_timer.cancel.assert_called_once()
        assert t._idle_timer is None

    def test_set_idle_unload_restarts_timer(self):
        """set_idle_unload should update timeout and restart timer."""
        t = self._make_transcriber(idle_unload=5)
        with patch.object(t, '_start_idle_timer') as mock_start:
            t.set_idle_unload(10)
            assert t._idle_unload == 10
            mock_start.assert_called_once()

    def test_ensure_model_updates_last_used(self):
        """_ensure_model should update _last_used timestamp."""
        t = self._make_transcriber(idle_unload=5)
        t._model = "already_loaded"
        old_time = t._last_used
        time.sleep(0.01)
        t._ensure_model()
        assert t._last_used > old_time

    def test_transcribe_updates_last_used(self):
        """transcribe() should update _last_used timestamp."""
        t = self._make_transcriber(idle_unload=5)
        t._model = "fake"
        old_time = t._last_used
        time.sleep(0.01)
        import numpy as np
        result = t.transcribe(np.array([], dtype=np.float32))
        assert result == ""
        assert t._last_used > old_time
