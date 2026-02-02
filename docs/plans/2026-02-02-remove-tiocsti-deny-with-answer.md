# Remove TIOCSTI & Restructure AFK Reply Routing

## Summary

Remove TIOCSTI ioctl dependency (deprecated on Linux, at risk on macOS) and restructure AFK reply routing into two clean paths:

1. **AskUserQuestion** — hook blocks synchronously, returns deny-with-answer (no keystroke injection)
2. **Free-text replies** — PTY proxy via invisible shell function (+ tmux fallback)

## Design Decisions

- **Deny reason format:** Natural language ("The user is in AFK mode and already answered this question via Telegram. Their answer was: ...") for maximum reliability with Claude
- **Timeout behavior:** Deny with timeout message ("AFK mode: the user did not respond within N minutes")
- **Injection fallbacks:** Proxy → tmux → fail with Telegram notification. No osascript keystroke simulation
- **Shell function install:** Auto-added to shell RC by deploy.sh, idempotent with marker comment
- **Shell RC detection:** zsh → .zshrc, bash on macOS → .bash_profile, bash on Linux → .bashrc

## Changes

### 1. `hooks/handle-ask-user.py` — Complete Rewrite

Replace spawn-and-return with synchronous block-and-deny:

1. Hook fires, parses questions/options from tool input
2. Sends request to daemon via `send_to_daemon()` (unchanged)
3. Daemon returns `{"wait": true, "response_path": "..."}`
4. Hook polls `response_path` using `wait_for_response()` (existing, from `_common.py`)
5. On answer, returns:
   ```python
   {
     "hookSpecificOutput": {
       "hookEventName": "PreToolUse",
       "permissionDecision": "deny",
       "permissionDecisionReason": "The user is in AFK mode and already answered this question via Telegram. Their answer was: \"<answer>\". Please continue with this answer and do not retry the question."
     }
   }
   ```
6. On timeout, returns:
   ```python
   {
     "hookSpecificOutput": {
       "hookEventName": "PreToolUse",
       "permissionDecision": "deny",
       "permissionDecisionReason": "AFK mode: the user did not respond within 10 minutes."
     }
   }
   ```

Remove: TTY capture (`/dev/tty` logic), `_type_answer.py` subprocess spawning, PID management.
Keep: `ASK_USER_FLAG` set/clear for duplicate notification prevention.

### 2. Delete `hooks/_type_answer.py`

Entire file removed. No longer needed — hook handles everything synchronously.

### 3. `daemon/afk.py` — Remove osascript injection

Remove:
- `_inject_reply()` method (Terminal.app tab targeting + System Events keystrokes)
- `_session_tty_paths` dict and all `tty_path` handling in `handle_hook_request()`

Simplify `_try_inject()`:
```python
def _try_inject(self, session, text):
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

### 4. `deploy.sh` — Auto-install shell function

After copying daemon/hooks files, add wrapper source line to shell RC:

```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    RC_FILE="$HOME/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    RC_FILE="$HOME/.bash_profile"
else
    RC_FILE="$HOME/.bashrc"
fi

MARKER="# Claude Voice integration"
if ! grep -q "$MARKER" "$RC_FILE" 2>/dev/null; then
    printf '\n%s\n[ -f ~/.claude-voice/claude-wrapper.sh ] && source ~/.claude-voice/claude-wrapper.sh\n' "$MARKER" >> "$RC_FILE"
    echo "Added Claude Voice shell integration to $RC_FILE"
    echo "Run 'source $RC_FILE' or open a new terminal to activate"
fi
```

### 5. `install.sh` — Fix bash_profile on macOS

Update shell RC detection in three places (lines 570, 640) to use:
```bash
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    SHELL_RC="$HOME/.bash_profile"
else
    SHELL_RC="$HOME/.bashrc"
fi
```

Also fix `uninstall.sh` (line 182) for consistency.

### 6. Test Changes

**Delete:**
- `tests/unit/test_type_answer.py` (if exists)

**Update `tests/unit/test_afk_reply_routing.py`:**
- Remove tests for `_inject_reply()` (osascript)
- Remove tests for `_session_tty_paths`
- Keep/update tests for `_inject_via_proxy()` and tmux fallback
- Add tests for simplified `_try_inject()` (proxy → tmux → fail)

**New/updated tests for `handle-ask-user.py`:**
- Synchronous flow: send to daemon → wait for response → deny-with-answer
- Timeout: no response → deny with timeout message
- Non-AFK mode: returns nothing (passthrough)
- Option button press: `opt:Blue` → reason includes "Blue"
- Free text: raw text → reason includes verbatim
- Answer formatting: verify `permissionDecisionReason` structure

## Files Affected

| File | Action |
|------|--------|
| `hooks/handle-ask-user.py` | Rewrite (synchronous deny-with-answer) |
| `hooks/_type_answer.py` | Delete |
| `daemon/afk.py` | Remove osascript injection, tty_path tracking |
| `deploy.sh` | Add shell function auto-install |
| `install.sh` | Fix bash_profile detection on macOS |
| `uninstall.sh` | Fix bash_profile detection on macOS |
| `tests/unit/test_type_answer.py` | Delete (if exists) |
| `tests/unit/test_afk_reply_routing.py` | Update (remove osascript tests) |
| `tests/unit/test_ask_user_hook.py` | New/updated tests for deny-with-answer |