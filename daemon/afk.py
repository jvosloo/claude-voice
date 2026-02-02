"""AFK mode manager - bridges Claude Code sessions to Telegram."""

import os
import subprocess
import time

from daemon.telegram import TelegramClient
from daemon.request_queue import RequestQueue, QueuedRequest
from daemon.request_router import QueueRouter
from daemon.session_presenter import SingleChatPresenter
from daemon.tmux_monitor import TmuxMonitor

# Response files directory
RESPONSE_DIR = os.path.expanduser("/tmp/claude-voice/sessions")

# Telegram message limit (4096 max, reserve space for header/buttons/HTML)
TELEGRAM_MAX_CHARS = 3900

# Setup instructions for /sessions (tmux + shell wrapper)
_TMUX_SETUP_STEPS = (
    "<b>Setup:</b>\n"
    "1. <code>brew install tmux</code>\n"
    "2. Add to ~/.zshrc:\n"
    "<code>source ~/.claude-voice/claude-wrapper.sh</code>\n"
    "3. Run <code>claude</code> in a new terminal"
)
_WRAPPER_SETUP_STEP = (
    "Add to ~/.zshrc:\n"
    "<code>source ~/.claude-voice/claude-wrapper.sh</code>"
)

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
        self._session_tty_paths = {}  # session -> TTY device path (e.g. /dev/ttys005)
        self._reply_target = None  # session that next free text reply goes to
        self._tmux_monitor = TmuxMonitor()
        self._tmux_reply = False  # True when reply target is tmux-based (not tty-based)
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

        # Create response directory
        os.makedirs(RESPONSE_DIR, exist_ok=True)

        self.active = True

        # Send activation message
        self._send("AFK mode active. Send /help for usage.")

        # Warn about /sessions setup (tmux + shell wrapper)
        tmux_ok = self._tmux_monitor.is_available()
        wrapper_ok = self._check_shell_wrapper()

        if not tmux_ok:
            self._send(
                "\u26a0\ufe0f tmux not found \u2014 /sessions (remote prompts) won't work.\n\n"
                + _TMUX_SETUP_STEPS
            )
        elif not wrapper_ok:
            self._send(
                "\u26a0\ufe0f tmux wrapper not found in shell config \u2014 "
                "sessions won't appear in /sessions.\n"
                + _WRAPPER_SETUP_STEP
            )

        return True

    def _check_shell_wrapper(self) -> bool:
        """Check if claude-wrapper.sh is sourced in the user's shell config."""
        for rc in [os.path.expanduser("~/.bashrc"), os.path.expanduser("~/.zshrc")]:
            try:
                with open(rc) as f:
                    if "claude-wrapper" in f.read():
                        return True
            except FileNotFoundError:
                continue
        return False

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
        self._session_contexts.clear()
        self._session_tty_paths.clear()
        self._reply_target = None
        self._tmux_reply = False
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

        # Store TTY path if provided
        tty_path = request.get("tty_path")
        if tty_path:
            self._session_tty_paths[session] = tty_path

        # Handle context-only updates
        if req_type == "context":
            # Update context, set reply target, send with Reply button
            emoji = self._queue.get_session_emoji(session)
            self._reply_target = session
            has_tty = session in self._session_tty_paths
            formatted_context = _markdown_to_telegram_html(display_context[:TELEGRAM_MAX_CHARS])
            text, markup = self._presenter.format_context_message(
                session, emoji, formatted_context, has_tty=has_tty,
            )
            self._presenter.send_to_session(session, text, markup)
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
            emoji = self._queue.get_session_emoji(session)
            last_line = context.strip().split("\n")[-1] if context else "No recent activity"

            # Determine state
            has_pending = session in pending_sessions
            is_reply_target = self._reply_target == session
            has_tty = session in self._session_tty_paths

            if has_pending:
                state = "⏳ waiting for you"
            elif is_reply_target:
                state = "💬 reply target"
            else:
                state = "idle"

            tty_indicator = " 🖥" if has_tty else ""
            lines.append(
                f"{emoji} <b>[{session}]</b>{tty_indicator} — {state}\n"
                f"{_escape_html(last_line)}\n"
            )

        self._send("\n".join(lines))

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

        # Tmux session buttons
        if data.startswith("tmux:"):
            self._client.answer_callback(callback_id, text="OK")
            self._client.edit_message_reply_markup(message_id)
            parts = data.split(":", 2)
            action = parts[1] if len(parts) > 1 else ""
            session = parts[2] if len(parts) > 2 else ""

            if action == "prompt":
                # Verify session is still idle
                status = self._tmux_monitor.get_session_status(session)
                if status["status"] == "idle":
                    self._reply_target = session
                    self._tmux_reply = True
                    emoji = self._queue.get_session_emoji(session)
                    self._presenter.send_to_session(
                        session,
                        f"\U0001f4ac Send a message to {emoji} [{session}]:"
                    )
                else:
                    self._presenter.send_to_session(
                        session,
                        f"\u26a0\ufe0f [{session}] is no longer idle (now: {status['status']})"
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

            # Prefer tmux injection if the session is running in tmux
            if self._tmux_monitor.is_available():
                status = self._tmux_monitor.get_session_status(target_session)
                if status["status"] in ("idle", "working", "waiting"):
                    self._tmux_reply = True
                    self._presenter.send_to_session(
                        target_session,
                        f"💬 Type your reply to [{target_session}]:"
                    )
                    return

            # Fall back to TTY-based osascript injection
            has_tty = target_session in self._session_tty_paths
            if has_tty:
                self._presenter.send_to_session(
                    target_session,
                    f"💬 Type your reply to [{target_session}]:"
                )
            else:
                self._presenter.send_to_session(
                    target_session,
                    f"⚠️ No terminal connected for [{target_session}]. "
                    "Reply not available."
                )
                self._reply_target = None
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

        pending = self._router.route_text_message(text)

        if not pending:
            # No queued request — try reply routing
            if self._reply_target:
                session = self._reply_target
                self._reply_target = None

                if self._tmux_reply:
                    # Tmux-based prompt injection
                    self._tmux_reply = False
                    success = self._tmux_monitor.send_prompt(session, text)
                    if success:
                        emoji = self._queue.get_session_emoji(session)
                        self._presenter.send_to_session(
                            session,
                            f"\u2713 Sent to {emoji} [{session}]: {_escape_html(text)}"
                        )
                    else:
                        self._presenter.send_to_session(
                            session,
                            f"\u26a0\ufe0f Failed to send prompt to [{session}]. Session may no longer be idle."
                        )
                    return
                elif session in self._session_tty_paths:
                    # Existing osascript-based injection
                    success = self._inject_reply(session, text)
                    if success:
                        emoji = self._queue.get_session_emoji(session)
                        self._presenter.send_to_session(
                            session,
                            f"\u2713 Sent to {emoji} [{session}]: {_escape_html(text)}"
                        )
                    else:
                        self._presenter.send_to_session(
                            session,
                            f"\u26a0\ufe0f Terminal for [{session}] may be closed. Reply failed."
                        )
                        del self._session_tty_paths[session]
                    return
                else:
                    self._presenter.send_to_session(
                        "",
                        f"\u26a0\ufe0f No terminal connected for [{session}]."
                    )
                    return
            else:
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
            "/sessions — list tmux sessions and send new prompts\n"
            "/skip — skip current request\n"
            "/flush — clear all pending requests\n"
            "/help — show this message\n"
            "\n"
            "When a request is active, any text you type is\n"
            "sent as the reply."
        )

    def _handle_sessions_command(self) -> None:
        """Handle /sessions command -- list tmux Claude Code sessions."""
        if not self._tmux_monitor.is_available():
            self._send("tmux is not available.\n\n" + _TMUX_SETUP_STEPS)
            return

        statuses = self._tmux_monitor.get_all_session_statuses()
        if not statuses:
            self._send("No Claude Code sessions found in tmux.")
            return

        # Cross-reference with request queue for waiting sessions
        pending_sessions = set()
        pending_counts = {}
        summary = self._queue.get_queue_summary()
        for item in summary:
            s = item['session']
            pending_sessions.add(s)
            pending_counts[s] = pending_counts.get(s, 0) + 1

        now = int(time.time())

        lines = ["\U0001f4cb <b>Sessions</b>\n"]
        keyboard = []

        for info in statuses:
            session = info["session"]
            status = info["status"]
            emoji = self._queue.get_session_emoji(session)

            # Override status if session has pending requests
            if session in pending_sessions:
                count = pending_counts[session]
                status_text = f"waiting for input ({count} pending)"
                status_icon = "\U0001f7e1"
            elif status == "idle":
                # Calculate idle duration
                pane_activity = info.get("pane_activity")
                if pane_activity:
                    idle_secs = now - pane_activity
                    if idle_secs < 60:
                        duration = f"{idle_secs}s"
                    elif idle_secs < 3600:
                        duration = f"{idle_secs // 60}m"
                    else:
                        duration = f"{idle_secs // 3600}h {(idle_secs % 3600) // 60}m"
                    status_text = f"idle ({duration})"
                else:
                    status_text = "idle"
                status_icon = "\U0001f7e2"
            elif status == "working":
                status_text = "working"
                status_icon = "\U0001f535"
            elif status == "dead":
                status_text = "dead"
                status_icon = "\u26ab"
            else:
                status_text = status
                status_icon = "\u26aa"

            lines.append(f"{status_icon} {emoji} <b>[{session}]</b> \u2014 {status_text}")

            # Add button for actionable sessions
            if status == "idle" and session not in pending_sessions:
                # Truncate session name for callback_data (Telegram 64-byte limit)
                # "tmux:prompt:" = 12 chars, leaving ~52 chars for session name
                cb_session = session[:50]
                keyboard.append([{
                    "text": f"{emoji} {session} \u2014 send prompt",
                    "callback_data": f"tmux:prompt:{cb_session}",
                }])
            elif session in pending_sessions:
                # "tmux:queue:" = 11 chars, leaving ~53 chars for session name
                cb_session = session[:50]
                keyboard.append([{
                    "text": f"{emoji} {session} \u2014 show requests",
                    "callback_data": f"tmux:queue:{cb_session}",
                }])

        text = "\n".join(lines)
        markup = {"inline_keyboard": keyboard} if keyboard else None
        self._send(text, reply_markup=markup)

    def _inject_reply(self, session: str, text: str) -> bool:
        """Inject text + Enter into the terminal via osascript keystroke simulation.

        Finds the specific Terminal.app tab by its TTY path so keystrokes
        go to the right window. For AFK mode this is fine — user isn't at
        the computer so focus stealing is a non-issue. macOS 15+ disabled
        TIOCSTI, so osascript is the only reliable cross-process input
        injection method.

        Returns True on success, False on error.
        """
        if session not in self._session_tty_paths:
            return False

        tty_path = self._session_tty_paths[session]
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        # Find the Terminal.app tab matching this session's TTY, bring it
        # to front, then type via System Events keystroke simulation
        script = (
            'tell application "Terminal"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            f'      if tty of t is "{tty_path}" then\n'
            '        set frontmost of w to true\n'
            '        set selected tab of w to t\n'
            '        activate\n'
            '      end if\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
            'delay 0.3\n'
            f'tell application "System Events" to keystroke "{escaped}"\n'
            'delay 0.1\n'
            'tell application "System Events" to key code 36'  # Return
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"AFK: osascript inject failed: {e}")
            return False

    def _type_into_terminal(self, text: str) -> None:
        """Type text into the terminal via osascript.

        Uses stored session info to verify a terminal exists.
        Falls back to notification if no terminal is tracked.
        """
        # Find session from active request
        active = self._queue.get_active()
        session = active.session if active else None

        if session and session in self._session_tty_paths:
            success = self._inject_reply(session, text)
            if success:
                self._send(f"💬 Typed into terminal: {_escape_html(text)}")
                return

        # No terminal available — notify user
        self._send(
            f"⚠️ No terminal connected. Could not type: {_escape_html(text)}"
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
        self._session_tty_paths.pop(session, None)
        if self._reply_target == session:
            self._reply_target = None
            self._tmux_reply = False


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
