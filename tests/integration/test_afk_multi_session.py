"""Integration tests for multi-session AFK queue handling."""

import os
import tempfile
from unittest.mock import Mock, patch
from daemon.afk import AfkManager
from daemon.config import (
    Config, AfkConfig, AfkTelegramConfig,
    InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig
)
from daemon.request_router import QueueRouter
from daemon.session_presenter import SingleChatPresenter


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


class TestMultiSessionQueue:

    def test_three_sessions_permission_requests(self):
        """Three sessions send permission requests, queued correctly."""
        config = _make_config()

        # Create AfkManager with mocked client
        afk = AfkManager(config)
        afk._client = Mock()
        afk._client.send_message = Mock(return_value=100)  # message_id
        afk._client.edit_message_reply_markup = Mock()
        afk._client.answer_callback = Mock()
        afk.active = True

        # Initialize abstractions manually (normally done in start_listening)
        afk._router = QueueRouter(afk._queue)
        afk._presenter = SingleChatPresenter(afk._client)

        # Session 1 sends permission request
        with tempfile.TemporaryDirectory() as tmpdir:
            resp1 = afk.handle_hook_request({
                "session": "session-a",
                "type": "permission",
                "prompt": "Bash execution - npm install",
            })

            assert resp1["wait"] is True
            assert "response_path" in resp1
            assert afk._queue.get_active().session == "session-a"

            # Session 2 sends permission request
            resp2 = afk.handle_hook_request({
                "session": "session-b",
                "type": "permission",
                "prompt": "File write - config.json",
            })

            assert resp2["wait"] is True
            assert afk._queue.size() == 1  # session-b queued
            assert afk._queue.get_active().session == "session-a"  # Still active

            # Session 3 sends permission request
            resp3 = afk.handle_hook_request({
                "session": "session-c",
                "type": "input",
                "prompt": "Provide API key",
            })

            assert resp3["wait"] is True
            assert afk._queue.size() == 2  # session-b and session-c queued

            # Simulate button press on session-a (approve)
            active = afk._queue.get_active()
            afk._handle_callback("cb_1", "yes", active.message_id)

            # Verify session-b is now active
            assert afk._queue.get_active().session == "session-b"
            assert afk._queue.size() == 1  # Only session-c queued

    def test_priority_jump_to_specific_session(self):
        """User can jump to specific session's request."""
        config = _make_config()

        afk = AfkManager(config)
        afk._client = Mock()
        afk._client.send_message = Mock(return_value=999)
        afk.active = True

        afk._router = QueueRouter(afk._queue)
        afk._presenter = SingleChatPresenter(afk._client)

        # Enqueue 3 requests
        afk.handle_hook_request({"session": "sess-a", "type": "permission", "prompt": "Test 1"})
        afk.handle_hook_request({"session": "sess-b", "type": "input", "prompt": "Test 2"})
        afk.handle_hook_request({"session": "sess-c", "type": "permission", "prompt": "Test 3"})

        assert afk._queue.get_active().session == "sess-a"
        assert afk._queue.size() == 2

        # Jump to sess-c (skip sess-b)
        afk._handle_queue_command("priority:sess-c")

        assert afk._queue.get_active().session == "sess-c"
        # Queue should have sess-b and sess-a (moved to end)
        assert afk._queue.size() == 2
