"""Tests for /sessions command and tmux integration in AfkManager."""

from unittest.mock import Mock, patch, MagicMock
from daemon.afk import AfkManager
from daemon.config import (
    Config, AfkConfig, AfkTelegramConfig,
    InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig
)


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


class TestSessionsCommand:

    @patch("daemon.afk.TmuxMonitor")
    def test_sessions_shows_idle_and_working(self, MockMonitor):
        mock_monitor = MockMonitor.return_value
        mock_monitor.is_available.return_value = True
        mock_monitor.get_all_session_statuses.return_value = [
            {"session": "claude-voice", "status": "idle", "pane_activity": 1000},
            {"session": "my-api", "status": "working", "pane_activity": None},
        ]

        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._client.send_message = Mock(return_value=123)
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)

        afk._handle_message("/sessions")

        # _handle_sessions_command uses self._send() which calls self._client.send_message()
        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "claude-voice" in msg
        assert "idle" in msg
        assert "my-api" in msg
        assert "working" in msg

    @patch("daemon.afk.TmuxMonitor")
    def test_sessions_no_tmux_no_known(self, MockMonitor):
        mock_monitor = MockMonitor.return_value
        mock_monitor.is_available.return_value = False
        mock_monitor.get_all_session_statuses.return_value = []

        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._client.send_message = Mock(return_value=123)

        afk._handle_message("/sessions")

        call_args = afk._client.send_message.call_args
        msg = call_args[0][0]
        assert "No Claude Code sessions" in msg


class TestSessionsButtonCallback:

    @patch("daemon.afk.TmuxMonitor")
    def test_tap_idle_session_sets_reply_target(self, MockMonitor):
        mock_monitor = MockMonitor.return_value
        mock_monitor.is_available.return_value = True
        mock_monitor.get_session_status.return_value = {
            "session": "claude-voice", "status": "idle",
        }

        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._client.answer_callback = Mock()
        afk._client.edit_message_reply_markup = Mock()
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)

        afk._handle_callback("cb1", "tmux:prompt:claude-voice", 456)

        assert afk._reply_target == "claude-voice"

    @patch("daemon.afk.TmuxMonitor")
    def test_tap_waiting_session_shows_queue(self, MockMonitor):
        mock_monitor = MockMonitor.return_value
        mock_monitor.is_available.return_value = True

        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._client.answer_callback = Mock()
        afk._client.edit_message_reply_markup = Mock()
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)
        afk._presenter.format_queue_summary = Mock(return_value=("Queue", None))

        afk._handle_callback("cb1", "tmux:queue:frontend", 456)

        # Should show message about no pending requests (queue is empty in this test)
        afk._presenter.send_to_session.assert_called()

    @patch("daemon.afk.TmuxMonitor")
    def test_tap_session_sets_reply_target_regardless(self, MockMonitor):
        """Prompt button always sets reply target (availability checked at delivery time)."""
        mock_monitor = MockMonitor.return_value

        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._client.answer_callback = Mock()
        afk._client.edit_message_reply_markup = Mock()
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)

        afk._handle_callback("cb1", "tmux:prompt:claude-voice", 456)

        assert afk._reply_target == "claude-voice"
        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "Send a message" in msg


class TestFollowupDelivery:

    @patch("daemon.afk.TmuxMonitor")
    def test_reply_to_target_delivers_via_stop_hook(self, MockMonitor):
        """Reply to target delivers followup via Stop hook response file."""
        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._reply_target = "claude-voice"
        afk._router = Mock()
        afk._router.route_text_message.return_value = None
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)

        with patch.object(afk, '_deliver_followup') as mock_deliver:
            afk._handle_message("implement the login feature")

        mock_deliver.assert_called_once_with("claude-voice", "implement the login feature")
        assert afk._reply_target is None

    @patch("daemon.afk.TmuxMonitor")
    def test_no_reply_target_shows_no_active_session_message(self, MockMonitor):
        """Without reply target or fallback session, shows error message."""
        config = _make_config()
        afk = AfkManager(config)
        afk.active = True
        afk._router = Mock()
        afk._router.route_text_message.return_value = None
        afk._presenter = Mock()
        afk._presenter.send_to_session = Mock(return_value=123)

        afk._handle_message("implement the login feature")

        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "No active session" in msg
