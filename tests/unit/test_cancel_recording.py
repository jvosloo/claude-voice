"""Tests for double-ESC cancel recording feature."""

import sys
import time
from unittest.mock import MagicMock, patch
from pynput import keyboard
from daemon.hotkey import HotkeyListener


class TestEscDuringRecording:
    """Test ESC dispatch in HotkeyListener."""

    def test_esc_fires_callback_when_recording(self):
        """ESC during recording should fire on_esc_during_recording."""
        callback = MagicMock()
        listener = HotkeyListener(
            hotkey="right_alt",
            on_press=MagicMock(),
            on_release=MagicMock(),
            on_esc_during_recording=callback,
        )
        listener._pressed = True
        listener._handle_press(keyboard.Key.esc)
        callback.assert_called_once()

    def test_esc_ignored_when_not_recording(self):
        """ESC when not recording should be ignored."""
        callback = MagicMock()
        listener = HotkeyListener(
            hotkey="right_alt",
            on_press=MagicMock(),
            on_release=MagicMock(),
            on_esc_during_recording=callback,
        )
        listener._pressed = False
        listener._handle_press(keyboard.Key.esc)
        callback.assert_not_called()

    def test_esc_ignored_without_callback(self):
        """ESC during recording should not crash if no callback."""
        listener = HotkeyListener(
            hotkey="right_alt",
            on_press=MagicMock(),
            on_release=MagicMock(),
        )
        listener._pressed = True
        # Should not raise
        listener._handle_press(keyboard.Key.esc)

    def test_clear_pressed(self):
        """clear_pressed() should set _pressed to False."""
        listener = HotkeyListener(
            hotkey="right_alt",
            on_press=MagicMock(),
            on_release=MagicMock(),
        )
        listener._pressed = True
        listener.clear_pressed()
        assert listener._pressed is False

    def test_release_after_clear_pressed_is_noop(self):
        """Releasing hotkey after clear_pressed should not call on_release."""
        on_release = MagicMock()
        listener = HotkeyListener(
            hotkey="right_alt",
            on_press=MagicMock(),
            on_release=on_release,
        )
        listener._pressed = True
        listener.clear_pressed()
        listener._handle_release(keyboard.Key.alt_r)
        on_release.assert_not_called()


class TestDoubleTapStateMachine:
    """Test the double-ESC state machine in VoiceDaemon."""

    def _make_daemon(self):
        """Create a minimal VoiceDaemon mock with cancel state."""
        daemon = MagicMock()
        daemon._cancel_warned = False
        daemon._cancel_esc_time = 0.0
        daemon._recording_cancelled = False
        daemon._languages = ["en"]
        daemon.recorder = MagicMock()
        daemon.recorder.is_recording = True
        daemon.hotkey_listener = MagicMock()
        daemon.hotkey_listener.active_language = "en"
        return daemon

    def _patch_overlay(self):
        """Patch daemon.overlay module for lazy imports in main.py methods."""
        mock_overlay = MagicMock()
        return patch.dict(sys.modules, {"daemon.overlay": mock_overlay}), mock_overlay

    def test_first_esc_sets_warned(self):
        """First ESC should set _cancel_warned and show warning."""
        from daemon.main import VoiceDaemon
        daemon = self._make_daemon()
        patcher, mock_overlay = self._patch_overlay()
        with patcher, \
             patch("daemon.main._play_cue"), \
             patch("daemon.main.threading"):
            VoiceDaemon._on_esc_during_recording(daemon)
        assert daemon._cancel_warned is True
        mock_overlay.show_cancel_warning.assert_called_once()

    def test_second_esc_within_2s_cancels(self):
        """Second ESC within 2s should cancel recording."""
        from daemon.main import VoiceDaemon
        daemon = self._make_daemon()
        daemon._cancel_warned = True
        daemon._cancel_esc_time = time.time()  # just now
        patcher, mock_overlay = self._patch_overlay()
        with patcher, \
             patch("daemon.main._play_cue"):
            VoiceDaemon._on_esc_during_recording(daemon)
        assert daemon._recording_cancelled is True
        assert daemon._cancel_warned is False
        daemon.recorder.stop.assert_called_once()
        daemon.hotkey_listener.clear_pressed.assert_called_once()
        mock_overlay.hide.assert_called_once()

    def test_second_esc_after_2s_resets_warning(self):
        """Second ESC after 2s should act as new first ESC."""
        from daemon.main import VoiceDaemon
        daemon = self._make_daemon()
        daemon._cancel_warned = True
        daemon._cancel_esc_time = time.time() - 3.0  # 3 seconds ago
        patcher, mock_overlay = self._patch_overlay()
        with patcher, \
             patch("daemon.main._play_cue"), \
             patch("daemon.main.threading"):
            VoiceDaemon._on_esc_during_recording(daemon)
        # Should show warning again (acts as first ESC)
        mock_overlay.show_cancel_warning.assert_called_once()
        assert daemon._cancel_warned is True

    def test_hotkey_release_skipped_when_cancelled(self):
        """Hotkey release should be a no-op when recording was cancelled."""
        from daemon.main import VoiceDaemon
        daemon = self._make_daemon()
        daemon._recording_cancelled = True
        patcher, _ = self._patch_overlay()
        with patcher:
            VoiceDaemon._on_hotkey_release(daemon)
        # Should not call recorder.stop (already stopped by ESC handler)
        daemon.recorder.stop.assert_not_called()
        # _recording_cancelled should be reset
        assert daemon._recording_cancelled is False

    def test_hotkey_press_resets_cancel_state(self):
        """New hotkey press should reset cancel state."""
        from daemon.main import VoiceDaemon
        daemon = self._make_daemon()
        daemon._cancel_warned = True
        daemon._recording_cancelled = True
        daemon.config = MagicMock()
        daemon.config.input.min_audio_length = 0.5
        daemon._interrupted_tts = False
        daemon.tts_engine = MagicMock()
        daemon.tts_engine.stop_playback.return_value = False
        patcher, _ = self._patch_overlay()
        with patcher, \
             patch("daemon.main._play_cue"), \
             patch("daemon.main.stop_notify_playback", return_value=False):
            VoiceDaemon._on_hotkey_press(daemon)
        assert daemon._cancel_warned is False
        assert daemon._recording_cancelled is False
