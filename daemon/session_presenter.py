"""Session presentation abstractions for AFK mode."""

from abc import ABC, abstractmethod
from daemon.request_queue import QueuedRequest


def _safe_callback_data(data: str) -> str:
    """Truncate callback_data to Telegram's 64-byte UTF-8 limit."""
    encoded = data.encode('utf-8')
    if len(encoded) <= 64:
        return data
    return encoded[:64].decode('utf-8', errors='ignore')


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
        markup = self._make_request_buttons(req.req_type, queue_size, req.options)

        return text, markup

    def _make_request_buttons(self, req_type: str, queue_size: int,
                               options: list = None) -> dict:
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
            # Show actual option buttons if available
            if options:
                for opt in options:
                    label = opt.get("label", "?")
                    keyboard.append([
                        {"text": label, "callback_data": _safe_callback_data(f"opt:{label}")},
                    ])
            # Always add "Other" for free-text input
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
            f"⏸️ QUEUED (position {position}/{total}) /queue",
            "",
            f"{emoji} [{req.session}]",
            f"{req.prompt[:100]}...",  # Preview
            "",
            f"Current: [{active_session}] {active_type}",
        ]

        return "\n".join(lines)

    def format_queue_summary(self, summary: list[dict]) -> tuple[str, dict]:
        """Format full queue summary. Returns (message_text, reply_markup)."""
        if not summary:
            return ("Queue is empty.", None)

        total = len(summary)
        lines = [f"📋 QUEUE ({total} total)", ""]

        keyboard = []

        for item in summary:
            emoji = item['emoji']
            session = item['session']
            req_type = item['req_type']
            status = item['status']
            position = item['position']
            waiting_sec = item['waiting_seconds']

            # Format waiting time
            if waiting_sec < 60:
                wait_str = f"{waiting_sec}s"
            elif waiting_sec < 3600:
                wait_str = f"{waiting_sec // 60}m {waiting_sec % 60}s"
            else:
                wait_str = f"{waiting_sec // 3600}h {(waiting_sec % 3600) // 60}m"

            if status == 'active':
                lines.append(f"{emoji} Active: [{session}] {req_type}")
                lines.append(f"  Waiting: {wait_str}")
                # Add skip button
                keyboard.append([{"text": f"{emoji} [{session}] Skip", "callback_data": "cmd:skip"}])
            else:
                lines.append(f"Position {position}: {emoji} [{session}] {req_type}")
                lines.append(f"  Waiting: {wait_str}")
                # Add handle now button
                keyboard.append([{
                    "text": f"{emoji} [{session}] Handle Now",
                    "callback_data": _safe_callback_data(f"cmd:priority:{session}")
                }])

            lines.append("")  # Blank line between items

        text = "\n".join(lines).rstrip()
        markup = {"inline_keyboard": keyboard} if keyboard else None

        return text, markup

    def format_context_message(self, session: str, emoji: str,
                               context_text: str, has_tty: bool = False) -> tuple[str, dict]:
        """Format a context message with Reply button.

        Returns (message_text, reply_markup).
        """
        tty_indicator = " 🖥" if has_tty else ""
        text = f"{emoji} [{session}]{tty_indicator}\n{context_text}"

        markup = {
            "inline_keyboard": [[
                {"text": "💬 Reply", "callback_data": _safe_callback_data(f"reply:{session}")},
            ]]
        }

        return text, markup

    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send message to main chat. Returns message_id."""
        return self._client.send_message(text, reply_markup=markup)
