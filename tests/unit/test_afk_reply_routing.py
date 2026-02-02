"""Tests for AFK reply routing — Telegram replies delivered via Stop hook response files."""

import os
import threading
from unittest.mock import Mock, patch
from daemon.afk import AfkManager
from daemon.request_queue import QueuedRequest
from daemon.session_presenter import _safe_callback_data
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


def _make_afk(active=True):
    """Create an AfkManager with mocked client/presenter/router."""
    config = _make_config()
    afk = AfkManager(config)
    afk.active = active
    afk._client = Mock()
    afk._client.send_message = Mock(return_value=100)
    afk._client.answer_callback = Mock()
    afk._client.edit_message_reply_markup = Mock()
    afk._presenter = Mock()
    afk._presenter.send_to_session = Mock(return_value=100)
    afk._presenter.format_context_message = Mock(return_value=("formatted", {"inline_keyboard": []}))
    afk._router = Mock()
    return afk


class TestContextMessageWithReplyButton:

    def test_context_request_sets_reply_target(self):
        """Context request sets the sending session as reply target."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
        })

        assert afk._reply_target == "my-session"

    def test_context_request_sends_formatted_message(self):
        """Context request sends formatted message to Telegram."""
        afk = _make_afk()

        result = afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
        })

        afk._presenter.format_context_message.assert_called_once()
        assert result["wait"] is True
        assert "response_path" in result

    def test_context_returns_stop_response_path(self):
        """Context request returns response path with 'stop' suffix for Stop hook blocking."""
        afk = _make_afk()

        result = afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
        })

        assert result["wait"] is True
        assert result["response_path"].endswith("response_stop")

    def test_last_context_sender_becomes_reply_target(self):
        """When multiple sessions send context, the last one becomes reply target."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "session-a",
            "type": "context",
            "context": "First",
        })
        afk.handle_hook_request({
            "session": "session-b",
            "type": "context",
            "context": "Second",
        })

        assert afk._reply_target == "session-b"


class TestReplyCallback:

    def test_reply_callback_sets_reply_target(self):
        """Tapping Reply button on context message sets reply target."""
        afk = _make_afk()

        afk._handle_callback("cb_1", "reply:my-session", 100)

        assert afk._reply_target == "my-session"

    def test_reply_callback_prompts_for_input(self):
        """Reply callback sends 'Type your reply' prompt."""
        afk = _make_afk()

        afk._handle_callback("cb_1", "reply:my-session", 100)

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "Type your reply" in msg
        assert "my-session" in msg


class TestFreeTextReplyRouting:

    def test_free_text_delivered_via_followup_when_reply_target_set(self):
        """Free text is delivered via Stop hook response file when reply target set."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)  # Empty queue
        afk._reply_target = "my-session"

        with patch.object(afk, '_deliver_followup') as mock_deliver:
            afk._handle_message("hello Claude")

        mock_deliver.assert_called_once_with("my-session", "hello Claude")
        assert afk._reply_target is None

    def test_free_text_no_target_shows_no_request_message(self):
        """Without reply target, shows 'No active request' message."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)
        # No reply target set

        afk._handle_message("hello Claude")

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "No active request" in msg

    def test_reply_target_takes_priority_over_queue(self):
        """When reply target is set, it takes priority over queued requests."""
        afk = _make_afk()
        active_req = QueuedRequest("sess1", "input", "Enter value:", "/tmp/r")
        afk._router.route_text_message = Mock(return_value=active_req)
        afk._reply_target = "other-session"

        with patch.object(afk, '_write_response'), \
             patch.object(afk, '_deliver_followup') as mock_deliver:
            afk._handle_message("my answer")

        # Reply target takes priority — message delivered as followup
        mock_deliver.assert_called_once_with("other-session", "my answer")
        assert afk._reply_target is None


class TestEnhancedStatus:

    def test_status_shows_emoji_per_session(self):
        """Each session shows its deterministic emoji."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"

        afk.handle_status_request()

        afk._client.send_message.assert_called_once()
        msg = afk._client.send_message.call_args[0][0]
        assert "[sess-a]" in msg

    def test_status_shows_reply_target_state(self):
        """Session that is the reply target shows 'reply target' state."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"
        afk._reply_target = "sess-a"

        afk.handle_status_request()

        msg = afk._client.send_message.call_args[0][0]
        assert "reply target" in msg

    def test_status_shows_waiting_state(self):
        """Session with pending request shows 'waiting for you'."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"
        req = QueuedRequest("sess-a", "permission", "Allow?", "/tmp/r")
        afk._queue.enqueue(req)

        afk.handle_status_request()

        msg = afk._client.send_message.call_args[0][0]
        assert "waiting for you" in msg

    def test_status_shows_idle_state(self):
        """Session without pending or reply target shows 'idle'."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"

        afk.handle_status_request()

        msg = afk._client.send_message.call_args[0][0]
        assert "idle" in msg

    def test_status_empty_sessions(self):
        """No sessions shows 'No active sessions'."""
        afk = _make_afk()

        afk.handle_status_request()

        msg = afk._client.send_message.call_args[0][0]
        assert "No active sessions" in msg


