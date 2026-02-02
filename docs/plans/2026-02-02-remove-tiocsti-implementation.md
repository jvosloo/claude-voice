# Remove TIOCSTI & Restructure AFK Reply Routing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove TIOCSTI ioctl dependency and restructure AFK reply routing so AskUserQuestion uses hook deny-with-answer (no keystroke injection) and free-text replies use PTY proxy only.

**Architecture:** Hook-based deny-with-answer for AskUserQuestion (hook blocks, waits for Telegram response, returns deny with answer in reason). PTY proxy + tmux for free-text injection. No TIOCSTI, no osascript keystroke simulation.

**Tech Stack:** Python, Claude Code hooks protocol (PreToolUse), Unix sockets, bash shell functions

---

### Task 1: Rewrite `handle-ask-user.py` to deny-with-answer

**Files:**
- Modify: `hooks/handle-ask-user.py`
- Reference: `hooks/_common.py` (for `wait_for_response`, `ASK_USER_FLAG`)
- Reference: `hooks/permission-request.py:151-160` (model for hook output format)

**Step 1: Write the failing test**

Create `tests/unit/test_ask_user_hook.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_ask_user_hook.py -v`
Expected: FAIL (hook still has old implementation)

**Step 3: Write the implementation**

Rewrite `hooks/handle-ask-user.py`:

```python
#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PreToolUse hook for AskUserQuestion.

In AFK mode, intercepts AskUserQuestion and routes it through Telegram.
Blocks synchronously until the user responds, then returns a deny decision
with the answer in the reason — Claude reads it and continues.

In non-AFK mode, returns nothing (tool runs normally with local picker).
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import send_to_daemon, make_debug_logger, read_mode, wait_for_response, ASK_USER_FLAG

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/ask-user-debug.log"))


def _deny(reason: str) -> None:
    """Print a deny decision with the given reason. Claude sees this reason."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))


def main():
    # Only active in AFK mode
    mode = read_mode()
    if mode != "afk":
        return

    debug("Hook fired in AFK mode")

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        debug("Failed to parse hook input")
        return

    tool_input = hook_input.get("tool_input", {})
    questions = tool_input.get("questions", [])
    if not questions:
        debug("No questions in tool_input")
        return

    debug(f"Got {len(questions)} questions")

    session = os.path.basename(os.getcwd())

    # Build a readable prompt for Telegram
    prompt_lines = []
    for q in questions:
        prompt_lines.append(q.get("question", ""))
        for i, opt in enumerate(q.get("options", []), 1):
            prompt_lines.append(f"  {i}. {opt.get('label', '')} — {opt.get('description', '')}")

    # Send to daemon
    response = send_to_daemon({
        "session": session,
        "type": "ask_user_question",
        "prompt": "\n".join(prompt_lines),
        "questions": questions,
    })

    debug(f"Daemon response: {response}")

    if not response or not response.get("wait"):
        return

    response_path = response.get("response_path", "")
    if not response_path:
        return

    # Set flag so notify-permission.py skips the duplicate notification
    try:
        os.makedirs(os.path.dirname(ASK_USER_FLAG), exist_ok=True)
        with open(ASK_USER_FLAG, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    # Block until Telegram response arrives
    debug(f"Waiting for response at {response_path}")
    answer = wait_for_response(response_path)

    # Clear flag
    try:
        os.remove(ASK_USER_FLAG)
    except FileNotFoundError:
        pass

    if not answer:
        debug("Timed out waiting for response")
        _deny("AFK mode: the user did not respond in time. You may retry or move on.")
        return

    if answer == "__flush__":
        debug("Queue flushed, denying")
        _deny("AFK mode: the request queue was flushed. The question was cancelled.")
        return

    # Skip/Other — let the local picker handle it
    if answer in ("opt:__other__", "__other__"):
        debug("User chose Skip/Other, allowing local picker")
        return

    # Extract the actual answer text
    if answer.startswith("opt:"):
        answer_text = answer[4:]
        debug(f"Option selected: {answer_text}")
    else:
        answer_text = answer
        debug(f"Free-text answer: {answer_text}")

    _deny(
        f'The user is in AFK mode and already answered this question via Telegram. '
        f'Their answer was: "{answer_text}". '
        f'Please continue with this answer and do not retry the question.'
    )


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_ask_user_hook.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add hooks/handle-ask-user.py tests/unit/test_ask_user_hook.py
git commit -m "feat: rewrite AskUserQuestion hook to deny-with-answer (no keystroke injection)"
```

