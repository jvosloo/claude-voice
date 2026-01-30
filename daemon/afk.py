"""AFK mode manager - bridges Claude Code sessions to Telegram."""

import json
import os
import threading
import time

from daemon.telegram import TelegramClient, make_permission_keyboard

# Response files directory
RESPONSE_DIR = os.path.expanduser("/tmp/claude-voice/sessions")

class PendingRequest:
    """A request from a hook waiting for a Telegram response."""

    def __init__(self, session: str, req_type: str, prompt: str, message_id: int | None = None):
        self.session = session
        self.req_type = req_type   # "permission" or "input"
        self.prompt = prompt
        self.message_id = message_id
        self.timestamp = time.time()


class AfkManager:
    """Manages AFK mode state and Telegram communication."""

    def __init__(self, config):
        self.config = config
        self.active = False
        self._client = None
        self._pending = {}  # message_id -> PendingRequest
        self._pending_lock = threading.Lock()
        self._session_contexts = {}  # session -> last known context string
        self._previous_mode = None  # mode before AFK was activated
        self._on_deactivate = None  # callback when AFK is turned off

    @property
    def is_configured(self) -> bool:
        """Check if Telegram credentials are configured."""
        return bool(self.config.afk.telegram.bot_token and self.config.afk.telegram.chat_id)

    def activate(self, on_deactivate=None) -> bool:
        """Activate AFK mode. Returns True on success."""
        if not self.is_configured:
            return False

        self._on_deactivate = on_deactivate
        self._client = TelegramClient(
            self.config.afk.telegram.bot_token,
            self.config.afk.telegram.chat_id,
        )

        # Verify connection
        if not self._client.verify():
            self._client = None
            return False

        # Create response directory
        os.makedirs(RESPONSE_DIR, exist_ok=True)

        self.active = True
        self._client.start_polling(
            on_callback=self._handle_callback,
            on_message=self._handle_message,
        )

        # Send activation message
        self._client.send_message("AFK mode active.")

        return True

    def deactivate(self) -> None:
        """Deactivate AFK mode."""
        if not self.active:
            return

        self.active = False
        if self._client:
            self._client.send_message("AFK mode off. Back to voice.")
            self._client.stop_polling()
            self._client = None

        with self._pending_lock:
            self._pending.clear()

        if self._on_deactivate:
            self._on_deactivate()
            self._on_deactivate = None

    def handle_hook_request(self, request: dict) -> dict:
        """Handle a request from a hook. Returns response for the hook.

        Returns:
            {"wait": True, "response_path": "/tmp/claude-voice/sessions/<session>/response"}
            or {"wait": False} if not in AFK mode.
        """
        if not self.active:
            return {"wait": False}

        session = request.get("session", "unknown")
        req_type = request.get("type", "input")  # "permission" or "input"
        context = request.get("context", "")
        prompt = request.get("prompt", "")

        # Store latest context for /status
        if context:
            self._session_contexts[session] = context

        # Build Telegram message
        lines = [f"<b>[{session}]</b>"]
        if context:
            # Truncate context to configured lines
            context_lines = context.strip().split("\n")
            max_lines = self.config.afk.context_lines
            if len(context_lines) > max_lines:
                context_lines = context_lines[-max_lines:]
            lines.append(
                "<pre>" + _escape_html("\n".join(context_lines)) + "</pre>"
            )

        if req_type == "permission":
            lines.append(f"\nPermission: {_escape_html(prompt)}")
            markup = make_permission_keyboard()
        else:
            lines.append(f"\nClaude asks: {_escape_html(prompt)}")
            lines.append("\nReply with your answer.")
            markup = None

        text = "\n".join(lines)
        msg_id = self._client.send_message(text, reply_markup=markup)

        # Register pending request
        pending = PendingRequest(session, req_type, prompt, msg_id)
        if msg_id:
            with self._pending_lock:
                self._pending[msg_id] = pending

        # Tell hook where to find the response
        response_path = self._response_path(session)
        return {"wait": True, "response_path": response_path}

    def handle_status_request(self) -> None:
        """Handle /status command from Telegram."""
        if not self._session_contexts:
            self._client.send_message("No active sessions.")
            return

        lines = ["<b>Active sessions:</b>\n"]
        for session, context in self._session_contexts.items():
            last_line = context.strip().split("\n")[-1] if context else "No recent activity"
            # Check if there's a pending request
            has_pending = any(
                p.session == session for p in self._pending.values()
            )
            status = " (waiting for you)" if has_pending else ""
            lines.append(f"<b>[{session}]</b>{status}\n{_escape_html(last_line)}\n")

        self._client.send_message("\n".join(lines))

    def _handle_callback(self, callback_id: str, data: str, message_id: int | None) -> None:
        """Handle an inline button press from Telegram."""
        self._client.answer_callback(callback_id, text=f"Sent: {data}")

        with self._pending_lock:
            pending = self._pending.pop(message_id, None)

        if not pending:
            return

        # Remove buttons from the message
        self._client.edit_message_reply_markup(message_id)

        # Write response for the hook
        self._write_response(pending.session, data)

    def _handle_message(self, text: str) -> None:
        """Handle a text message from Telegram."""
        # Handle commands
        if text.strip().lower() == "/back":
            self.deactivate()
            return

        if text.strip().lower() == "/status":
            self.handle_status_request()
            return

        # Route text reply to the most recent pending input request
        with self._pending_lock:
            # Find most recent pending input (not permission) request
            target = None
            for msg_id, pending in sorted(
                self._pending.items(), key=lambda x: x[1].timestamp, reverse=True
            ):
                if pending.req_type == "input":
                    target = (msg_id, pending)
                    break
            # If no input request, try any pending request
            if not target:
                for msg_id, pending in sorted(
                    self._pending.items(), key=lambda x: x[1].timestamp, reverse=True
                ):
                    target = (msg_id, pending)
                    break

            if target:
                msg_id, pending = target
                del self._pending[msg_id]

        if target:
            msg_id, pending = target
            self._write_response(pending.session, text)
            self._client.send_message(
                f"Sent to [{pending.session}]: {_escape_html(text)}"
            )
        else:
            self._client.send_message("No pending requests to respond to.")

    def _response_path(self, session: str) -> str:
        """Get the response file path for a session."""
        session_dir = os.path.join(RESPONSE_DIR, session)
        os.makedirs(session_dir, exist_ok=True)
        return os.path.join(session_dir, "response")

    def _write_response(self, session: str, response: str) -> None:
        """Write a response for a hook to pick up."""
        path = self._response_path(session)
        with open(path, "w") as f:
            f.write(response)

    def cleanup_session(self, session: str) -> None:
        """Clean up response files for a session that has ended."""
        session_dir = os.path.join(RESPONSE_DIR, session)
        if os.path.exists(session_dir):
            import shutil
            shutil.rmtree(session_dir, ignore_errors=True)

        # Remove pending requests for this session
        with self._pending_lock:
            to_remove = [
                mid for mid, p in self._pending.items() if p.session == session
            ]
            for mid in to_remove:
                del self._pending[mid]

        self._session_contexts.pop(session, None)


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
