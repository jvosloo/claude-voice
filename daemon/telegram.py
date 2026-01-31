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

    def delete_message(self, message_id: int) -> bool:
        """Delete a message. Returns True on success."""
        try:
            resp = requests.post(
                f"{self._base_url}/deleteMessage",
                json={"chat_id": self.chat_id, "message_id": message_id},
                timeout=5,
            )
            return resp.json().get("ok", False)
        except Exception:
            return False

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


def make_options_keyboard(options: list[dict]) -> dict:
    """Create an inline keyboard from AskUserQuestion options.

    Each option is {"label": "...", "description": "..."}.
    Creates one button per row, plus an "Other" button at the end.
    Callback data is the option label.
    """
    rows = []
    for opt in options:
        label = opt.get("label", "?")
        rows.append([{"text": label, "callback_data": f"opt:{label}"}])
    return {"inline_keyboard": rows}


def make_permission_keyboard() -> dict:
    """Create an inline keyboard with Yes/Always/No buttons for permission prompts."""
    return {
        "inline_keyboard": [
            [{"text": "\u2713 Yes", "callback_data": "yes"}],
            [{"text": "\u2713 Always allow", "callback_data": "always"}],
            [{"text": "\u2717 No", "callback_data": "no"}],
        ]
    }
