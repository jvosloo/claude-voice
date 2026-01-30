# AFK Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an AFK mode that bridges Claude Code sessions to a Telegram bot, allowing the user to approve permissions and provide text input from their phone.

**Architecture:** New `daemon/telegram.py` handles Telegram Bot API communication. New `daemon/afk.py` manages AFK state, pending requests, and response routing. Hooks are modified to send session context and optionally block waiting for a Telegram response. The daemon's socket server and voice command handler are extended to support the new mode.

**Tech Stack:** Python 3.12+, `requests` library for Telegram Bot API, existing Unix socket IPC, file-based response routing.

---

### Task 1: Add `requests` dependency and AFK config dataclass

**Files:**
- Modify: `.worktrees/afk-mode/requirements.txt`
- Modify: `.worktrees/afk-mode/daemon/config.py`
- Modify: `.worktrees/afk-mode/config.yaml.example`

**Step 1: Add `requests` to requirements.txt**

Add to the end of `requirements.txt`:

```
# AFK mode (Telegram)
requests>=2.28.0
```

**Step 2: Add AFK config dataclass to `daemon/config.py`**

After `OverlayConfig` (line 54), add:

```python
@dataclass
class AfkTelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

@dataclass
class AfkConfig:
    telegram: AfkTelegramConfig = None
    hotkey: str = "right_alt+a"
    voice_commands_activate: list = None
    voice_commands_deactivate: list = None
    context_lines: int = 10

    def __post_init__(self):
        if self.telegram is None:
            self.telegram = AfkTelegramConfig()
        elif isinstance(self.telegram, dict):
            self.telegram = AfkTelegramConfig(**self.telegram)
        if self.voice_commands_activate is None:
            self.voice_commands_activate = ["going afk", "away from keyboard"]
        if self.voice_commands_deactivate is None:
            self.voice_commands_deactivate = ["back at keyboard", "i'm back"]
```

Add `afk: AfkConfig` to the `Config` dataclass. In `load_config()`, add:

```python
afk=AfkConfig(**data.get('afk', {})),
```

**Step 3: Add AFK section to `config.yaml.example`**

Add at the end:

```yaml
# AFK Mode (Telegram) - receive notifications on your phone when away
# afk:
#   telegram:
#     bot_token: ""       # Create bot via @BotFather on Telegram
#     chat_id: ""         # Your Telegram chat ID (message @userinfobot)
#   hotkey: "right_alt+a"  # Toggle AFK mode
#   context_lines: 10      # Lines of Claude output to include in messages
```

**Step 4: Commit**

```bash
git add requirements.txt daemon/config.py config.yaml.example
git commit -m "feat: add AFK mode configuration and requests dependency"
```

---

### Task 2: Create `daemon/telegram.py` - Telegram Bot API client

**Files:**
- Create: `.worktrees/afk-mode/daemon/telegram.py`

**Step 1: Create `daemon/telegram.py`**

This module handles all Telegram Bot API communication. No SDK - direct HTTP calls.

