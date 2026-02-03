"""Tests for /sessions command and session callbacks in AfkManager."""

from unittest.mock import Mock, patch
from daemon.afk import AfkManager
from daemon.config import (
    Config, AfkConfig, AfkTelegramConfig,
    InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig
)
from daemon.request_queue import QueuedRequest


def _make_config():
    return Config(
        input=InputConfig(),
        transcription=TranscriptionConfig(),
        speech=SpeechConfig(),
        audio=AudioConfig(),
        overlay=OverlayConfig(),
        afk=AfkConfig(
            telegram=AfkTelegramConfig(bot_token="test_token", chat_id="test_chat"),
        ),
    )


def _make_afk(**overrides):
    """Create an AfkManager with mocked client/presenter, ready for testing."""
    config = _make_config()
    afk = AfkManager(config)
    afk.active = True
    afk._client = Mock()
    afk._client.send_message = Mock(return_value=123)
    afk._client.answer_callback = Mock()
    afk._client.edit_message_reply_markup = Mock()
    afk._presenter = Mock()
    afk._presenter.send_to_session = Mock(return_value=123)
    afk._presenter.format_queue_summary = Mock(return_value=("Queue", None))
    afk._presenter.format_context_message = Mock(return_value=("Context msg", {"inline_keyboard": []}))
    afk._router = Mock()
    afk._router.route_text_message = Mock(return_value=None)
    for k, v in overrides.items():
        setattr(afk, k, v)
    return afk


class TestSessionsCommand:

    def test_sessions_empty_when_no_contexts(self):
        afk = _make_afk()
        afk._handle_message("/sessions")

        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "No Claude Code sessions" in msg

    def test_sessions_shows_active_sessions(self):
        afk = _make_afk()
        afk._session_contexts["claude-voice"] = "Working on feature X"
        afk._session_contexts["my-api"] = "Running tests"

        afk._handle_message("/sessions")

        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "claude-voice" in msg
        assert "my-api" in msg
        assert "active" in msg

        # Check buttons use session: prefix
        markup = call_args[1]["reply_markup"]
        buttons = [btn for row in markup["inline_keyboard"] for btn in row]
        assert any("session:context:" in btn["callback_data"] for btn in buttons)

    def test_sessions_shows_waiting_with_pending_requests(self):
        afk = _make_afk()
        afk._session_contexts["frontend"] = "Waiting for permission"

        # Enqueue a request for the session
        req = QueuedRequest(
            session="frontend",
            req_type="permission",
            prompt="Allow file write?",
            response_path="/tmp/test",
        )
        afk._queue.enqueue(req)

        afk._handle_message("/sessions")

        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "frontend" in msg
        assert "waiting for input" in msg
        assert "1 pending" in msg

        # Check buttons use session:queue prefix
        markup = call_args[1]["reply_markup"]
        buttons = [btn for row in markup["inline_keyboard"] for btn in row]
        assert any("session:queue:frontend" in btn["callback_data"] for btn in buttons)

    def test_sessions_multiple_pending_counted(self):
        afk = _make_afk()
        afk._session_contexts["backend"] = "Processing"

        for i in range(3):
            req = QueuedRequest(
                session="backend",
                req_type="input",
                prompt=f"Question {i}",
                response_path=f"/tmp/test{i}",
            )
            afk._queue.enqueue(req)

        afk._handle_message("/sessions")

        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "3 pending" in msg


class TestSessionsButtonCallback:

    def test_tap_active_session_shows_context(self):
        afk = _make_afk()
        afk._session_contexts["claude-voice"] = "Working on feature X"

        afk._handle_callback("cb1", "session:context:claude-voice", 456)

        # Should format and re-send the stored context
        afk._presenter.format_context_message.assert_called_once()
        afk._presenter.send_to_session.assert_called()

    def test_tap_waiting_session_shows_queue(self):
        afk = _make_afk()
        afk._session_contexts["frontend"] = "Waiting"

        afk._handle_callback("cb1", "session:queue:frontend", 456)

        # Queue is empty so it shows "No pending requests"
        afk._presenter.send_to_session.assert_called()
        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "No pending requests" in msg

    def test_tap_waiting_session_with_items_shows_summary(self):
        afk = _make_afk()
        afk._session_contexts["frontend"] = "Waiting"

        req = QueuedRequest(
            session="frontend",
            req_type="permission",
            prompt="Allow?",
            response_path="/tmp/test",
        )
        afk._queue.enqueue(req)

        afk._handle_callback("cb1", "session:queue:frontend", 456)

        afk._presenter.format_queue_summary.assert_called_once()


class TestFollowupDelivery:

    def test_reply_to_target_delivers_via_stop_hook(self):
        """Reply to target delivers followup via Stop hook response file."""
        afk = _make_afk()
        afk._reply_target = "claude-voice"

        with patch.object(afk, '_deliver_followup') as mock_deliver:
            afk._handle_message("implement the login feature")

        mock_deliver.assert_called_once_with("claude-voice", "implement the login feature")
        assert afk._reply_target is None

    def test_no_reply_target_shows_no_active_session_message(self):
        """Without reply target or fallback session, shows error message."""
        afk = _make_afk()

        afk._handle_message("implement the login feature")

        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "No active session" in msg
