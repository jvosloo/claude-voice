"""AFK mode manager - bridges Claude Code sessions to Telegram."""

import json
import os
import subprocess
import sys
import threading
import time

from daemon.telegram import TelegramClient, make_options_keyboard, make_permission_keyboard

# Response files directory
RESPONSE_DIR = os.path.expanduser("/tmp/claude-voice/sessions")

# Telegram message limit (4096 max, reserve space for header/buttons/HTML)
TELEGRAM_MAX_CHARS = 3900

class PendingRequest:
    """A request from a hook waiting for a Telegram response."""

    def __init__(self, session: str, req_type: str, prompt: str,
                 message_id: int | None = None, response_path: str = ""):
        self.session = session
        self.req_type = req_type   # "permission", "input", or "ask_user_question"
        self.prompt = prompt
        self.message_id = message_id
        self.response_path = response_path
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
        self._sent_message_ids = []  # track all sent message IDs for /clear
        self._previous_mode = None  # mode before AFK was activated
        self._on_toggle = None  # callback for /afk command

    def _send(self, text: str, reply_markup: dict | None = None) -> int | None:
        """Send a Telegram message and track its ID for /clear."""
        msg_id = self._client.send_message(text, reply_markup=reply_markup)
        if msg_id:
            self._sent_message_ids.append(msg_id)
        return msg_id

    @property
    def is_configured(self) -> bool:
        """Check if Telegram credentials are configured."""
        return bool(self.config.afk.telegram.bot_token and self.config.afk.telegram.chat_id)

    def start_listening(self, on_toggle=None) -> bool:
        """Start Telegram polling (always-on). Called once at daemon startup.

        When not in AFK mode, only /afk and other commands are processed.
        Returns True on success.
        """
        if not self.is_configured:
            return False

        self._on_toggle = on_toggle
        self._client = TelegramClient(
            self.config.afk.telegram.bot_token,
            self.config.afk.telegram.chat_id,
        )

        if not self._client.verify():
            self._client = None
            return False

        self._client.start_polling(
            on_callback=self._handle_callback,
            on_message=self._handle_message,
        )
        return True

    def stop_listening(self) -> None:
        """Stop Telegram polling. Called at daemon shutdown."""
        if self._client:
            self._client.stop_polling()
            self._client = None

    def activate(self) -> bool:
        """Activate AFK mode. Returns True on success."""
        if not self._client:
            return False

        # Create response directory
        os.makedirs(RESPONSE_DIR, exist_ok=True)

        self.active = True

        # Send activation message
        self._send("AFK mode active. Send /back to deactivate.")

        return True

    def deactivate(self) -> None:
        """Deactivate AFK mode. Polling continues for /afk command.

        Note: does NOT call the on_deactivate callback. The caller
        (VoiceDaemon._deactivate_afk) is responsible for mode restore
        and UI feedback.
        """
        if not self.active:
            return

        self.active = False
        self._sent_message_ids.clear()
        if self._client:
            self._send("AFK mode off. Send /afk to reactivate.")

        with self._pending_lock:
            self._pending.clear()

    def handle_hook_request(self, request: dict) -> dict:
        """Handle a request from a hook. Returns response for the hook.

        Returns:
            {"wait": True, "response_path": "/tmp/claude-voice/sessions/<session>/response"}
            or {"wait": False} if not in AFK mode.
        """
        if not self.active:
            return {"wait": False}

        session = request.get("session", "unknown")
        req_type = request.get("type", "input")  # "permission", "input", "context", "ask_user_question"
        context = request.get("context", "")
        raw_text = request.get("raw_text", "")
        prompt = request.get("prompt", "")

        # Store latest context for /status (prefer raw_text for full content)
        display_context = raw_text or context
        if display_context:
            self._session_contexts[session] = display_context
        elif session in self._session_contexts:
            # Use last known context as fallback (e.g. permission prompts lack context)
            display_context = self._session_contexts[session]

        max_chars = TELEGRAM_MAX_CHARS
        lines = [f"<b>[{session}]</b>"]
        if display_context:
            context_text = display_context.strip()
            if len(context_text) > max_chars:
                context_text = context_text[-max_chars:]
                # Don't start mid-line
                nl = context_text.find("\n")
                if nl != -1:
                    context_text = context_text[nl + 1:]
            lines.append(
                _markdown_to_telegram_html(context_text)
            )

        if req_type == "context":
            # Context update from speak-response — show text, no pending request
            text = "\n".join(lines)
            self._send(text)
            return {"wait": False}

        if req_type == "permission":
            lines.append(f"\nPermission: {_escape_html(prompt)}")
            markup = make_permission_keyboard()
        elif req_type == "ask_user_question":
            questions = request.get("questions", [])
            for q in questions:
                lines.append(f"\n<b>{_escape_html(q.get('question', ''))}</b>")
                for opt in q.get("options", []):
                    lines.append(
                        f"  • <b>{_escape_html(opt.get('label', ''))}</b>"
                        f" — {_escape_html(opt.get('description', ''))}"
                    )
            # Use first question's options for keyboard buttons
            first_options = questions[0].get("options", []) if questions else []
            markup = make_options_keyboard(first_options) if first_options else None
        else:
            lines.append(f"\nClaude asks: {_escape_html(prompt)}")
            lines.append("\nReply with your answer.")
            markup = None

        text = "\n".join(lines)
        msg_id = self._send(text, reply_markup=markup)

        # Each request type gets its own response file to avoid collisions
        response_path = self._response_path(session, suffix=req_type)

        # Register pending request
        pending = PendingRequest(session, req_type, prompt, msg_id,
                                 response_path=response_path)
        if msg_id:
            with self._pending_lock:
                self._pending[msg_id] = pending

        # Tell hook where to find the response
        return {"wait": True, "response_path": response_path}

    def handle_status_request(self) -> None:
        """Handle /status command from Telegram."""
        if not self._session_contexts:
            self._send("No active sessions.")
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

        self._send("\n".join(lines))

    def _handle_clear(self) -> None:
        """Handle /clear command - delete all tracked bot messages."""
        deleted = 0
        for msg_id in self._sent_message_ids:
            if self._client.delete_message(msg_id):
                deleted += 1
        self._sent_message_ids.clear()
        self._send(f"Cleared {deleted} messages.")

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
        self._write_response(pending.response_path, data)

    def _handle_message(self, text: str) -> None:
        """Handle a text message from Telegram."""
        cmd = text.strip().lower()

        # Commands that work regardless of AFK state
        if cmd == "/afk":
            if self._on_toggle:
                self._on_toggle()
            return

        if cmd == "/back":
            if self.active:
                if self._on_toggle:
                    self._on_toggle()
                else:
                    self.deactivate()
            else:
                self._send("Not in AFK mode. Send /afk to activate.")
            return

        if cmd == "/status":
            self.handle_status_request()
            return

        if cmd == "/clear":
            self._handle_clear()
            return

        # When not in AFK mode, ignore non-command messages
        if not self.active:
            self._send("Not in AFK mode. Send /afk to activate.")
            return

        # Route text reply to the best pending request.
        # Priority: ask_user_question > input > any (permission last)
        with self._pending_lock:
            target = None
            by_recency = sorted(
                self._pending.items(), key=lambda x: x[1].timestamp, reverse=True
            )
            # First: ask_user_question (accepts free-text via "Other")
            for msg_id, pending in by_recency:
                if pending.req_type == "ask_user_question":
                    target = (msg_id, pending)
                    break
            # Then: generic input
            if not target:
                for msg_id, pending in by_recency:
                    if pending.req_type == "input":
                        target = (msg_id, pending)
                        break
            # Fallback: any pending request
            if not target:
                for msg_id, pending in by_recency:
                    target = (msg_id, pending)
                    break

            if target:
                msg_id, pending = target
                del self._pending[msg_id]

        if target:
            msg_id, pending = target
            self._write_response(pending.response_path, text)
            self._send(
                f"Sent to [{pending.session}]: {_escape_html(text)}"
            )
        else:
            # No pending request — type directly into the terminal prompt
            self._type_into_terminal(text)

    def _type_into_terminal(self, text: str) -> None:
        """Type text into the terminal prompt via a background subprocess."""
        self._send(f"Typing into terminal: {_escape_html(text)}")
        # Use the venv Python to get pynput
        venv_python = os.path.expanduser("~/.claude-voice/venv/bin/python3")
        script = (
            "import time, sys\n"
            "from pynput.keyboard import Controller, Key\n"
            "kb = Controller()\n"
            "text = sys.argv[1]\n"
            "time.sleep(0.3)\n"
            "for char in text:\n"
            "    kb.type(char)\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.1)\n"
            "kb.press(Key.enter)\n"
            "kb.release(Key.enter)\n"
        )
        subprocess.Popen(
            [venv_python, "-c", script, text],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _response_path(self, session: str, suffix: str = "") -> str:
        """Get the response file path for a session."""
        session_dir = os.path.join(RESPONSE_DIR, session)
        os.makedirs(session_dir, exist_ok=True)
        filename = f"response_{suffix}" if suffix else "response"
        return os.path.join(session_dir, filename)

    def _write_response(self, response_path: str, response: str) -> None:
        """Write a response for a hook to pick up."""
        with open(response_path, "w") as f:
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


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram HTML. Handles code blocks, inline code, bold, italic."""
    import re

    result = []
    # Split on fenced code blocks first
    parts = re.split(r'(```\w*\n[\s\S]*?```)', text)

    for part in parts:
        # Fenced code block
        m = re.match(r'```(\w*)\n([\s\S]*?)```', part)
        if m:
            lang = m.group(1)
            code = m.group(2).rstrip('\n')
            if lang:
                result.append(f'<pre><code class="language-{_escape_html(lang)}">'
                              f'{_escape_html(code)}</code></pre>')
            else:
                result.append(f'<pre>{_escape_html(code)}</pre>')
            continue

        # Process inline formatting
        # Inline code
        part = re.sub(r'`([^`]+)`', lambda m: f'<code>{_escape_html(m.group(1))}</code>', part)
        # Bold (must be before italic)
        part = re.sub(r'\*\*([^*]+)\*\*', lambda m: f'<b>{m.group(1)}</b>', part)
        # Italic
        part = re.sub(r'\*([^*]+)\*', lambda m: f'<i>{m.group(1)}</i>', part)
        # Escape remaining HTML in non-tagged text
        # We need to escape only the parts that aren't already tagged
        # Simple approach: escape &, <, > that aren't part of our tags
        part = re.sub(r'&(?!amp;|lt;|gt;)', '&amp;', part)
        part = re.sub(r'<(?!/?(b|i|code|pre)[ >])', '&lt;', part)

        result.append(part)

    return ''.join(result)
