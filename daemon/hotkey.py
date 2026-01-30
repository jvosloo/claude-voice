"""Hotkey detection for Claude Voice daemon."""

from pynput import keyboard
from typing import Callable, Optional
import threading

# Map config names to pynput keys
KEY_MAP = {
    "right_alt": keyboard.Key.alt_r,
    "left_alt": keyboard.Key.alt_l,
    "right_cmd": keyboard.Key.cmd_r,
    "left_cmd": keyboard.Key.cmd_l,
    "right_ctrl": keyboard.Key.ctrl_r,
    "left_ctrl": keyboard.Key.ctrl_l,
    "right_shift": keyboard.Key.shift_r,
    "caps_lock": keyboard.Key.caps_lock,
    "f18": keyboard.Key.f18,
    "f19": keyboard.Key.f19,
}

class HotkeyListener:
    """Listens for push-to-talk hotkey and optional language cycle hotkey."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        language_hotkey: Optional[str] = None,
        languages: Optional[list[str]] = None,
        on_language_change: Optional[Callable[[str], None]] = None,
    ):
        self.hotkey = KEY_MAP.get(hotkey, keyboard.Key.alt_r)
        self.on_press = on_press
        self.on_release = on_release
        self._listener: Optional[keyboard.Listener] = None
        self._pressed = False

        # Language cycling
        self._language_hotkey = KEY_MAP.get(language_hotkey) if language_hotkey else None
        self._languages = languages or ["en"]
        self._language_index = 0
        self._on_language_change = on_language_change

    @property
    def active_language(self) -> str:
        return self._languages[self._language_index]

    def _handle_press(self, key) -> None:
        """Handle key press event."""
        if key == self.hotkey and not self._pressed:
            self._pressed = True
            self.on_press()

    def _handle_release(self, key) -> None:
        """Handle key release event."""
        if key == self.hotkey and self._pressed:
            self._pressed = False
            self.on_release()
        elif key == self._language_hotkey and self._language_hotkey is not None:
            self._cycle_language()

    def _cycle_language(self) -> None:
        self._language_index = (self._language_index + 1) % len(self._languages)
        lang = self._languages[self._language_index]
        if self._on_language_change:
            self._on_language_change(lang)

    def start(self) -> None:
        """Start listening for hotkey."""
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop listening."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        """Wait for listener thread to finish."""
        if self._listener:
            self._listener.join()
