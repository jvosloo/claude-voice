"""Tests for AFK reply routing — Telegram replies injected into terminal via osascript."""

import subprocess
from unittest.mock import Mock, patch, call
from daemon.afk import AfkManager
from daemon.request_queue import QueuedRequest
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

    def test_context_request_stores_tty_path(self):
        """TTY path from context request is stored in _session_tty_paths."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
            "tty_path": "/dev/ttys005",
        })

        assert afk._session_tty_paths["my-session"] == "/dev/ttys005"

    def test_context_request_sets_reply_target(self):
        """Context request sets the sending session as reply target."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
        })

        assert afk._reply_target == "my-session"

    def test_context_request_sends_with_reply_button(self):
        """Context message is sent via format_context_message with Reply button."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
            "tty_path": "/dev/ttys005",
        })

        # format_context_message should be called with has_tty=True
        afk._presenter.format_context_message.assert_called_once()
        args = afk._presenter.format_context_message.call_args
        assert args.kwargs.get("has_tty") is True or args[1].get("has_tty") is True

    def test_context_without_tty_has_no_tty_indicator(self):
        """Context without tty_path passes has_tty=False."""
        afk = _make_afk()

        afk.handle_hook_request({
            "session": "my-session",
            "type": "context",
            "context": "Hello world",
        })

        args = afk._presenter.format_context_message.call_args
        assert args.kwargs.get("has_tty") is False or args[1].get("has_tty") is False

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
        afk._session_tty_paths["my-session"] = "/dev/ttys005"

        afk._handle_callback("cb_1", "reply:my-session", 100)

        assert afk._reply_target == "my-session"

    def test_reply_callback_prompts_for_input(self):
        """Reply callback sends 'Type your reply' prompt."""
        afk = _make_afk()
        afk._session_tty_paths["my-session"] = "/dev/ttys005"

        afk._handle_callback("cb_1", "reply:my-session", 100)

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "Type your reply" in msg
        assert "my-session" in msg

    def test_reply_callback_without_tty_warns(self):
        """Reply callback warns when session has no TTY."""
        afk = _make_afk()
        # No tty_path stored for this session

        afk._handle_callback("cb_1", "reply:no-tty-session", 100)

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "No terminal" in msg
        assert afk._reply_target is None


class TestFreeTextReplyRouting:

    def test_free_text_injected_when_queue_empty_and_reply_target(self):
        """Free text is injected via TIOCSTI when queue is empty and reply target set."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)  # Empty queue
        afk._reply_target = "my-session"
        afk._session_tty_paths["my-session"] = "/dev/ttys005"

        with patch.object(afk, '_inject_reply', return_value=True) as mock_inject:
            afk._handle_message("hello Claude")

        mock_inject.assert_called_once_with("my-session", "hello Claude")

    def test_free_text_sends_confirmation_on_success(self):
        """Successful injection sends confirmation to Telegram."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)
        afk._reply_target = "my-session"
        afk._session_tty_paths["my-session"] = "/dev/ttys005"

        with patch.object(afk, '_inject_reply', return_value=True):
            afk._handle_message("hello Claude")

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "Sent to" in msg
        assert "hello Claude" in msg

    def test_free_text_warns_on_injection_failure(self):
        """Failed injection warns about stale terminal."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)
        afk._reply_target = "my-session"
        afk._session_tty_paths["my-session"] = "/dev/ttys005"

        with patch.object(afk, '_inject_reply', return_value=False):
            afk._handle_message("hello Claude")

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "may be closed" in msg
        # Should clean up stale state
        assert "my-session" not in afk._session_tty_paths
        assert afk._reply_target is None

    def test_free_text_no_target_shows_empty_queue(self):
        """Without reply target, shows standard 'queue empty' message."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)
        # No reply target set

        afk._handle_message("hello Claude")

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "Queue is empty" in msg

    def test_free_text_target_without_tty_warns(self):
        """Reply target set but no TTY stored warns user."""
        afk = _make_afk()
        afk._router.route_text_message = Mock(return_value=None)
        afk._reply_target = "orphan-session"
        # No TTY path for this session

        afk._handle_message("hello")

        afk._presenter.send_to_session.assert_called_once()
        msg = afk._presenter.send_to_session.call_args[0][1]
        assert "No terminal" in msg
        assert afk._reply_target is None

    def test_queue_takes_priority_over_reply_target(self):
        """When queue has active request, it takes priority over reply routing."""
        afk = _make_afk()
        active_req = QueuedRequest("sess1", "input", "Enter value:", "/tmp/r")
        afk._router.route_text_message = Mock(return_value=active_req)
        afk._reply_target = "other-session"
        afk._session_tty_paths["other-session"] = "/dev/ttys005"

        with patch.object(afk, '_write_response'), \
             patch.object(afk, '_inject_reply') as mock_inject:
            afk._handle_message("my answer")

        # Should NOT inject reply — queue handler should process it
        mock_inject.assert_not_called()


class TestInjectReply:

    @patch('daemon.afk.subprocess.run')
    def test_inject_reply_success(self, mock_run):
        """Successful osascript injection returns True."""
        mock_run.return_value = Mock(returncode=0)
        afk = _make_afk()
        afk._session_tty_paths["sess"] = "/dev/ttys005"

        result = afk._inject_reply("sess", "hi")

        assert result is True
        mock_run.assert_called_once()
        # Verify osascript was called
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"

    @patch('daemon.afk.subprocess.run')
    def test_inject_reply_sends_keystroke(self, mock_run):
        """Osascript command includes the text as a keystroke."""
        mock_run.return_value = Mock(returncode=0)
        afk = _make_afk()
        afk._session_tty_paths["sess"] = "/dev/ttys005"

        afk._inject_reply("sess", "hello world")

        script = mock_run.call_args[0][0][2]  # -e argument
        assert "hello world" in script
        assert "key code 36" in script  # Return key

    @patch('daemon.afk.subprocess.run')
    def test_inject_reply_escapes_quotes(self, mock_run):
        """Text with quotes is properly escaped for AppleScript."""
        mock_run.return_value = Mock(returncode=0)
        afk = _make_afk()
        afk._session_tty_paths["sess"] = "/dev/ttys005"

        afk._inject_reply("sess", 'say "hello"')

        script = mock_run.call_args[0][0][2]
        assert '\\"hello\\"' in script

    def test_inject_reply_no_session_stored(self):
        """Returns False when session has no terminal tracked."""
        afk = _make_afk()

        result = afk._inject_reply("unknown-session", "hello")

        assert result is False

    @patch('daemon.afk.subprocess.run', return_value=Mock(returncode=1))
    def test_inject_reply_osascript_fails(self, mock_run):
        """Returns False when osascript exits non-zero."""
        afk = _make_afk()
        afk._session_tty_paths["sess"] = "/dev/ttys005"

        result = afk._inject_reply("sess", "hi")

        assert result is False

    @patch('daemon.afk.subprocess.run', side_effect=subprocess.TimeoutExpired("osascript", 10))
    def test_inject_reply_timeout(self, mock_run):
        """Returns False on timeout."""
        import subprocess
        afk = _make_afk()
        afk._session_tty_paths["sess"] = "/dev/ttys005"

        result = afk._inject_reply("sess", "hi")

        assert result is False


class TestTypeIntoTerminalReplacement:

    @patch.object(AfkManager, '_inject_reply', return_value=True)
    def test_type_into_terminal_uses_tiocsti(self, mock_inject):
        """_type_into_terminal uses TIOCSTI when session has TTY."""
        afk = _make_afk()
        active_req = QueuedRequest("sess1", "permission", "Test", "/tmp/r")
        afk._queue.enqueue(active_req)
        afk._session_tty_paths["sess1"] = "/dev/ttys005"

        afk._type_into_terminal("question text")

        mock_inject.assert_called_once_with("sess1", "question text")

    @patch.object(AfkManager, '_inject_reply', return_value=False)
    def test_type_into_terminal_warns_on_failure(self, mock_inject):
        """Warns user when injection fails."""
        afk = _make_afk()
        active_req = QueuedRequest("sess1", "permission", "Test", "/tmp/r")
        afk._queue.enqueue(active_req)
        afk._session_tty_paths["sess1"] = "/dev/ttys005"

        afk._type_into_terminal("question text")

        # Should send warning via _send
        afk._client.send_message.assert_called()
        msg = afk._client.send_message.call_args[0][0]
        assert "No terminal connected" in msg

    def test_type_into_terminal_no_tty_warns(self):
        """Warns user when no TTY is available for the session."""
        afk = _make_afk()
        active_req = QueuedRequest("sess1", "permission", "Test", "/tmp/r")
        afk._queue.enqueue(active_req)
        # No TTY stored

        afk._type_into_terminal("question text")

        afk._client.send_message.assert_called()
        msg = afk._client.send_message.call_args[0][0]
        assert "No terminal connected" in msg


class TestEnhancedStatus:

    def test_status_shows_emoji_per_session(self):
        """Each session shows its deterministic emoji."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"

        afk.handle_status_request()

        afk._client.send_message.assert_called_once()
        msg = afk._client.send_message.call_args[0][0]
        assert "[sess-a]" in msg

    def test_status_shows_tty_indicator(self):
        """Sessions with TTY show terminal indicator."""
        afk = _make_afk()
        afk._session_contexts["sess-a"] = "Some context"
        afk._session_tty_paths["sess-a"] = "/dev/ttys005"

        afk.handle_status_request()

        msg = afk._client.send_message.call_args[0][0]
        assert "\U0001f5a5" in msg  # computer emoji (🖥)

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
        # Enqueue a request for sess-a
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

    def test_cleanup_removes_tty_path(self):
        """cleanup_session removes TTY path for the session."""
        afk = _make_afk()
        afk._session_tty_paths["sess-a"] = "/dev/ttys005"

        with patch("daemon.afk.os.path.exists", return_value=False):
            afk.cleanup_session("sess-a")

        assert "sess-a" not in afk._session_tty_paths

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


