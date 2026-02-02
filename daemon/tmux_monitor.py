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
        """Check if a tmux session is running a claude process.

        Uses two methods: first checks tmux's pane_current_command, then
        falls back to checking child processes of the pane shell. The
        fallback is needed because tmux resolves symlinks — Claude Code
        installs as a symlink to a versioned path, so pane_current_command
        reports the version number (e.g. '2.1.29') instead of 'claude'.
        """
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-t", session, "-F", "#{pane_current_command}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False
            commands = result.stdout.strip().split("\n")
            if any("claude" in cmd.lower() for cmd in commands):
                return True

            # Fallback: check child processes of the pane shell via ps.
            # We avoid pgrep because macOS pgrep requires a pattern arg
            # and excludes ancestor processes by default.
            result = subprocess.run(
                ["tmux", "list-panes", "-t", session, "-F", "#{pane_pid}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False
            pane_pids = {p.strip() for p in result.stdout.strip().split("\n") if p.strip()}
            if not pane_pids:
                return False
            ps_result = subprocess.run(
                ["ps", "-eo", "ppid,comm"],
                capture_output=True, text=True, timeout=5,
            )
            if ps_result.returncode != 0:
                return False
            for line in ps_result.stdout.strip().split("\n"):
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0] in pane_pids and "claude" in parts[1].lower():
                    return True
            return False
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

        # Working: various interrupt messages
        if "ctrl+c to interrupt" in tail or "esc to interrupt" in tail:
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
