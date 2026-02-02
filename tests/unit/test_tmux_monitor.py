"""Tests for tmux session monitoring."""

import subprocess
from unittest.mock import patch, MagicMock
from daemon.tmux_monitor import TmuxMonitor


class TestTmuxAvailable:

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_tmux_available_when_installed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        monitor = TmuxMonitor()
        assert monitor.is_available() is True

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_tmux_not_available_when_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        monitor = TmuxMonitor()
        assert monitor.is_available() is False


class TestListSessions:

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_list_sessions_returns_session_names(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-voice\nmy-api\nfrontend\n",
        )
        monitor = TmuxMonitor()
        assert monitor.list_sessions() == ["claude-voice", "my-api", "frontend"]

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_list_sessions_empty_when_no_server(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        monitor = TmuxMonitor()
        assert monitor.list_sessions() == []


class TestSessionHasClaude:

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_detects_claude_process(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="claude\n")
        monitor = TmuxMonitor()
        assert monitor.session_has_claude("my-session") is True

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_no_claude_process(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="zsh\n")
        monitor = TmuxMonitor()
        assert monitor.session_has_claude("my-session") is False


class TestDetectStatus:

    def test_idle_when_prompt_no_interrupt(self):
        pane_content = (
            "some output\n"
            "more output\n"
            "❯ "
        )
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content(pane_content) == "idle"

    def test_working_when_interrupt_visible(self):
        pane_content = (
            "some output\n"
            "⏳ Running tool...\n"
            "  ctrl+c to interrupt"
        )
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content(pane_content) == "working"

    def test_waiting_when_yn_prompt(self):
        pane_content = (
            "Allow Bash tool?\n"
            "[y/n]"
        )
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content(pane_content) == "waiting"

    def test_unknown_when_empty_content(self):
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content("") == "unknown"

    def test_unknown_when_none_content(self):
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content(None) == "unknown"

    def test_unknown_when_no_recognizable_pattern(self):
        pane_content = "random log output\nnothing special here"
        monitor = TmuxMonitor()
        assert monitor._detect_status_from_content(pane_content) == "unknown"


class TestGetAllSessionStatuses:

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_full_scan(self, mock_run):
        """Scan returns status for each claude-running tmux session."""
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "list-sessions" in cmd_str:
                return MagicMock(returncode=0, stdout="claude-voice\nother-app\n")
            if "list-panes" in cmd_str and "claude-voice" in cmd_str:
                return MagicMock(returncode=0, stdout="claude\n")
            if "list-panes" in cmd_str and "other-app" in cmd_str:
                return MagicMock(returncode=0, stdout="vim\n")
            if "capture-pane" in cmd_str:
                return MagicMock(returncode=0, stdout="❯ \n")
            if "display-message" in cmd_str:
                return MagicMock(returncode=0, stdout="1706900000\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        monitor = TmuxMonitor()
        statuses = monitor.get_all_session_statuses()

        assert len(statuses) == 1
        assert statuses[0]["session"] == "claude-voice"
        assert statuses[0]["status"] == "idle"

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_full_scan_no_claude_sessions(self, mock_run):
        """Returns empty list when no sessions run claude."""
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "list-sessions" in cmd_str:
                return MagicMock(returncode=0, stdout="vim-session\n")
            if "list-panes" in cmd_str:
                return MagicMock(returncode=0, stdout="vim\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        monitor = TmuxMonitor()
        statuses = monitor.get_all_session_statuses()
        assert statuses == []

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_full_scan_no_sessions_at_all(self, mock_run):
        """Returns empty list when tmux has no sessions."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        monitor = TmuxMonitor()
        statuses = monitor.get_all_session_statuses()
        assert statuses == []


class TestCapturePaneMethod:

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_capture_pane_returns_content(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="line1\nline2\n❯ \n"
        )
        monitor = TmuxMonitor()
        result = monitor.capture_pane("my-session")
        assert result == "line1\nline2\n❯ \n"

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_capture_pane_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        monitor = TmuxMonitor()
        assert monitor.capture_pane("bad-session") is None

    @patch("daemon.tmux_monitor.subprocess.run")
    def test_capture_pane_returns_none_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=5)
        monitor = TmuxMonitor()
        assert monitor.capture_pane("my-session") is None