```python
"""Telegram Bot API client for AFK mode."""

import json
import requests
import threading
import time

class TelegramClient:
    """Minimal Telegram Bot API client using direct HTTP calls."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._offset = 0  # For long-polling getUpdates
        self._polling = False
        self._poll_thread = None
        self._callback_handler = None  # Called with (callback_query_id, data, message_id)
        self._message_handler = None   # Called with (text,)

    def verify(self) -> bool:
        """Verify bot token and chat_id work. Returns True on success."""
        try:
            resp = requests.get(f"{self._base_url}/getMe", timeout=10)
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception:
            return False

    def send_message(self, text: str, reply_markup: dict | None = None) -> int | None:
        """Send a message. Returns message_id or None on failure."""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            resp = requests.post(
                f"{self._base_url}/sendMessage",
                json=payload,
                timeout=10,
            )
            data = resp.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        except Exception as e:
            print(f"Telegram send error: {e}")
        return None

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        """Answer a callback query (acknowledge button press)."""
        try:
            requests.post(
                f"{self._base_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
                timeout=5,
            )
        except Exception:
            pass

    def edit_message_reply_markup(self, message_id: int, reply_markup: dict | None = None) -> None:
        """Edit the reply markup of a sent message (e.g., remove buttons after press)."""
        try:
            payload = {
                "chat_id": self.chat_id,
                "message_id": message_id,
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)
            else:
                payload["reply_markup"] = json.dumps({"inline_keyboard": []})
            requests.post(
                f"{self._base_url}/editMessageReplyMarkup",
                json=payload,
                timeout=5,
            )
        except Exception:
            pass

    def start_polling(self, on_callback=None, on_message=None) -> None:
        """Start long-polling for updates in a background thread."""
        self._callback_handler = on_callback
        self._message_handler = on_message
        self._polling = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_polling(self) -> None:
        """Stop the polling loop."""
        self._polling = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None

    def _poll_loop(self) -> None:
        """Long-polling loop for incoming updates."""
        consecutive_errors = 0
        while self._polling:
            try:
                resp = requests.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 10},
                    timeout=15,
                )
                data = resp.json()
                if not data.get("ok"):
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        print("Telegram: too many polling errors, stopping")
                        self._polling = False
                        break
                    time.sleep(min(2 ** consecutive_errors, 30))
                    continue

                consecutive_errors = 0
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)

            except requests.exceptions.Timeout:
                continue  # Normal for long-polling
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    print(f"Telegram: polling failed: {e}")
                    self._polling = False
                    break
                time.sleep(min(2 ** consecutive_errors, 30))

    def _handle_update(self, update: dict) -> None:
        """Route an incoming update to the appropriate handler."""
        # Validate chat_id on ALL incoming messages
        callback = update.get("callback_query")
        if callback:
            msg = callback.get("message", {})
            chat = msg.get("chat", {})
            if str(chat.get("id")) != str(self.chat_id):
                return  # Ignore messages from other chats
            if self._callback_handler:
                self._callback_handler(
                    callback["id"],
                    callback.get("data", ""),
                    msg.get("message_id"),
                )
            return

        message = update.get("message")
        if message:
            chat = message.get("chat", {})
            if str(chat.get("id")) != str(self.chat_id):
                return  # Ignore messages from other chats
            text = message.get("text", "")
            if self._message_handler and text:
                self._message_handler(text)


def make_permission_keyboard() -> dict:
    """Create an inline keyboard with Yes/No buttons for permission prompts."""
    return {
        "inline_keyboard": [
            [
                {"text": "✓ Yes", "callback_data": "yes"},
                {"text": "✗ No", "callback_data": "no"},
            ]
        ]
    }
```

**Step 2: Commit**

```bash
git add daemon/telegram.py
git commit -m "feat: add Telegram Bot API client for AFK mode"
```

---

### Task 3: Create `daemon/afk.py` - AFK mode manager

**Files:**
- Create: `.worktrees/afk-mode/daemon/afk.py`

**Step 1: Create `daemon/afk.py`**

This module manages AFK state, pending requests, and routes responses between Telegram and Claude Code hooks.

```python
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
```

**Step 2: Commit**

```bash
git add daemon/afk.py
git commit -m "feat: add AFK mode manager with Telegram request routing"
```

---

### Task 4: Modify hooks to send session context and support AFK blocking

**Files:**
- Modify: `.worktrees/afk-mode/hooks/notify-permission.py`
- Modify: `.worktrees/afk-mode/hooks/speak-response.py`
- Modify: `.worktrees/afk-mode/hooks/notify-error.py`

**Step 1: Update `hooks/notify-permission.py`**

The permission hook needs to:
1. Send session ID and context to the daemon
2. Receive a response indicating whether to wait (AFK mode)
3. If waiting, poll a response file and type the answer

Replace the current socket send block (lines 47-55) with a new approach. The full updated file:

```python
#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code Notification hook to notify when permission is needed.

Uses the Notification hook with permission_prompt matcher, which fires
only when Claude Code actually shows a permission dialog to the user.
"""

import json
import os
import socket
import sys
import time

TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
AFK_RESPONSE_TIMEOUT = 600  # 10 minutes


def send_to_daemon(payload: dict) -> dict | None:
    """Send JSON to daemon and receive a JSON response."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)  # Signal we're done sending
        # Read response
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        if data:
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    except Exception:
        pass
    return None


def wait_for_response(response_path: str) -> str | None:
    """Poll for a response file. Returns response text or None on timeout."""
    deadline = time.time() + AFK_RESPONSE_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(response_path):
            try:
                with open(response_path) as f:
                    response = f.read().strip()
                os.remove(response_path)
                return response
            except Exception:
                pass
        time.sleep(1)
    return None


def type_response(text: str) -> None:
    """Type a response into the terminal using pynput."""
    from pynput.keyboard import Controller, Key
    kb = Controller()
    time.sleep(0.1)
    for char in text:
        kb.type(char)
        time.sleep(0.01)
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)


def main():
    # Check mode - only fire in notify or AFK-eligible modes
    mode = ""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                mode = f.read().strip()
        except Exception:
            return

    if mode not in ("notify", "afk"):
        return

    # Check if silent (but not in AFK mode - AFK overrides silent)
    if mode != "afk" and os.path.exists(SILENT_FLAG):
        return

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    if hook_input.get("notification_type") != "permission_prompt":
        return

    session = os.path.basename(os.getcwd())
    message = hook_input.get("message", "Permission needed")

    # Send to daemon with session info
    response = send_to_daemon({
        "notify_category": "permission",
        "session": session,
        "prompt": message,
        "type": "permission",
    })

    # If daemon says to wait (AFK mode), poll for response
    if response and response.get("wait"):
        response_path = response.get("response_path", "")
        if response_path:
            answer = wait_for_response(response_path)
            if answer and answer.lower() in ("yes", "y"):
                type_response("y")


if __name__ == "__main__":
    main()
```