class TestCleanupSession:

    def test_cleanup_clears_reply_target(self):
        """cleanup_session clears reply target if it matches the session."""
        afk = _make_afk()
        afk._reply_target = "sess-a"

        with patch("daemon.afk.os.path.exists", return_value=False):
            afk.cleanup_session("sess-a")

        assert afk._reply_target is None

    def test_cleanup_preserves_other_reply_target(self):
        """cleanup_session doesn't clear reply target for a different session."""
        afk = _make_afk()
        afk._reply_target = "sess-b"

        with patch("daemon.afk.os.path.exists", return_value=False):
            afk.cleanup_session("sess-a")

        assert afk._reply_target == "sess-b"

    def test_cleanup_clears_pending_followups(self):
        """cleanup_session clears pending followups for the session."""
        afk = _make_afk()
        afk._pending_followups["sess-a"] = ["msg1"]
        afk._pending_followups["sess-b"] = ["msg2"]

        with patch("daemon.afk.os.path.exists", return_value=False):
            afk.cleanup_session("sess-a")

        assert "sess-a" not in afk._pending_followups
        assert afk._pending_followups["sess-b"] == ["msg2"]


class TestDeactivateFlush:

    def test_deactivate_flushes_pending_requests(self):
        """deactivate() writes __flush__ sentinel to all pending response paths."""
        afk = _make_afk()
        req1 = QueuedRequest("s1", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test 2", "/tmp/r2")
        afk._queue.enqueue(req1)
        afk._queue.enqueue(req2)

        with patch.object(afk, '_write_response') as mock_write, \
             patch.object(afk, '_unblock_stop_hooks'):
            afk.deactivate()

        assert mock_write.call_count == 2
        mock_write.assert_any_call("/tmp/r1", "__flush__")
        mock_write.assert_any_call("/tmp/r2", "__flush__")

    def test_deactivate_clears_session_state(self):
        """deactivate() clears contexts and reply_target."""
        afk = _make_afk()
        afk._session_contexts["s1"] = "some context"
        afk._reply_target = "s1"

        afk.deactivate()

        assert afk._session_contexts == {}
        assert afk._reply_target is None

    def test_deactivate_goodbye_includes_flush_count(self):
        """Goodbye message includes flush count when requests were pending."""
        afk = _make_afk()
        req1 = QueuedRequest("s1", "permission", "Test", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test", "/tmp/r2")
        req3 = QueuedRequest("s3", "input", "Test", "/tmp/r3")
        afk._queue.enqueue(req1)
        afk._queue.enqueue(req2)
        afk._queue.enqueue(req3)

        with patch.object(afk, '_write_response'):
            afk.deactivate()

        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed 3" in msg

    def test_deactivate_no_flush_count_when_empty(self):
        """Goodbye message is simple when no pending requests."""
        afk = _make_afk()

        afk.deactivate()

        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed" not in msg
        assert "AFK mode off" in msg


class TestFlushCommand:

    def test_flush_command_clears_queue(self):
        """The /flush command writes sentinels and reports count."""
        afk = _make_afk()
        req1 = QueuedRequest("s1", "permission", "Test", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test", "/tmp/r2")
        afk._queue.enqueue(req1)
        afk._queue.enqueue(req2)

        with patch.object(afk, '_write_response') as mock_write:
            afk._handle_message("/flush")

        mock_write.assert_any_call("/tmp/r1", "__flush__")
        mock_write.assert_any_call("/tmp/r2", "__flush__")
        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed 2" in msg

    def test_flush_command_empty_queue(self):
        """/flush with empty queue reports 0."""
        afk = _make_afk()

        afk._handle_message("/flush")

        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed 0" in msg


class TestUnblockStopHooks:

    def test_writes_back_sentinel_to_session_dirs(self, tmp_path):
        """_unblock_stop_hooks() writes __back__ to all session dirs."""
        afk = _make_afk()

        # Create two session dirs (simulating active Stop hooks)
        s1 = tmp_path / "sess-a"
        s1.mkdir()
        s2 = tmp_path / "sess-b"
        s2.mkdir()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._unblock_stop_hooks()

        assert (s1 / "response_stop").read_text() == "__back__"
        assert (s2 / "response_stop").read_text() == "__back__"

    def test_skips_dirs_with_existing_response(self, tmp_path):
        """_unblock_stop_hooks() doesn't overwrite existing response files."""
        afk = _make_afk()

        s1 = tmp_path / "sess-a"
        s1.mkdir()
        (s1 / "response_stop").write_text("pending followup")

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._unblock_stop_hooks()

        # Should NOT overwrite the existing followup
        assert (s1 / "response_stop").read_text() == "pending followup"

    def test_handles_missing_response_dir(self):
        """_unblock_stop_hooks() handles missing RESPONSE_DIR gracefully."""
        afk = _make_afk()

        with patch("daemon.afk.RESPONSE_DIR", "/nonexistent/dir"):
            afk._unblock_stop_hooks()  # Should not raise

    def test_deactivate_calls_unblock(self):
        """deactivate() calls _unblock_stop_hooks()."""
        afk = _make_afk()

        with patch.object(afk, '_unblock_stop_hooks') as mock_unblock:
            afk.deactivate()

        mock_unblock.assert_called_once()

    def test_deactivate_clears_pending_followups(self):
        """deactivate() clears pending followups."""
        afk = _make_afk()
        afk._pending_followups = {"sess-a": ["msg1", "msg2"]}

        afk.deactivate()

        assert afk._pending_followups == {}


class TestDeliverFollowup:

    def test_writes_to_response_file_when_session_dir_exists(self, tmp_path):
        """_deliver_followup() writes to response_stop when session dir exists."""
        afk = _make_afk()
        session_dir = tmp_path / "my-session"
        session_dir.mkdir()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._deliver_followup("my-session", "do the thing")

        assert (session_dir / "response_stop").read_text() == "do the thing"

    def test_queues_when_session_dir_missing(self, tmp_path):
        """_deliver_followup() queues message when no session dir exists."""
        afk = _make_afk()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._deliver_followup("nonexistent-session", "hello")

        assert "nonexistent-session" in afk._pending_followups
        assert afk._pending_followups["nonexistent-session"] == ["hello"]

    def test_sends_confirmation_on_direct_delivery(self, tmp_path):
        """_deliver_followup() sends Telegram confirmation when written."""
        afk = _make_afk()
        session_dir = tmp_path / "sess-a"
        session_dir.mkdir()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._deliver_followup("sess-a", "test message")

        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "Sent to" in msg

    def test_sends_queued_notification_on_queue(self, tmp_path):
        """_deliver_followup() sends 'queued' notification when session dir missing."""
        afk = _make_afk()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            afk._deliver_followup("nonexistent", "test")

        call_args = afk._presenter.send_to_session.call_args
        msg = call_args[0][1]
        assert "Queued" in msg


class TestPendingFollowups:

    def test_queued_followups_delivered_on_next_context(self, tmp_path):
        """Pending followups are delivered immediately when context arrives."""
        afk = _make_afk()
        afk._pending_followups["my-session"] = ["msg1", "msg2"]

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            result = afk.handle_hook_request({
                "session": "my-session",
                "type": "context",
                "context": "Claude response",
            })

        # Followups should have been written to the response file
        response_path = result["response_path"]
        assert os.path.exists(response_path)
        content = open(response_path).read()
        assert "msg1" in content
        assert "msg2" in content

        # Pending list should be cleared
        assert "my-session" not in afk._pending_followups

    def test_no_pending_followups_leaves_response_file_absent(self, tmp_path):
        """Without pending followups, response file is not pre-created."""
        afk = _make_afk()

        with patch("daemon.afk.RESPONSE_DIR", str(tmp_path)):
            result = afk.handle_hook_request({
                "session": "my-session",
                "type": "context",
                "context": "Claude response",
            })

        response_path = result["response_path"]
        assert not os.path.exists(response_path)

    def test_queue_followup_accumulates(self):
        """_queue_followup() accumulates multiple messages."""
        afk = _make_afk()

        afk._queue_followup("sess-a", "first")
        afk._queue_followup("sess-a", "second")
        afk._queue_followup("sess-b", "other")

        assert afk._pending_followups["sess-a"] == ["first", "second"]
        assert afk._pending_followups["sess-b"] == ["other"]


class TestStaleButtonFeedback:

    def test_stale_button_shows_expired_toast(self):
        """Pressing a button for an expired request shows 'Request expired'."""
        afk = _make_afk()
        afk._router.route_button_press = Mock(return_value=None)

        afk._handle_callback("cb_1", "yes", 999)

        afk._client.answer_callback.assert_called_once_with("cb_1", text="Request expired")

    def test_stale_button_strips_markup(self):
        """Pressing a stale button removes inline keyboard from the message."""
        afk = _make_afk()
        afk._router.route_button_press = Mock(return_value=None)

        afk._handle_callback("cb_1", "yes", 999)

        afk._client.edit_message_reply_markup.assert_called_once_with(999)


class TestSafeCallbackData:
    """Tests for Telegram callback_data 64-byte truncation."""

    def test_short_data_unchanged(self):
        assert _safe_callback_data("opt:Yes") == "opt:Yes"

    def test_exactly_64_bytes_unchanged(self):
        data = "x" * 64
        assert _safe_callback_data(data) == data

    def test_over_64_bytes_truncated(self):
        data = "opt:" + "a" * 100
        result = _safe_callback_data(data)
        assert len(result.encode('utf-8')) <= 64

    def test_multibyte_truncation_safe(self):
        """Truncation doesn't split multi-byte UTF-8 characters."""
        data = "opt:" + "\U0001f600" * 20  # each emoji is 4 bytes
        result = _safe_callback_data(data)
        assert len(result.encode('utf-8')) <= 64
        # Should be decodable without errors
        result.encode('utf-8').decode('utf-8')


class TestStateLock:
    """Verify AfkManager has a threading lock for shared state."""

    def test_has_state_lock(self):
        afk = _make_afk()
        assert hasattr(afk, '_state_lock')
        assert isinstance(afk._state_lock, type(threading.Lock()))
