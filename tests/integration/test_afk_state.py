"""Integration tests for AFK basic state management.

Note: Queue-based request handling is tested in test_afk_manager_refactor.py
and test_afk_multi_session.py. This file contains only basic state tests.
"""

from unittest.mock import MagicMock, patch

from daemon.afk import AfkManager
from daemon.config import (
    AfkConfig, AfkTelegramConfig, Config,
    InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig
)


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


class TestAfkManagerState:
    """Test basic configuration and activation state."""

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

    def test_deactivate_noop_when_inactive(self):
        mgr = AfkManager(_make_config())
        mgr.deactivate()  # should not raise
        assert mgr.active is False


class TestHandleHookRequest:
    """Test basic hook request handling."""

    def test_returns_no_wait_when_inactive(self):
        mgr = AfkManager(_make_config())
        resp = mgr.handle_hook_request({"type": "permission"})
        assert resp == {"wait": False}

    def test_returns_no_wait_without_presenter(self):
        """Without presenter initialized, should not wait."""
        mgr = AfkManager(_make_config())
        mgr.active = True  # Active but no presenter
        resp = mgr.handle_hook_request({
            "session": "test",
            "type": "permission",
            "prompt": "Allow?",
        })
        assert resp == {"wait": False}


class TestHandleMessage:
    """Test command handling."""

    def test_afk_command(self):
        mgr = AfkManager(_make_config())
        mgr.active = True
        mgr._client = MagicMock()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/afk")
        toggle.assert_called_once()

    def test_back_command_deactivates(self):
        mgr = AfkManager(_make_config())
        mgr.active = True
        mgr._client = MagicMock()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/back")
        toggle.assert_called_once()

    def test_status_command(self):
        mgr = AfkManager(_make_config())
        mgr.active = True
        mgr._client = MagicMock()
        with patch.object(mgr, "handle_status_request") as mock_status:
            mgr._handle_message("/status")
        mock_status.assert_called_once()

    def test_help_command(self):
        mgr = AfkManager(_make_config())
        mgr._client = MagicMock()
        mgr._client.send_message.return_value = 1
        mgr._handle_message("/help")
        mgr._client.send_message.assert_called_once()
        text = mgr._client.send_message.call_args[0][0]
        assert "/afk" in text
        assert "/back" in text
        assert "/queue" in text
        assert "Commands" in text