**Step 2: Update `hooks/speak-response.py`**

Add session context to the message sent to daemon. Add the same AFK response handling for when Claude is asking a question. Modify the `speak()` function and `main()`:

After the existing `speak()` function, add `send_with_context()`:

```python
def send_with_context(text: str, config: dict) -> dict | None:
    """Send text to daemon with session context. Returns daemon response."""
    if not text:
        return None

    session = os.path.basename(os.getcwd())

    # Get last N lines as context
    context_lines = text.strip().split("\n")[-10:]
    context = "\n".join(context_lines)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps({
            "text": text,
            "voice": config.get("voice", "af_heart"),
            "speed": config.get("speed", 1.0),
            "lang_code": config.get("lang_code", "a"),
            "session": session,
            "context": context,
        }).encode())
        s.shutdown(socket.SHUT_WR)
        # Read response
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        if data:
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    except Exception:
        pass
    return None
```

Update `main()` to use `send_with_context()` instead of `speak()`:

```python
def main():
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    transcript_path = hook_input.get('transcript_path')
    if not transcript_path:
        return

    config = load_config()

    if not config.get('enabled', True):
        return
    if os.path.exists(SILENT_FLAG):
        # Check if in AFK mode (AFK overrides silent)
        mode = ""
        if os.path.exists(os.path.expanduser("~/.claude-voice/.mode")):
            try:
                with open(os.path.expanduser("~/.claude-voice/.mode")) as f:
                    mode = f.read().strip()
            except Exception:
                pass
        if mode != "afk":
            return

    text = extract_last_assistant_message(transcript_path)
    text = clean_text_for_speech(text, config)

    if text:
        send_with_context(text, config)
```

**Step 3: Update `hooks/notify-error.py`**

