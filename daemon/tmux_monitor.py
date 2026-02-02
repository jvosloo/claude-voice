"""Tmux session monitoring for AFK remote control.

Discovers Claude Code sessions running in tmux and detects their status
(idle, working, waiting, dead) by pattern-matching pane content.
"""

import subprocess


class TmuxMonitor:
    """Monitors tmux sessions for Claude Code instances."""

    def is_available(self) -> bool:
        """Check if tmux is installed and accessible."""
        try:
            result = subprocess.run(
                ["tmux", "-V"], capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def list_sessions(self) -> list[str]:
        """List all tmux session names."""
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return []
            return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

    def session_has_claude(self, session: str) -> bool:
        """Check if a tmux session is running a claude process."""
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-t", session, "-F", "#{pane_current_command}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False
            commands = result.stdout.strip().split("\n")
            return any("claude" in cmd.lower() for cmd in commands)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def capture_pane(self, session: str, lines: int = 50) -> str | None:
        """Capture the last N lines of a tmux session's pane."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", session, "-p", "-l", str(lines)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _detect_status_from_content(self, content: str | None) -> str:
        """Detect Claude Code status from pane content.

        Returns: "idle", "working", "waiting", or "unknown".
        """
        if not content:
            return "unknown"

        # Check last ~20 lines for patterns
        lines = content.strip().split("\n")
        tail = "\n".join(lines[-20:])

        # Working: "ctrl+c to interrupt" visible
        if "ctrl+c to interrupt" in tail:
            return "working"

        # Waiting: permission prompt
        if "[y/n]" in tail:
            return "waiting"

        # Idle: prompt character visible without interrupt message
        if "\u276f" in tail:
            return "idle"

        return "unknown"

    def get_session_status(self, session: str) -> dict:
        """Get status of a single tmux session.

        Returns dict with 'session', 'status', and 'pane_activity'.
        """
        if not self.session_has_claude(session):
            return {"session": session, "status": "dead"}

        content = self.capture_pane(session)
        status = self._detect_status_from_content(content) if content else "unknown"

        # Get pane activity timestamp for idle duration
        pane_activity = None
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-t", session, "-p", "#{pane_activity}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pane_activity = int(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass

        return {
            "session": session,
            "status": status,
            "pane_activity": pane_activity,
        }

    def get_all_session_statuses(self) -> list[dict]:
        """Scan all tmux sessions for Claude Code instances and their status."""
        sessions = self.list_sessions()
        results = []

        for session in sessions:
            status = self.get_session_status(session)
            if status["status"] != "dead":
                results.append(status)

        return results

    def send_prompt(self, session: str, text: str) -> bool:
        """Send a prompt to an idle Claude Code session via tmux send-keys.

        Returns True on success, False on error.
        """
        # Verify session is idle before sending
        status = self.get_session_status(session)
        if status["status"] != "idle":
            return False

        try:
            # Send text literally (no special key interpretation)
            result = subprocess.run(
                ["tmux", "send-keys", "-t", session, "-l", text],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False

            # Send Enter key
            result = subprocess.run(
                ["tmux", "send-keys", "-t", session, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
