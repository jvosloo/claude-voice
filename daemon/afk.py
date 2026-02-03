"""AFK mode manager - bridges Claude Code sessions to Telegram."""

import os
import shutil
import tempfile
import threading
import time

from daemon.telegram import TelegramClient
from daemon.request_queue import RequestQueue, QueuedRequest
from daemon.request_router import QueueRouter
from daemon.session_presenter import SingleChatPresenter

# Response files directory
RESPONSE_DIR = os.path.expanduser("/tmp/claude-voice/sessions")

# Telegram message limit (4096 max, reserve space for header/buttons/HTML)
TELEGRAM_MAX_CHARS = 3900

# Session dirs older than this are cleaned up on activate()
STALE_SESSION_AGE = 3600  # 1 hour

class AfkManager:
    """Manages AFK mode state and Telegram communication."""

    def __init__(self, config):
        self.config = config
        self.active = False
        self._client = None

        self._queue = RequestQueue()
        self._router = None  # Set when client is created
        self._presenter = None  # Set when client is created

        self._state_lock = threading.Lock()  # protects compound state operations
        self._session_contexts = {}  # session -> last known context string
        self._reply_target = None  # session that next free text reply goes to
        self._last_followup_session = None  # fallback for routing when no explicit target
        self._pending_followups = {}  # session -> list[str] queued messages
        self._previous_mode = None  # mode before AFK was activated
        self._on_toggle = None  # callback for /afk command

    def _send(self, text: str, reply_markup: dict | None = None) -> int | None:
        """Send a Telegram message."""
        return self._client.send_message(text, reply_markup=reply_markup)

    @property
    def is_configured(self) -> bool:
        """Check if Telegram credentials are configured."""
        return bool(self.config.afk.telegram.bot_token and self.config.afk.telegram.chat_id)

    def start_listening(self, on_toggle=None) -> tuple[bool, str]:
        """Start Telegram polling (always-on). Called once at daemon startup.

        When not in AFK mode, only /afk and other commands are processed.
        Returns (ok, error_reason).
        """
        if not self.is_configured:
            return False, ""

        self._on_toggle = on_toggle
        self._client = TelegramClient(
            self.config.afk.telegram.bot_token,
            self.config.afk.telegram.chat_id,
        )

        ok, reason = self._client.verify()
        if not ok:
            self._client = None
            return False, reason

        self._router = QueueRouter(self._queue)
        self._presenter = SingleChatPresenter(self._client)

        self._client.start_polling(
            on_callback=self._handle_callback,
            on_message=self._handle_message,
        )
        return True, ""

    def stop_listening(self) -> None:
        """Stop Telegram polling. Called at daemon shutdown."""
        if self._client:
            self._client.stop_polling()
            self._client = None

    def activate(self) -> bool:
        """Activate AFK mode. Returns True on success."""
        if not self._client:
            return False
        os.makedirs(RESPONSE_DIR, exist_ok=True)
        self._cleanup_stale_sessions()
        self._cleanup_response_files()
        self.active = True
        self._send("AFK mode active. Send /help for usage.")
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
        flushed = self._flush_queue()
        self._unblock_stop_hooks()
        with self._state_lock:
            self._session_contexts.clear()
            self._reply_target = None
            self._last_followup_session = None
            self._pending_followups.clear()
        if self._client:
            if flushed:
                self._send(f"AFK mode off. Flushed {flushed} pending request(s). Send /afk to reactivate.")
            else:
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

        # Handle context-only updates (Stop hook)
        if req_type == "context":
            emoji = self._queue.get_session_emoji(session)
            self._reply_target = session
            self._last_followup_session = session

            # Send context to Telegram with Reply button
            formatted_context = _markdown_to_telegram_html(display_context[:TELEGRAM_MAX_CHARS])
            text, markup = self._presenter.format_context_message(
                session, emoji, formatted_context,
            )
            self._presenter.send_to_session(session, text, markup)

            # Create response path for Stop hook blocking
            response_path = self._response_path(session, suffix="stop")

            # If followups are already queued, deliver immediately
            with self._state_lock:
                if session in self._pending_followups and self._pending_followups[session]:
                    messages = self._pending_followups.pop(session)
                else:
                    messages = None
            if messages:
                combined = "\n\n".join(messages)
                self._write_response(response_path, combined)
                print(f"AFK: delivered {len(messages)} queued followup(s) to [{session}]")

            return {"wait": True, "response_path": response_path}

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
        keyboard = []

        # Get all sessions with pending requests from queue
        pending_sessions = set()
        summary = self._queue.get_queue_summary()
        for item in summary:
            pending_sessions.add(item['session'])

        for session, context in self._session_contexts.items():
            emoji = self._queue.get_session_emoji(session)
            last_line = context.strip().split("\n")[-1] if context else "No recent activity"

            # Determine state
            has_pending = session in pending_sessions
            is_reply_target = self._reply_target == session

            if has_pending:
                state = "⏳ waiting for you"
            elif is_reply_target:
                state = "💬 reply target"
            else:
                state = "idle"

            lines.append(
                f"{emoji} <b>[{session}]</b> — {state}\n"
                f"{_escape_html(last_line)}\n"
            )

            cb_session = session[:50]
            keyboard.append([{
                "text": f"💬 Reply to {emoji} {session}",
                "callback_data": f"reply:{cb_session}",
            }])

        text = "\n".join(lines)
        markup = {"inline_keyboard": keyboard} if keyboard else None
        self._send(text, reply_markup=markup)

    def _flush_queue(self) -> int:
        """Flush all pending requests. Writes __flush__ sentinel so hooks stop waiting.

        Returns the number of flushed requests.
        """
        removed = self._queue.clear()
        for req in removed:
            self._write_response(req.response_path, "__flush__")
        return len(removed)

    def _handle_callback(self, callback_id: str, data: str, message_id: int | None) -> None:
        """Handle an inline button press from Telegram."""
        print(f"AFK: callback received: data={data!r}, msg_id={message_id}, "
              f"queue_active={self._queue.get_active() is not None}")

        # Session buttons (from /sessions command)
        if data.startswith("session:"):
            self._client.answer_callback(callback_id, text="OK")
            self._client.edit_message_reply_markup(message_id)
            parts = data.split(":", 2)
            action = parts[1] if len(parts) > 1 else ""
            session = parts[2] if len(parts) > 2 else ""

            if action == "context":
                emoji = self._queue.get_session_emoji(session)
                context = self._session_contexts.get(session, "")
                if context:
                    formatted = _markdown_to_telegram_html(context[:TELEGRAM_MAX_CHARS])
                    text, markup = self._presenter.format_context_message(
                        session, emoji, formatted,
                    )
                    self._presenter.send_to_session(session, text, markup)
                else:
                    self._reply_target = session
                    self._presenter.send_to_session(
                        session,
                        f"\U0001f4ac Send a message to {emoji} [{session}]:"
                    )
            elif action == "queue":
                # Show pending requests for this session
                summary = self._queue.get_queue_summary()
                session_items = [i for i in summary if i['session'] == session]
                if session_items:
                    text, markup = self._presenter.format_queue_summary(session_items)
                    self._presenter.send_to_session(session, text, markup)
                else:
                    self._presenter.send_to_session(session, f"No pending requests for [{session}].")
            return

        # Queue management commands work from any message (e.g., /queue summary)
        if data.startswith("cmd:"):
            self._client.answer_callback(callback_id, text=f"Sent: {data}")
            self._client.edit_message_reply_markup(message_id)
            self._handle_queue_command(data[4:])
            return

        # Reply button on context messages
        if data.startswith("reply:"):
            self._client.answer_callback(callback_id, text=f"Sent: {data}")
            target_session = data[6:]
            self._reply_target = target_session
            self._presenter.send_to_session(
                target_session,
                f"💬 Type your reply to [{target_session}]:"
            )
            return

        # Route via QueueRouter (matches active request by message_id)
        pending = self._router.route_button_press(data, message_id)

        if not pending:
            self._client.answer_callback(callback_id, text="Request expired")
            self._client.edit_message_reply_markup(message_id)
            return

        self._client.answer_callback(callback_id, text=f"Sent: {data}")

        # Remove buttons from the message
        self._client.edit_message_reply_markup(message_id)

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

        if cmd == "/flush":
            flushed = self._flush_queue()
            self._send(f"Flushed {flushed} pending request(s).")
            return

        if cmd == "/queue":
            self._send_queue_summary()
            return

        if cmd == "/skip":
            self._handle_queue_command("skip")
            return

        if cmd == "/help":
            self._send_help()
            return

        if cmd == "/sessions":
            self._handle_sessions_command()
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

        # Reply target (user tapped Reply) takes priority over queued requests
        with self._state_lock:
            target = self._reply_target
            if target:
                self._reply_target = None
        if target:
            self._last_followup_session = target
            self._deliver_followup(target, text)
            return

        pending = self._router.route_text_message(text)

        if not pending:
            fallback = self._last_followup_session
            if fallback and fallback in self._session_contexts:
                self._deliver_followup(fallback, text)
                return
            self._presenter.send_to_session(
                "", "No active session. Use the Reply button or /sessions to send a message."
            )
            return

        # For permission requests, treat text as a question/comment
        if pending.req_type == "permission":
            # Deny permission and deliver the question as a followup
            self._write_response(pending.response_path, "deny_for_question")
            self._presenter.send_to_session(
                pending.session,
                f"💬 Question sent to [{pending.session}]: {_escape_html(text)}\n\n"
                "Permission denied. Claude will see your question."
            )
            # Queue the question as a followup for when the Stop hook fires
            self._queue_followup(pending.session, text)
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

    def _send_help(self) -> None:
        """Send help message listing available commands."""
        self._send(
            "<b>AFK Mode — Help</b>\n"
            "\n"
            "Respond to Claude Code remotely via Telegram.\n"
            "Permission requests, input prompts, and questions\n"
            "appear here. Reply with buttons or free text.\n"
            "\n"
            "<b>Commands:</b>\n"
            "/afk — toggle AFK mode on/off\n"
            "/back — deactivate AFK mode\n"
            "/status — show active sessions\n"
            "/queue — show pending requests\n"
            "/sessions — list Claude Code sessions and send new prompts\n"
            "/skip — skip current request\n"
            "/flush — clear all pending requests\n"
            "/help — show this message\n"
            "\n"
            "When a request is active, any text you type is\n"
            "sent as the reply."
        )

    def _deliver_followup(self, session: str, text: str) -> None:
        """Deliver a follow-up message to a session's Stop hook response file."""
        self._last_followup_session = session
        # Check if session directory exists before creating it — if it doesn't,
        # no Stop hook has ever registered for this session, so queue instead.
        session_dir = os.path.join(RESPONSE_DIR, session)
        if os.path.isdir(session_dir):
            response_path = self._response_path(session, suffix="stop")
            self._write_response(response_path, text)
            emoji = self._queue.get_session_emoji(session)
            self._presenter.send_to_session(
                session,
                f"\u2713 Sent to {emoji} [{session}]: {_escape_html(text)}"
            )
        else:
            # No active Stop hook — queue for later
            self._queue_followup(session, text)
            emoji = self._queue.get_session_emoji(session)
            self._presenter.send_to_session(
                session,
                f"\U0001f4e8 Queued for {emoji} [{session}]: {_escape_html(text)}\n"
                "Will be delivered when Claude finishes its current turn."
            )

    def _queue_followup(self, session: str, text: str) -> None:
        """Queue a message to be delivered when the next Stop hook fires."""
        with self._state_lock:
            if session not in self._pending_followups:
                self._pending_followups[session] = []
            self._pending_followups[session].append(text)
            count = len(self._pending_followups[session])
        print(f"AFK: queued followup for [{session}], total={count}")

    def _unblock_stop_hooks(self) -> None:
        """Write __back__ sentinel to all Stop hook response files.

        Unconditionally overwrites any existing content — this clears both
        actively-polling hooks AND stale followup files left from a previous
        AFK cycle (e.g. a followup written after the hook already returned).
        """
        try:
            for name in os.listdir(RESPONSE_DIR):
                session_dir = os.path.join(RESPONSE_DIR, name)
                stop_file = os.path.join(session_dir, "response_stop")
                if os.path.isdir(session_dir):
                    self._write_response(stop_file, "__back__")
        except FileNotFoundError:
            pass

    def _handle_sessions_command(self) -> None:
        """Handle /sessions command -- list Claude Code sessions."""
        if not self._session_contexts:
            self._send("No Claude Code sessions found.")
            return

        # Cross-reference with request queue for waiting sessions
        pending_sessions = set()
        pending_counts = {}
        summary = self._queue.get_queue_summary()
        for item in summary:
            s = item['session']
            pending_sessions.add(s)
            pending_counts[s] = pending_counts.get(s, 0) + 1

        lines = ["\U0001f4cb <b>Sessions</b>\n"]
        keyboard = []

        for session in sorted(self._session_contexts):
            emoji = self._queue.get_session_emoji(session)
            cb_session = session[:50]

            if session in pending_sessions:
                count = pending_counts[session]
                status_text = f"waiting for input ({count} pending)"
                lines.append(f"{emoji} <b>[{session}]</b> \u2014 {status_text}")
                keyboard.append([{
                    "text": f"{emoji} {session} \u2014 show requests",
                    "callback_data": f"session:queue:{cb_session}",
                }])
            else:
                status_text = "active"
                lines.append(f"{emoji} <b>[{session}]</b> \u2014 {status_text}")
                keyboard.append([{
                    "text": f"{emoji} {session} \u2014 show context",
                    "callback_data": f"session:context:{cb_session}",
                }])

        text = "\n".join(lines)
        markup = {"inline_keyboard": keyboard} if keyboard else None
        self._send(text, reply_markup=markup)

    def _response_path(self, session: str, suffix: str = "") -> str:
        """Get the response file path for a session."""
        session_dir = os.path.join(RESPONSE_DIR, session)
        os.makedirs(session_dir, exist_ok=True)
        filename = f"response_{suffix}" if suffix else "response"
        return os.path.join(session_dir, filename)

    def _write_response(self, response_path: str, response: str) -> None:
        """Write a response for a hook to pick up.

        Uses write-then-rename for atomic handoff so the polling hook
        never reads a partially-written file.
        """
        dir_path = os.path.dirname(response_path)
        os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".resp_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(response)
            os.rename(tmp_path, response_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def cleanup_session(self, session: str) -> None:
        """Clean up response files for a session that has ended."""
        session_dir = os.path.join(RESPONSE_DIR, session)
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)

        with self._state_lock:
            self._session_contexts.pop(session, None)
            self._pending_followups.pop(session, None)
            if self._reply_target == session:
                self._reply_target = None
            if self._last_followup_session == session:
                self._last_followup_session = None

    def _cleanup_stale_sessions(self) -> None:
        """Remove session directories older than STALE_SESSION_AGE.

        Called on activate() to prevent accumulation of orphaned session
        dirs from crashed hooks or daemon restarts.
        """
        try:
            cutoff = time.time() - STALE_SESSION_AGE
            for name in os.listdir(RESPONSE_DIR):
                session_dir = os.path.join(RESPONSE_DIR, name)
                if not os.path.isdir(session_dir):
                    continue
                try:
                    mtime = os.path.getmtime(session_dir)
                    if mtime < cutoff:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        print(f"AFK: cleaned stale session dir [{name}]")
                except OSError:
                    pass
        except FileNotFoundError:
            pass

    def _cleanup_response_files(self) -> None:
        """Delete stale response_stop files from all session directories.

        Called on activate() so that __back__ sentinels left by the previous
        deactivation don't cause the first Stop hook to return immediately.
        No hooks should be blocking at this point (AFK was off).
        """
        try:
            for name in os.listdir(RESPONSE_DIR):
                session_dir = os.path.join(RESPONSE_DIR, name)
                if not os.path.isdir(session_dir):
                    continue
                stop_file = os.path.join(session_dir, "response_stop")
                try:
                    os.remove(stop_file)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass


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