Add AFK mode support: in AFK mode, also write the error flag (don't skip just because mode is not "notify").

Change the mode check (lines 28-29) from:
```python
    if mode != "notify":
        return
```
to:
```python
    if mode not in ("notify", "afk"):
        return
```

**Step 4: Commit**

```bash
git add hooks/notify-permission.py hooks/speak-response.py hooks/notify-error.py
git commit -m "feat: update hooks with session context and AFK response handling"
```

---

### Task 5: Modify daemon socket server to support AFK mode

**Files:**
- Modify: `.worktrees/afk-mode/daemon/main.py`

**Step 1: Add AFK imports and state to `VoiceDaemon.__init__`**

At the top of `main.py`, add import:

```python
from daemon.afk import AfkManager
```

In `VoiceDaemon.__init__`, after `self._interrupted_tts = False` (line 125), add:

```python
        self.afk = AfkManager(self.config)
```

**Step 2: Modify `_run_tts_server` to handle AFK mode**

The socket server needs to:
1. Send a JSON response back to the hook (not just receive)
2. Route requests through AfkManager when AFK is active
3. Pass session/context from hooks

Replace the connection handling in `_run_tts_server` (the try block inside the while loop, lines 199-231) with:

```python
            try:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk

                request = json.loads(data.decode())

                # Check if this is an AFK-eligible request
                session = request.get("session")

                if self.afk.active and session:
                    # Route through AFK manager
                    response = self.afk.handle_hook_request(request)
                    # Send response back to hook
                    conn.sendall(json.dumps(response).encode())
                    conn.close()
                    continue

                # Not AFK - send non-waiting response and handle normally
                if session:
                    conn.sendall(json.dumps({"wait": False}).encode())
                conn.close()

                # Direct category from hooks (e.g. PreToolUse permission)
                notify_category = request.get("notify_category")
                if notify_category:
                    print(f"Notify: {notify_category}")
                    play_phrase(notify_category, self.config.speech.notify_phrases)
                    continue

                text = request.get("text", "")
                voice = request.get("voice", self.config.speech.voice)
                speed = request.get("speed", self.config.speech.speed)
                lang_code = request.get("lang_code", self.config.speech.lang_code)

                if text:
                    mode = _read_mode()
                    if mode == "notify":
                        category = classify(text)
                        print(f"Notify: {category}")
                        play_phrase(category, self.config.speech.notify_phrases)
                    else:
                        self.tts_engine.speak(text, voice=voice, speed=speed, lang_code=lang_code)
            except Exception as e:
                print(f"TTS server error: {e}")
```

Note: The key change is that `conn.close()` moves inside the logic (after sending a response in AFK mode, or after sending `{"wait": False}` in normal mode). For requests without a session field (backward compat), conn is closed after reading.

**Step 3: Add AFK voice commands to `_handle_voice_command`**

After the existing mode switching commands (line 174), add:

```python
        # AFK mode commands
        if text_lower in self.config.afk.voice_commands_activate:
            if not self.afk.is_configured:
                print("AFK mode: Telegram not configured")
                return True
            if self.afk.active:
                print("Already in AFK mode")
                return True
            self.afk._previous_mode = _read_mode()
            _write_mode("afk")
            if self.afk.activate(on_deactivate=self._exit_afk):
                _play_cue([440, 660, 880])  # Ascending triple-tone
                print("AFK mode activated - notifications going to Telegram")
            else:
                _write_mode(self.afk._previous_mode or "notify")
                print("AFK mode: failed to connect to Telegram")
            return True

        if text_lower in self.config.afk.voice_commands_deactivate:
            if self.afk.active:
                self._exit_afk()
                _play_cue([880, 660, 440])  # Descending triple-tone
                print("AFK mode deactivated - back to voice")
            return True
```

**Step 4: Add `_exit_afk` method to `VoiceDaemon`**

After `_handle_voice_command`, add:

```python
    def _exit_afk(self) -> None:
        """Exit AFK mode and restore previous voice mode."""
        previous = self.afk._previous_mode or "notify"
        self.afk.deactivate()
        _write_mode(previous)
        print(f"Restored {previous} mode")
```

**Step 5: Add AFK mode display to startup banner**

In `run()`, after printing TTS mode (line 317), add:

```python
        if self.afk.is_configured:
            print(f"AFK mode: configured (Telegram)")
        else:
            print(f"AFK mode: not configured (set telegram bot_token and chat_id)")
```

**Step 6: Add AFK cleanup to `_shutdown`**

In `_shutdown()`, before setting `_shutting_down` (line 277), add:

```python
        if self.afk.active:
            self.afk.deactivate()
```

**Step 7: Commit**

```bash
git add daemon/main.py
git commit -m "feat: integrate AFK mode into daemon socket server and voice commands"
```

---

### Task 6: Add AFK hotkey toggle support

**Files:**
- Modify: `.worktrees/afk-mode/daemon/main.py`

**Step 1: Add AFK hotkey listener**

The AFK hotkey is separate from the push-to-talk hotkey. In `VoiceDaemon.__init__`, after the AfkManager initialization, add:

```python
        # AFK hotkey (separate from push-to-talk)
        self._afk_hotkey_listener = None
        afk_hotkey = self.config.afk.hotkey
        if afk_hotkey and "+" in afk_hotkey:
            # Combo hotkey like "right_alt+a" - handle as modifier+key
            self._setup_afk_hotkey(afk_hotkey)
```

Add the setup method:

```python
    def _setup_afk_hotkey(self, hotkey_str: str) -> None:
        """Set up AFK hotkey listener for modifier+key combos."""
        from pynput import keyboard as kb

        parts = hotkey_str.split("+")
        if len(parts) != 2:
            print(f"AFK hotkey: unsupported format '{hotkey_str}' (expected modifier+key)")
            return

        from daemon.hotkey import KEY_MAP
        modifier_name, key_char = parts[0], parts[1]
        modifier = KEY_MAP.get(modifier_name)
        if not modifier:
            print(f"AFK hotkey: unknown modifier '{modifier_name}'")
            return

        pressed_keys = set()

        def on_press(key):
            pressed_keys.add(key)
            try:
                if key == modifier:
                    return
                if hasattr(key, 'char') and key.char == key_char and modifier in pressed_keys:
                    self._toggle_afk()
            except AttributeError:
                pass

        def on_release(key):
            pressed_keys.discard(key)

        self._afk_hotkey_listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._afk_hotkey_listener.start()

    def _toggle_afk(self) -> None:
        """Toggle AFK mode on/off."""
        if self.afk.active:
            self._exit_afk()
            _play_cue([880, 660, 440])
            print("AFK mode deactivated")
        else:
            if not self.afk.is_configured:
                print("AFK mode: Telegram not configured")
                return
            self.afk._previous_mode = _read_mode()
            _write_mode("afk")
            if self.afk.activate(on_deactivate=self._exit_afk):
                _play_cue([440, 660, 880])
                print("AFK mode activated")
            else:
                _write_mode(self.afk._previous_mode or "notify")
                print("AFK mode: failed to connect to Telegram")
```

**Step 2: Stop AFK hotkey in `_shutdown`**

In `_shutdown()`, after stopping the main hotkey listener, add:

```python
        if self._afk_hotkey_listener:
            self._afk_hotkey_listener.stop()
```

**Step 3: Commit**

```bash
git add daemon/main.py
git commit -m "feat: add AFK mode hotkey toggle support"
```

---

### Task 7: Update `config.yaml.example` and README documentation

**Files:**
- Modify: `.worktrees/afk-mode/config.yaml.example`
- Modify: `.worktrees/afk-mode/README.md`

**Step 1: Update config.yaml.example**

Already done in Task 1. Verify the AFK section is present.

**Step 2: Update README.md**

Add an "AFK Mode" section after the "Voice Commands" section. Include:

- What AFK mode does
- One-time Telegram setup (BotFather + chat ID)
- Configuration
- How to activate/deactivate (voice, hotkey, Telegram /back)
- Telegram commands (/status, /back)
- Security considerations

Example content:

```markdown
## AFK Mode

AFK mode lets you interact with Claude Code from your phone via Telegram when you're away from your keyboard. When Claude needs permission or input, you get a Telegram message and can respond directly.

### Setup

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token
4. Search for **@userinfobot** to find your chat ID
5. Add both to your config:

```yaml
afk:
  telegram:
    bot_token: "123456:ABC-DEF..."
    chat_id: "987654321"
```

### Usage

| Action | Method |
|--------|--------|
| Activate | Say "going AFK" or press Right Alt+A |
| Deactivate | Say "back at keyboard", press Right Alt+A, or send `/back` in Telegram |
| Check status | Send `/status` in Telegram |
| Approve permission | Tap ✓ Yes / ✗ No button |
| Provide input | Type your reply in the Telegram chat |

### Security

- Messages are validated by chat ID (only your messages are accepted)
- No ports opened on your machine (uses outbound long-polling)
- Bot token stored in local config.yaml (gitignored)
- Telegram can see message content (not end-to-end encrypted)
```

**Step 3: Commit**

```bash
git add config.yaml.example README.md
git commit -m "docs: add AFK mode setup and usage documentation"
```

---

### Task 8: End-to-end manual testing

**Files:** None (testing only)

**Step 1: Verify config loads correctly**

```bash
cd .worktrees/afk-mode
python3 -c "from daemon.config import load_config; c = load_config(); print(f'AFK configured: {bool(c.afk.telegram.bot_token)}')"
```

Expected: `AFK configured: False` (no token set)

**Step 2: Verify Telegram client works (if token configured)**

```bash
python3 -c "
from daemon.telegram import TelegramClient
c = TelegramClient('YOUR_TOKEN', 'YOUR_CHAT_ID')
print('Verified:', c.verify())
mid = c.send_message('Test from claude-voice!')
print('Message ID:', mid)
"
```

Expected: `Verified: True`, message received on phone.

**Step 3: Test AFK activation via voice command**

1. Start daemon: `python3 -m daemon.main`
2. Hold hotkey, say "going AFK"
3. Verify Telegram message: "AFK mode active."
4. Hold hotkey, say "back at keyboard"
5. Verify Telegram message: "AFK mode off. Back to voice."

**Step 4: Test permission flow in AFK mode**

1. Activate AFK mode
2. In another terminal, run Claude Code and trigger a permission prompt
3. Verify Telegram message with inline buttons
4. Tap "Yes" button
5. Verify permission is approved in Claude Code terminal

**Step 5: Test /status and /back commands**

1. While in AFK mode, send `/status` in Telegram
2. Verify session summary appears
3. Send `/back` in Telegram
4. Verify daemon returns to voice mode

**Step 6: Final commit (if any test-driven fixes were needed)**

```bash
git add -A
git commit -m "fix: address issues found during manual testing"
```
