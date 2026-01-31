"""Request routing abstractions for AFK mode."""

from abc import ABC, abstractmethod
from daemon.request_queue import RequestQueue, QueuedRequest


class RequestRouter(ABC):
    """Routes responses to pending requests. Swappable implementation."""

    @abstractmethod
    def route_button_press(self, callback_data: str, message_id: int) -> QueuedRequest | None:
        """Find the request associated with this button press."""
        pass

    @abstractmethod
    def route_text_message(self, text: str, context: dict = None) -> QueuedRequest | None:
        """Find the request that should receive this text."""
        pass


class QueueRouter(RequestRouter):
    """Routes to active request only (queue-based system)."""

    def __init__(self, queue: RequestQueue):
        self._queue = queue

    def route_button_press(self, callback_data: str, message_id: int) -> QueuedRequest | None:
        """Route button press to active request if message_id matches."""
        active = self._queue.get_active()
        if active and active.message_id == message_id:
            return active
        return None

    def route_text_message(self, text: str, context: dict = None) -> QueuedRequest | None:
        """Route text message to active request only."""
        return self._queue.get_active()
