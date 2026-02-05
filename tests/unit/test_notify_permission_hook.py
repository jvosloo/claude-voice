"""Tests for notify-permission.py — time-based ASK_USER_FLAG expiry."""

import importlib.util
import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

# Import hook via importlib (hyphen in filename)
_hook_path = os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "notify-permission.py")
_spec = importlib.util.spec_from_file_location("notify_permission", _hook_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["notify_permission"] = _mod
main = _mod.main


def _make_hook_input(notification_type="permission_prompt"):
    """Build a minimal Notification hook input dict."""
    return {"notification_type": notification_type, "message": "Permission needed"}


class TestAskUserFlagExpiry:

    def test_fresh_flag_skips_notification(self, tmp_path):
        """When ASK_USER_FLAG exists and is fresh (< 5s), permission hook skips."""
        flag_path = str(tmp_path / ".ask_user_active")
        with open(flag_path, "w") as f:
            f.write(str(time.time()))

        hook_input = _make_hook_input()

        with patch("notify_permission.read_mode", return_value="notify"), \
             patch("notify_permission.SILENT_FLAG", str(tmp_path / ".silent_nonexistent")), \
             patch("notify_permission.ASK_USER_FLAG", flag_path), \
             patch("json.load", return_value=hook_input), \
             patch("notify_permission.send_to_daemon") as mock_send:
            main()

        mock_send.assert_not_called()

    def test_stale_flag_proceeds_with_notification(self, tmp_path):
        """When ASK_USER_FLAG exists but is stale (> 5s), permission hook proceeds."""
        flag_path = str(tmp_path / ".ask_user_active")
        with open(flag_path, "w") as f:
            f.write(str(time.time()))
        # Backdate mtime by 10 seconds
        stale_time = time.time() - 10
        os.utime(flag_path, (stale_time, stale_time))

        hook_input = _make_hook_input()

        with patch("notify_permission.read_mode", return_value="notify"), \
             patch("notify_permission.SILENT_FLAG", str(tmp_path / ".silent_nonexistent")), \
             patch("notify_permission.ASK_USER_FLAG", flag_path), \
             patch("json.load", return_value=hook_input), \
             patch("notify_permission.get_session", return_value="test_session"), \
             patch("notify_permission.send_to_daemon") as mock_send:
            main()

        mock_send.assert_called_once()
        sent = mock_send.call_args[0][0]
        assert sent["notify_category"] == "permission"

    def test_no_flag_proceeds_with_notification(self, tmp_path):
        """When ASK_USER_FLAG does not exist, permission hook proceeds normally."""
        flag_path = str(tmp_path / ".ask_user_active_nonexistent")
        hook_input = _make_hook_input()

        with patch("notify_permission.read_mode", return_value="notify"), \
             patch("notify_permission.SILENT_FLAG", str(tmp_path / ".silent_nonexistent")), \
             patch("notify_permission.ASK_USER_FLAG", flag_path), \
             patch("json.load", return_value=hook_input), \
             patch("notify_permission.get_session", return_value="test_session"), \
             patch("notify_permission.send_to_daemon") as mock_send:
            main()

        mock_send.assert_called_once()
        sent = mock_send.call_args[0][0]
        assert sent["notify_category"] == "permission"

    def test_afk_mode_returns_early(self):
        """In AFK mode, hook returns without sending (handled by permission-request.py)."""
        with patch("notify_permission.read_mode", return_value="afk"), \
             patch("notify_permission.send_to_daemon") as mock_send:
            main()

        mock_send.assert_not_called()

    def test_non_permission_notification_ignored(self, tmp_path):
        """Non-permission_prompt notifications are ignored."""
        hook_input = _make_hook_input(notification_type="other_type")

        with patch("notify_permission.read_mode", return_value="notify"), \
             patch("notify_permission.SILENT_FLAG", str(tmp_path / ".silent_nonexistent")), \
             patch("notify_permission.ASK_USER_FLAG", str(tmp_path / ".flag_nonexistent")), \
             patch("json.load", return_value=hook_input), \
             patch("notify_permission.send_to_daemon") as mock_send:
            main()

        mock_send.assert_not_called()
