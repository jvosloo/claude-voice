"""Integration tests for AFK state machine (daemon/afk.py)."""

import threading
from unittest.mock import MagicMock, patch

from daemon.afk import AfkManager, PendingRequest, TELEGRAM_MAX_CHARS
from daemon.config import AfkConfig, AfkTelegramConfig, Config, InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig


def _make_config(bot_token="tok", chat_id="123"):
    return Config(
        input=InputConfig(),
        transcription=TranscriptionConfig(),
        speech=SpeechConfig(),
        audio=AudioConfig(),
        overlay=OverlayConfig(),
        afk=AfkConfig(
            telegram=AfkTelegramConfig(bot_token=bot_token, chat_id=chat_id),
        ),
    )


def _make_active_manager():
    """Create an AfkManager in active state with mocked Telegram client."""
    cfg = _make_config()
    mgr = AfkManager(cfg)
    mgr._client = MagicMock()
    mgr._client.send_message.return_value = 100  # message ID
    mgr.active = True
    return mgr


class TestAfkManagerState:

    def test_is_configured_with_credentials(self):
        mgr = AfkManager(_make_config())
        assert mgr.is_configured is True

    def test_not_configured_without_credentials(self):
        mgr = AfkManager(_make_config(bot_token="", chat_id=""))
        assert mgr.is_configured is False

    def test_activate_sets_active(self):
        mgr = AfkManager(_make_config())
        mgr._client = MagicMock()
        mgr._client.send_message.return_value = 1

        with patch("daemon.afk.os.makedirs"):
            assert mgr.activate() is True
        assert mgr.active is True

    def test_activate_fails_without_client(self):
        mgr = AfkManager(_make_config())
        assert mgr.activate() is False
        assert mgr.active is False

    def test_deactivate_clears_state(self):
        mgr = _make_active_manager()
        mgr._pending[1] = MagicMock()
        mgr._sent_message_ids = [1, 2, 3]

        mgr.deactivate()

        assert mgr.active is False
        assert len(mgr._pending) == 0
        assert len(mgr._sent_message_ids) == 1  # deactivate sends one message

    def test_deactivate_noop_when_inactive(self):
        mgr = AfkManager(_make_config())
        mgr.deactivate()  # should not raise
        assert mgr.active is False


class TestHandleHookRequest:

    def test_returns_no_wait_when_inactive(self):
        mgr = AfkManager(_make_config())
        resp = mgr.handle_hook_request({"type": "permission"})
        assert resp == {"wait": False}

    def test_context_type_no_wait(self):
        mgr = _make_active_manager()
        resp = mgr.handle_hook_request({
            "session": "test-session",
            "type": "context",
            "context": "Some context",
        })
        assert resp == {"wait": False}

    def test_permission_returns_wait_with_path(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test-session",
                "type": "permission",
                "prompt": "Run command?",
            })
        assert resp["wait"] is True
        assert "response" in resp["response_path"]

    def test_permission_registers_pending(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            mgr.handle_hook_request({
                "session": "test-session",
                "type": "permission",
                "prompt": "Allow?",
            })
        assert len(mgr._pending) == 1

    def test_ask_user_question_with_options(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test",
                "type": "ask_user_question",
                "questions": [
                    {
                        "question": "Which approach?",
                        "options": [
                            {"label": "A", "description": "First"},
                            {"label": "B", "description": "Second"},
                        ],
                    }
                ],
            })
        assert resp["wait"] is True

    def test_input_type(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test",
                "type": "input",
                "prompt": "Enter name:",
            })
        assert resp["wait"] is True

    def test_context_truncation(self):
        mgr = _make_active_manager()
        long_context = "Line\n" * 2000  # well over TELEGRAM_MAX_CHARS
        resp = mgr.handle_hook_request({
            "session": "test",
            "type": "context",
            "context": long_context,
        })
        # The message sent to Telegram should be truncated
        call_args = mgr._client.send_message.call_args[0][0]
        assert len(call_args) <= TELEGRAM_MAX_CHARS + 500  # header overhead


class TestHandleCallback:

    def test_writes_response_for_pending(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "permission", "Allow?", 100,
                                 response_path="/tmp/test_resp")

        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_callback("cb1", "yes", 100)

        mock_write.assert_called_once_with("/tmp/test_resp", "yes")
        assert 100 not in mgr._pending

    def test_ignores_unknown_message_id(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_callback("cb1", "yes", 999)
        mock_write.assert_not_called()


class TestHandleMessage:

    def test_afk_command(self):
        mgr = _make_active_manager()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/afk")
        toggle.assert_called_once()

    def test_back_command_deactivates(self):
        mgr = _make_active_manager()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/back")
        toggle.assert_called_once()

    def test_status_command(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "handle_status_request") as mock_status:
            mgr._handle_message("/status")
        mock_status.assert_called_once()

    def test_text_routes_to_pending_ask_user(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "ask_user_question", "Q?", 100,
                                 response_path="/tmp/resp")
        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_message("my answer")

        mock_write.assert_called_once_with("/tmp/resp", "my answer")

    def test_text_routes_to_pending_input_when_no_ask(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "input", "Name?", 100,
                                 response_path="/tmp/resp")
        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_message("Johan")

        mock_write.assert_called_once_with("/tmp/resp", "Johan")

    def test_text_types_into_terminal_when_no_pending(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "_type_into_terminal") as mock_type:
            mgr._handle_message("some text")
        mock_type.assert_called_once_with("some text")

    def test_not_afk_rejects_non_commands(self):
        mgr = AfkManager(_make_config())
        mgr._client = MagicMock()
        mgr._client.send_message.return_value = 1
        mgr.active = False

        mgr._handle_message("hello")
        # Should send "Not in AFK mode" message
        mgr._client.send_message.assert_called_once()
        assert "Not in AFK" in mgr._client.send_message.call_args[0][0]
