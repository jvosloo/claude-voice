"""Tests for the get_session() helper in hooks/_common.py."""

import os
import sys
from unittest.mock import patch

# Import _common from hooks directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))
from _common import get_session


class TestGetSession:

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_returns_project_with_session_id_prefix(self, _mock_cwd):
        hook_input = {"session_id": "c12d0f43-acda-49ee-9127-f1b33d22bfd5"}
        assert get_session(hook_input) == "claude-voice_c12d0f43"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/my-api")
    def test_different_project_name(self, _mock_cwd):
        hook_input = {"session_id": "aabbccdd-1234-5678-9abc-def012345678"}
        assert get_session(hook_input) == "my-api_aabbccdd"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_falls_back_to_basename_when_no_session_id(self, _mock_cwd):
        hook_input = {"tool_name": "Bash"}
        assert get_session(hook_input) == "claude-voice"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_falls_back_to_basename_when_no_hook_input(self, _mock_cwd):
        assert get_session(None) == "claude-voice"
        assert get_session() == "claude-voice"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_falls_back_when_session_id_empty(self, _mock_cwd):
        hook_input = {"session_id": ""}
        assert get_session(hook_input) == "claude-voice"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_two_sessions_same_project_produce_different_keys(self, _mock_cwd):
        """The core scenario: two tabs in same project must be distinguishable."""
        input_a = {"session_id": "aaaaaaaa-1111-2222-3333-444444444444"}
        input_b = {"session_id": "bbbbbbbb-5555-6666-7777-888888888888"}
        assert get_session(input_a) != get_session(input_b)
        assert get_session(input_a) == "claude-voice_aaaaaaaa"
        assert get_session(input_b) == "claude-voice_bbbbbbbb"

    @patch("os.getcwd", return_value="/Users/johan/IdeaProjects/claude-voice")
    def test_short_session_id_still_works(self, _mock_cwd):
        """If session_id is shorter than 8 chars, use what's available."""
        hook_input = {"session_id": "abc"}
        assert get_session(hook_input) == "claude-voice_abc"
