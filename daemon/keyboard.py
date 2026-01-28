"""Keyboard simulation for Claude Voice daemon."""

import time
from pynput.keyboard import Controller, Key
from typing import Optional

class KeyboardSimulator:
    """Types text by simulating keyboard input."""

    def __init__(self, typing_delay: float = 0.01, auto_submit: bool = True):
        self.typing_delay = typing_delay
        self.auto_submit = auto_submit
        self._keyboard = Controller()

    def type_text(self, text: str) -> None:
        """Type text character by character.

        Args:
            text: The text to type
        """
        if not text:
            return

        for char in text:
            self._keyboard.type(char)
            if self.typing_delay > 0:
                time.sleep(self.typing_delay)

        if self.auto_submit:
            time.sleep(0.1)  # Small pause before Enter
            self._keyboard.press(Key.enter)
            self._keyboard.release(Key.enter)
