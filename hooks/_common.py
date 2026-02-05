"""Shared utilities for Claude Voice hook scripts."""

import json
import os
import socket
import stat
import sys
import time

# Shared paths
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")
AFK_RESPONSE_TIMEOUT = 10800  # 3 hours — hooks block while user is AFK

# How often hooks poll for response files (seconds).
# Lower = less latency after Telegram reply, higher = less CPU.
# 1s is a good balance: imperceptible delay for a human, negligible CPU.
POLL_INTERVAL = 1

_ERROR_LOG = os.path.expanduser("/tmp/claude-voice/logs/hook_errors.log")


def log_error(hook: str, error: Exception) -> None:
    """Log hook errors to debug file and stderr."""
    msg = f"[{hook}] {type(error).__name__}: {error}"
    try:
        log_dir = os.path.dirname(_ERROR_LOG)
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        # Ensure directory permissions are restrictive
        try:
            os.chmod(log_dir, stat.S_IRWXU)  # 0o700
        except PermissionError:
            pass
        with open(_ERROR_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass
    print(msg, file=sys.stderr)


def make_debug_logger(log_path: str):
    """Create a debug logging function that writes to the given log file."""
    def debug(msg: str) -> None:
        try:
            log_dir = os.path.dirname(log_path)
            os.makedirs(log_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(log_dir, stat.S_IRWXU)  # 0o700
            except PermissionError:
                pass
            with open(log_path, "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass  # Expected: dir unwritable, disk full
        except Exception as e:
            print(f"[claude-voice] log write failed: {e}", file=sys.stderr)
    return debug


def get_session(hook_input: dict | None = None) -> str:
    """Derive a unique, human-readable session key.

    Uses the Claude Code session_id (UUID) from hook input combined with
    the project directory name to produce a key like "claude-voice_c12d0f43".
    Falls back to just the directory basename if session_id is unavailable.
    """
    project = os.path.basename(os.getcwd())
    if hook_input:
        session_id = hook_input.get("session_id", "")
        if session_id:
            return f"{project}_{session_id[:8]}"
    return project


def send_to_daemon(payload: dict, with_context: bool = False, raw_text: str = "",
                   hook_input: dict | None = None) -> dict | None:
    """Send JSON to daemon and receive a JSON response.

    Args:
        payload: JSON payload to send.
        with_context: If True, add session/context fields for AFK routing.
        raw_text: Original unprocessed text (used for context extraction).
        hook_input: Raw hook input JSON (used to extract session_id).
    """
    if with_context:
        session = get_session(hook_input)
        source = raw_text or payload.get("text", "")
        context_lines = source.strip().split("\n")[-10:] if source else []
        payload = {
            **payload,
            "session": session,
            "context": "\n".join(context_lines),
            "type": "context",
        }
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(TTS_SOCK_PATH)
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        if data:
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        pass  # Daemon not running — expected
    except Exception as e:
        log_error("send_to_daemon", e)
    return None


def wait_for_response(response_path: str, timeout: float | None = None) -> str | None:
    """Poll for a response file. Returns response text or None on timeout."""
    deadline = time.time() + (timeout if timeout is not None else AFK_RESPONSE_TIMEOUT)
    while time.time() < deadline:
        if os.path.exists(response_path):
            try:
                with open(response_path) as f:
                    response = f.read().strip()
            except OSError:
                continue  # File not ready yet
            try:
                os.remove(response_path)
            except OSError:
                pass  # Will be cleaned up later
            return response
        time.sleep(POLL_INTERVAL)
    return None


def read_mode() -> str:
    """Read the current TTS mode from the mode file."""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                return f.read().strip()
        except (OSError, ValueError):
            pass
    return ""


PERMISSION_RULES_FILE = os.path.expanduser("~/.claude-voice/permission_rules.json")


def load_permission_rules() -> list[dict]:
    """Load permission rules from file."""
    if not os.path.exists(PERMISSION_RULES_FILE):
        return []
    try:
        with open(PERMISSION_RULES_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Warning: corrupt permission rules file: {e}", file=sys.stderr)
        return []
    except OSError:
        return []


def store_permission_rule(pattern: str) -> None:
    """Store a new 'always allow' rule."""
    rules = load_permission_rules()

    # Check if pattern already exists
    for rule in rules:
        if rule.get("pattern") == pattern:
            return  # Already exists

    # Add new rule
    rules.append({
        "pattern": pattern,
        "behavior": "allow",
        "added": time.time(),
    })

    # Save with restrictive permissions (contains permission patterns)
    try:
        dir_path = os.path.dirname(PERMISSION_RULES_FILE)
        os.makedirs(dir_path, mode=0o700, exist_ok=True)
        # Use os.open to create file with restrictive permissions
        fd = os.open(
            PERMISSION_RULES_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,  # 0o600
        )
        with os.fdopen(fd, "w") as f:
            json.dump(rules, f, indent=2)
    except OSError as e:
        print(f"Warning: could not save permission rule: {e}", file=sys.stderr)


def check_permission_rules(message: str) -> str | None:
    """Check if message matches any permission rules. Returns behavior or None."""
    rules = load_permission_rules()

    for rule in rules:
        pattern = rule.get("pattern", "")
        behavior = rule.get("behavior", "ask")

        # Simple substring match for now
        if pattern and pattern in message:
            return behavior

    return None
