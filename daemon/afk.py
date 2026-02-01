"""AFK mode manager - bridges Claude Code sessions to Telegram."""

import os
import subprocess
import time

from daemon.telegram import TelegramClient
from daemon.request_queue import RequestQueue, QueuedRequest
from daemon.request_router import QueueRouter
from daemon.session_presenter import SingleChatPresenter

# Response files directory
RESPONSE_DIR = os.path.expanduser("/tmp/claude-voice/sessions")

# Telegram message limit (4096 max, reserve space for header/buttons/HTML)
TELEGRAM_MAX_CHARS = 3900

class AfkManager:
    """Manages AFK mode state and Telegram communication."""

    def __init__(self, config):
        self.config = config
        self.active = False
        self._client = None

        self._queue = RequestQueue()
        self._router = None  # Set when client is created
        self._presenter = None  # Set when client is created

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

        self._router = QueueRouter(self._queue)
        self._presenter = SingleChatPresenter(self._client)

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

    def handle_hook_request(self, request: dict) -> dict:
        """Handle a request from a hook. Returns response for the hook.

        Returns:
            {"wait": True, "response_path": "/tmp/claude-voice/sessions/<session>/response"}
            or {"wait": False} if not in AFK mode.
        """
        if not self.active:
            return {"wait": False}

        # Require presenter for queue-based handling
        if not self._presenter:
            return {"wait": False}

        session = request.get("session", "unknown")
        req_type = request.get("type", "input")
        prompt = request.get("prompt", "")
        context = request.get("context", "")
        raw_text = request.get("raw_text", "")

        # Update session context
        display_context = raw_text or context
        if display_context:
            self._session_contexts[session] = display_context
        elif session in self._session_contexts:
            display_context = self._session_contexts[session]

        # Handle context-only updates
        if req_type == "context":
            # Just update context, don't queue
            emoji = self._queue.get_session_emoji(session)
            text = f"{emoji} [{session}]\n{_markdown_to_telegram_html(display_context[:3900])}"
            self._presenter.send_to_session(session, text)
            return {"wait": False}

        # Extract options from AskUserQuestion
        options = None
        questions = request.get("questions", [])
        if questions:
            options = questions[0].get("options", [])

        # Create response path
        response_path = self._response_path(session, suffix=req_type)

        # Create queued request
        queued_req = QueuedRequest(
            session=session,
            req_type=req_type,
            prompt=prompt,
            response_path=response_path,
            options=options,
        )

        # Enqueue request
        status = self._queue.enqueue(queued_req)
        print(f"AFK: enqueued {req_type} from [{session}] → {status}")

        if status == "active":
            # Present immediately
            self._present_active_request()
        else:
            # Send queued notification
            self._send_queued_notification(queued_req)

        return {"wait": True, "response_path": response_path}

    def handle_status_request(self) -> None:
        """Handle /status command from Telegram."""
        if not self._session_contexts:
            self._send("No active sessions.")
            return

        lines = ["<b>Active sessions:</b>\n"]

        # Get all sessions with pending requests from queue
        pending_sessions = set()
        summary = self._queue.get_queue_summary()
        for item in summary:
            pending_sessions.add(item['session'])

        for session, context in self._session_contexts.items():
            last_line = context.strip().split("\n")[-1] if context else "No recent activity"
            # Check if there's a pending request
            has_pending = session in pending_sessions
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
        print(f"AFK: callback received: data={data!r}, msg_id={message_id}, "
              f"queue_active={self._queue.get_active() is not None}")
        self._client.answer_callback(callback_id, text=f"Sent: {data}")

        # Route via QueueRouter
        pending = self._router.route_button_press(data, message_id)

        if not pending:
            return

        # Remove buttons from the message
        self._client.edit_message_reply_markup(message_id)

        # Handle commands (skip, show queue)
        if data.startswith("cmd:"):
            self._handle_queue_command(data[4:])
            return

        # "Other" button: don't dequeue, just prompt for free text
        if data == "opt:__other__":
            self._presenter.send_to_session(
                pending.session, "Type your reply below:"
            )
            return

        # Write response for the hook
        self._write_response(pending.response_path, data)

        # Send confirmation
        self._send_confirmation(pending.session, data)

        # Advance queue
        next_req = self._queue.dequeue_active()
        if next_req:
            self._present_active_request()
        else:
            self._presenter.send_to_session(pending.session, "✅ All requests handled!")

    def _handle_message(self, text: str) -> None:
        """Handle a text message from Telegram."""
        print(f"AFK: message received: {text!r}, "
              f"active={self.active}, "
              f"queue_active={self._queue.get_active() is not None}, "
              f"queue_size={self._queue.size()}")
        cmd = text.strip().lower()

        # Handle commands (work regardless of AFK state)
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
                if self._presenter:
                    self._presenter.send_to_session("", "Not in AFK mode. Send /afk to activate.")
                else:
                    self._send("Not in AFK mode. Send /afk to activate.")
            return

        if cmd == "/status":
            self.handle_status_request()
            return

        if cmd == "/clear":
            self._handle_clear()
            return

        if cmd == "/queue":
            self._send_queue_summary()
            return

        if cmd == "/skip":
            self._handle_queue_command("skip")
            return

        # Not in AFK mode
        if not self.active:
            if self._presenter:
                self._presenter.send_to_session("", "Not in AFK mode. Send /afk to activate.")
            else:
                self._send("Not in AFK mode. Send /afk to activate.")
            return

        # Route text to active request (requires presenter/router)
        if not self._router or not self._presenter:
            return

        pending = self._router.route_text_message(text)

        if not pending:
            self._presenter.send_to_session("", "No active request. Queue is empty.")
            return

        # For permission requests, treat text as a question/comment
        if pending.req_type == "permission":
            self._type_into_terminal(text)
            self._presenter.send_to_session(
                pending.session,
                f"💬 Sent question to [{pending.session}]: {_escape_html(text)}\n\n"
                "Permission will be re-requested after Claude responds."
            )
            # Deny this permission request (user wants more info)
            self._write_response(pending.response_path, "deny_for_question")
            # Dequeue and present next
            next_req = self._queue.dequeue_active()
            if next_req:
                self._present_active_request()
        else:
            # Normal text response
            self._write_response(pending.response_path, text)
            self._send_confirmation(pending.session, text)

            # Advance queue
            next_req = self._queue.dequeue_active()
            if next_req:
                self._present_active_request()
            else:
                self._presenter.send_to_session(pending.session, "✅ All requests handled!")

    def _present_active_request(self) -> None:
        """Present the active request to user."""
        active = self._queue.get_active()
        if not active:
            return

        summary = self._queue.get_queue_summary()
        active_info = summary[0] if summary else {}

        queue_info = {
            'emoji': active_info.get('emoji', '🟢'),
            'queue_size': self._queue.size(),
            'queue_sessions': [s['session'] for s in summary[1:]] if len(summary) > 1 else [],
        }

        text, markup = self._presenter.format_active_request(active, queue_info)
        msg_id = self._presenter.send_to_session(active.session, text, markup)

        # Store message_id for routing
        if msg_id:
            active.message_id = msg_id
            self._sent_message_ids.append(msg_id)

    def _send_queued_notification(self, req: QueuedRequest) -> None:
        """Send notification that request was queued."""
        summary = self._queue.get_queue_summary()

        # Find this request in summary
        req_info = None
        active_info = summary[0] if summary else {}
        for item in summary:
            if item['request'] == req:
                req_info = item
                break

        if not req_info:
            return

        queue_info = {
            'emoji': req_info.get('emoji', '⏸️'),
            'position': req_info.get('position', 0),
            'total': len(summary),
            'active_session': active_info.get('session', 'unknown'),
            'active_type': active_info.get('req_type', 'request'),
        }

        text = self._presenter.format_queued_notification(req, queue_info)
        self._presenter.send_to_session(req.session, text)

    def _send_confirmation(self, session: str, data: str) -> None:
        """Send confirmation that response was sent."""
        emoji = self._queue.get_session_emoji(session)
        text = f"✓ Sent to {emoji} [{session}]: {_escape_html(data)}"
        self._presenter.send_to_session(session, text)

    def _handle_queue_command(self, cmd: str) -> None:
        """Handle queue management commands (skip, show_queue, priority:<session>)."""
        if cmd == "skip":
            next_req = self._queue.skip_active()
            if next_req:
                emoji = self._queue.get_session_emoji(next_req.session)
                self._presenter.send_to_session(
                    "",
                    f"⏭️ Skipped. Next: {emoji} [{next_req.session}]"
                )
                self._present_active_request()

        elif cmd == "show_queue":
            self._send_queue_summary()

        elif cmd.startswith("priority:"):
            session = cmd[9:]  # Extract session name
            jumped = self._queue.priority_jump(session)
            if jumped:
                emoji = self._queue.get_session_emoji(session)
                self._presenter.send_to_session(
                    "",
                    f"⏭️ Jumped to {emoji} [{session}]"
                )
                self._present_active_request()
            else:
                self._presenter.send_to_session(
                    "",
                    f"No pending requests from [{session}]"
                )

    def _send_queue_summary(self) -> None:
        """Send full queue summary to user."""
        summary = self._queue.get_queue_summary()

        if not summary:
            self._presenter.send_to_session("", "Queue is empty.")
            return

        text, markup = self._presenter.format_queue_summary(summary)
        self._presenter.send_to_session("", text, markup)

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

        # Note: Queue cleanup would require additional methods
        # For now, requests will remain in queue until timeout or completion
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