---

### Task 2: Delete `_type_answer.py` and its tests

**Files:**
- Delete: `hooks/_type_answer.py`
- Delete: `tests/unit/test_type_answer.py`

**Step 1: Delete both files**

```bash
rm hooks/_type_answer.py tests/unit/test_type_answer.py
```

**Step 2: Run all tests to verify nothing else depends on these files**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`
Expected: All remaining tests PASS (no imports of `_type_answer`)

**Step 3: Commit**

```bash
git add -u hooks/_type_answer.py tests/unit/test_type_answer.py
git commit -m "refactor: delete _type_answer.py (TIOCSTI and osascript keystroke injection removed)"
```

---

### Task 3: Remove osascript injection and `_session_tty_paths` from `daemon/afk.py`

**Files:**
- Modify: `daemon/afk.py`
- Modify: `daemon/session_presenter.py:162-177`

**Step 1: Write the failing test**

Add to `tests/unit/test_afk_reply_routing.py` — replace `TestInjectReply` and `TestTypeIntoTerminalReplacement` with proxy/tmux tests:

```python
class TestTryInject:
    """Tests for _try_inject with proxy + tmux only (no osascript)."""

    def test_proxy_injection_succeeds(self):
        """_try_inject returns True when proxy injection works."""
        afk = _make_afk()

        with patch.object(afk, '_inject_via_proxy', return_value=True):
            result = afk._try_inject("sess1", "hello")

        assert result is True

    def test_tmux_fallback_when_proxy_fails(self):
        """Falls back to tmux when proxy injection fails."""
        afk = _make_afk()
        afk._tmux_monitor = Mock()
        afk._tmux_monitor.is_available.return_value = True
        afk._tmux_monitor.get_session_status.return_value = {"status": "idle"}
        afk._tmux_monitor.send_prompt.return_value = True

        with patch.object(afk, '_inject_via_proxy', return_value=False):
            result = afk._try_inject("sess1", "hello")

        assert result is True
        afk._tmux_monitor.send_prompt.assert_called_once()

    def test_returns_false_when_all_methods_fail(self):
        """Returns False when both proxy and tmux fail."""
        afk = _make_afk()
        afk._tmux_monitor = Mock()
        afk._tmux_monitor.is_available.return_value = False

        with patch.object(afk, '_inject_via_proxy', return_value=False):
            result = afk._try_inject("sess1", "hello")

        assert result is False
```

**Step 2: Run test to verify current state**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_reply_routing.py::TestTryInject -v`
Expected: These new tests should PASS even before code changes (proxy/tmux path already exists). But the old tests referencing `_inject_reply` and `_session_tty_paths` need removal.

**Step 3: Apply changes to `daemon/afk.py`**

Remove from `__init__` (line 42):
```python
# DELETE this line:
self._session_tty_paths = {}  # session -> TTY device path (e.g. /dev/ttys005)
```

Remove from `handle_hook_request` (lines 176-179):
```python
# DELETE these lines:
        tty_path = request.get("tty_path")
        if tty_path:
            self._session_tty_paths[session] = tty_path
```

Update context handler (line 186) — replace `has_tty` with proxy/tmux check:
```python
            has_terminal = self._proxy_session_alive(session) or (
                self._tmux_monitor.is_available()
                and self._tmux_monitor.get_session_status(session)["status"] != "dead"
            )
```
And line 189: `has_tty=has_tty` → `has_tty=has_terminal`

