"""Tests for refactored AfkManager using RequestQueue and abstractions."""

from unittest.mock import Mock, patch
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


class TestAfkManagerQueueIntegration:

    def test_handle_hook_request_enqueues_first_request(self):
        """First hook request becomes active and is presented."""
        config = _make_config()

        afk = AfkManager(config)
        afk.active = True

        # Mock presenter
        afk._presenter = Mock()
        afk._presenter.format_active_request = Mock(return_value=("Test message", {}))
        afk._presenter.send_to_session = Mock(return_value=123)

        # Send request
        response = afk.handle_hook_request({
            "session": "test-session",
            "type": "permission",
            "prompt": "Allow test?",
        })

        assert response["wait"] is True
        assert "response_path" in response

        # Verify presenter was called
        afk._presenter.send_to_session.assert_called_once()


class TestAfkManagerCallbackRouting:

    def test_handle_callback_routes_via_queue_router(self):
        """Callback query routes through QueueRouter to active request."""
        config = _make_config()

        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._router = Mock()
        afk._presenter = Mock()

        # Mock active request
        from daemon.request_queue import QueuedRequest
        active_req = QueuedRequest("sess1", "permission", "Test", "/tmp/r1")
        active_req.message_id = 123
        afk._router.route_button_press = Mock(return_value=active_req)

        # Mock queue operations
        afk._queue = Mock()
        afk._queue.dequeue_active = Mock(return_value=None)

        # Handle callback
        afk._handle_callback("callback_123", "yes", 123)

        # Verify routing was used
        afk._router.route_button_press.assert_called_once_with("yes", 123)
