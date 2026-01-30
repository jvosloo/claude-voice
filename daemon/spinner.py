"""Animated spinner for long-running operations."""

import sys
import threading
import time


class Spinner:
    """Context manager that shows an animated spinner with a message."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str):
        self.message = message
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join()
        # Clear the spinner line and print done
        sys.stdout.write(f"\r\033[K{self.message} done.\n")
        sys.stdout.flush()

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r\033[K{frame} {self.message}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)