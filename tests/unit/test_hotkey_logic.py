"""Tests for hotkey cycling logic in daemon/hotkey.py."""

from unittest.mock import MagicMock
import sys

# Mock pynput so we don't need system keyboard access
sys.modules.setdefault('pynput', MagicMock())
sys.modules.setdefault('pynput.keyboard', MagicMock())

from daemon.hotkey import HotkeyListener


class TestCycleLanguage:

    def _make_listener(self, languages):
        """Create a HotkeyListener with mocked callbacks."""
        return HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            languages=languages,
        )

    def test_single_language_stays_on_index_zero(self):
        hl = self._make_listener(["en"])
        assert hl.active_language == "en"
        hl._cycle_language()
        assert hl.active_language == "en"

    def test_cycles_through_languages(self):
        hl = self._make_listener(["en", "af", "de"])
        assert hl.active_language == "en"
        hl._cycle_language()
        assert hl.active_language == "af"
        hl._cycle_language()
        assert hl.active_language == "de"

    def test_wraps_around(self):
        hl = self._make_listener(["en", "af"])
        hl._cycle_language()  # -> af
        hl._cycle_language()  # -> en (wrap)
        assert hl.active_language == "en"

    def test_calls_on_language_change(self):
        callback = MagicMock()
        hl = HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            languages=["en", "af"],
            on_language_change=callback,
        )
        hl._cycle_language()
        callback.assert_called_once_with("af")
