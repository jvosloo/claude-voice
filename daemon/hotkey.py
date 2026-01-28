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
    """Listens for push-to-talk hotkey."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ):
        self.hotkey = KEY_MAP.get(hotkey, keyboard.Key.alt_r)
        self.on_press = on_press
        self.on_release = on_release
        self._listener: Optional[keyboard.Listener] = None
        self._pressed = False

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