Remove from `deactivate` (line 140):
```python
# DELETE this line:
        self._session_tty_paths.clear()
```

Update `handle_status_request` (line 246): replace `has_tty = session in self._session_tty_paths` with:
```python
            has_tty = self._proxy_session_alive(session) or (
                self._tmux_monitor.is_available()
                and self._tmux_monitor.get_session_status(session)["status"] != "dead"
            )
```

Update `_handle_callback` reply button check (lines 328-333): remove `has_tty` line, simplify condition:
```python
            has_proxy = self._proxy_session_alive(target_session)
            has_tmux = (self._tmux_monitor.is_available()
                        and self._tmux_monitor.get_session_status(target_session)["status"] != "dead")

            if has_proxy or has_tmux:
```

Delete entire `_inject_reply` method (lines 701-744).

Simplify `_try_inject` (lines 769-793) — remove osascript fallback:
```python
    def _try_inject(self, session: str, text: str) -> bool:
        """Try all available injection methods in priority order.

        Order: proxy socket → tmux send-keys.
        Returns True if any method succeeded.
        """
        # 1. PTY proxy socket (primary)
        if self._inject_via_proxy(session, text):
            return True

        # 2. tmux send-keys (fallback)
        if self._tmux_monitor.is_available():
            status = self._tmux_monitor.get_session_status(session)
            if status["status"] != "dead":
                if self._tmux_monitor.send_prompt(session, text, require_idle=False):
                    return True

        return False
```

Remove from `cleanup_session` (line 858):
```python
# DELETE this line:
        self._session_tty_paths.pop(session, None)
```

Update `_check_shell_wrapper` (line 118) — add `~/.bash_profile`:
```python
    def _check_shell_wrapper(self) -> bool:
        """Check if claude-wrapper.sh is sourced in the user's shell config."""
        for rc in [
            os.path.expanduser("~/.zshrc"),
            os.path.expanduser("~/.bash_profile"),
            os.path.expanduser("~/.bashrc"),
        ]:
            try:
                with open(rc) as f:
                    if "claude-wrapper" in f.read():
                        return True
            except FileNotFoundError:
                continue
        return False
```

**Step 4: Update tests in `tests/unit/test_afk_reply_routing.py`**

Remove these test classes entirely (they test removed functionality):
- `TestInjectReply` (lines 240-309)
- `TestTypeIntoTerminalReplacement` (lines 312-352)

Update `TestContextMessageWithReplyButton`:
- Remove `test_context_request_stores_tty_path` (line 44-55)
- Update `test_context_request_sends_with_reply_button` — mock `_proxy_session_alive` returning True instead of setting tty_path
- Update `test_context_without_tty_has_no_tty_indicator` — mock `_proxy_session_alive` returning False

Update `TestReplyCallback`:
- Remove `test_reply_callback_without_tty_warns` or update to mock proxy/tmux
- Update `test_reply_callback_sets_reply_target` — mock proxy alive check

Update `TestFreeTextReplyRouting`:
- Replace all `_inject_reply` patches with `_try_inject` patches
- Remove `_session_tty_paths` assignments

Update `TestDeactivateFlush`:
- Remove `test_deactivate_clears_session_state` assertion about `_session_tty_paths`

Update `TestCleanupSession`:
- Remove `test_cleanup_removes_tty_path`

Update `TestEnhancedStatus`:
- Remove `test_status_shows_tty_indicator` or update to mock proxy

**Step 5: Run all tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add daemon/afk.py daemon/session_presenter.py tests/unit/test_afk_reply_routing.py
git commit -m "refactor: remove osascript injection and _session_tty_paths from AfkManager"
```

---

### Task 4: Add shell function auto-install to `deploy.sh`

**Files:**
- Modify: `deploy.sh`

**Step 1: Add shell RC integration block at end of `deploy.sh`**

Add before the final "Deployment complete" message (before line 117):

```bash
# Ensure shell wrapper is sourced in user's shell RC
if [[ "$SHELL" == *"zsh"* ]]; then
    RC_FILE="$HOME/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    RC_FILE="$HOME/.bash_profile"
