"""Keyboard simulation for Claude Voice daemon."""

import time
from pynput.keyboard import Controller, Key

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
            # Pause before Enter to let UI catch up
            # Use whichever is longer: text-based pause or typing-time-based pause
            text_pause = len(text) * 0.002  # 2ms per char for UI rendering
            typing_time = len(text) * self.typing_delay
            pause = max(0.1, text_pause, typing_time * 0.2)  # 20% of typing time
            time.sleep(pause)
            self._keyboard.press(Key.enter)
            self._keyboard.release(Key.enter)
