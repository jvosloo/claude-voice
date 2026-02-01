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


class TestComboHotkey2:
    """Tests for the second combo hotkey slot (speech hotkey)."""

    def _make_listener(self, combo_hotkey_2=None, on_combo_2=None):
        return HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            combo_hotkey_2=combo_hotkey_2,
            on_combo_2=on_combo_2,
        )

    def test_combo2_parses_modifier_and_vk(self):
        hl = self._make_listener(combo_hotkey_2="left_alt+v", on_combo_2=lambda: None)
        assert hl._combo_modifier_2 is not None
        assert hl._combo_vk_2 == 9  # macOS vk code for 'v'

    def test_combo2_none_when_not_set(self):
        hl = self._make_listener()
        assert hl._combo_modifier_2 is None
        assert hl._combo_vk_2 is None

    def test_combo2_fires_callback_on_press(self):
        callback = MagicMock()
        hl = self._make_listener(combo_hotkey_2="left_alt+v", on_combo_2=callback)
        # Simulate: modifier held, then key with matching vk pressed
        modifier_key = hl._combo_modifier_2
        key_v = MagicMock()
        key_v.vk = 9  # vk code for 'v'
        hl._handle_press(modifier_key)
        hl._handle_press(key_v)
        callback.assert_called_once()

    def test_combo2_does_not_fire_without_modifier(self):
        callback = MagicMock()
        hl = self._make_listener(combo_hotkey_2="left_alt+v", on_combo_2=callback)
        key_v = MagicMock()
        key_v.vk = 9
        hl._handle_press(key_v)
        callback.assert_not_called()

    def test_combo2_independent_of_combo1(self):
        """Both combo hotkeys can coexist and fire independently."""
        combo1_cb = MagicMock()
        combo2_cb = MagicMock()
        hl = HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            combo_hotkey="left_alt+a",
            on_combo=combo1_cb,
            combo_hotkey_2="left_alt+v",
            on_combo_2=combo2_cb,
        )
        modifier_key = hl._combo_modifier_2  # left_alt for both
        key_v = MagicMock()
        key_v.vk = 9  # 'v'
        hl._handle_press(modifier_key)
        hl._handle_press(key_v)
        combo2_cb.assert_called_once()
        # combo1 should NOT have fired (vk 9 != vk for 'a')
        combo1_cb.assert_not_called()
