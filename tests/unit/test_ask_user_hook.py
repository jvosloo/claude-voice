"""Tests for handle-ask-user.py PreToolUse hook — question notification."""

import importlib.util
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Import hook via importlib (hyphen in filename)
_hook_path = os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "handle-ask-user.py")
_spec = importlib.util.spec_from_file_location("handle_ask_user", _hook_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["handle_ask_user"] = _mod
main = _mod.main


def _make_hook_input(questions=None):
    """Build a minimal AskUserQuestion hook input dict."""
    if questions is None:
        questions = [{
            "question": "Which color?",
            "options": [
                {"label": "Red", "description": "A warm color"},
                {"label": "Blue", "description": "A cool color"},
            ],
        }]
    return {"tool_input": {"questions": questions}}


class TestQuestionNotification:

    def test_sends_question_notification(self, capsys):
        """Hook sends notify_category='question' to daemon."""
        hook_input = _make_hook_input()

        with patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input), \
             patch("handle_ask_user.send_to_daemon") as mock_send, \
             patch("handle_ask_user.get_session", return_value="test_session"):
            main()

        mock_send.assert_called_once()
        sent = mock_send.call_args[0][0]
        assert sent["notify_category"] == "question"
        assert sent["session"] == "test_session"

        # No decision printed — tool runs normally with local picker
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_sets_ask_user_flag(self, tmp_path):
        """Hook sets ASK_USER_FLAG so permission hook skips."""
        flag_path = str(tmp_path / ".ask_user_active")
        hook_input = _make_hook_input()

        with patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input), \
             patch("handle_ask_user.send_to_daemon"), \
             patch("handle_ask_user.get_session", return_value="test_session"), \
             patch("handle_ask_user.ASK_USER_FLAG", flag_path):
            main()

        assert os.path.exists(flag_path)

    def test_bad_stdin_exits_gracefully(self, capsys):
        """If stdin is bad JSON, exits without sending."""
        with patch("json.load", side_effect=json.JSONDecodeError("", "", 0)), \
             patch("handle_ask_user.send_to_daemon") as mock_send:
            main()

        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_no_questions_exits_gracefully(self, capsys):
        """If no questions in input, exits without sending."""
        hook_input = {"tool_input": {}}

        with patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input), \
             patch("handle_ask_user.send_to_daemon") as mock_send:
            main()

        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert captured.out == ""
