"""Tests for SessionPresenter."""

from unittest.mock import Mock
from daemon.session_presenter import SingleChatPresenter
from daemon.request_queue import QueuedRequest


class TestSingleChatPresenterFormatting:

    def test_format_active_permission_request(self):
        """Format active permission request with buttons."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("test-session", "permission", "Bash execution - rm cache/*", "/tmp/r")
        req.message_id = None
        queue_info = {
            'emoji': '🟢',
            'queue_size': 2,
            'queue_sessions': ['sess-a', 'sess-b'],
        }

        text, markup = presenter.format_active_request(req, queue_info)

        assert "🟢 ACTIVE REQUEST" in text
        assert "[test-session]" in text
        assert "Bash execution - rm cache/*" in text
        assert "Queue: 2 more requests waiting" in text

        # Check buttons
        assert markup is not None
        keyboard = markup['inline_keyboard']
        # First row: [Yes] [Always] [No]
        assert len(keyboard[0]) == 3
        assert keyboard[0][0]['text'] == "✓ Yes"
        assert keyboard[0][0]['callback_data'] == "yes"
        assert keyboard[0][1]['text'] == "✓ Always"
        assert keyboard[0][2]['text'] == "✗ No"

        # Second row: [⏭️ Skip] [👀 Show All]
        assert len(keyboard[1]) == 2
        assert "Skip" in keyboard[1][0]['text']
        assert "Show All" in keyboard[1][1]['text']

    def test_format_queued_notification(self):
        """Format queued notification shows position and active context."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("myapp", "input", "Provide API key", "/tmp/r")
        queue_info = {
            'emoji': '🔵',
            'position': 3,
            'total': 5,
            'active_session': 'claude-voice',
            'active_type': 'permission',
        }

        text = presenter.format_queued_notification(req, queue_info)

        assert "⏸️ QUEUED (position 3/5)" in text
        assert "[myapp]" in text or "myapp" in text
        assert "Provide API key" in text
        assert "claude-voice" in text  # Active session context
