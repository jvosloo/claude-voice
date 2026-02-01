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


class TestAskUserQuestionButtons:

    def test_with_options(self):
        """Options list produces one button per option plus 'Other'."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        options = [
            {"label": "Red", "description": "Pick red"},
            {"label": "Blue", "description": "Pick blue"},
        ]
        req = QueuedRequest("sess", "ask_user_question", "Pick a color?", "/tmp/r",
                            options=options)
        queue_info = {'emoji': '🟢', 'queue_size': 0}

        text, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        assert len(keyboard) == 3  # Red, Blue, Other
        assert keyboard[0][0]['text'] == "Red"
        assert keyboard[0][0]['callback_data'] == "opt:Red"
        assert keyboard[1][0]['text'] == "Blue"
        assert keyboard[1][0]['callback_data'] == "opt:Blue"

    def test_without_options(self):
        """Only 'Other' button when options is None."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("sess", "ask_user_question", "What?", "/tmp/r",
                            options=None)
        queue_info = {'emoji': '🟢', 'queue_size': 0}

        _, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        assert len(keyboard) == 1
        assert "Other" in keyboard[0][0]['text']

    def test_empty_options(self):
        """Only 'Other' button when options is empty list."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("sess", "ask_user_question", "What?", "/tmp/r",
                            options=[])
        queue_info = {'emoji': '🟢', 'queue_size': 0}

        _, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        assert len(keyboard) == 1
        assert keyboard[0][0]['callback_data'] == "opt:__other__"

    def test_callback_data_format(self):
        """Button callback_data uses opt:<label> format."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        options = [{"label": "Yes & No", "description": "mixed"}]
        req = QueuedRequest("sess", "ask_user_question", "Q?", "/tmp/r",
                            options=options)
        queue_info = {'emoji': '🟢', 'queue_size': 0}

        _, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        assert keyboard[0][0]['callback_data'] == "opt:Yes & No"

    def test_other_button_always_last(self):
        """'Other' button is always the last row."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        options = [
            {"label": "A", "description": ""},
            {"label": "B", "description": ""},
            {"label": "C", "description": ""},
        ]
        req = QueuedRequest("sess", "ask_user_question", "Q?", "/tmp/r",
                            options=options)
        queue_info = {'emoji': '🟢', 'queue_size': 0}

        _, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        assert len(keyboard) == 4  # A, B, C, Other
        assert keyboard[-1][0]['callback_data'] == "opt:__other__"

    def test_with_queue_adds_management_buttons(self):
        """Queue management buttons appear after option buttons when queue_size > 0."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        options = [{"label": "X", "description": ""}]
        req = QueuedRequest("sess", "ask_user_question", "Q?", "/tmp/r",
                            options=options)
        queue_info = {'emoji': '🟢', 'queue_size': 1}

        _, markup = presenter.format_active_request(req, queue_info)

        keyboard = markup['inline_keyboard']
        # X, Other, Skip+ShowAll
        assert len(keyboard) == 3
        assert "Skip" in keyboard[-1][0]['text']


class TestContextMessageFormatting:

    def test_format_context_message_with_tty(self):
        """Context message includes terminal indicator when TTY available."""
        client = Mock()
        presenter = SingleChatPresenter(client)

        text, markup = presenter.format_context_message(
            "my-session", "\U0001f7e2", "Hello world", has_tty=True,
        )

        assert "[my-session]" in text
        assert "\U0001f5a5" in text  # computer emoji
        assert "Hello world" in text

        # Reply button
        keyboard = markup["inline_keyboard"]
        assert len(keyboard) == 1
        assert keyboard[0][0]["text"] == "\U0001f4ac Reply"
        assert keyboard[0][0]["callback_data"] == "reply:my-session"

    def test_format_context_message_without_tty(self):
        """Context message has no terminal indicator without TTY."""
        client = Mock()
        presenter = SingleChatPresenter(client)

        text, markup = presenter.format_context_message(
            "my-session", "\U0001f7e2", "Hello world", has_tty=False,
        )

        assert "\U0001f5a5" not in text
        # Reply button still present (button handler checks TTY availability)
        assert markup["inline_keyboard"][0][0]["callback_data"] == "reply:my-session"


class TestSingleChatPresenterQueueSummary:

    def test_format_queue_summary_with_multiple_requests(self):
        """Format full queue summary with active and queued requests."""
        client = Mock()
        presenter = SingleChatPresenter(client)

        summary = [
            {
                'session': 'sess-a',
                'req_type': 'permission',
                'prompt': 'Bash execution',
                'status': 'active',
                'position': 0,
                'emoji': '🟢',
                'waiting_seconds': 125,
            },
            {
                'session': 'sess-b',
                'req_type': 'input',
                'prompt': 'Provide API key',
                'status': 'queued',
                'position': 1,
                'emoji': '🔵',
                'waiting_seconds': 45,
            },
            {
                'session': 'sess-a',
                'req_type': 'ask_user_question',
                'prompt': 'Choose method',
                'status': 'queued',
                'position': 2,
                'emoji': '🟢',
                'waiting_seconds': 12,
            },
        ]

        text, markup = presenter.format_queue_summary(summary)

        assert "📋 QUEUE (3 total)" in text
        assert "🟢 Active: [sess-a] permission" in text
        assert "Waiting: 2m 5s" in text

        assert "Position 1: 🔵 [sess-b] input" in text
        assert "Waiting: 45s" in text

        assert "Position 2: 🟢 [sess-a]" in text

        # Check buttons
        assert markup is not None
        keyboard = markup['inline_keyboard']
        # First button: Skip active (with session label)
        assert "[sess-a]" in keyboard[0][0]['text']
        # Other buttons: Handle Now with session label
        assert "[sess-b]" in keyboard[1][0]['text']
        assert keyboard[1][0]['callback_data'] == "cmd:priority:sess-b"
