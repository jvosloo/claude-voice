"""Background helper: waits for an AFK response file, then selects the option
or types a free-text answer via the 'Other' path.

Primary method: TIOCSTI ioctl to inject characters directly into the terminal's
input buffer. This bypasses the window event system and writes to the TTY input
queue where Claude Code's interactive picker reads from.

Fallback: osascript (AppleScript System Events) for keystroke simulation."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import wait_for_response, make_debug_logger, ASK_USER_FLAG

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/ask-user-debug.log"))

# PID file to track the active _type_answer process per response path
PID_DIR = os.path.expanduser("/tmp/claude-voice/pids")

# macOS TIOCSTI ioctl: inject a single byte into the terminal input queue
# Defined in <sys/ttycom.h> as _IOW('t', 114, char) = 0x80017472
TIOCSTI = 0x80017472

# Terminal escape sequences for TIOCSTI injection
SEQ_DOWN = b'\x1b[B'   # Down arrow
SEQ_RETURN = b'\r'      # Enter/Return


def clear_flag() -> None:
    """Remove the ask_user_active flag."""
    try:
        os.remove(ASK_USER_FLAG)
    except FileNotFoundError:
        pass


def _pid_file_for(response_path: str) -> str:
    """Get PID file path for a given response path."""
    safe_name = response_path.replace("/", "_")
    return os.path.join(PID_DIR, f"typer{safe_name}.pid")


def kill_previous_typer(response_path: str) -> None:
    """Kill any previous _type_answer process watching the same response path."""
    pid_path = _pid_file_for(response_path)
    if os.path.exists(pid_path):
        try:
            with open(pid_path) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, signal.SIGTERM)
            debug(f"Killed previous typer (PID {old_pid})")
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        try:
            os.remove(pid_path)
        except FileNotFoundError:
            pass


def register_typer_pid(response_path: str) -> None:
    """Register this process as the active typer for the response path."""
    os.makedirs(PID_DIR, exist_ok=True)
    pid_path = _pid_file_for(response_path)
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))


def unregister_typer_pid(response_path: str) -> None:
    """Remove this process's PID file."""
    pid_path = _pid_file_for(response_path)
    try:
        os.remove(pid_path)
    except FileNotFoundError:
        pass


# --- TIOCSTI-based input injection (primary method) ---

def _inject_bytes(tty_fd: int, data: bytes) -> None:
    """Inject bytes into the terminal input buffer via TIOCSTI ioctl."""
    for b in data:
        fcntl.ioctl(tty_fd, TIOCSTI, bytes([b]))


def _pty_down(tty_fd: int) -> None:
    """Inject Down arrow escape sequence."""
    _inject_bytes(tty_fd, SEQ_DOWN)


def _pty_return(tty_fd: int) -> None:
    """Inject Return key."""
    _inject_bytes(tty_fd, SEQ_RETURN)


def _pty_type_text(tty_fd: int, text: str) -> None:
    """Inject a string character by character."""
    _inject_bytes(tty_fd, text.encode())


# --- osascript fallback ---

def _osascript_key(code: int) -> None:
    """Send a single key code via AppleScript System Events."""
    subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to key code {code}'],
        capture_output=True, timeout=5,
    )


def _osascript_type_text(text: str) -> None:
    """Type a string via AppleScript System Events."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to keystroke "{escaped}"'],
        capture_output=True, timeout=10,
    )


# osascript key codes
KEY_DOWN = 125
KEY_RETURN = 36


def select_option(index: int, tty_fd: int = None) -> None:
    """Navigate a TUI picker: press Down arrow `index` times, then Return."""
    time.sleep(0.5)
    if tty_fd is not None:
        for _ in range(index):
            _pty_down(tty_fd)
            time.sleep(0.1)
        time.sleep(0.2)
        _pty_return(tty_fd)
    else:
        for _ in range(index):
            _osascript_key(KEY_DOWN)
            time.sleep(0.15)
        time.sleep(0.3)
        _osascript_key(KEY_RETURN)


def type_free_text(text: str, num_options: int, tty_fd: int = None) -> None:
    """Select 'Other' in the TUI picker, then type free-text answer.

    'Other' is the last item in the picker, after all options.
    """
    time.sleep(0.5)

    if tty_fd is not None:
        # Navigate to "Other" (after all options)
        for _ in range(num_options):
            _pty_down(tty_fd)
            time.sleep(0.1)
        time.sleep(0.2)
        _pty_return(tty_fd)
        time.sleep(0.5)  # Wait for text input to appear
        _pty_type_text(tty_fd, text)
        time.sleep(0.1)
        _pty_return(tty_fd)
    else:
        for _ in range(num_options):
            _osascript_key(KEY_DOWN)
            time.sleep(0.15)
        time.sleep(0.3)
        _osascript_key(KEY_RETURN)
        time.sleep(1.0)
        _osascript_type_text(text)
        time.sleep(0.2)
        _osascript_key(KEY_RETURN)


def main():
    if len(sys.argv) < 3:
        debug("Usage: _type_answer.py <response_path> <options_json> [tty_path]")
        return

    response_path = sys.argv[1]
    try:
        options = json.loads(sys.argv[2])
    except json.JSONDecodeError:
        debug("Failed to parse options JSON")
        clear_flag()
        return

    tty_path = sys.argv[3] if len(sys.argv) > 3 else None

    # Kill any previous typer for the same response path (stale process from prior question)
    kill_previous_typer(response_path)
    register_typer_pid(response_path)

    tty_fd = None
    try:
        # Try to open the TTY for TIOCSTI injection
        if tty_path:
            try:
                tty_fd = os.open(tty_path, os.O_RDWR)
                debug(f"Opened TTY {tty_path} (fd={tty_fd}) for TIOCSTI")
            except OSError as e:
                debug(f"Failed to open TTY {tty_path}: {e}")
                tty_fd = None

        method = "TIOCSTI" if tty_fd is not None else "osascript"
        if tty_fd is None:
            debug("No TTY available, falling back to osascript")

        debug(f"Waiting for response at {response_path}")
        debug(f"Options: {[o.get('label') for o in options]}")

        answer = wait_for_response(response_path)
        if not answer:
            debug("Timed out waiting for response")
            return

        debug(f"Got answer: {answer}")

        # Handle skip — user tapped "Skip / Other" button, let them answer locally
        if answer in ("opt:__other__", "__other__"):
            debug("User chose Skip/Other button, not acting")
            return

        # Button press: "opt:<label>"
        if answer.startswith("opt:"):
            selected = answer[4:]
            for i, opt in enumerate(options):
                if opt.get("label") == selected:
                    debug(f"Selecting option {i}: {selected} (method={method})")
                    try:
                        select_option(i, tty_fd)
                    except OSError as e:
                        if tty_fd is not None:
                            debug(f"TIOCSTI failed: {e}, falling back to osascript")
                            tty_fd = None
                            select_option(i, None)
                        else:
                            raise
                    debug("Done selecting")
                    return
            debug(f"Could not find option matching '{selected}', skipping")
            return

        # Free-text reply from Telegram (no "opt:" prefix)
        debug(f"Free-text answer: {answer} (method={method})")
        try:
            type_free_text(answer, len(options), tty_fd)
        except OSError as e:
            if tty_fd is not None:
                debug(f"TIOCSTI failed: {e}, falling back to osascript")
                tty_fd = None
                type_free_text(answer, len(options), None)
            else:
                raise
        debug("Done typing free-text")
    finally:
        if tty_fd is not None:
            os.close(tty_fd)
        unregister_typer_pid(response_path)
        clear_flag()


if __name__ == "__main__":
    main()