else
    RC_FILE="$HOME/.bashrc"
fi

WRAPPER_MARKER="# Claude Voice integration"
if ! grep -q "$WRAPPER_MARKER" "$RC_FILE" 2>/dev/null; then
    printf '\n%s\n[ -f ~/.claude-voice/claude-wrapper.sh ] && source ~/.claude-voice/claude-wrapper.sh\n' "$WRAPPER_MARKER" >> "$RC_FILE"
    echo -e "  ${GREEN}+${NC} Added shell integration to $RC_FILE"
    echo "  Run 'source $RC_FILE' or open a new terminal to activate"
fi
```

**Step 2: Test manually**

Run: `./deploy.sh`
Expected: See "Added shell integration to ~/.zshrc" (first run) or no output (idempotent)

**Step 3: Commit**

```bash
git add deploy.sh
git commit -m "feat: auto-install shell wrapper function in deploy.sh"
```

---

### Task 5: Fix shell RC detection in `install.sh` and `uninstall.sh`

**Files:**
- Modify: `install.sh:569-576` and `install.sh:640-643`
- Modify: `uninstall.sh:181-184`

**Step 1: Update `install.sh` shell RC detection (line 569-576)**

Replace:
```bash
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
        SHELL_NAME="zsh"
    else
        SHELL_RC="$HOME/.bashrc"
        SHELL_NAME="bash"
    fi
```

With:
```bash
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
        SHELL_NAME="zsh"
    elif [ "$(uname)" = "Darwin" ]; then
        SHELL_RC="$HOME/.bash_profile"
        SHELL_NAME="bash"
    else
        SHELL_RC="$HOME/.bashrc"
        SHELL_NAME="bash"
    fi
```

**Step 2: Update `install.sh` reminder message (line 640-643)**

Replace:
```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="~/.zshrc"
else
    SHELL_RC="~/.bashrc"
fi
```

With:
```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="~/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    SHELL_RC="~/.bash_profile"
else
    SHELL_RC="~/.bashrc"
fi
```

**Step 3: Update `uninstall.sh` (line 181-184)**

Replace:
```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
else
    SHELL_RC="$HOME/.bashrc"
fi
```

With:
```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    SHELL_RC="$HOME/.bash_profile"
else
    SHELL_RC="$HOME/.bashrc"
fi
```

Also update `uninstall.sh` to clean up the wrapper source line (add after the alias cleanup):
```bash
# Remove wrapper source line
if grep -q "Claude Voice integration" "$SHELL_RC" 2>/dev/null; then
    sed -i '' '/# Claude Voice integration/d' "$SHELL_RC"
    sed -i '' '/claude-wrapper\.sh/d' "$SHELL_RC"
    echo "Removed Claude Voice shell integration from $SHELL_RC"
fi
```

**Step 4: Commit**

```bash
git add install.sh uninstall.sh
git commit -m "fix: use bash_profile on macOS for shell RC detection"
```

---

### Task 6: Deploy and verify

**Step 1: Deploy changes**

```bash
./deploy.sh
```

**Step 2: Run full test suite**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`
Expected: All PASS

**Step 3: Verify hook deleted from installation**

```bash
# _type_answer.py should NOT exist in installed hooks
ls -la ~/.claude/hooks/_type_answer.py 2>/dev/null && echo "WARNING: _type_answer.py still installed" || echo "OK: _type_answer.py removed"
```

If it still exists, delete it manually:
```bash
rm ~/.claude/hooks/_type_answer.py
```

**Step 4: Source the shell wrapper**

```bash
source ~/.zshrc  # or ~/.bash_profile
```

Verify: `type claude` should show it's a function, not just the binary path.

**Step 5: Commit (if any deployment fixes needed)**

```bash
git add -A && git commit -m "fix: deployment cleanup"
```