"""Session presentation abstractions for AFK mode."""

from abc import ABC, abstractmethod
from daemon.request_queue import QueuedRequest


class SessionPresenter(ABC):
    """Formats and sends messages to Telegram. Swappable for Topics."""

    @abstractmethod
    def format_active_request(self, req: QueuedRequest, queue_info: dict) -> tuple[str, dict]:
        """Format active request. Returns (message_text, reply_markup)."""
        pass

    @abstractmethod
    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send a message. Returns message_id."""
        pass


class SingleChatPresenter(SessionPresenter):
    """Formats messages for single Telegram chat (queue-based)."""

    def __init__(self, telegram_client):
        self._client = telegram_client

    def format_active_request(self, req: QueuedRequest, queue_info: dict) -> tuple[str, dict]:
        """Format active request with emoji, context, and buttons."""
        emoji = queue_info.get('emoji', '🟢')
        queue_size = queue_info.get('queue_size', 0)

        # Build message text
        lines = [
            f"{emoji} ACTIVE REQUEST",
            "",
            f"[{req.session}]",
        ]

        # Add prompt based on type
        if req.req_type == "permission":
            lines.append(f"Permission: {req.prompt}")
        elif req.req_type == "ask_user_question":
            lines.append(req.prompt)
        else:
            lines.append(f"Claude asks: {req.prompt}")

        # Add queue status
        if queue_size > 0:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            plural = "request" if queue_size == 1 else "requests"
            lines.append(f"Queue: {queue_size} more {plural} waiting")

        text = "\n".join(lines)

        # Build button markup
        markup = self._make_request_buttons(req.req_type, queue_size)

        return text, markup

    def _make_request_buttons(self, req_type: str, queue_size: int) -> dict:
        """Create inline keyboard buttons for request type."""
        keyboard = []

        if req_type == "permission":
            # Permission buttons: [Yes] [Always] [No]
            keyboard.append([
                {"text": "✓ Yes", "callback_data": "yes"},
                {"text": "✓ Always", "callback_data": "always"},
                {"text": "✗ No", "callback_data": "no"},
            ])
        elif req_type == "ask_user_question":
            # Options added by caller (not in this method)
            # For now, just add Other button
            keyboard.append([
                {"text": "💬 Other (type reply)", "callback_data": "opt:__other__"},
            ])
        # For "input" type, no predefined buttons (user types freely)

        # Add queue management buttons if there's a queue
        if queue_size > 0:
            keyboard.append([
                {"text": "⏭️ Skip", "callback_data": "cmd:skip"},
                {"text": "👀 Show All", "callback_data": "cmd:show_queue"},
            ])

        return {"inline_keyboard": keyboard}

    def format_queued_notification(self, req: QueuedRequest, queue_info: dict) -> str:
        """Format notification that request was queued."""
        emoji = queue_info.get('emoji', '⏸️')
        position = queue_info.get('position', 0)
        total = queue_info.get('total', 0)
        active_session = queue_info.get('active_session', 'unknown')
        active_type = queue_info.get('active_type', 'request')

        lines = [
            f"⏸️ QUEUED (position {position}/{total})",
            "",
            f"{emoji} [{req.session}]",
            f"{req.prompt[:100]}...",  # Preview
            "",
            f"Current: [{active_session}] {active_type}",
        ]

        return "\n".join(lines)

    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send message to main chat. Returns message_id."""
        return self._client.send_message(text, reply_markup=markup)