class TestDeactivateFlush:

    def test_deactivate_flushes_pending_requests(self):
        """deactivate() writes __flush__ sentinel to all pending response paths."""
        afk = _make_afk()
        req1 = QueuedRequest("s1", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test 2", "/tmp/r2")
        afk._queue.enqueue(req1)
        afk._queue.enqueue(req2)

        with patch.object(afk, '_write_response') as mock_write:
            afk.deactivate()

        # Should write __flush__ to both response paths
        assert mock_write.call_count == 2
        mock_write.assert_any_call("/tmp/r1", "__flush__")
        mock_write.assert_any_call("/tmp/r2", "__flush__")

    def test_deactivate_clears_session_state(self):
        """deactivate() clears contexts, tty_paths, and reply_target."""
        afk = _make_afk()
        afk._session_contexts["s1"] = "some context"
        afk._session_tty_paths["s1"] = "/dev/ttys005"
        afk._reply_target = "s1"

        afk.deactivate()

        assert afk._session_contexts == {}
        assert afk._session_tty_paths == {}
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

        # Sentinel written to both
        mock_write.assert_any_call("/tmp/r1", "__flush__")
        mock_write.assert_any_call("/tmp/r2", "__flush__")
        # Report sent
        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed 2" in msg

    def test_flush_command_empty_queue(self):
        """/flush with empty queue reports 0."""
        afk = _make_afk()

        afk._handle_message("/flush")

        msg = afk._client.send_message.call_args[0][0]
        assert "Flushed 0" in msg


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
