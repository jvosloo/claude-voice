"""Tests for handle-ask-user.py PreToolUse hook — deny-with-answer approach."""

import importlib.util
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

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


class TestNonAfkPassthrough:

    def test_non_afk_mode_returns_nothing(self, capsys):
        """In non-AFK mode, hook outputs nothing (allows tool to run normally)."""
        with patch("handle_ask_user.read_mode", return_value="notify"):
            main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_mode_returns_nothing(self, capsys):
        """With no mode set, hook outputs nothing."""
        with patch("handle_ask_user.read_mode", return_value=""):
            main()

        captured = capsys.readouterr()
        assert captured.out == ""


class TestDenyWithAnswer:

    def test_option_button_press_returns_deny_with_label(self, capsys, tmp_path):
        """When user taps an option button, deny reason includes the label."""
        response_file = tmp_path / "response_ask_user_question"
        response_file.write_text("opt:Blue")

        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value={
                 "wait": True,
                 "response_path": str(response_file),
             }), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "Blue" in reason
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_free_text_reply_returns_deny_with_text(self, capsys, tmp_path):
        """When user types free text, deny reason includes verbatim text."""
        response_file = tmp_path / "response_ask_user_question"
        response_file.write_text("I want something custom")

        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value={
                 "wait": True,
                 "response_path": str(response_file),
             }), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "I want something custom" in reason

    def test_timeout_returns_deny_with_timeout_message(self, capsys):
        """When response times out, deny reason mentions timeout."""
        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value={
                 "wait": True,
                 "response_path": "/tmp/nonexistent-response-file",
             }), \
             patch("handle_ask_user.wait_for_response", return_value=None), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "did not respond" in reason
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_flush_sentinel_returns_deny_with_flush_message(self, capsys, tmp_path):
        """When queue is flushed, deny reason mentions flush."""
        response_file = tmp_path / "response_ask_user_question"
        response_file.write_text("__flush__")

        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value={
                 "wait": True,
                 "response_path": str(response_file),
             }), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "flushed" in reason.lower() or "cancelled" in reason.lower()

    def test_daemon_not_running_returns_nothing(self, capsys):
        """When daemon is not running (send_to_daemon returns None), allow passthrough."""
        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value=None), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_skip_other_returns_nothing(self, capsys, tmp_path):
        """When user taps Skip/Other, hook outputs nothing (allow tool for local input)."""
        response_file = tmp_path / "response_ask_user_question"
        response_file.write_text("opt:__other__")

        hook_input = _make_hook_input()

        with patch("handle_ask_user.read_mode", return_value="afk"), \
             patch("handle_ask_user.send_to_daemon", return_value={
                 "wait": True,
                 "response_path": str(response_file),
             }), \
             patch("sys.stdin", new=MagicMock(read=lambda: json.dumps(hook_input))), \
             patch("json.load", return_value=hook_input):
            main()

        captured = capsys.readouterr()
        assert captured.out == ""
